import streamlit as st
from datetime import date, datetime, timezone, timedelta
import pandas as pd
import gspread
from gspread.utils import column_letter_to_index
from google.oauth2.service_account import Credentials

# --- 상수 정의 (공용) ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))
TEMP_BACKUP_PREFIX = "임시백업_"
MONTHLY_BACKUP_PREFIX = "백업_"

# --- Google Sheets 연동 (공용) ---
@st.cache_resource
def connect_to_gsheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open("Container_Data_DB")
        return spreadsheet
    except Exception as e:
        st.error(f"Google Sheets 연결에 실패했습니다: {e}")
        return None

spreadsheet = connect_to_gsheet()

# --- 서식 강제 함수 ---
def ensure_text_format(worksheet, column_name):
    """지정된 워크시트의 특정 열이 '일반 텍스트' 서식인지 확인하고 강제합니다."""
    try:
        headers = worksheet.row_values(1)
        if column_name in headers:
            col_index = headers.index(column_name) + 1
            col_letter = gspread.utils.rowcol_to_a1(1, col_index)[0]
            worksheet.format(f"{col_letter}:{col_letter}", {"numberFormat": {"type": "TEXT"}})
    except Exception as e:
        st.warning(f"'{worksheet.title}' 시트의 '{column_name}' 열 서식을 강제하는 중 오류 발생: {e}")

# --- 로그 기록 함수 (공용) ---
def log_change(action):
    if spreadsheet is None: return
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")

# --- 데이터 관리 함수들 (공용) ---
def load_data_from_gsheet():
    if spreadsheet is None: return []
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        
        all_values = worksheet.get_all_values()
        if len(all_values) < 2: return []
        
        headers = all_values[0]
        data = all_values[1:]
        df = pd.DataFrame(data, columns=headers)
        df.replace('', pd.NA, inplace=True)
        
        if '씰 번호' in df.columns: df['씰 번호'] = df['씰 번호'].astype(str)
        if '등록일시' in df.columns: df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce')
        if '완료일시' in df.columns: df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce')
        
        return df.to_dict('records')
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"'{MAIN_SHEET_NAME}' 시트를 찾을 수 없습니다.")
        return []
    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
        return []

def add_row_to_gsheet(data):
    if spreadsheet is None: return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        data_copy = data.copy()
        if isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_insert = [data_copy.get(header, "") for header in SHEET_HEADERS]
        worksheet.append_row(row_to_insert, value_input_option='USER_ENTERED')
        log_change(f"신규 등록: {data_copy.get('컨테이너 번호')}")
        return True, "성공"
    except Exception as e:
        st.error(f"Google Sheets 저장 중 오류 발생: {e}")
        return False, str(e)


def update_row_in_gsheet(index, data):
    if spreadsheet is None: return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        data_copy = data.copy()
        if isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_update = [data_copy.get(header, "") for header in SHEET_HEADERS]
        worksheet.update(f'A{index+2}:G{index+2}', [row_to_update], value_input_option='USER_ENTERED')
        log_change(f"데이터 수정: {data_copy.get('컨테이너 번호')}")
    except Exception as e:
        st.error(f"Google Sheets 업데이트 중 오류가 발생했습니다: {e}")


def delete_row_from_gsheet(index, container_no):
    if spreadsheet is None: return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        worksheet.delete_rows(index + 2)
        log_change(f"데이터 삭제: {container_no}")
    except Exception as e:
        st.error(f"Google Sheets에서 행 삭제 중 오류가 발생했습니다: {e}")


def backup_data_to_new_sheet(container_data):
    if spreadsheet is None: return False, "스프레드시트 연결 안됨"
    try:
        df_new = pd.DataFrame(container_data)
        
        if '등록일시' in df_new.columns: df_new['등록일시'] = pd.to_datetime(df_new['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '완료일시' in df_new.columns: df_new['완료일시'] = pd.to_datetime(df_new['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '씰 번호' in df_new.columns: df_new['씰 번호'] = df_new['씰 번호'].astype(str)
        for header in SHEET_HEADERS:
            if header not in df_new.columns: df_new[header] = ""
        df_new = df_new[SHEET_HEADERS]

        # --- 1. 월별 통합 백업 (중복 방지 기능 추가) ---
        month_str = date.today().strftime('%Y-%m')
        monthly_backup_name = f"{MONTHLY_BACKUP_PREFIX}{month_str}"
        try:
            backup_sheet = spreadsheet.worksheet(monthly_backup_name)
            # [수정] 이미 존재하는 시트도 매번 서식을 강제하여 안전성 확보
            ensure_text_format(backup_sheet, '씰 번호')
            existing_values = backup_sheet.get_all_values()
            if len(existing_values) > 1:
                existing_df = pd.DataFrame(existing_values[1:], columns=existing_values[0])
                new_unique_df = df_new[~df_new['컨테이너 번호'].isin(existing_df['컨테이너 번호'])]
            else:
                new_unique_df = df_new
            if not new_unique_df.empty:
                backup_sheet.append_rows(new_unique_df.values.tolist(), value_input_option='USER_ENTERED')
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=monthly_backup_name, rows=len(df_new) + 1, cols=len(SHEET_HEADERS))
            ensure_text_format(new_sheet, '씰 번호')
            new_sheet.update([SHEET_HEADERS] + df_new.values.tolist(), value_input_option='USER_ENTERED')

        # --- 2. 실시간 임시 백업 ---
        now_str = datetime.now(KST).strftime('%Y-%m-%d_%H%M%S')
        temp_backup_name = f"{TEMP_BACKUP_PREFIX}{now_str}"
        temp_sheet = spreadsheet.add_worksheet(title=temp_backup_name, rows=len(df_new) + 1, cols=len(SHEET_HEADERS))
        ensure_text_format(temp_sheet, '씰 번호')
        temp_sheet.update([SHEET_HEADERS] + df_new.values.tolist(), value_input_option='USER_ENTERED')
            
        return True, None
    except Exception as e:
        return False, str(e)

def delete_temporary_backups():
    if spreadsheet is None: return 0, "스프레드시트 연결 안됨"
    try:
        all_worksheets = spreadsheet.worksheets()
        sheets_to_delete = [
            sheet for sheet in all_worksheets if sheet.title.startswith(TEMP_BACKUP_PREFIX)
        ]
        
        if not sheets_to_delete:
            return 0, "삭제할 임시 백업 시트가 없습니다."

        for sheet in sheets_to_delete:
            spreadsheet.del_worksheet(sheet)
        
        return len(sheets_to_delete), "성공"
    except Exception as e:
        return 0, str(e)