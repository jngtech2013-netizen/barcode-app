import streamlit as st
import pandas as pd
from utils import load_data_from_gsheet

st.set_page_config(page_title="검색/필터", layout="wide", initial_sidebar_state="expanded")

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

if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

st.markdown("""
    <div style="margin-top: -3rem;">
        <h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>
    </div>
""", unsafe_allow_html=True)

st.markdown("#### 🔍 검색 / 필터")

col_refresh = st.columns([0.8, 0.2])
with col_refresh[1]:
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.session_state.container_list = load_data_from_gsheet()
        st.rerun()

if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
    st.stop()

df = pd.DataFrame(st.session_state.container_list)

# 날짜 포맷
if '등록일시' in df.columns:
    df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce')
if '완료일시' in df.columns:
    df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce')

st.markdown("---")

# --- 필터 영역 ---
with st.container(border=True):
    st.markdown("##### 필터 조건")
    col1, col2, col3 = st.columns(3)

    with col1:
        # 컨테이너 번호 검색
        search_no = st.text_input("🔎 컨테이너 번호", placeholder="일부만 입력해도 됩니다")

    with col2:
        # 출고처 필터
        destinations = ['전체'] + sorted(df['출고처'].dropna().unique().tolist())
        selected_dest = st.selectbox("📦 출고처", destinations)

    with col3:
        # 상태 필터
        selected_status = st.selectbox("🚦 상태", ['전체', '선적중', '선적완료'])

    col4, col5 = st.columns(2)
    with col4:
        # 피트수 필터
        feet_options = ['전체'] + sorted(df['피트수'].dropna().unique().tolist())
        selected_feet = st.selectbox("📐 피트수", feet_options)

    with col5:
        # 등록일 범위 필터
        if '등록일시' in df.columns and df['등록일시'].notna().any():
            min_date = df['등록일시'].min().date()
            max_date = df['등록일시'].max().date()
            date_range = st.date_input(
                "📅 등록일 범위",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date
            )
        else:
            date_range = None

# --- 필터 적용 ---
filtered_df = df.copy()

if search_no:
    filtered_df = filtered_df[filtered_df['컨테이너 번호'].str.contains(search_no.upper(), na=False)]

if selected_dest != '전체':
    filtered_df = filtered_df[filtered_df['출고처'] == selected_dest]

if selected_status != '전체':
    filtered_df = filtered_df[filtered_df['상태'] == selected_status]

if selected_feet != '전체':
    filtered_df = filtered_df[filtered_df['피트수'] == selected_feet]

if date_range and len(date_range) == 2:
    start_date, end_date = date_range
    filtered_df = filtered_df[
        (filtered_df['등록일시'].dt.date >= start_date) &
        (filtered_df['등록일시'].dt.date <= end_date)
    ]

st.markdown("---")

# --- 결과 표시 ---
total = len(filtered_df)
pending = len(filtered_df[filtered_df['상태'] == '선적중'])
completed = len(filtered_df[filtered_df['상태'] == '선적완료'])

st.markdown(
    f"""
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous">
    <style>
    .metric-card {{ padding: 1rem; border: 1px solid #DCDCDC; border-radius: 10px; text-align: center; margin-bottom: 10px; }}
    .metric-value {{ font-size: 2.5rem; font-weight: bold; }}
    .metric-label {{ font-size: 1rem; color: #555555; }}
    .blue-value {{ color: #1a73e8; }}
    .red-value {{ color: #FF4B4B; }}
    .green-value {{ color: #28A745; }}
    </style>
    <div class="row">
        <div class="col"><div class="metric-card"><div class="metric-value blue-value">{total}</div><div class="metric-label">검색 결과</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value red-value">{pending}</div><div class="metric-label">선적중</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value green-value">{completed}</div><div class="metric-label">선적완료</div></div></div>
    </div>
    """, unsafe_allow_html=True
)

st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

if filtered_df.empty:
    st.warning("조건에 맞는 컨테이너가 없습니다.")
else:
    display_df = filtered_df.copy()
    display_df['등록일시'] = display_df['등록일시'].dt.strftime('%Y-%m-%d %H:%M').fillna('')
    display_df['완료일시'] = pd.to_datetime(display_df['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M').fillna('')
    display_df.fillna('', inplace=True)

    column_order = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시']
    st.dataframe(
        display_df[column_order],
        use_container_width=True,
        hide_index=True,
        column_config={
            "컨테이너 번호": st.column_config.TextColumn("컨테이너 번호"),
            "출고처": st.column_config.TextColumn("출고처"),
            "피트수": st.column_config.TextColumn("피트수"),
            "씰 번호": st.column_config.TextColumn("씰 번호"),
            "상태": st.column_config.TextColumn("상태"),
            "등록일시": st.column_config.TextColumn("등록일시"),
            "완료일시": st.column_config.TextColumn("완료일시"),
        }
    )

    # CSV 다운로드
    csv = display_df[column_order].to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 CSV 다운로드",
        data=csv,
        file_name=f"컨테이너_검색결과_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )
