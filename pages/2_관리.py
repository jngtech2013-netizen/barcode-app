import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone, timedelta
from utils import (
    SHEET_HEADERS,
    MAIN_SHEET_NAME,
    load_data_from_gsheet, 
    add_row_to_gsheet, 
    update_row_in_gsheet, 
    delete_row_from_gsheet, 
    backup_data_to_new_sheet,
    log_change,
    connect_to_gsheet,
    refresh_container_data,
    ensure_data_sync,
    manual_refresh_data,
    validate_data_consistency
)

# --- 앱 초기 설정 ---
st.set_page_config(page_title="관리 페이지", layout="wide", initial_sidebar_state="expanded")

# --- CSS 스타일 ---
st.markdown(
    """
    <style>
    /* 사이드바 스타일 */
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

# --- 데이터 초기화 및 동기화 확인 ---
st.session_state.container_list = ensure_data_sync()

# --- 제목과 데이터 상태 표시 ---
st.markdown("""
    <div style="margin-top: -3rem;">
        <h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>
    </div>
""", unsafe_allow_html=True)

# 데이터 동기화 상태 표시
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    last_refresh = st.session_state.get('last_refresh_time')
    if last_refresh:
        st.caption(f"마지막 업데이트: {last_refresh.strftime('%H:%M:%S')}")
    else:
        st.caption("데이터 로딩 중...")

with col2:
    if st.button("🔄 새로고침", help="구글시트에서 최신 데이터를 가져옵니다"):
        manual_refresh_data()
        st.rerun()

with col3:
    # 데이터 일치 상태 표시
    is_synced = validate_data_consistency()
    if is_synced:
        st.success("🟢 동기화됨", help="앱과 구글시트 데이터가 일치합니다")
    else:
        st.warning("🟡 확인 필요", help="데이터 불일치 가능성. 새로고침을 권장합니다")

# --- 데이터 수정 및 삭제 ---
st.markdown("#### ✏️ 데이터 수정 및 삭제")

if st.session_state.container_list:
    container_numbers_for_edit = [c.get('컨테이너 번호', '') for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정 또는 삭제할 컨테이너를 선택하세요:", container_numbers_for_edit, key="edit_selector")
    selected_data = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c.get('컨테이너 번호') == selected_for_edit), -1)
    
    if selected_data:
        registration_time = selected_data.get('등록일시')
        completion_time = selected_data.get('완료일시')
        if registration_time and pd.notna(registration_time):
            st.info(f"등록일시: {pd.to_datetime(registration_time).strftime('%Y-%m-%d %H:%M')}")
        if completion_time and pd.notna(completion_time):
            st.info(f"완료일시: {pd.to_datetime(completion_time).strftime('%Y-%m-%d %H:%M')}")

        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            current_dest_idx = dest_options.index(selected_data.get('출고처', '베트남'))
            new_dest = st.radio("출고처 수정", options=dest_options, index=current_dest_idx, horizontal=True)
            feet_options = ['40', '20']
            current_feet_idx = feet_options.index(str(selected_data.get('피트수', '40')))
            new_feet = st.radio("피트수 수정", options=feet_options, index=current_feet_idx, horizontal=True)
            new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data.get('상태', '선적중'))
            new_status = st.radio("상태 변경", options=status_options, index=current_status_idx, horizontal=True)
            
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                updated_data = {
                    '컨테이너 번호': selected_for_edit, '출고처': new_dest, '피트수': new_feet, 
                    '씰 번호': str(new_seal), '상태': new_status,
                    '등록일시': registration_time,
                    '완료일시': completion_time
                }
                
                # 상태 변경에 따른 완료일시 처리
                if new_status == '선적완료' and not completion_time:
                    updated_data['완료일시'] = datetime.now(timezone(timedelta(hours=9)))
                elif new_status == '선적중':
                    updated_data['완료일시'] = None

                # 구글시트 업데이트 (자동으로 세션 상태도 새로고침됨)
                with st.spinner('수정사항을 저장하는 중...'):
                    if update_row_in_gsheet(selected_idx, updated_data):
                        st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                        st.rerun()
                    else:
                        st.error("수정 중 오류가 발생했습니다. 다시 시도해주세요.")
        
        st.error("주의: 아래 버튼은 데이터를 영구적으로 삭제합니다.")
        if st.button("🗑️ 이 컨테이너 삭제", use_container_width=True):
            with st.spinner('데이터를 삭제하는 중...'):
                if delete_row_from_gsheet(selected_idx, selected_for_edit):
                    st.success(f"'{selected_for_edit}' 컨테이너 정보가 삭제되었습니다.")
                    st.rerun()
                else:
                    st.error("삭제 중 오류가 발생했습니다. 다시 시도해주세요.")
else:
    st.info("현재 데이터가 없습니다.")

# --- 백업 시트에서 데이터 복구 ---
st.divider()
st.markdown("#### ⬆️ 데이터 복구")
st.info("실수로 데이터를 초기화했거나 이전 데이터를 추가할 때 사용하세요.")

spreadsheet = connect_to_gsheet()
if spreadsheet:
    all_sheets = [s.title for s in spreadsheet.worksheets()]
    backup_sheets = sorted([s for s in all_sheets if s.startswith("백업_")], reverse=True)
    if not backup_sheets:
        st.warning("복구할 백업 시트가 없습니다.")
    else:
        selected_backup_sheet = st.selectbox(
            "복구할 백업 시트를 선택하세요:", 
            backup_sheets, 
            key="backup_sheet_selector"
        )
        
        if selected_backup_sheet:
            try:
                backup_worksheet = spreadsheet.worksheet(selected_backup_sheet)
                backup_records = backup_worksheet.get_all_records()

                if not backup_records:
                    st.info("선택한 백업 시트에는 데이터가 없습니다.")
                else:
                    df_backup = pd.DataFrame(backup_records)
                    
                    if '씰 번호' in df_backup.columns:
                        df_backup['씰 번호'] = df_backup['씰 번호'].astype(str)

                    # 옛날 백업 시트에 없는 컬럼 추가
                    if '등록일시' not in df_backup.columns:
                        df_backup['등록일시'] = pd.NA
                    if '완료일시' not in df_backup.columns:
                        df_backup['완료일시'] = pd.NA
                    
                    st.markdown("##### 📋 선택된 백업 시트 현황")
                    if '상태' in df_backup.columns:
                        status_counts = df_backup['상태'].value_counts()
                        pending_count = status_counts.get('선적중', 0)
                        completed_count = status_counts.get('선적완료', 0)
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
                    
                    existing_nos = {c.get('컨테이너 번호') for c in st.session_state.container_list}
                    recoverable_df = df_backup[~df_backup['컨테이너 번호'].isin(existing_nos)].copy()

                    if recoverable_df.empty:
                        st.success("백업 시트의 모든 데이터가 이미 현재 목록에 존재합니다.")
                    else:
                        st.markdown("---")
                        st.markdown("##### 1. 개별 컨테이너 선택 복구")
                        st.write("아래 테이블에서 복구할 컨테이너를 선택하세요.")

                        recoverable_df.insert(0, '선택', False)
                        recoverable_df.insert(1, 'No.', range(1, len(recoverable_df) + 1))
                        
                        display_order = ['선택', 'No.'] + [h for h in SHEET_HEADERS if h in recoverable_df.columns]
                        
                        edited_df = st.data_editor(
                            recoverable_df,
                            column_order=display_order,
                            use_container_width=True,
                            hide_index=True,
                            key=f"recovery_editor_{selected_backup_sheet}",
                            column_config={
                                "선택": st.column_config.CheckboxColumn(),
                                "No.": st.column_config.NumberColumn(disabled=True),
                                "컨테이너 번호": st.column_config.TextColumn(disabled=True),
                                "출고처": st.column_config.TextColumn(disabled=True),
                                "피트수": st.column_config.TextColumn(disabled=True),
                                "씰 번호": st.column_config.TextColumn(disabled=True),
                                "상태": st.column_config.TextColumn(disabled=True),
                                "등록일시": st.column_config.TextColumn(disabled=True),
                                "완료일시": st.column_config.TextColumn(disabled=True),
                            }
                        )
                        
                        selected_rows = edited_df[edited_df['선택']]

                        if not selected_rows.empty:
                            if st.button(f"선택된 {len(selected_rows)}개 컨테이너 복구하기", use_container_width=True, type="primary"):
                                with st.spinner(f'{len(selected_rows)}개 컨테이너를 복구하는 중...'):
                                    added_count = 0
                                    for index, row in selected_rows.iterrows():
                                        row_to_add = row.to_dict()
                                        # 날짜 처리
                                        try: 
                                            row_to_add['등록일시'] = pd.to_datetime(row_to_add.get('등록일시')).to_pydatetime()
                                        except: 
                                            row_to_add['등록일시'] = None
                                        try: 
                                            row_to_add['완료일시'] = pd.to_datetime(row_to_add.get('완료일시')).to_pydatetime()
                                        except: 
                                            row_to_add['완료일시'] = None
                                        
                                        # 구글시트에 추가 (자동으로 세션 상태도 새로고침됨)
                                        success, message = add_row_to_gsheet(row_to_add)
                                        if success:
                                            added_count += 1
                                
                                log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {added_count}개 선택 복구")
                                st.success(f"'{selected_backup_sheet}' 시트에서 {added_count}개의 컨테이너를 성공적으로 복구했습니다!")
                                st.rerun()

                        st.divider()
                        st.markdown("##### 2. 시트 전체 복구 (현재 목록에 없는 데이터만)")
                        st.warning("주의: 이 작업은 위 테이블에 보이는 모든 컨테이너를 한 번에 추가합니다.")
                        
                        if st.button(f"'{selected_backup_sheet}' 시트의 모든 데이터 추가하기", use_container_width=True):
                            with st.spinner(f'{len(recoverable_df)}개 컨테이너를 복구하는 중...'):
                                added_count = 0
                                for index, row in recoverable_df.iterrows():
                                    row_to_add = row.to_dict()
                                    # 날짜 처리
                                    try: 
                                        row_to_add['등록일시'] = pd.to_datetime(row_to_add.get('등록일시')).to_pydatetime()
                                    except: 
                                        row_to_add['등록일시'] = None
                                    try: 
                                        row_to_add['완료일시'] = pd.to_datetime(row_to_add.get('완료일시')).to_pydatetime()
                                    except: 
                                        row_to_add['완료일시'] = None
                                    
                                    # 구글시트에 추가 (자동으로 세션 상태도 새로고침됨)
                                    success, message = add_row_to_gsheet(row_to_add)
                                    if success:
                                        added_count += 1
                                        
                                log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {added_count}개 전체 복구")
                                st.success(f"'{selected_backup_sheet}' 시트에서 {added_count}개의 새로운 데이터를 성공적으로 추가했습니다!")
                                st.rerun()

            except Exception as e:
                st.error(f"백업 시트 정보를 불러오는 중 오류가 발생했습니다: {e}")

st.divider()

# --- 추가 관리 기능 ---
st.markdown("#### 🛠️ 시스템 관리")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🔄 전체 데이터 새로고침", use_container_width=True, type="secondary"):
        with st.spinner('구글시트에서 전체 데이터를 다시 로드하는 중...'):
            fresh_data = load_data_from_gsheet()
            st.session_state.container_list = fresh_data
            st.session_state.last_refresh_time = datetime.now(timezone(timedelta(hours=9)))
            st.success(f"전체 데이터 새로고침 완료! ({len(fresh_data)}개 항목)")
            st.rerun()

with col2:
    if st.button("📊 데이터 통계", use_container_width=True, type="secondary"):
        if st.session_state.container_list:
            total = len(st.session_state.container_list)
            pending = len([x for x in st.session_state.container_list if x.get('상태') == '선적중'])
            completed = len([x for x in st.session_state.container_list if x.get('상태') == '선적완료'])
            
            st.info(f"""
            📈 **데이터 현황**
            - 전체: {total}개
            - 선적중: {pending}개 ({pending/total*100:.1f}%)
            - 선적완료: {completed}개 ({completed/total*100:.1f}%)
            """)
        else:
            st.info("표시할 데이터가 없습니다.")

with col3:
    if st.button("🔍 연결 상태 확인", use_container_width=True, type="secondary"):
        test_connection = connect_to_gsheet()
        if test_connection:
            st.success("✅ 구글시트 연결 정상")
            # 데이터 일치 확인
            is_consistent = validate_data_consistency()
            if is_consistent:
                st.success("✅ 데이터 동기화 정상")
            else:
                st.warning("⚠️ 데이터 불일치 감지됨")
        else:
            st.error("❌ 구글시트 연결 실패")