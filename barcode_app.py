import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date, datetime
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import gspread
from google.oauth2.service_account import Credentials

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 관리 시스템")

# --- Google Sheets 연동 및 데이터 관리 함수들 (이전과 동일) ---
SHEET_HEADERS = ['컨테이너 번호', '출고처', '씰 번호', '상태', '작업일자']

@st.cache_resource
def connect_to_gsheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open("Container_Data_DB") 
        return spreadsheet.sheet1
    except Exception as e:
        st.error(f"Google Sheets 연결에 실패했습니다: {e}")
        return None

worksheet = connect_to_gsheet()

def load_data_from_gsheet():
    if worksheet is None: return []
    all_values = worksheet.get_all_values()
    if len(all_values) < 2: return []
    data = all_values[1:]
    try:
        df = pd.DataFrame(data, columns=SHEET_HEADERS)
        df.replace('', pd.NA, inplace=True)
        if '작업일자' in df.columns:
            df['작업일자'] = pd.to_datetime(df['작업일자'], errors='coerce').dt.date
        return df.to_dict('records')
    except ValueError:
        st.error("Google Sheet의 데이터 형식이 올바르지 않습니다.")
        return []

def add_row_to_gsheet(data):
    if worksheet is None: return
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_insert = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.append_row(row_to_insert)

def update_row_in_gsheet(index, data):
    if worksheet is None: return
    if isinstance(data.get('작업일자'), date): data['작업일자'] = data['작업일자'].isoformat()
    row_to_update = [data.get(header, "") for header in SHEET_HEADERS]
    worksheet.update(f'A{index+2}:E{index+2}', [row_to_update])

def send_excel_email(recipient, container_data):
    # (이메일 발송 함수는 변경 없음)
    try:
        df_to_save = pd.DataFrame(container_data)
        df_to_save['작업일자'] = pd.to_datetime(df_to_save['작업일자']).dt.strftime('%Y-%m-%d')
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_to_save[SHEET_HEADERS].to_excel(writer, index=False, sheet_name='Sheet1')
        excel_data = output.getvalue()
        sender_email = st.secrets["email_credentials"]["username"]
        sender_password = st.secrets["email_credentials"]["password"]
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient
        msg['Subject'] = f"{date.today().isoformat()} 컨테이너 작업 데이터"
        msg.attach(MIMEText(f"{date.today().isoformat()}자 컨테이너 작업 데이터를 첨부 파일로 발송합니다.", 'plain'))
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_data)
        encoders.encode_base64(part)
        file_name = f"container_data_{date.today().isoformat()}.xlsx"
        part.add_header('Content-Disposition', f'attachment; filename="{file_name}"')
        msg.attach(part)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

# --- 데이터 초기화 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

# --- 화면 UI 구성 ---
st.subheader("🚢 컨테이너 관리 시스템")

# --- 1. (상단) 바코드 생성 섹션 (변경 없음) ---
with st.expander("🔳 바코드 생성", expanded=True):
    shippable_containers = [c['컨테이너 번호'] for c in st.session_state.container_list if c.get('상태') == '선적중']
    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        selected_for_barcode = st.selectbox("컨테이너를 선택하면 바코드가 자동 생성됩니다:", shippable_containers)
        container_info = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_barcode), None)
        if container_info:
            st.info(f"**출고처:** {container_info.get('출고처', 'N/A')}")
        barcode_data = selected_for_barcode
        fp = BytesIO()
        Code128(barcode_data, writer=ImageWriter()).write(fp)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(fp)

st.divider()

# --- 2. (중단) 전체 목록 및 신규 등록 ---
st.subheader("📋 컨테이너 목록")
if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    df = pd.DataFrame(st.session_state.container_list)
    if not df.empty and all(col in df.columns for col in SHEET_HEADERS):
        df['작업일자'] = df['작업일자'].apply(lambda x: pd.to_datetime(x).strftime('%Y-%m-%d') if pd.notna(x) else '')
        st.dataframe(df[SHEET_HEADERS], use_container_width=True, hide_index=True)

st.divider()

st.subheader("📝 신규 컨테이너 등록하기")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
    
    # <<<<<<<<<<<<<<< [변경점] st.selectbox를 st.radio로 변경 >>>>>>>>>>>>>>>>>
    destination = st.radio("2. 출고처", options=destinations, horizontal=True) # horizontal=True로 가로 배치
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
    
    seal_no = st.text_input("3. 씰 번호")
    work_date = st.date_input("4. 작업일자", value=date.today())
    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    if submitted:
        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        if not container_no or not seal_no: st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
        elif not pattern.match(container_no): st.error("컨테이너 번호 형식이 올바르지 않습니다. '영문 대문자 4자리 + 숫자 7자리' 형식으로 입력해주세요.")
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list): st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
        else:
            new_container = {'컨테이너 번호': container_no, '출고처': destination, '씰 번호': seal_no, '작업일자': work_date, '상태': '선적중'}
            st.session_state.container_list.append(new_container)
            add_row_to_gsheet(new_container)
            st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
            st.rerun()

st.divider()

# --- 3. (하단) 데이터 수정 섹션 (변경 없음) ---
st.subheader("✏️ 개별 데이터 수정")
# ... (이하 모든 코드는 이전과 동일)
if not st.session_state.container_list:
    st.warning("수정할 데이터가 없습니다.")
else:
    container_numbers_for_edit = [c.get('컨테이너 번호', '') for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정할 컨테이너를 선택하세요:", container_numbers_for_edit, key="edit_selector")
    selected_data = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c.get('컨테이너 번호') == selected_for_edit), -1)
    if selected_data:
        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            # 수정 폼의 selectbox는 그대로 둡니다. 키보드가 떠도 큰 문제가 되지 않기 때문입니다.
            current_dest_idx = dest_options.index(selected_data.get('출고처', dest_options[0]))
            new_dest = st.selectbox("출고처 수정", options=dest_options, index=current_dest_idx)
            new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data.get('상태', status_options[0]))
            new_status = st.selectbox("상태 변경", options=status_options, index=current_status_idx)
            work_date_value = selected_data.get('작업일자', date.today())
            if not isinstance(work_date_value, date):
                try: work_date_value = datetime.strptime(str(work_date_value), '%Y-%m-%d').date()
                except (ValueError, TypeError): work_date_value = date.today()
            new_work_date = st.date_input("작업일자 수정", value=work_date_value)
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                updated_data = {'컨테이너 번호': selected_for_edit, '출고처': new_dest, '씰 번호': new_seal, '상태': new_status, '작업일자': new_work_date}
                st.session_state.container_list[selected_idx] = updated_data
                update_row_in_gsheet(selected_idx, updated_data)
                st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                st.rerun()

st.divider()

st.subheader("📁 하루 마감 및 데이터 관리")
st.info("데이터는 모든 사용자가 공유하는 중앙 데이터베이스에 실시간으로 저장됩니다.")
recipient_email = st.text_input("데이터 백업 파일을 수신할 이메일 주소를 입력하세요:", key="recipient_email_main")
if st.button("🚀 이메일 발송 후 새로 시작 (하루 마감)", use_container_width=True, type="primary"):
    if not st.session_state.container_list: st.warning("마감할 데이터가 없습니다.")
    elif not recipient_email: st.error("수신자 이메일 주소를 반드시 입력해야 합니다.")
    else:
        success, error_msg = send_excel_email(recipient_email, st.session_state.container_list)
        if success:
            st.success(f"'{recipient_email}' 주소로 최종 백업 이메일을 성공적으로 발송했습니다!")
            if worksheet:
                worksheet.clear()
                worksheet.update('A1', [SHEET_HEADERS])
            st.session_state.container_list = []
            st.success("중앙 데이터베이스를 초기화했습니다. 새로운 하루를 시작하세요!")
            st.rerun()
        else:
            st.error(f"최종 백업 이메일 발송 중 오류가 발생했습니다: {error_msg}")
            st.warning("이메일 발송에 실패하여 데이터를 초기화하지 않았습니다.")

st.write("---")
with st.expander("⬆️ (필요시 사용) 백업 파일로 데이터 복구/일괄 등록"):
    st.info("실수로 데이터를 삭제했거나, 이전 데이터를 불러올 때 사용하세요.")
    uploaded_file = st.file_uploader("백업된 엑셀(xlsx) 파일을 업로드하세요.", type=['xlsx'])
    if uploaded_file is not None:
        try:
            df_upload = pd.read_excel(uploaded_file)
            required_columns = ['컨테이너 번호', '작업일자', '출고처', '씰 번호', '상태']
            if not all(col in df_upload.columns for col in required_columns): st.error("업로드한 파일의 컬럼이 앱의 형식과 다릅니다.")
            else:
                existing_nos = {c.get('컨테이너 번호') for c in st.session_state.container_list}
                temp_list_to_add = []
                for index, row in df_upload.iterrows():
                    if row['컨테이너 번호'] not in existing_nos:
                        work_date_obj = pd.to_datetime(row['작업일자']).date()
                        new_entry = {'컨테이너 번호': row['컨테이너 번호'], '작업일자': work_date_obj, '출고처': row['출고처'], '씰 번호': row['씰 번호'], '상태': row['상태']}
                        st.session_state.container_list.append(new_entry)
                        temp_list_to_add.append(new_entry)
                for entry in temp_list_to_add:
                    add_row_to_gsheet(entry)
                st.success(f"일괄 등록 완료! {len(temp_list_to_add)}개의 새 데이터를 추가했습니다.")
                st.rerun()
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")