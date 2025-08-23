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
from streamlit_local_storage import LocalStorage

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 관리 시스템")

# LocalStorage 객체 생성
localS = LocalStorage()

# --- 데이터 저장/불러오기 함수들 ---
def save_data_to_storage():
    list_to_save = []
    for item in st.session_state.container_list:
        new_item = item.copy()
        if isinstance(new_item.get('작업일자'), date):
            new_item['작업일자'] = new_item['작업일자'].isoformat()
        list_to_save.append(new_item)
    localS.setItem("container_list", list_to_save)

def load_data_from_storage():
    saved_list = localS.getItem("container_list") or []
    deserialized_list = []
    for item in saved_list:
        new_item = item.copy()
        if isinstance(new_item.get('작업일자'), str):
            try:
                new_item['작업일자'] = datetime.fromisoformat(new_item['작업일자']).date()
            except ValueError:
                new_item['작업일자'] = date.today()
        deserialized_list.append(new_item)
    return deserialized_list

# --- 데이터 관리 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_storage()

# --- 이메일 발송 공통 함수 (이전과 동일) ---
def send_excel_email(recipient, container_data):
    # (내용 변경 없음)
    try:
        df_to_save = pd.DataFrame(container_data)
        df_to_save['작업일자'] = pd.to_datetime(df_to_save['작업일자']).dt.strftime('%Y-%m-%d')
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_to_save.to_excel(writer, index=False, sheet_name='Sheet1')
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

# --- 화면 UI 구성 ---
st.header("🚢 컨테이너 관리 시스템")

# <<<<<<<<<<<<<<< [변경점 1] 바코드 자동 생성 로직 >>>>>>>>>>>>>>>>>
with st.expander("🔳 바코드 생성", expanded=True):
    shippable_containers = [c['컨테이너 번호'] for c in st.session_state.container_list if c['상태'] == '선적중']
    
    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        # 드롭다운 메뉴 생성
        selected_for_barcode = st.selectbox("컨테이너를 선택하면 바코드가 자동 생성됩니다:", shippable_containers)
        
        # 선택된 컨테이너 정보 찾기 및 출고처 표시
        container_info = next((c for c in st.session_state.container_list if c['컨테이너 번호'] == selected_for_barcode), None)
        if container_info:
            st.info(f"**출고처:** {container_info['출고처']}")

        # 버튼 없이 바로 바코드 생성 및 표시
        barcode_data = selected_for_barcode
        fp = BytesIO()
        Code128(barcode_data, writer=ImageWriter()).write(fp)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(fp)
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

st.divider()

st.subheader("📋 컨테이너 목록")
with st.expander("📝 신규 컨테이너 등록하기"):
    with st.form(key="new_container_form"):
        destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
        
        # <<<<<<<<<<<<<<< [변경점 2] 작업일자 입력 순서 변경 >>>>>>>>>>>>>>>>>
        container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
        destination = st.selectbox("2. 출고처", options=destinations)
        seal_no = st.text_input("3. 씰 번호")
        work_date = st.date_input("4. 작업일자", value=date.today())
        # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
        
        submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
        if submitted:
            pattern = re.compile(r'^[A-Z]{4}\d{7}$')
            if not container_no or not seal_no:
                st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
            elif not pattern.match(container_no):
                st.error("컨테이너 번호 형식이 올바르지 않습니다. '영문 대문자 4자리 + 숫자 7자리' 형식으로 입력해주세요.")
            elif any(c['컨테이너 번호'] == container_no for c in st.session_state.container_list):
                st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
            else:
                new_container = {'컨테이너 번호': container_no, '출고처': destination, '씰 번호': seal_no, '작업일자': work_date, '상태': '선적중'}
                st.session_state.container_list.append(new_container)
                st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
                save_data_to_storage()
                st.rerun()

if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    df = pd.DataFrame(st.session_state.container_list)
    df['작업일자'] = pd.to_datetime(df['작업일자']).dt.strftime('%Y-%m-%d')
    
    # <<<<<<<<<<<<<<< [변경점 3] 컬럼 표시 순서 변경 >>>>>>>>>>>>>>>>>
    column_order = ['컨테이너 번호', '출고처', '씰 번호', '상태', '작업일자']
    st.dataframe(df[column_order], use_container_width=True, hide_index=True)
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

st.divider()

st.subheader("✏️ 개별 데이터 수정")
if not st.session_state.container_list:
    st.warning("수정할 데이터가 없습니다.")
else:
    container_numbers_for_edit = [c['컨테이너 번호'] for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정할 컨테이너를 선택하세요:", container_numbers_for_edit, key="edit_selector")
    selected_data = next((c for c in st.session_state.container_list if c['컨테이너 번호'] == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c['컨테이너 번호'] == selected_for_edit), -1)
    if selected_data:
        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            
            # <<<<<<<<<<<<<<< [변경점 4] 작업일자 수정 순서 변경 >>>>>>>>>>>>>>>>>
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            current_dest_idx = dest_options.index(selected_data['출고처'])
            new_dest = st.selectbox("출고처 수정", options=dest_options, index=current_dest_idx)
            new_seal = st.text_input("씰 번호 수정", value=selected_data['씰 번호'])
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data['상태'])
            new_status = st.selectbox("상태 변경", options=status_options, index=current_status_idx)
            new_work_date = st.date_input("작업일자 수정", value=selected_data['작업일자'])
            # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
            
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                st.session_state.container_list[selected_idx] = {'컨테이너 번호': selected_for_edit, '출고처': new_dest, '씰 번호': new_seal, '상태': new_status, '작업일자': new_work_date}
                st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                save_data_to_storage()
                st.rerun()

st.divider()

# (하루 마감 및 데이터 관리 섹션은 변경 없음)
st.subheader("📁 하루 마감 및 데이터 관리")
# ...

# (스크립트 마지막 자동 저장 로직은 변경 없음)
save_data_to_storage()