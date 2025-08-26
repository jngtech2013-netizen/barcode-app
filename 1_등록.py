import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date
import re
from utils import SHEET_HEADERS, load_data_from_gsheet, add_row_to_gsheet

# --- 앱 초기 설정 ---
st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")


# 방법 1: 더 구체적인 CSS 선택자 사용
st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 0.2rem !important;
        padding-bottom: 1rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 사이드바 스타일 ---
# (이전과 동일한 사이드바 스타일 코드)
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

# --- 이하 코드는 모두 기존과 동일합니다 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

st.markdown("<h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>", unsafe_allow_html=True)

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
    if not df.empty:
        for col in SHEET_HEADERS:
            if col not in df.columns: df[col] = pd.NA
        df['작업일자'] = df['작업일자'].apply(lambda x: pd.to_datetime(x).strftime('%Y-%m-%d') if pd.notna(x) else '')
        st.dataframe(df[SHEET_HEADERS], use_container_width=True, hide_index=True)

st.divider()

st.markdown("#### 📝 신규 컨테이너 등록")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True)
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True)
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