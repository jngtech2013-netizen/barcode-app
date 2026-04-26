import streamlit as st
from datetime import datetime, timezone, timedelta
import pandas as pd
import gspread
from gspread.utils import column_letter_to_index
from google.oauth2.service_account import Credentials

# --- 상수 정의 (공용) ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))
BACKUP_PREFIX = "백업_"

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

# --- 서식 강제 함수 ---
def ensure_text_format(worksheet, column_name):
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
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")

# --- 데이터 관리 함수들 (공용) ---
def load_data_from_gsheet():
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return []
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')

        all_values = worksheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        data = all_values[1:]

        df = pd.DataFrame(data, columns=headers, dtype=str)
        df.replace('', pd.NA, inplace=True)

        if '등록일시' in df.columns:
            df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce')
        if '완료일시' in df.columns:
            df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce')

        if '상태' in df.columns and '완료일시' in df.columns:
            inconsistent_rows = (df['상태'] == '선적중') & (df['완료일시'].notna())
            df.loc[inconsistent_rows, '완료일시'] = pd.NaT

        return df.to_dict('records')
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"'{MAIN_SHEET_NAME}' 시트를 찾을 수 없습니다.")
        return []
    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
        return []


def add_row_to_gsheet(data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
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


def add_rows_to_gsheet_batch(data_list):
    """여러 행을 한 번의 API 호출로 일괄 추가 (복구 시 사용)"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')

        rows_to_insert = []
        container_nos = []
        for data in data_list:
            data_copy = data.copy()
            if isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
                data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
            if pd.isna(data_copy.get('등록일시')) or data_copy.get('등록일시') is None:
                data_copy['등록일시'] = ''
            if isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
                data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')
            if pd.isna(data_copy.get('완료일시')) or data_copy.get('완료일시') is None:
                data_copy['완료일시'] = ''
            rows_to_insert.append([data_copy.get(header, "") for header in SHEET_HEADERS])
            container_nos.append(data_copy.get('컨테이너 번호', ''))

        worksheet.append_rows(rows_to_insert, value_input_option='USER_ENTERED')
        log_change(f"일괄 복구: {len(data_list)}개 ({', '.join(container_nos)})")
        return True, "성공"
    except Exception as e:
        st.error(f"Google Sheets 일괄 저장 중 오류 발생: {e}")
        return False, str(e)


def update_row_in_gsheet(index, data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        data_copy = data.copy()
        if isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')

        if data_copy.get('완료일시') is None or pd.isna(data_copy.get('완료일시')):
            data_copy['완료일시'] = ''
        elif isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_update = [data_copy.get(header, "") for header in SHEET_HEADERS]
        worksheet.update(f'A{index+2}:G{index+2}', [row_to_update], value_input_option='USER_ENTERED')
        log_change(f"데이터 수정: {data_copy.get('컨테이너 번호')}")
    except Exception as e:
        st.error(f"Google Sheets 업데이트 중 오류가 발생했습니다: {e}")


def delete_row_from_gsheet(index, container_no):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        worksheet.delete_rows(index + 2)
        log_change(f"데이터 삭제: {container_no}")
    except Exception as e:
        st.error(f"Google Sheets에서 행 삭제 중 오류가 발생했습니다: {e}")


def delete_from_backup_sheets(container_nos, source_sheet_name):
    """복구된 컨테이너를 해당 일별/월별 백업 시트에서만 삭제
    source_sheet_name: 복구한 시트명 (예: 백업_2025-04-25 또는 백업_2025-04)
    """
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        container_nos_set = set(container_nos)

        # 복구한 시트명에서 날짜 추출 후 관련 시트 목록 결정
        date_part = source_sheet_name.replace(BACKUP_PREFIX, '')  # 예: 2025-04-25 or 2025-04

        if len(date_part) == 10:
            # 일별 시트에서 복구한 경우 → 해당 일별 + 해당 월별 시트
            month_part = date_part[:7]  # 2025-04
            target_sheets = [
                f"{BACKUP_PREFIX}{date_part}",   # 백업_2025-04-25
                f"{BACKUP_PREFIX}{month_part}",  # 백업_2025-04
            ]
        elif len(date_part) == 7:
            # 월별 시트에서 복구한 경우 → 해당 월별 시트만 (일별은 이미 정리됐을 수 있음)
            target_sheets = [f"{BACKUP_PREFIX}{date_part}"]  # 백업_2025-04
        else:
            return False, f"시트명 형식을 인식할 수 없습니다: {source_sheet_name}"

        total_deleted = 0
        all_sheet_titles = [s.title for s in spreadsheet.worksheets()]

        for sheet_name in target_sheets:
            if sheet_name not in all_sheet_titles:
                continue
            try:
                ws = spreadsheet.worksheet(sheet_name)
                all_values = ws.get_all_values()
                if len(all_values) < 2:
                    continue

                headers = all_values[0]
                if '컨테이너 번호' not in headers:
                    continue

                col_idx = headers.index('컨테이너 번호')

                # 삭제할 행 번호를 역순으로 수집
                rows_to_delete = [
                    i + 2  # 헤더(1행) + 0-index 보정
                    for i, row in enumerate(all_values[1:])
                    if len(row) > col_idx and row[col_idx] in container_nos_set
                ]

                for row_num in sorted(rows_to_delete, reverse=True):
                    ws.delete_rows(row_num)
                    total_deleted += 1

            except Exception:
                continue

        log_change(f"백업 시트 정리: {len(container_nos)}개 복구 후 {target_sheets}에서 {total_deleted}행 삭제")
        return True, total_deleted

    except Exception as e:
        return False, str(e)


def backup_data_to_new_sheet(container_data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "스프레드시트 연결 안됨"
    try:
        df_new = pd.DataFrame(container_data)

        if '등록일시' in df_new.columns:
            df_new['등록일시'] = pd.to_datetime(df_new['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '완료일시' in df_new.columns:
            df_new['완료일시'] = pd.to_datetime(df_new['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '씰 번호' in df_new.columns:
            df_new['씰 번호'] = df_new['씰 번호'].astype(str)
        for header in SHEET_HEADERS:
            if header not in df_new.columns:
                df_new[header] = ""
        df_new = df_new[SHEET_HEADERS]

        kst_now = datetime.now(KST)

        # --- 1. 일별 백업 (Daily Report & Restore Point) ---
        today_str = kst_now.date().isoformat()
        daily_backup_name = f"{BACKUP_PREFIX}{today_str}"
        try:
            backup_sheet = spreadsheet.worksheet(daily_backup_name)
            ensure_text_format(backup_sheet, '씰 번호')
            existing_values = backup_sheet.get_all_values()
            if len(existing_values) > 1:
                df_existing = pd.DataFrame(existing_values[1:], columns=existing_values[0], dtype=str)
                df_combined = pd.concat([df_existing, df_new])
                df_final = df_combined.drop_duplicates(subset=['컨테이너 번호'], keep='last')
                backup_sheet.clear()
                backup_sheet.update('A1', [SHEET_HEADERS] + df_final.values.tolist(), value_input_option='USER_ENTERED')
            else:
                # 헤더만 있거나 빈 시트인 경우 A1부터 명시적으로 덮어쓰기
                backup_sheet.update('A1', [SHEET_HEADERS] + df_new.values.tolist(), value_input_option='USER_ENTERED')
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=daily_backup_name, rows=len(df_new) + 50, cols=len(SHEET_HEADERS))
            new_sheet.update('A1', [SHEET_HEADERS], value_input_option='USER_ENTERED')
            ensure_text_format(new_sheet, '씰 번호')
            if not df_new.empty:
                new_sheet.update('A2', df_new.values.tolist(), value_input_option='USER_ENTERED')

        # --- 2. 월별 통합 백업 (Monthly Aggregation) ---
        month_str = kst_now.date().strftime('%Y-%m')
        monthly_backup_name = f"{BACKUP_PREFIX}{month_str}"
        try:
            backup_sheet = spreadsheet.worksheet(monthly_backup_name)
            ensure_text_format(backup_sheet, '씰 번호')
            existing_values = backup_sheet.get_all_values()
            if len(existing_values) > 1:
                existing_df = pd.DataFrame(existing_values[1:], columns=existing_values[0], dtype=str)
                new_unique_df = df_new[~df_new['컨테이너 번호'].isin(existing_df['컨테이너 번호'])]
            else:
                new_unique_df = df_new
            if not new_unique_df.empty:
                backup_sheet.append_rows(new_unique_df.values.tolist(), value_input_option='USER_ENTERED')
        except gspread.exceptions.WorksheetNotFound:
            # 월별 시트는 한 달 누적 데이터를 담으므로 넉넉하게 1000행으로 고정
            new_sheet = spreadsheet.add_worksheet(title=monthly_backup_name, rows=1000, cols=len(SHEET_HEADERS))
            new_sheet.update('A1', [SHEET_HEADERS], value_input_option='USER_ENTERED')
            ensure_text_format(new_sheet, '씰 번호')
            if not df_new.empty:
                new_sheet.update('A2', df_new.values.tolist(), value_input_option='USER_ENTERED')

        return True, None
    except Exception as e:
        return False, str(e)


def cleanup_old_daily_sheets(months=3):
    """3개월 이상 된 일별 백업 시트 삭제 (월별 시트는 보존)"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        from datetime import date
        cutoff_date = datetime.now(KST).date() - timedelta(days=months * 30)

        all_sheets = [s.title for s in spreadsheet.worksheets()]
        # 일별 시트만 대상: 백업_YYYY-MM-DD (길이 체크)
        daily_sheets = [
            s for s in all_sheets
            if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 10
        ]

        deleted_sheets = []
        for sheet_name in daily_sheets:
            date_part = sheet_name.replace(BACKUP_PREFIX, '')
            try:
                sheet_date = datetime.strptime(date_part, '%Y-%m-%d').date()
                if sheet_date < cutoff_date:
                    spreadsheet.del_worksheet(spreadsheet.worksheet(sheet_name))
                    deleted_sheets.append(sheet_name)
            except ValueError:
                continue

        if deleted_sheets:
            log_change(f"일별 백업 정리: {len(deleted_sheets)}개 시트 삭제 ({', '.join(deleted_sheets)})")

        return True, deleted_sheets

    except Exception as e:
        return False, str(e)


def archive_log_sheet(keep_rows=200):
    """로그 시트가 1000행 초과 시 오래된 로그를 분기별 아카이브 시트로 이관"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        all_values = log_sheet.get_all_values()
        total_rows = len(all_values)

        if total_rows <= 1000:
            return False, f"현재 {total_rows}행으로 아카이브 기준(1000행) 미만입니다."

        # 이관할 행: 최근 keep_rows행을 제외한 나머지
        rows_to_archive = all_values[:total_rows - keep_rows]
        rows_to_keep = all_values[total_rows - keep_rows:]

        if not rows_to_archive:
            return False, "이관할 데이터가 없습니다."

        # 분기 계산 (첫 번째 이관 행의 날짜 기준)
        try:
            first_date = datetime.strptime(rows_to_archive[0][0][:10], '%Y-%m-%d')
            quarter = (first_date.month - 1) // 3 + 1
            archive_name = f"로그_{first_date.year}-Q{quarter}"
        except Exception:
            archive_name = f"로그_아카이브_{datetime.now(KST).strftime('%Y%m%d')}"

        # 아카이브 시트에 저장 (기존 시트가 있으면 이어붙이기)
        all_sheet_titles = [s.title for s in spreadsheet.worksheets()]
        if archive_name in all_sheet_titles:
            archive_sheet = spreadsheet.worksheet(archive_name)
            archive_sheet.append_rows(rows_to_archive, value_input_option='USER_ENTERED')
        else:
            archive_sheet = spreadsheet.add_worksheet(title=archive_name, rows=len(rows_to_archive) + 50, cols=2)
            archive_sheet.update('A1', rows_to_archive, value_input_option='USER_ENTERED')

        # 메인 로그 시트는 최근 keep_rows행만 남기기
        log_sheet.clear()
        log_sheet.update('A1', rows_to_keep, value_input_option='USER_ENTERED')

        log_change(f"로그 아카이브: {len(rows_to_archive)}행 → '{archive_name}'으로 이관, {len(rows_to_keep)}행 유지")
        return True, (archive_name, len(rows_to_archive))

    except Exception as e:
        return False, str(e)
