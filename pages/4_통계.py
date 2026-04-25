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

# -------------------------------------------------------
# 데이터 범위 선택 (일별 / 월별)
# -------------------------------------------------------
st.markdown("##### 📅 분석 범위 선택")
range_type = st.radio("범위 유형", options=["월별", "일별"], horizontal=True)

spreadsheet = connect_to_gsheet()

def load_backup_sheet(sheet_name):
    """백업 시트에서 데이터 로드"""
    try:
        ws = spreadsheet.worksheet(sheet_name)
        values = ws.get_all_values()
        if len(values) >= 2:
            return pd.DataFrame(values[1:], columns=values[0], dtype=str)
    except Exception as e:
        st.error(f"시트 로드 오류: {e}")
    return pd.DataFrame()

df_selected = pd.DataFrame()

if range_type == "월별":
    if spreadsheet:
        all_sheets = [s.title for s in spreadsheet.worksheets()]
        # 월별 백업: 백업_YYYY-MM 형태 (길이 체크)
        monthly_sheets = sorted(
            [s for s in all_sheets if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 7],
            reverse=True
        )
        if monthly_sheets:
            selected_month = st.selectbox("월 선택", monthly_sheets)
            df_selected = load_backup_sheet(selected_month)
        else:
            st.info("월별 백업 시트가 없습니다.")
    else:
        st.error("Google Sheets 연결 실패")

elif range_type == "일별":
    if spreadsheet:
        all_sheets = [s.title for s in spreadsheet.worksheets()]
        # 일별 백업: 백업_YYYY-MM-DD 형태
        daily_sheets = sorted(
            [s for s in all_sheets if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 10],
            reverse=True
        )
        if daily_sheets:
            selected_day = st.selectbox("일 선택", daily_sheets)
            df_selected = load_backup_sheet(selected_day)
        else:
            st.info("일별 백업 시트가 없습니다.")
    else:
        st.error("Google Sheets 연결 실패")

if df_selected.empty:
    st.info("선택한 범위에 데이터가 없습니다.")
    st.stop()

# 선적완료 데이터만 필터
df_selected['피트수'] = pd.to_numeric(df_selected['피트수'], errors='coerce').fillna(0).astype(int)
df_selected['완료일시'] = pd.to_datetime(df_selected.get('완료일시', pd.NaT), errors='coerce')
df_selected['완료일'] = df_selected['완료일시'].dt.date

df_done = df_selected[df_selected['상태'] == '선적완료'].copy()

if df_done.empty:
    st.info("선택한 범위에 선적완료 데이터가 없습니다.")
    st.stop()

st.markdown("---")

# -------------------------------------------------------
# 요약 카드 (선적완료만)
# -------------------------------------------------------
completed = len(df_done)
total_ft = int(df_done['피트수'].sum())
ft40 = int(df_done[df_done['피트수'] == 40]['피트수'].sum())
ft20 = int(df_done[df_done['피트수'] == 20]['피트수'].sum())

st.markdown(
    f"""
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous">
    <style>
    .metric-card {{ padding: 1rem; border: 1px solid #DCDCDC; border-radius: 10px; text-align: center; margin-bottom: 10px; }}
    .metric-value {{ font-size: 2.5rem; font-weight: bold; }}
    .metric-label {{ font-size: 1rem; color: #555555; }}
    .green-value {{ color: #28A745; }}
    .blue-value {{ color: #1a73e8; }}
    </style>
    <div class="row">
        <div class="col"><div class="metric-card"><div class="metric-value green-value">{completed:,}</div><div class="metric-label">선적완료 건수</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value blue-value">{total_ft:,}</div><div class="metric-label">전체 피트수</div></div></div>
    </div>
    """, unsafe_allow_html=True
)

st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
st.markdown("---")

# -------------------------------------------------------
# 출고처별 현황 (전체 건수 / 전체 피트수 합계, 천자리 컴마)
# -------------------------------------------------------
st.markdown("##### 📦 출고처별 현황")

dest_group = df_done.groupby('출고처')

dest_stats = pd.DataFrame({
    '전체 건수': dest_group.size(),
    '전체 피트수(ft)': dest_group['피트수'].sum(),
}).fillna(0).astype(int)

dest_stats = dest_stats.sort_values('전체 피트수(ft)', ascending=False)
dest_stats.index.name = '출고처'

# 천자리 컴마 포맷
dest_stats_display = dest_stats.copy()
dest_stats_display['전체 건수'] = dest_stats_display['전체 건수'].apply(lambda x: f"{x:,}")
dest_stats_display['전체 피트수(ft)'] = dest_stats_display['전체 피트수(ft)'].apply(lambda x: f"{x:,}")

st.dataframe(dest_stats_display, use_container_width=True)

st.markdown("---")

# -------------------------------------------------------
# 일자별 현황 크로스 테이블 (출고처 × 날짜, 단위: ft)
# -------------------------------------------------------
st.markdown("##### 📅 일자별 현황 (단위: ft)")

if df_done['완료일'].notna().any():
    cross = df_done.groupby(['출고처', '완료일'])['피트수'].sum().unstack(fill_value=0)
    cross.index.name = '출고처'

    # 날짜 컬럼을 M/D 형식으로 변환 (크로스플랫폼 호환)
    cross.columns = [
        pd.Timestamp(str(c)).strftime('%m/%d').lstrip('0').replace('/0', '/')
        for c in cross.columns
    ]

    # 합계 행/열 추가
    cross['합계'] = cross.sum(axis=1)
    total_row = cross.sum(axis=0).rename('합계')
    cross = pd.concat([cross, total_row.to_frame().T])

    # 천자리 컴마 포맷 (applymap → map, pandas 최신 버전 대응)
    cross_display = cross.map(lambda x: f"{int(x):,}" if x != 0 else "-")

    st.dataframe(cross_display, use_container_width=True)
else:
    st.info("완료일시 데이터가 없습니다.")
