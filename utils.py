# utils.py

import streamlit as st
from datetime import date, datetime, timezone, timedelta
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 상수 정의 (공용) ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '작업일자']
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

# --- 로그 기록 및 데이터 관리 함수들 (이전과 동일) ---
# ... (log_change, load_data, add_row 등 모든 함수는 이전과 동일합니다)
def log_change(action):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")
def load_data_from_gsheet():
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return []
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        all_values = worksheet.get_all_values()
        if len(all_values) < 2: return []
        data = all_values[1:]
        df = pd.DataFrame(data, columns=SHEET_HEADERS)
        df.replace('', pd.NA, inplace=True)
        if '작업일자' in df.columns:
            df['작업일자'] = pd.to_datetime(df['작업일자'], errors='coerce').dt.date
        return df.to_dict('records')
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"'{MAIN_SHEET_NAME}' 시트를 찾을 수 없습니다.")
        return []
    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
        return []
def add_row_to_gsheet(data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return
    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_insert = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.append_row(row_to_insert)
    log_change(f"신규 등록: {data.get('컨테이너 번호')}")
def update_row_in_gsheet(index, data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return
    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_update = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.update(f'A{index+2}:F{index+2}', [row_to_update])
    log_change(f"데이터 수정: {data.get('컨테이너 번호')}")
def delete_row_from_gsheet(index, container_no):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return
    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
    worksheet.delete_rows(index + 2)
    log_change(f"데이터 삭제: {container_no}")
def backup_data_to_new_sheet(container_data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None: return False, "스프레드시트 연결 안됨"
    try:
        today_str = date.today().isoformat()
        backup_sheet_name = f"백업_{today_str}"
        df_new = pd.DataFrame(container_data)
        df_new['작업일자'] = pd.to_datetime(df_new['작업일자']).dt.strftime('%Y-%m-%d')
        try:
            backup_sheet = spreadsheet.worksheet(backup_sheet_name)
            all_values = backup_sheet.get_all_values()
            if len(all_values) > 1:
                df_existing = pd.DataFrame(all_values[1:], columns=SHEET_HEADERS)
                df_combined = pd.concat([df_existing, df_new])
                df_final = df_combined.drop_duplicates(subset=['컨테이너 번호'], keep='last')
            else:
                df_final = df_new
            backup_sheet.clear()
            backup_sheet.update('A1', [SHEET_HEADERS])
            backup_sheet.update('A2', df_final.values.tolist())
            log_change(f"데이터 덮어쓰기 백업: '{backup_sheet_name}' 시트 업데이트")
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=backup_sheet_name, rows=100, cols=20)
            new_sheet.update('A1', [SHEET_HEADERS])
            new_sheet.update('A2', df_new.values.tolist())
            log_change(f"데이터 신규 백업: '{backup_sheet_name}' 시트 생성")
        return True, None
    except Exception as e:
        return False, str(e)


# <<<<<<<<<<<<<<< [변경점] 하단 고정 탐색 바를 그리는 함수 추가 >>>>>>>>>>>>>>>>>
def render_footer():
    """
    모든 페이지 하단에 고정된 탐색 바를 렌더링하는 함수.
    HTML 링크를 사용하여 페이지를 전환합니다.
    """
    footer_html = """
    <style>
        .footer {
            position: fixed;
            left: 0;
            bottom: 0;
            width: 100%;
            background-color: white;
            border-top: 1px solid #EAEAEA;
            text-align: center;
            padding: 10px;
            z-index: 99;
            display: flex;
            justify-content: space-around;
            align-items: center;
        }
        .footer-link {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #333;
            font-size: 14px;
        }
        .footer-link:hover {
            color: #FF4B4B;
        }
        .footer-icon {
            font-size: 24px;
            margin-bottom: 4px;
        }
    </style>
    <div class="footer">
        <a href="/" target="_self" class="footer-link">
            <div class="footer-icon">📝</div>
            <div>등록</div>
        </a>
        <a href="/관리" target="_self" class="footer-link">
            <div class="footer-icon">⚙️</div>
            <div>관리</div>
        </a>
    </div>
    """
    st.markdown(footer_html, unsafe_allow_html=True)
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<