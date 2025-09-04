import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date, datetime, timedelta
import re
from utils import SHEET_HEADERS, MAIN_SHEET_NAME, load_data_from_gsheet, add_row_to_gsheet, update_row_in_gsheet, backup_data_to_new_sheet, connect_to_gsheet, log_change

# --- 앱 초기 설정 ---
st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")

# --- 한국 시간 함수 ---
def get_korea_today():
    try:
        utc_now = datetime.utcnow()
        korea_now = utc_now + timedelta(hours=9)
        return korea_now.date()
    except:
        return date.today()

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
completed_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적완료'])
pending_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적중'])

st.markdown(
    f"""
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous">
    <style>
    .metric-card {{ padding: 1rem; border: 1px solid #DCDCDC; border-radius: 10px; text-align: center; margin-bottom: 10px; }}
    .metric-value {{ font-size: 2.5rem; font-weight: bold; }}
    .metric-label {{ font-size: 1rem; color: #555555; }}
    .red-value {{ color: #FF4B4B; }}
    .green-value {{ color: #28A745; }}
    </style>
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

if st.button("🚀 데이터 백업", use_container_width=True, type="primary"):
    completed_data = [item for item in st.session_state.container_list if item.get('상태') == '선적완료']
    pending_data = [item for item in st.session_state.container_list if item.get('상태') == '선적중']
    
    if completed_data:
        success, error_msg = backup_data_to_new_sheet(completed_data)
        if success:
            st.success(f"'선적완료'된 {len(completed_data)}개 데이터를 백업했습니다!")
            spreadsheet = connect_to_gsheet()
            if spreadsheet:
                worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
                worksheet.clear()
                worksheet.update('A1', [SHEET_HEADERS])
                if pending_data:
                    df_pending = pd.DataFrame(pending_data)
                    df_pending['작업일자'] = df_pending['작업일자'].apply(lambda x: x.isoformat() if isinstance(x, date) else x)
                    worksheet.update('A2', df_pending[SHEET_HEADERS].values.tolist())
            log_message = f"데이터 백업: {len(completed_data)}개 백업, {len(pending_data)}개 이월."
            log_change(log_message)
            st.session_state.container_list = pending_data
            st.rerun()
        else:
            st.error(f"백업 중 오류 발생: {error_msg}")
    else:
        st.info("백업할 '선적완료' 상태의 데이터가 없습니다.")

st.divider()

# --- 신규 컨테이너 등록 ---
st.markdown("#### 📝 신규 컨테이너 등록")

korea_today = get_korea_today()

with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("4. 씰 번호", key="form_seal_no")
    work_date = st.date_input("5. 작업일자", value=korea_today)
    
    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    
    # <<<<<<<<<<<<<<< ✨ 여기가 수정되었습니다 (안정성 강화) ✨ >>>>>>>>>>>>>>>>>
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
            
            with st.spinner('데이터를 저장하는 중...'):
                success, message = add_row_to_gsheet(new_container)
            
            if success:
                st.session_state.container_list.append(new_container)
                st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
                st.session_state.submission_success = True
                st.rerun()
            else:
                st.error(f"등록 실패: {message}. 잠시 후 다시 시도해주세요.")
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<