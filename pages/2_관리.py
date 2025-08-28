import streamlit as st
import pandas as pd
from datetime import date, datetime
from utils import (
    SHEET_HEADERS,
    MAIN_SHEET_NAME,
    load_data_from_gsheet, 
    add_row_to_gsheet, 
    update_row_in_gsheet, 
    delete_row_from_gsheet, 
    backup_data_to_new_sheet,
    log_change,
    connect_to_gsheet
)

# --- 앱 초기 설정 ---
st.set_page_config(page_title="관리 페이지", layout="wide", initial_sidebar_state="expanded")

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

# --- 데이터 수정 및 삭제 ---
st.markdown("#### ✏️ 데이터 수정 및 삭제")

# <<<<<<<<<<<<<<< ✨ 2. 데이터가 있을 때만 수정/삭제 섹션을 보여주도록 변경 ✨ >>>>>>>>>>>>>>>>>
if st.session_state.container_list:
    container_numbers_for_edit = [c.get('컨테이너 번호', '') for c in st.session_state.container_list]
    selected_for_edit = st.selectbox("수정 또는 삭제할 컨테이너를 선택하세요:", container_numbers_for_edit, key="edit_selector")
    selected_data = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == selected_for_edit), None)
    selected_idx = next((i for i, c in enumerate(st.session_state.container_list) if c.get('컨테이너 번호') == selected_for_edit), -1)
    
    if selected_data:
        with st.form(key=f"edit_form_{selected_for_edit}"):
            st.write(f"**'{selected_for_edit}' 정보 수정**")
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
            current_dest_idx = dest_options.index(selected_data.get('출고처', dest_options[0]))
            new_dest = st.radio("출고처 수정", options=dest_options, index=current_dest_idx, horizontal=True)
            feet_options = ['40', '20']
            current_feet_idx = feet_options.index(str(selected_data.get('피트수', '40')))
            new_feet = st.radio("피트수 수정", options=feet_options, index=current_feet_idx, horizontal=True)
            new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
            status_options = ['선적중', '선적완료']
            current_status_idx = status_options.index(selected_data.get('상태', status_options[0]))
            new_status = st.radio("상태 변경", options=status_options, index=current_status_idx, horizontal=True)
            work_date_value = selected_data.get('작업일자', date.today())
            if not isinstance(work_date_value, date):
                try: work_date_value = datetime.strptime(str(work_date_value), '%Y-%m-%d').date()
                except (ValueError, TypeError): work_date_value = date.today()
            new_work_date = st.date_input("작업일자 수정", value=work_date_value)
            
            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                updated_data = {'컨테이너 번호': selected_for_edit, '출고처': new_dest, '피트수': new_feet, '씰 번호': new_seal, '상태': new_status, '작업일자': new_work_date}
                st.session_state.container_list[selected_idx] = updated_data
                update_row_in_gsheet(selected_idx, updated_data)
                st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                st.rerun()

        st.error("주의: 아래 버튼은 데이터를 영구적으로 삭제합니다.")
        if st.button("🗑️ 이 컨테이너 삭제", use_container_width=True):
            delete_row_from_gsheet(selected_idx, selected_for_edit)
            st.session_state.container_list.pop(selected_idx)
            st.success(f"'{selected_for_edit}' 컨테이너 정보가 삭제되었습니다.")
            st.rerun()
else:
    # 데이터가 없을 때 보여줄 메시지
    st.info("현재 데이터가 없습니다. 아래 '데이터 복구' 기능을 사용하거나 등록 페이지에서 데이터를 추가해주세요.")
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

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
        selected_backup_sheet = st.selectbox("복구할 백업 시트를 선택하세요:", backup_sheets)
        
        if selected_backup_sheet:
            try:
                backup_worksheet = spreadsheet.worksheet(selected_backup_sheet)
                backup_records = backup_worksheet.get_all_records()

                if not backup_records:
                    st.info("선택한 백업 시트에는 데이터가 없습니다.")
                else:
                    df_backup = pd.DataFrame(backup_records)
                    
                    # <<<<<<<<<<<<<<< ✨ 1. '씰 번호'를 항상 텍스트로 처리 ✨ >>>>>>>>>>>>>>>>>
                    if '씰 번호' in df_backup.columns:
                        df_backup['씰 번호'] = df_backup['씰 번호'].astype(str)

                    # (기존 카드 UI 및 테이블 표시 로직은 동일)
                    st.markdown("##### 📋 선택된 백업 시트 현황")
                    # ... (카드 UI 코드 생략)
                    st.dataframe(df_backup, use_container_width=True, hide_index=True)
                    
                    # <<<<<<<<<<<<<<< ✨ 3. 컨테이너 단위로 선택하여 복구하는 기능 ✨ >>>>>>>>>>>>>>>>>
                    st.divider()
                    st.markdown("#####  selective 컨테이너 선택 및 복구")

                    # 현재 목록에 없는 컨테이너만 복구 대상으로 필터링
                    existing_nos = {c.get('컨테이너 번호') for c in st.session_state.container_list}
                    recoverable_containers = df_backup[~df_backup['컨테이너 번호'].isin(existing_nos)]

                    if recoverable_containers.empty:
                        st.success("백업 시트의 모든 데이터가 이미 현재 목록에 존재합니다.")
                    else:
                        options = recoverable_containers['컨테이너 번호'].tolist()
                        selected_for_recovery = st.multiselect(
                            "복구할 컨테이너를 모두 선택하세요:",
                            options=options,
                            help="여러 컨테이너를 선택할 수 있습니다."
                        )

                        if selected_for_recovery:
                            if st.button(f"선택된 {len(selected_for_recovery)}개 컨테이너 복구하기", use_container_width=True, type="primary"):
                                added_count = 0
                                for container_no in selected_for_recovery:
                                    # 복구할 컨테이너의 전체 데이터를 df_backup에서 찾음
                                    row_to_add = recoverable_containers[recoverable_containers['컨테이너 번호'] == container_no].iloc[0].to_dict()
                                    
                                    # 날짜 형식 변환
                                    work_date_str = row_to_add.get('작업일자')
                                    try:
                                        row_to_add['작업일자'] = datetime.strptime(work_date_str, '%Y-%m-%d').date()
                                    except (ValueError, TypeError):
                                        row_to_add['작업일자'] = date.today()

                                    st.session_state.container_list.append(row_to_add)
                                    add_row_to_gsheet(row_to_add)
                                    added_count += 1
                                
                                log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {added_count}개 선택 복구")
                                st.success(f"'{selected_backup_sheet}' 시트에서 {added_count}개의 컨테이너를 성공적으로 복구했습니다!")
                                st.rerun()
                    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
            except Exception as e:
                st.error(f"백업 시트 정보를 불러오는 중 오류가 발생했습니다: {e}")