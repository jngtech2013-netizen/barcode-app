import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from utils import (
    SHEET_HEADERS,
    MAIN_SHEET_NAME,
    load_data_from_gsheet,
    add_row_to_gsheet,
    add_rows_to_gsheet_batch,
    update_row_in_gsheet,
    delete_row_from_gsheet,
    delete_from_backup_sheets,
    backup_data_to_new_sheet,
    cleanup_old_daily_sheets,
    archive_log_sheet,
    move_containers_between_backup_sheets,
    log_change,
    connect_to_gsheet,
    BACKUP_PREFIX
)

st.set_page_config(page_title="관리 페이지", layout="wide", initial_sidebar_state="expanded")

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
            dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '타이닌', '기타']
            current_dest_idx = dest_options.index(selected_data.get('출고처', '베트남'))
            new_dest = st.radio("출고처 수정", options=dest_options, index=current_dest_idx, horizontal=True)
            feet_options = ['40', '20']
            current_feet_idx = feet_options.index(str(selected_data.get('피트수', '40')))
            new_feet = st.radio("피트수 수정", options=feet_options, index=current_feet_idx, horizontal=True)
            new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
            status_options = ['선적중', '선적완료']
            current_status = selected_data.get('상태', '선적중')
            current_status_idx = status_options.index(current_status)
            new_status = st.radio("상태 변경", options=status_options, index=current_status_idx, horizontal=True)

            if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                updated_data = selected_data.copy()
                updated_data.update({
                    '출고처': new_dest,
                    '피트수': new_feet,
                    '씰 번호': str(new_seal),
                    '상태': new_status,
                })

                if new_status == '선적완료':
                    if current_status == '선적중':
                        aware_time = datetime.now(timezone(timedelta(hours=9)))
                        naive_time = aware_time.replace(tzinfo=None)
                        updated_data['완료일시'] = pd.to_datetime(naive_time)
                else:
                    updated_data['완료일시'] = None

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
    st.info("현재 데이터가 없습니다.")

st.divider()
st.markdown("#### ⬆️ 데이터 복구")
st.info("실수로 데이터를 초기화했거나 이전 데이터를 추가할 때 사용하세요.")

spreadsheet = connect_to_gsheet()
if spreadsheet:
    all_sheets = [s.title for s in spreadsheet.worksheets()]

    # 개선 3: 일별/월별 시트 분리 표시
    daily_sheets = sorted(
        [s for s in all_sheets if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 10],
        reverse=True
    )
    monthly_sheets = sorted(
        [s for s in all_sheets if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 7],
        reverse=True
    )

    sheet_type = st.radio("백업 시트 유형", options=["일별", "월별"], horizontal=True)
    backup_sheets = daily_sheets if sheet_type == "일별" else monthly_sheets

    if not backup_sheets:
        st.warning(f"복구할 {sheet_type} 백업 시트가 없습니다.")
    else:
        selected_backup_sheet = st.selectbox(
            "복구할 백업 시트를 선택하세요:",
            backup_sheets,
            key="backup_sheet_selector"
        )

        if selected_backup_sheet:
            try:
                backup_worksheet = spreadsheet.worksheet(selected_backup_sheet)
                all_values = backup_worksheet.get_all_values()

                if len(all_values) < 2:
                    st.info("선택한 백업 시트에는 데이터가 없습니다.")
                else:
                    headers = all_values[0]
                    data = all_values[1:]
                    df_backup = pd.DataFrame(data, columns=headers, dtype=str)

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

                    # 개선 1: 세션이 아닌 Google Sheets 실시간 데이터 기준으로 중복 체크
                    current_data = load_data_from_gsheet()
                    existing_nos = {c.get('컨테이너 번호') for c in current_data}
                    recoverable_df = df_backup[~df_backup['컨테이너 번호'].isin(existing_nos)].copy()

                    if recoverable_df.empty:
                        st.success("백업 시트의 모든 데이터가 이미 현재 목록에 존재합니다.")
                    else:
                        st.markdown("---")
                        st.markdown("##### 개별 컨테이너 선택 복구")
                        st.write("아래 테이블에서 복구할 컨테이너를 선택하세요.")

                        recoverable_df.insert(0, '선택', False)
                        recoverable_df.insert(1, 'No.', range(1, len(recoverable_df) + 1))

                        display_order = ['선택', 'No.'] + [h for h in SHEET_HEADERS if h in recoverable_df.columns and h != 'No.']

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
                                rows_to_add = []
                                for index, row in selected_rows.iterrows():
                                    row_to_add = {k: v for k, v in row.to_dict().items() if k in SHEET_HEADERS}
                                    row_to_add['등록일시'] = pd.to_datetime(row_to_add.get('등록일시'), errors='coerce')
                                    row_to_add['완료일시'] = pd.to_datetime(row_to_add.get('완료일시'), errors='coerce')
                                    rows_to_add.append(row_to_add)

                                # 메인 시트에 일괄 복구
                                success, msg = add_rows_to_gsheet_batch(rows_to_add)
                                if success:
                                    st.session_state.container_list.extend(rows_to_add)
                                    log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {len(rows_to_add)}개 선택 복구")

                                    # 해당 일별/월별 시트에서만 삭제
                                    container_nos = [r.get('컨테이너 번호') for r in rows_to_add]
                                    with st.spinner('백업 시트에서 복구된 데이터를 정리하는 중...'):
                                        del_success, del_result = delete_from_backup_sheets(container_nos, selected_backup_sheet)
                                    if del_success:
                                        st.success(f"{len(rows_to_add)}개 복구 완료, 백업 시트에서 {del_result}행 정리됐습니다.")
                                    else:
                                        st.warning(f"복구는 완료됐으나 백업 시트 정리 중 오류 발생: {del_result}")
                                    st.rerun()
                                else:
                                    st.error(f"복구 중 오류 발생: {msg}")

                        st.divider()
                        st.markdown("##### 시트 전체 복구 (현재 목록에 없는 데이터만)")
                        st.warning("주의: 이 작업은 위 테이블에 보이는 모든 컨테이너를 한 번에 추가합니다.")

                        if st.button(f"'{selected_backup_sheet}' 시트의 모든 데이터 추가하기", use_container_width=True):
                            rows_to_add = []
                            for index, row in recoverable_df.iterrows():
                                row_to_add = {k: v for k, v in row.to_dict().items() if k in SHEET_HEADERS}
                                row_to_add['등록일시'] = pd.to_datetime(row_to_add.get('등록일시'), errors='coerce')
                                row_to_add['완료일시'] = pd.to_datetime(row_to_add.get('완료일시'), errors='coerce')
                                rows_to_add.append(row_to_add)

                            # 메인 시트에 일괄 복구
                            success, msg = add_rows_to_gsheet_batch(rows_to_add)
                            if success:
                                st.session_state.container_list.extend(rows_to_add)
                                log_change(f"데이터 복구: '{selected_backup_sheet}'에서 {len(rows_to_add)}개 전체 복구")

                                # 해당 일별/월별 시트에서만 삭제
                                container_nos = [r.get('컨테이너 번호') for r in rows_to_add]
                                with st.spinner('백업 시트에서 복구된 데이터를 정리하는 중...'):
                                    del_success, del_result = delete_from_backup_sheets(container_nos, selected_backup_sheet)
                                if del_success:
                                    st.success(f"{len(rows_to_add)}개 복구 완료, 백업 시트에서 {del_result}행 정리됐습니다.")
                                else:
                                    st.warning(f"복구는 완료됐으나 백업 시트 정리 중 오류 발생: {del_result}")
                                st.rerun()
                            else:
                                st.error(f"복구 중 오류 발생: {msg}")

            except Exception as e:
                st.error(f"백업 시트 정보를 불러오는 중 오류가 발생했습니다: {e}")

st.divider()
st.markdown("#### 🗂️ 시트 관리")

# --- 일별 백업 시트 정리 ---
with st.container(border=True):
    st.markdown("##### 🗑️ 오래된 일별 백업 시트 삭제")
    st.info("3개월 이상 된 일별 백업 시트(`백업_YYYY-MM-DD`)를 삭제합니다. 월별 시트는 보존됩니다.")

    # 삭제 대상 미리보기
    spreadsheet_preview = connect_to_gsheet()
    if spreadsheet_preview:
        from datetime import date as date_cls
        cutoff = datetime.now().date()
        from datetime import timedelta as td
        cutoff = (datetime.now() - td(days=90)).date()
        all_sheet_titles = [s.title for s in spreadsheet_preview.worksheets()]
        target_daily = [
            s for s in all_sheet_titles
            if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 10
            and datetime.strptime(s.replace(BACKUP_PREFIX, ''), '%Y-%m-%d').date() < cutoff
        ]
        if target_daily:
            st.warning(f"삭제 대상: {len(target_daily)}개 시트 ({', '.join(target_daily)})")
        else:
            st.success("삭제할 오래된 일별 백업 시트가 없습니다.")

    if st.button("🗑️ 3개월 이상 일별 백업 시트 삭제", use_container_width=True, type="primary"):
        with st.spinner("오래된 일별 백업 시트를 삭제하는 중..."):
            success, result = cleanup_old_daily_sheets(months=3)
        if success:
            if result:
                st.success(f"{len(result)}개 일별 백업 시트가 삭제됐습니다: {', '.join(result)}")
            else:
                st.info("삭제할 오래된 일별 백업 시트가 없습니다.")
        else:
            st.error(f"삭제 중 오류 발생: {result}")

st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

# --- 로그 아카이브 ---
with st.container(border=True):
    st.markdown("##### 📦 로그 아카이브")
    st.info("업데이트 로그가 1000행 초과 시 오래된 로그를 분기별 시트(`로그_YYYY-QN`)로 이관합니다. 최근 200행은 유지됩니다.")

    # 현재 로그 행 수 표시
    spreadsheet_log = connect_to_gsheet()
    if spreadsheet_log:
        try:
            log_ws = spreadsheet_log.worksheet("업데이트 로그")
            log_row_count = len(log_ws.get_all_values())
            if log_row_count > 1000:
                st.warning(f"현재 로그: {log_row_count}행 — 아카이브를 권장합니다.")
            else:
                st.success(f"현재 로그: {log_row_count}행 (기준: 1000행)")
        except Exception:
            st.warning("로그 시트 행 수를 불러올 수 없습니다.")

    if st.button("📦 로그 아카이브 실행", use_container_width=True):
        with st.spinner("로그를 아카이브하는 중..."):
            success, result = archive_log_sheet(keep_rows=200)
        if success:
            archive_name, archived_count = result
            st.success(f"{archived_count}행을 '{archive_name}' 시트로 이관했습니다. 최근 200행은 유지됩니다.")
        else:
            st.info(result)

st.divider()
st.markdown("#### 📁 백업 데이터 이동")
st.info("백업 시트 간 컨테이너 데이터를 이동합니다. 선적완료를 늦게 눌러 날짜가 잘못 기록된 경우 사용하세요.")

spreadsheet_move = connect_to_gsheet()
if spreadsheet_move:
    all_sheets_move = [s.title for s in spreadsheet_move.worksheets()]
    daily_sheets_move = sorted(
        [s for s in all_sheets_move if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + 10],
        reverse=True
    )

    if not daily_sheets_move:
        st.warning("이동할 수 있는 일별 백업 시트가 없습니다.")
    else:
        with st.container(border=True):
            st.markdown("##### 1단계 - 원본 시트 및 컨테이너 선택")

            source_sheet = st.selectbox(
                "원본 시트 선택 (이동할 데이터가 있는 시트)",
                daily_sheets_move,
                key="move_source_sheet"
            )

            # 원본 시트 데이터 로드
            if source_sheet:
                try:
                    source_ws = spreadsheet_move.worksheet(source_sheet)
                    source_values = source_ws.get_all_values()

                    if len(source_values) < 2:
                        st.warning("선택한 시트에 데이터가 없습니다.")
                    else:
                        source_headers = source_values[0]
                        source_df = pd.DataFrame(source_values[1:], columns=source_headers, dtype=str)
                        source_df.replace('', pd.NA, inplace=True)

                        # 컨테이너 선택 (멀티셀렉트)
                        container_options = source_df['컨테이너 번호'].dropna().tolist()
                        selected_containers = st.multiselect(
                            "이동할 컨테이너 선택",
                            container_options,
                            key="move_containers"
                        )

                        if selected_containers:
                            # 선택된 컨테이너 미리보기
                            preview_df = source_df[source_df['컨테이너 번호'].isin(selected_containers)]
                            display_cols = [c for c in ['컨테이너 번호', '출고처', '피트수', '상태', '완료일시'] if c in preview_df.columns]
                            st.dataframe(preview_df[display_cols], use_container_width=True, hide_index=True)

                            st.markdown("##### 2단계 - 대상 날짜 및 옵션 설정")
                            col1, col2 = st.columns(2)

                            with col1:
                                # 원본 시트 날짜에서 하루 전을 기본값으로
                                source_date = datetime.strptime(
                                    source_sheet.replace(BACKUP_PREFIX, ''), '%Y-%m-%d'
                                ).date()
                                default_target = source_date - timedelta(days=1)
                                target_date = st.date_input(
                                    "대상 날짜 선택",
                                    value=default_target,
                                    key="move_target_date"
                                )

                            with col2:
                                update_done_time = st.checkbox(
                                    "완료일시도 대상 날짜로 수정",
                                    value=True,
                                    key="move_update_done_time",
                                    help="체크 시 완료일시가 선택한 대상 날짜 00:00:00으로 변경됩니다."
                                )

                            target_date_str = target_date.strftime('%Y-%m-%d')
                            target_daily_name = f"{BACKUP_PREFIX}{target_date_str}"

                            st.markdown(f"**이동 요약:** `{source_sheet}` → `{target_daily_name}` / {len(selected_containers)}개 컨테이너" +
                                        (" / 완료일시 수정" if update_done_time else ""))

                            if st.button("📁 선택한 컨테이너 이동", use_container_width=True, type="primary"):
                                with st.spinner("데이터를 이동하는 중..."):
                                    success, result = move_containers_between_backup_sheets(
                                        container_nos=selected_containers,
                                        source_sheet_name=source_sheet,
                                        target_date_str=target_date_str,
                                        update_completion_date=update_done_time
                                    )
                                if success:
                                    st.success(f"{result}개 컨테이너를 '{target_daily_name}'으로 이동했습니다!")
                                    st.rerun()
                                else:
                                    st.error(f"이동 중 오류 발생: {result}")

                except Exception as e:
                    st.error(f"원본 시트 데이터를 불러오는 중 오류가 발생했습니다: {e}")
