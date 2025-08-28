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

# --- CSS 스타일 ---
st.markdown(
    """
    <style>
    /* 사이드바 스타일 */
    [data-testid="stSidebar"] { width: 150px !important; }
    /* (중략...) */
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

if st.session_state.container_list:
    # ... (데이터 수정/삭제 UI 코드는 이전과 동일)
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
                updated_data = {'컨테이너 번호': selected_for_edit, '출고처': new_dest, '피트수': new_feet, '씰 번호': str(new_seal), '상태': new_status, '작업일자': new_work_date}
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
    st.info("현재 데이터가 없습니다. 아래 '데이터 복구' 기능을 사용하거나 등록 페이지에서 데이터를 추가해주세요.")

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
                    
                    if '씰 번호' in df_backup.columns:
                        df_backup['씰 번호'] = df_backup['씰 번호'].astype(str)
                    
                    st.markdown("##### 📋 선택된 백업 시트 현황")
                    # <<<<<<<<<<<<<<< ✨ 카드 UI 코드가 다시 복원되었습니다 ✨ >>>>>>>>>>>>>>>>>
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
                        
                        # <<<<<<<<<<<<<<< ✨ 컬럼 순서를 명시적으로 지정하여 오류를 해결했습니다 ✨ >>>>>>>>>>>>>>>>>
                        display_order = ['선택', 'No.'] + [h for h in SHEET_HEADERS if h in recoverable_df.columns]
                        
                        edited_df = st.data_editor(
                            recoverable_df,
                            column_order=display_order, # 컬럼 순서 명시
                            use_container_width=True,
                            hide_index=True,
                            key=f"recovery_editor_{selected_backup_sheet}",
                            column_config={
                                "선택": st.column_config.CheckboxColumn(width="small"),
                                "No.": st.column_config.NumberColumn(disabled=True, width="small"),
                                "컨테이너 번호": st.column_config.TextColumn(disabled=True),
                                "출고처": st.column_config.TextColumn(disabled=True),
                                "피트수": st.column_config.TextColumn(disabled=True),
                                "씰 번호": st.column_config.TextColumn(disabled=True),
                                "상태": st.column_config.TextColumn(disabled=True),
                                "작업일자": st.column_config.TextColumn(disabled=True),
                            }
                        )
                        
                        selected_rows = edited_df[edited_df['선택']]

                        if not selected_rows.empty:
                            if st.button(f"선택된 {len(selected_rows)}개 컨테이너 복구하기", use_container_width=True, type="primary"):
                                added_count = 0
                                for index, row in selected_rows.iterrows():
                                    row_to_add = row.to_dict()
                                    try: row_to_add['작업일자'] = datetime.strptime(row_to_add.get('작업일자'), '%Y-%m-%d').date()
                                    except (ValueError, TypeError): row_to_add['작업일자'] = date.today()
                                    st.session_state.container_list.append(row_to_add)
                                    add_row_to_gsheet(row_to_add)
                                    added_count += 1
                                log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {added_count}개 선택 복구")
                                st.success(f"'{selected_backup_sheet}' 시트에서 {added_count}개의 컨테이너를 성공적으로 복구했습니다!")
                                st.rerun()

                        st.divider()
                        st.markdown("##### 2. 시트 전체 복구 (현재 목록에 없는 데이터만)")
                        st.warning("주의: 이 작업은 위 테이블에 보이는 모든 컨테이너를 한 번에 추가합니다.")
                        
                        if st.button(f"'{selected_backup_sheet}' 시트의 모든 데이터 추가하기", use_container_width=True):
                            added_count = 0
                            for index, row in recoverable_df.iterrows():
                                row_to_add = row.to_dict()
                                try: row_to_add['작업일자'] = datetime.strptime(row_to_add.get('작업일자'), '%Y-%m-%d').date()
                                except (ValueError, TypeError): row_to_add['작업일자'] = date.today()
                                st.session_state.container_list.append(row_to_add)
                                add_row_to_gsheet(row_to_add)
                                added_count += 1
                            log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {added_count}개 전체 복구")
                            st.success(f"'{selected_backup_sheet}' 시트에서 {added_count}개의 새로운 데이터를 성공적으로 추가했습니다!")
                            st.rerun()

            except Exception as e:
                st.error(f"백업 시트 정보를 불러오는 중 오류가 발생했습니다: {e}")