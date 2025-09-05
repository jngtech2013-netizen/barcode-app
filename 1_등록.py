import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date, datetime, timedelta, timezone
import re
from utils import (
    SHEET_HEADERS,
    MAIN_SHEET_NAME,
    load_data_from_gsheet,
    add_row_to_gsheet,
    update_row_in_gsheet,
    backup_data_to_new_sheet,
    connect_to_gsheet,
    log_change
)

# --- 앱 초기 설정 ---
st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")

# --- 한국 시간 함수 ---
def get_korea_now():
    return datetime.now(timezone(timedelta(hours=9)))

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
    if '등록일시' in df.columns:
        df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
    if '완료일시' in df.columns:
        df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
    df.fillna('', inplace=True)

    column_order = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '등록일시', '완료일시', '선적완료']

    edited_df = st.data_editor(
        df,
        column_order=column_order,
        use_container_width=True,
        hide_index=True,
        key="data_editor_final",
        column_config={
            "선적완료": st.column_config.CheckboxColumn("선적완료", width="small"),
            "컨테이너 번호": st.column_config.TextColumn(disabled=True),
            "출고처": st.column_config.TextColumn(disabled=True),
            "피트수": st.column_config.TextColumn(disabled=True),
            "씰 번호": st.column_config.TextColumn(disabled=True),
            "등록일시": st.column_config.TextColumn(disabled=True),
            "완료일시": st.column_config.TextColumn(disabled=True),
        }
    )

    if edited_df is not None:
        edited_list = edited_df.to_dict('records')
        for i, (original_row, edited_row) in enumerate(zip(st.session_state.container_list, edited_list)):
            original_status = original_row.get('상태', '선적중')
            new_status_from_checkbox = "선적완료" if edited_row.get('선적완료') else "선적중"

            if original_status != new_status_from_checkbox:
                new_status_bool = edited_row.get('선적완료', False)
                edited_row['상태'] = "선적완료" if new_status_bool else "선적중"

                if new_status_bool:
                    edited_row['완료일시'] = get_korea_now()
                else:
                    edited_row['완료일시'] = None

                edited_row['등록일시'] = original_row.get('등록일시')

                st.session_state.container_list[i] = edited_row
                update_row_in_gsheet(i, edited_row)
                st.rerun()

if st.button("🚀 데이터 백업", use_container_width=True, type="primary"):
    completed_data = [item for item in st.session_state.container_list if item.get('상태') == '선적완료']
    pending_data = [item for item in st.session_state.container_list if item.get('상태') == '선적중']

    if not completed_data:
        st.info("백업할 '선적완료' 상태의 데이터가 없습니다.")
    else:
        with st.spinner('데이터를 백업하는 중...'):
            success, error_msg = backup_data_to_new_sheet(completed_data)

        if success:
            st.success(f"'선적완료'된 {len(completed_data)}개 데이터를 백업했습니다!")

            with st.spinner('메인 시트를 정리하는 중...'):
                try:
                    spreadsheet = connect_to_gsheet()
                    if spreadsheet:
                        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
                        completed_nos = {item['컨테이너 번호'] for item in completed_data}
                        all_data = worksheet.get_all_records()
                        rows_to_delete = []
                        for i in range(len(all_data) - 1, -1, -1):
                            if all_data[i].get('컨테이너 번호') in completed_nos:
                                rows_to_delete.append(i + 2)
                        for row_num in rows_to_delete:
                            worksheet.delete_rows(row_num)

                        log_message = f"데이터 백업: {len(completed_data)}개 백업, {len(pending_data)}개 이월."
                        log_change(log_message)

                        st.session_state.container_list = pending_data
                        st.success("메인 시트 정리가 완료되었습니다.")
                        st.rerun()

                except Exception as e:
                    st.error(f"메인 시트 정리 중 오류가 발생했습니다: {e}")
                    st.warning("데이터 백업은 완료되었으나, 메인 시트 정리에 실패했습니다. 수동으로 '선적완료' 데이터를 삭제해주세요.")
        else:
            st.error(f"백업 중 오류 발생: {error_msg}")

st.divider()

# --- 신규 컨테이너 등록 ---
st.markdown("#### 📝 신규 컨테이너 등록")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("4. 씰 번호", key="form_seal_no")

    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    if submitted:
        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        if not container_no or not seal_no:
            st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
        elif not pattern.match(container_no):
            st.error("컨테이너 번호 형식이 올바르지 않습니다.")
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list):
            st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
        else:
            # [최종 수정된 부분]
            # 시간대 정보가 있는 datetime 객체에서 시간대 정보를 제거(.replace(tzinfo=None))하여
            # session_state에 저장된 모든 시간 데이터 타입을 'timezone-naive'로 통일합니다.
            korea_now = get_korea_now()
            naive_datetime = korea_now.replace(tzinfo=None)

            new_container = {
                '컨테이너 번호': container_no, '출고처': destination, '피트수': feet,
                '씰 번호': seal_no, '상태': '선적중',
                '등록일시': pd.to_datetime(naive_datetime),
                '완료일시': ''
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