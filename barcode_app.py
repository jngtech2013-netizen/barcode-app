import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 관리 시스템")

# --- 데이터 관리 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = []

# --- 이메일 발송 공통 함수 ---
def send_excel_email(recipient, container_data):
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
# <<<<<<<<<<<<<<< [변경점] st.title을 st.header로 변경하여 제목 크기 축소 >>>>>>>>>>>>>>>>>
st.header("🚢 컨테이너 관리 시스템")
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# --- 1. (상단) 바코드 생성 섹션 ---
with st.expander("🔳 바코드 생성", expanded=True):
    shippable_containers = [c['컨테이너 번호'] for c in st.session_state.container_list if c['상태'] == '선적중']
    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        selected_for_barcode = st.selectbox("바코드를 생성할 컨테이너를 선택하세요:", shippable_containers)
        if selected_for_barcode:
            container_info = next((c for c in st.session_state.container_list if c['컨테이너 번호'] == selected_for_barcode), None)
            if container_info:
                st.info(f"**출고처:** {container_info['출고처']}")
        
        if st.button("바코드 생성하기", use_container_width=True, type="primary"):
            barcode_data = selected_for_barcode
            fp = BytesIO()
            Code128(barcode_data, writer=ImageWriter()).write(fp)
            
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.image(fp)

st.divider()

# --- 2. (중단) 신규 등록 및 전체 목록 ---
st.subheader("📋 컨테이너 목록")
with st.expander("📝 신규 컨테이너 등록하기"):
    with st.form(key="new_container_form"):
        destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
        container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
        work_date = st.date_input("2. 작업일자", value=date.today())
        destination = st.selectbox("3. 출고처", options=destinations)
        seal_no = st.text_input("4. 씰 번호")
        
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
                new_container = {'컨테이너 번호': container_no, '작업일자': work_date, '출고처': destination, '씰 번호': seal_no, '상태': '선적중'}
                st.session_state.container_list.append(new_container)
                st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
                st.rerun()

if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    df = pd.DataFrame(st.session_state.container_list)
    df['작업일자'] = pd.to_datetime(df['작업일자']).dt.strftime('%Y-%m-%d')
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()

# --- 3. (하단) 데이터 수정 섹션 ---
st.subheader("✏️ 개별 데이터 수정")
if not st.session_state.container_list:
    st.warning("수정할 데이터가 없습니다.")
else:
    container_numbers_for_edit = [c['컨테이너 번호'] for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정할 컨테이너를 선택하세요:", container_numbers_for_edit)
    selected_data = next((c for c in st.session_state.container_list if c['컨테이너 번호'] == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c['컨테이너 번호'] == selected_for_edit), -1)
    
    if selected_data:
        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            new_work_date = st.date_input("작업일자 수정", value=selected_data['작업일자'])
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            current_dest_idx = dest_options.index(selected_data['출고처'])
            new_dest = st.selectbox("출고처 수정", options=dest_options, index=current_dest_idx)
            new_seal = st.text_input("씰 번호 수정", value=selected_data['씰 번호'])
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data['상태'])
            new_status = st.selectbox("상태 변경", options=status_options, index=current_status_idx)
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                st.session_state.container_list[selected_idx] = {'컨테이너 번호': selected_for_edit, '작업일자': new_work_date, '출고처': new_dest, '씰 번호': new_seal, '상태': new_status}
                st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                st.rerun()

st.divider()

# --- 4. (최하단) 하루 마감 및 데이터 관리 섹션 ---
st.subheader("📁 하루 마감 및 데이터 관리")

st.info("데이터는 브라우저를 새로고침하거나 탭을 닫으면 사라질 수 있습니다. 중요한 작업 후에는 **중간 백업**을 권장합니다.")

recipient_email = st.text_input("데이터 백업 파일을 수신할 이메일 주소를 입력하세요:", key="recipient_email_main")

# 중간 백업 기능
if st.button("📧 현재 데이터 이메일로 중간 백업", use_container_width=True):
    if not st.session_state.container_list:
        st.warning("백업할 데이터가 없습니다.")
    elif not recipient_email:
        st.error("수신자 이메일 주소를 반드시 입력해야 합니다.")
    else:
        success, error_msg = send_excel_email(recipient_email, st.session_state.container_list)
        if success:
            st.success(f"'{recipient_email}' 주소로 중간 백업 이메일을 성공적으로 발송했습니다! 작업은 계속 유지됩니다.")
        else:
            st.error(f"백업 이메일 발송 중 오류가 발생했습니다: {error_msg}")

st.write("---")

# 하루 마감 기능 (이메일 발송 + 초기화)
st.error("주의: 아래 버튼은 데이터를 이메일로 보낸 후 **목록을 완전히 초기화**합니다. 하루 작업을 마칠 때만 사용하세요.")
if st.button("🚀 이메일 발송 후 새로 시작 (하루 마감)", use_container_width=True, type="primary"):
    if not st.session_state.container_list:
        st.warning("마감할 데이터가 없습니다.")
    elif not recipient_email:
        st.error("수신자 이메일 주소를 반드시 입력해야 합니다.")
    else:
        success, error_msg = send_excel_email(recipient_email, st.session_state.container_list)
        if success:
            st.success(f"'{recipient_email}' 주소로 최종 백업 이메일을 성공적으로 발송했습니다!")
            st.session_state.container_list = []
            st.success("데이터를 백업하고 목록을 초기화했습니다. 새로운 하루를 시작하세요!")
            st.rerun()
        else:
            st.error(f"최종 백업 이메일 발송 중 오류가 발생했습니다: {error_msg}")
            st.warning("이메일 발송에 실패하여 데이터를 초기화하지 않았습니다. Secrets 설정을 확인 후 다시 시도해주세요.")

st.write("---")

# 일괄 재등록 기능
with st.expander("⬆️ (필요시 사용) 백업 파일로 데이터 복구/일괄 등록"):
    st.info("실수로 데이터를 삭제했거나, 이전 데이터를 불러올 때 사용하세요.")
    uploaded_file = st.file_uploader("백업된 엑셀(xlsx) 파일을 업로드하세요.", type=['xlsx'])
    
    if uploaded_file is not None:
        try:
            df_upload = pd.read_excel(uploaded_file)
            required_columns = ['컨테이너 번호', '작업일자', '출고처', '씰 번호', '상태']
            if not all(col in df_upload.columns for col in required_columns):
                st.error("업로드한 파일의 컬럼이 앱의 형식과 다릅니다. 필요한 컬럼: " + ", ".join(required_columns))
            else:
                existing_nos = {c['컨테이너 번호'] for c in st.session_state.container_list}
                added_count = 0
                skipped_count = 0
                for index, row in df_upload.iterrows():
                    if row['컨테이너 번호'] not in existing_nos:
                        work_date_obj = pd.to_datetime(row['작업일자']).date()
                        new_entry = {'컨테이너 번호': row['컨테이너 번호'], '작업일자': work_date_obj, '출고처': row['출고처'], '씰 번호': row['씰 번호'], '상태': row['상태']}
                        st.session_state.container_list.append(new_entry)
                        added_count += 1
                    else:
                        skipped_count += 1
                st.success(f"일괄 등록 완료! {added_count}개의 새 데이터를 추가했고, {skipped_count}개의 중복 데이터를 건너뛰었습니다.")
                st.rerun()
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")