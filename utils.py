import streamlit as st
from datetime import date, datetime, timezone, timedelta
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 상수 정의 (공용) ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))

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
        all_records = worksheet.get_all_records()
        if not all_records: return []
        
        df = pd.DataFrame(all_records)
        df.replace('', pd.NA, inplace=True)
        if '등록일시' in df.columns:
            df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce')
        if '완료일시' in df.columns:
            df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce')
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
        if isinstance(data.get('등록일시'), datetime):
            data['등록일시'] = data['등록일시'].strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(data.get('완료일시'), datetime):
            data['완료일시'] = data['완료일시'].strftime('%Y-%m-%d %H:%M:%S')
        
        row_to_insert = [data.get(header, "") for header in SHEET_HEADERS]
        worksheet.append_row(row_to_insert)
        log_change(f"신규 등록: {data.get('컨테이너 번호')}")
        return True, "성공"
    except Exception as e:
        st.error(f"Google Sheets 저장 중 오류 발생: {e}")
        return False, str(e)

def update_row_in_gsheet(index, data):
    if spreadsheet is None: return
    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
    if isinstance(data.get('등록일시'), datetime):
        data['등록일시'] = data['등록일시'].strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(data.get('완료일시'), datetime):
        data['완료일시'] = data['완료일시'].strftime('%Y-%m-%d %H:%M:%S')
    
    row_to_update = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.update(f'A{index+2}:G{index+2}', [row_to_update])
    log_change(f"데이터 수정: {data.get('컨테이너 번호')}")

def delete_row_from_gsheet(index, container_no):
    if spreadsheet is None: return
    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
    worksheet.delete_rows(index + 2)
    log_change(f"데이터 삭제: {container_no}")

def backup_data_to_new_sheet(container_data):
    if spreadsheet is None: return False, "스프레드시트 연결 안됨"
    try:
        today_str = date.today().isoformat()
        backup_sheet_name = f"백업_{today_str}"
        df_new = pd.DataFrame(container_data)
        
        if '등록일시' in df_new.columns:
            df_new['등록일시'] = pd.to_datetime(df_new['등록일시']).dt.strftime('%Y-%m-%d %H:%M:%S')
        if '완료일시' in df_new.columns:
            df_new['완료일시'] = pd.to_datetime(df_new['완료일시']).dt.strftime('%Y-%m-%d %H:%M:%S')

        for header in SHEET_HEADERS:
            if header not in df_new.columns:
                df_new[header] = ""
        df_new = df_new[SHEET_HEADERS]

        try:
            backup_sheet = spreadsheet.worksheet(backup_sheet_name)
            all_records = backup_sheet.get_all_records()
            if all_records:
                df_existing = pd.DataFrame(all_records)
                df_combined = pd.concat([df_existing, df_new])
                df_final = df_combined.drop_duplicates(subset=['컨테이너 번호'], keep='last')
            else:
                df_final = df_new
            backup_sheet.clear()
            backup_sheet.update([SHEET_HEADERS] + df_final.values.tolist())
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=backup_sheet_name, rows=100, cols=30)
            new_sheet.update([SHEET_HEADERS] + df_new.values.tolist())
        return True, None
    except Exception as e:
        return False, str(e)