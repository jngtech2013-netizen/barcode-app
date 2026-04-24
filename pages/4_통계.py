import streamlit as st
import pandas as pd
from utils import load_data_from_gsheet, connect_to_gsheet, BACKUP_PREFIX

st.set_page_config(page_title="통계 대시보드", layout="wide", initial_sidebar_state="expanded")

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

st.markdown("#### 📊 통계 대시보드")

col_refresh = st.columns([0.8, 0.2])
with col_refresh[1]:
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.session_state.container_list = load_data_from_gsheet()
        st.rerun()

# --- 데이터 범위 선택 ---
st.markdown("##### 📅 분석 범위 선택")
data_source = st.radio(
    "데이터 범위",
    options=["현재 데이터 (메인 시트)", "백업 데이터 포함 (월별)"],
    horizontal=True
)

df_all = pd.DataFrame(st.session_state.container_list)

if data_source == "백업 데이터 포함 (월별)":
    spreadsheet = connect_to_gsheet()
    if spreadsheet:
        all_sheets = [s.title for s in spreadsheet.worksheets()]
        monthly_sheets = sorted(
            [s for s in all_sheets if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 7],
            reverse=True
        )
        if monthly_sheets:
            selected_month = st.selectbox("월별 백업 시트 선택", monthly_sheets)
            try:
                ws = spreadsheet.worksheet(selected_month)
                values = ws.get_all_values()
                if len(values) >= 2:
                    df_backup = pd.DataFrame(values[1:], columns=values[0], dtype=str)
                    df_all = pd.concat([df_all, df_backup], ignore_index=True)
                    df_all = df_all.drop_duplicates(subset=['컨테이너 번호'], keep='last')
            except Exception as e:
                st.error(f"백업 시트 로드 오류: {e}")
        else:
            st.info("월별 백업 시트가 없습니다. 현재 데이터만 표시합니다.")

if df_all.empty:
    st.info("표시할 데이터가 없습니다.")
    st.stop()

df_all['등록일시'] = pd.to_datetime(df_all['등록일시'], errors='coerce')
df_all['완료일시'] = pd.to_datetime(df_all['완료일시'], errors='coerce')

st.markdown("---")

# --- 요약 카드 (선적중 / 선적완료만 표시) ---
pending = len(df_all[df_all['상태'] == '선적중'])
completed = len(df_all[df_all['상태'] == '선적완료'])

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
        <div class="col"><div class="metric-card"><div class="metric-value green-value">{completed}</div><div class="metric-label">선적완료</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value red-value">{pending}</div><div class="metric-label">선적중</div></div></div>
    </div>
    """, unsafe_allow_html=True
)

st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
st.markdown("---")

# --- 출고처별 현황 (피트수 합계 기준, 선적완료 / 선적중 / 합계 순) ---
st.markdown("##### 📦 출고처별 현황 (단위: ft)")
if '출고처' in df_all.columns:
    df_feet = df_all.copy()
    df_feet['피트수'] = pd.to_numeric(df_feet['피트수'], errors='coerce').fillna(0).astype(int)

    dest_stats = df_feet.groupby(['출고처', '상태'])['피트수'].sum().unstack(fill_value=0)
    if '선적중' not in dest_stats.columns:
        dest_stats['선적중'] = 0
    if '선적완료' not in dest_stats.columns:
        dest_stats['선적완료'] = 0
    dest_stats['합계'] = dest_stats['선적완료'] + dest_stats['선적중']
    dest_stats = dest_stats[['선적완료', '선적중', '합계']].sort_values('합계', ascending=False)
    dest_stats.index.name = '출고처'

    st.dataframe(dest_stats, use_container_width=True)