import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date
import re
from utils import SHEET_HEADERS, MAIN_SHEET_NAME, load_data_from_gsheet, add_row_to_gsheet, update_row_in_gsheet, backup_data_to_new_sheet, connect_to_gsheet, log_change

# --- 앱 초기 설정 ---
st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")

# --- 초기화 함수와 성공 플래그 로직 ---
def clear_form_inputs():
    st.session_state["form_container_no"] = ""
    st.session_state["form_seal_no"] = ""
    st.session_state["form_destination"] = "베트남"
    st.session_state["form_feet"] = "40"

if st.session_state.get("submission_success", False):
    clear_form_inputs()
    st.session_state.submission_success = False

# --- 사이드바 스타일 ---
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { width: 150px !important; }
    [data-testid="stSidebar"] * { font-size: 22px !important; font-weight: bold !important; }
    [data-testid="stSidebar"] a { font-size: 22px !important; font-weight: bold !important; }
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] div,
    [data-testid="stSidebar"] span, [data-testid="stSidebar"] button { font-size: 22px !important; font-weight: bold !important; }
    @media (max-width: 768px) {
        [data-testid="stSidebar"] * { font-size: 22px !important; font-weight: bold !important; }
        [data-testid="stSidebar"] a { font-size: 22px !important; font-weight: bold !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 데이터 초기화 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

# --- 제목 (여백 조절됨) ---
st.markdown("""
    <div style="margin-top: -3rem;">
        <h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>
    </div>
""", unsafe_allow_html=True)

# --- 바코드 생성 ---
st.markdown("#### 🔳 바코드 생성")
with st.container(border=True):
    shippable_containers = [c.get('컨테이너 번호', '') for c in st.session_state.container_list if c.get('상태') == '선적중']
    shippable_containers = [c for c in shippable_containers if c]
    
    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        selected_for_barcode = st.selectbox("컨테이너를 선택하면 바코드가 자동 생성됩니다:", shippable_containers, label_visibility="collapsed")
        container_info = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_barcode), {})
        
        st.info(f"**출고처:** {container_info.get('출고처', 'N/A')} / **피트수:** {container_info.get('피트수', 'N/A')}")
        
        barcode_data = selected_for_barcode
        fp = BytesIO()
        Code128(barcode_data, writer=ImageWriter()).write(fp)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(fp)

st.divider()

# --- 컨테이너 현황 ---
st.markdown("#### 📋 컨테이너 현황")
# ... (카드 UI 부분은 동일)
completed_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적완료'])
pending_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적중'])
st.markdown(
    f"""
    <div class="row">
        <div class="col"><div class="metric-card"><div class="metric-value red-value">{pending_count}</div><div class="metric-label">선적중</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value green-value">{completed_count}</div><div class="metric-label">선적완료</div></div></div>
    </div>
    """, unsafe_allow_html=True
)

if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    df = pd.DataFrame(st.session_state.container_list)
    df['선적완료'] = df['상태'].apply(lambda x: True if x == '선적완료' else False)
    if '작업일자' in df.columns:
        df['작업일자'] = pd.to_datetime(df['작업일자'], errors='coerce').dt.strftime('%Y-%m-%d')
    df.fillna('', inplace=True)
    column_order = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '작업일자', '선적완료']
    
    edited_df = st.data_editor(
        df,
        column_order=column_order,
        use_container_width=True,
        hide_index=True,
        key="data_editor_toggle_reverted",
        column_config={
            "선적완료": st.column_config.CheckboxColumn("선적완료", help="체크하면 '선적완료'로 상태가 변경됩니다.", width="small"),
            "컨테이너 번호": st.column_config.TextColumn(disabled=True),
            "출고처": st.column_config.TextColumn(disabled=True),
            "피트수": st.column_config.TextColumn(disabled=True),
            "씰 번호": st.column_config.TextColumn(disabled=True),
            "작업일자": st.column_config.TextColumn(disabled=True),
        }
    )

    if edited_df is not None:
        edited_df['상태'] = edited_df['선적완료'].apply(lambda x: '선적완료' if x else '선적중')
        edited_list = edited_df[SHEET_HEADERS].to_dict('records')
        for i, (original_row, edited_row) in enumerate(zip(st.session_state.container_list, edited_list)):
            if original_row != edited_row:
                st.session_state.container_list[i] = edited_row
                update_row_in_gsheet(i, edited_row)
                st.rerun()

# <<<<<<<<<<<<<<< ✨ '데이터 백업' 버튼이 여기로 이동 및 수정되었습니다 ✨ >>>>>>>>>>>>>>>>>
st.markdown("#### 📁 데이터 백업")
st.info("하루 작업을 마친 후, 아래 버튼을 눌러 **'선적완료'된 데이터만 백업**하고, **'선적중'인 데이터는 내일로 이월**합니다.")
if st.button("🚀 데이터 백업", use_container_width=True, type="primary"):
    completed_data = [item for item in st.session_state.container_list if item.get('상태') == '선적완료']
    pending_data = [item for item in st.session_state.container_list if item.get('상태') == '선적중']
    total_count = len(st.session_state.container_list)
    completed_count = len(completed_data)
    pending_count = len(pending_data)
    backup_success = False
    if completed_data:
        success, error_msg = backup_data_to_new_sheet(completed_data)
        if success:
            st.success(f"'선적완료'된 {completed_count}개의 데이터를 백업 시트에 성공적으로 저장(또는 추가)했습니다!")
            backup_success = True
        else:
            st.error(f"백업 중 오류가 발생했습니다: {error_msg}")
    else:
        st.info("백업할 '선적완료' 상태의 데이터가 없습니다.")
        backup_success = True
    if backup_success:
        spreadsheet = connect_to_gsheet()
        if spreadsheet:
            worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
            worksheet.clear()
            worksheet.update('A1', [SHEET_HEADERS])
            if pending_data:
                df_pending = pd.DataFrame(pending_data)
                df_pending['작업일자'] = df_pending['작업일자'].apply(lambda x: x.isoformat() if isinstance(x, date) else x)
                worksheet.update('A2', df_pending[SHEET_HEADERS].values.tolist())
        
        log_message = f"하루 마감: 총 {total_count}개 중 {completed_count}개 백업, {pending_count}개 이월."
        log_change(log_message)
        
        st.session_state.container_list = pending_data
        st.success("데이터 백업 및 정리가 완료되었습니다. '선적중' 데이터만 남았습니다.")
        st.rerun()
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

st.divider()

# --- 신규 컨테이너 등록 ---
st.markdown("#### 📝 신규 컨테이너 등록")
with st.form(key="new_container_form"):
    # ... (신규 등록 폼 코드는 동일)
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("4. 씰 번호", key="form_seal_no")
    work_date = st.date_input("5. 작업일자", value=date.today())
    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    if submitted:
        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        if not container_no or not seal_no: 
            st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
        elif not pattern.match(container_no): 
            st.error("컨테이너 번호 형식이 올바르지 않습니다.")
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list): 
            st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
        else:
            new_container = {
                '컨테이너 번호': container_no, '출고처': destination, '피트수': feet, 
                '씰 번호': seal_no, '작업일자': work_date, '상태': '선적중'
            }
            st.session_state.container_list.append(new_container)
            add_row_to_gsheet(new_container)
            st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
            st.session_state.submission_success = True
            st.rerun()