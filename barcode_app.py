import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date, datetime, timezone, timedelta
import re
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
# <<<<<<<<<<<<<<< [변경점] MediaIoUploader 대신 MediaIoBaseUpload를 임포트 >>>>>>>>>>>>>>>>>
from googleapiclient.http import MediaIoBaseUpload
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 관리 시스템")

# --- 상수 정의 ---
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '작업일자']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))

# --- Google Sheets 연동 ---
@st.cache_resource
def connect_to_gsheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open("Container_Data_DB")
        drive_service = build('drive', 'v3', credentials=creds)
        return spreadsheet, drive_service
    except Exception as e:
        st.error(f"Google 서비스 연결에 실패했습니다: {e}")
        return None, None

spreadsheet, drive_service = connect_to_gsheet()

# --- 로그 기록 함수 ---
def log_change(action):
    if spreadsheet is None: return
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except gspread.exceptions.WorksheetNotFound:
        st.warning(f"'{LOG_SHEET_NAME}' 시트를 찾을 수 없어 로그를 기록하지 못했습니다.")
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")

# --- 데이터 관리 함수 ---
def load_data_from_gsheet():
    if spreadsheet is None: return []
    worksheet = spreadsheet.sheet1
    all_values = worksheet.get_all_values()
    if len(all_values) < 2: return []
    data = all_values[1:]
    df = pd.DataFrame(data)
    num_data_columns = len(df.columns)
    df.columns = SHEET_HEADERS[:num_data_columns]
    df.replace('', pd.NA, inplace=True)
    if '작업일자' in df.columns:
        df['작업일자'] = pd.to_datetime(df['작업일자'], errors='coerce').dt.date
    return df.to_dict('records')

def add_row_to_gsheet(data):
    if spreadsheet is None: return
    worksheet = spreadsheet.sheet1
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_insert = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.append_row(row_to_insert)
    log_change(f"신규 등록: {data.get('컨테이너 번호')}")

def update_row_in_gsheet(index, data):
    if spreadsheet is None: return
    worksheet = spreadsheet.sheet1
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_update = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.update(f'A{index+2}:F{index+2}', [row_to_update])
    log_change(f"데이터 수정: {data.get('컨테이너 번호')}")

def delete_row_from_gsheet(index, container_no):
    if spreadsheet is None: return
    worksheet = spreadsheet.sheet1
    worksheet.delete_rows(index + 2)
    log_change(f"데이터 삭제: {container_no}")

# <<<<<<<<<<<<<<< [변경점] Google Drive 백업 함수를 최신 방식으로 수정 >>>>>>>>>>>>>>>>>
def save_excel_to_drive(container_data):
    try:
        df_to_save = pd.DataFrame(container_data)
        df_to_save['작업일자'] = pd.to_datetime(df_to_save['작업일자']).dt.strftime('%Y-%m-%d')
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_to_save[SHEET_HEADERS].to_excel(writer, index=False, sheet_name='Sheet1')
        
        # BytesIO 객체의 포인터를 처음으로 되돌립니다.
        output.seek(0)

        file_name = f"container_data_{date.today().isoformat()}.xlsx"
        file_metadata = {
            'name': file_name,
            'parents': [st.secrets["google_drive"]["backup_folder_id"]]
        }
        
        # MediaIoBaseUpload를 사용하여 미디어 객체를 생성합니다.
        media = MediaIoBaseUpload(output, 
                                  mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                  resumable=True)
        
        # 파일을 생성하고 업로드합니다.
        drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        return True, None
    except Exception as e:
        return False, str(e)
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# --- 데이터 초기화 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

# --- 화면 UI 구성 (이하 모든 UI 코드는 변경 없음) ---
st.subheader("🚢 컨테이너 관리 시스템")

with st.expander("🔳 바코드 생성", expanded=True):
    shippable_containers = [c['컨테이너 번호'] for c in st.session_state.container_list if c.get('상태') == '선적중']
    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        selected_for_barcode = st.selectbox("컨테이너를 선택하면 바코드가 자동 생성됩니다:", shippable_containers)
        container_info = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_barcode), None)
        if container_info:
            st.info(f"**출고처:** {container_info.get('출고처', 'N/A')} / **피트수:** {container_info.get('피트수', 'N/A')}")
        barcode_data = selected_for_barcode
        fp = BytesIO()
        Code128(barcode_data, writer=ImageWriter()).write(fp)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2: st.image(fp)

st.divider()

st.markdown("#### 📋 컨테이너 목록")
if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    df = pd.DataFrame(st.session_state.container_list)
    if not df.empty:
        for col in SHEET_HEADERS:
            if col not in df.columns: df[col] = pd.NA
        df['작업일자'] = df['작업일자'].apply(lambda x: pd.to_datetime(x).strftime('%Y-%m-%d') if pd.notna(x) else '')
        st.dataframe(df[SHEET_HEADERS], use_container_width=True, hide_index=True)

st.divider()

st.markdown("#### 📝 신규 컨테이너 등록하기")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True)
    feet = st.radio("3. 피트수", options=['20', '40'], horizontal=True)
    seal_no = st.text_input("4. 씰 번호")
    work_date = st.date_input("5. 작업일자", value=date.today())
    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    if submitted:
        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        if not container_no or not seal_no: st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
        elif not pattern.match(container_no): st.error("컨테이너 번호 형식이 올바르지 않습니다.")
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list): st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
        else:
            new_container = {'컨테이너 번호': container_no, '출고처': destination, '피트수': feet, '씰 번호': seal_no, '작업일자': work_date, '상태': '선적중'}
            st.session_state.container_list.append(new_container)
            add_row_to_gsheet(new_container)
            st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
            st.rerun()

st.divider()

st.markdown("#### ✏️ 개별 데이터 수정 및 삭제")
if not st.session_state.container_list:
    st.warning("수정할 데이터가 없습니다.")
else:
    container_numbers_for_edit = [c.get('컨테이너 번호', '') for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정 또는 삭제할 컨테이너를 선택하세요:", container_numbers_for_edit, key="edit_selector")
    selected_data = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c.get('컨테이너 번호') == selected_for_edit), -1)
    if selected_data:
        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            current_dest_idx = dest_options.index(selected_data.get('출고처', dest_options[0]))
            new_dest = st.radio("출고처 수정", options=dest_options, index=current_dest_idx, horizontal=True)
            feet_options = ['20', '40']
            current_feet_idx = feet_options.index(str(selected_data.get('피트수', feet_options[0])))
            new_feet = st.radio("피트수 수정", options=feet_options, index=current_feet_idx, horizontal=True)
            new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data.get('상태', status_options[0]))
            new_status = st.radio("상태 변경", options=status_options, index=current_status_idx, horizontal=True)
            work_date_value = selected_data.get('작업일자', date.today())
            if not isinstance(work_date_value, date):
                try: work_date_value = datetime.strptime(str(work_date_value), '%Y-%m-%d').date()
                except (ValueError, TypeError): work_date_value = date.today()
            new_work_date = st.date_input("작업일자 수정", value=work_date_value)
            
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                updated_data = {'컨테이너 번호': selected_for_edit, '출고처': new_dest, '피트수': new_feet, '씰 번호': new_seal, '상태': new_status, '작업일자': new_work_date}
                st.session_state.container_list[selected_idx] = updated_data
                update_row_in_gsheet(selected_idx, updated_data)
                st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                st.rerun()

        st.error("주의: 아래 버튼은 데이터를 영구적으로 삭제합니다.")
        if st.button("🗑️ 이 컨테이너 삭제", use_container_width=True):
            delete_row_from_gsheet(selected_idx, selected_for_edit)
            st.session_state.container_list.pop(selected_idx)
            st.success(f"'{selected_for_edit}' 컨테이너 정보가 삭제되었습니다.")
            st.rerun()

st.divider()

st.markdown("#### 📁 하루 마감 및 데이터 관리")
st.info("데이터는 모든 사용자가 공유하는 중앙 데이터베이스에 실시간으로 저장됩니다.")
if st.button("🚀 Google Drive에 백업 후 새로 시작 (하루 마감)", use_container_width=True, type="primary"):
    if not st.session_state.container_list: st.warning("마감할 데이터가 없습니다.")
    else:
        success, error_msg = save_excel_to_drive(st.session_state.container_list)
        if success:
            st.success("Google Drive에 최종 백업 파일을 성공적으로 저장했습니다!")
            if worksheet:
                worksheet.clear()
                worksheet.update('A1', [SHEET_HEADERS])
            st.session_state.container_list = []
            log_change("하루 마감 (데이터 초기화)")
            st.success("중앙 데이터베이스를 초기화했습니다. 새로운 하루를 시작하세요!")
            st.rerun()
        else:
            st.error(f"최종 백업 중 오류가 발생했습니다: {error_msg}")
            st.warning("백업에 실패하여 데이터를 초기화하지 않았습니다.")

st.write("---")

with st.expander("⬆️ (필요시 사용) 백업 파일로 데이터 복구/일괄 등록"):
    st.info("실수로 데이터를 삭제했거나, 이전 데이터를 불러올 때 사용하세요.")
    uploaded_file = st.file_uploader("백업된 엑셀(xlsx) 파일을 업로드하세요.", type=['xlsx'])
    if uploaded_file is not None:
        try:
            df_upload = pd.read_excel(uploaded_file)
            required_columns = ['컨테이너 번호', '작업일자', '출고처', '피트수', '씰 번호', '상태']
            if not all(col in df_upload.columns for col in required_columns): st.error("업로드한 파일의 컬럼이 앱의 형식과 다릅니다.")
            else:
                existing_nos = {c.get('컨테이너 번호') for c in st.session_state.container_list}
                temp_list_to_add = []
                for index, row in df_upload.iterrows():
                    if row['컨테이너 번호'] not in existing_nos:
                        work_date_obj = pd.to_datetime(row['작업일자']).date()
                        new_entry = {'컨테이너 번호': row['컨테이너 번호'], '출고처': row['출고처'], '피트수': str(row['피트수']), '씰 번호': row['씰 번호'], '상태': row['상태'], '작업일자': work_date_obj}
                        st.session_state.container_list.append(new_entry)
                        temp_list_to_add.append(new_entry)
                
                if temp_list_to_add:
                    log_change(f"일괄 등록: {len(temp_list_to_add)}개 데이터 추가")
                    for entry in temp_list_to_add:
                        add_row_to_gsheet(entry)
                    st.success(f"일괄 등록 완료! {len(temp_list_to_add)}개의 새 데이터를 추가했습니다.")
                    st.rerun()
                else:
                    st.warning("추가할 새로운 데이터가 없습니다 (모두 중복).")
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")