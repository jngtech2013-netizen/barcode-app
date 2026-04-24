import streamlit as st
import pandas as pd
from utils import connect_to_gsheet, LOG_SHEET_NAME

st.set_page_config(page_title="변경 이력", layout="wide", initial_sidebar_state="expanded")

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

st.markdown("""
    <div style="margin-top: -3rem;">
        <h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>
    </div>
""", unsafe_allow_html=True)

st.markdown("#### 📋 변경 이력 조회")

col_refresh = st.columns([0.8, 0.2])
with col_refresh[1]:
    if st.button("🔄 새로고침", use_container_width=True):
        st.rerun()

# --- 로그 데이터 로드 ---
spreadsheet = connect_to_gsheet()
if not spreadsheet:
    st.error("Google Sheets 연결에 실패했습니다.")
    st.stop()

try:
    log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
    all_values = log_sheet.get_all_values()
except Exception as e:
    st.error(f"이력 시트를 불러오는 중 오류가 발생했습니다: {e}")
    st.stop()

if len(all_values) < 1:
    st.info("기록된 변경 이력이 없습니다.")
    st.stop()

# 헤더 없이 [타임스탬프, 액션] 형태로 저장되어 있으므로 직접 컬럼 지정
df_log = pd.DataFrame(all_values, columns=['일시', '내용'])
df_log['일시'] = pd.to_datetime(df_log['일시'], errors='coerce')
df_log = df_log.dropna(subset=['일시'])
df_log = df_log.sort_values('일시', ascending=False).reset_index(drop=True)

st.markdown("---")

# --- 필터 ---
with st.container(border=True):
    st.markdown("##### 필터 조건")
    col1, col2, col3 = st.columns(3)

    with col1:
        search_keyword = st.text_input("🔎 키워드 검색", placeholder="컨테이너 번호, 작업 내용 등")

    with col2:
        action_types = ['전체', '신규 등록', '데이터 수정', '데이터 삭제', '데이터 백업', '데이터 복구']
        selected_action = st.selectbox("📌 작업 유형", action_types)

    with col3:
        if df_log['일시'].notna().any():
            min_date = df_log['일시'].min().date()
            max_date = df_log['일시'].max().date()
            date_range = st.date_input(
                "📅 날짜 범위",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date
            )
        else:
            date_range = None

# --- 필터 적용 ---
filtered_log = df_log.copy()

if search_keyword:
    filtered_log = filtered_log[filtered_log['내용'].str.contains(search_keyword, na=False)]

if selected_action != '전체':
    filtered_log = filtered_log[filtered_log['내용'].str.contains(selected_action, na=False)]

if date_range and len(date_range) == 2:
    start_date, end_date = date_range
    filtered_log = filtered_log[
        (filtered_log['일시'].dt.date >= start_date) &
        (filtered_log['일시'].dt.date <= end_date)
    ]

st.markdown("---")

# --- 요약 카드 ---
total_logs = len(filtered_log)
reg_count = len(filtered_log[filtered_log['내용'].str.contains('신규 등록', na=False)])
mod_count = len(filtered_log[filtered_log['내용'].str.contains('데이터 수정', na=False)])
del_count = len(filtered_log[filtered_log['내용'].str.contains('데이터 삭제', na=False)])

st.markdown(
    f"""
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous">
    <style>
    .metric-card {{ padding: 1rem; border: 1px solid #DCDCDC; border-radius: 10px; text-align: center; margin-bottom: 10px; }}
    .metric-value {{ font-size: 2.5rem; font-weight: bold; }}
    .metric-label {{ font-size: 1rem; color: #555555; }}
    .blue-value {{ color: #1a73e8; }}
    .green-value {{ color: #28A745; }}
    .orange-value {{ color: #FF8C00; }}
    .red-value {{ color: #FF4B4B; }}
    </style>
    <div class="row">
        <div class="col"><div class="metric-card"><div class="metric-value blue-value">{total_logs}</div><div class="metric-label">전체 이력</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value green-value">{reg_count}</div><div class="metric-label">신규 등록</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value orange-value">{mod_count}</div><div class="metric-label">수정</div></div></div>
        <div class="col"><div class="metric-card"><div class="metric-value red-value">{del_count}</div><div class="metric-label">삭제</div></div></div>
    </div>
    """, unsafe_allow_html=True
)

st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

if filtered_log.empty:
    st.warning("조건에 맞는 이력이 없습니다.")
else:
    # 표시용 포맷
    display_log = filtered_log.copy()
    display_log['일시'] = display_log['일시'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # 작업 유형 컬러 뱃지
    def get_action_tag(content):
        if '신규 등록' in str(content):
            return '🟢 신규 등록'
        elif '데이터 수정' in str(content):
            return '🟡 수정'
        elif '데이터 삭제' in str(content):
            return '🔴 삭제'
        elif '데이터 백업' in str(content):
            return '🔵 백업'
        elif '데이터 복구' in str(content):
            return '🟣 복구'
        return '⚪ 기타'

    display_log['작업 유형'] = display_log['내용'].apply(get_action_tag)
    display_log = display_log[['일시', '작업 유형', '내용']]

    st.dataframe(
        display_log,
        use_container_width=True,
        hide_index=True,
        column_config={
            "일시": st.column_config.TextColumn("일시", width="medium"),
            "작업 유형": st.column_config.TextColumn("작업 유형", width="small"),
            "내용": st.column_config.TextColumn("내용", width="large"),
        }
    )

    # CSV 다운로드
    csv = display_log.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 이력 CSV 다운로드",
        data=csv,
        file_name=f"변경이력_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True
    )