import streamlit as st
import pandas as pd
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta, timezone
import re
import streamlit.components.v1 as components
from utils import (
    SHEET_HEADERS,
    MAIN_SHEET_NAME,
    load_data_from_gsheet,
    add_row_to_gsheet,
    update_row_in_gsheet,
    backup_data_to_new_sheet,
    connect_to_gsheet,
    log_change,
    delete_row_from_gsheet
)

st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")

def get_korea_now():
    return datetime.now(timezone(timedelta(hours=9)))

@st.cache_data
def generate_qrcode(data: str) -> bytes:
    img = qrcode.make(data)
    fp = BytesIO()
    img.save(fp, format="PNG")
    fp.seek(0)
    return fp.getvalue()

def make_zpl(container_no, dpi=203):
    """QR코드 ZPL 생성 (90mm x 60mm 기준)"""
    width = 720 if dpi == 203 else 1080
    height = 480 if dpi == 203 else 720
    return (
        "^XA"
        f"^PW{width}"
        f"^LL{height}"
        "^FO260,40"
        "^BQN,2,8"
        f"^FDQA,{container_no}^FS"
        "^XZ"
    )

def send_zpl_to_printer(printer_ip, zpl_code, result_key):
    """브라우저(스마트폰)가 직접 ZT411로 ZPL을 전송 (사내 로컬 네트워크 전용)"""
    zpl_escaped = zpl_code.replace("`", "\\`")
    components.html(f"""
    <div id="print-status-{result_key}" style="font-family:sans-serif;font-size:14px;color:#888;">출력 요청 전송 중...</div>
    <script>
    (function() {{
        fetch('http://{printer_ip}:9100', {{
            method: 'POST',
            body: `{zpl_escaped}`,
            mode: 'no-cors'
        }})
        .then(function() {{
            document.getElementById('print-status-{result_key}').innerHTML =
                '<span style="color:#28A745;">✅ 출력 요청을 프린터로 전송했습니다.</span>';
        }})
        .catch(function(err) {{
            document.getElementById('print-status-{result_key}').innerHTML =
                '<span style="color:#FF4B4B;">❌ 프린터 연결 실패: ' + err + '</span>';
        }});
    }})();
    </script>
    """, height=40)

def clear_form_inputs():
    st.session_state["form_container_no"] = ""
    st.session_state["form_seal_no"] = ""
    st.session_state["form_destination"] = "베트남"
    st.session_state["form_feet"] = "40"

if st.session_state.get("submission_success", False):
    clear_form_inputs()
    st.session_state.submission_success = False

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

st.markdown("#### 🔳 바코드 생성 및 출력")
with st.container(border=True):
    shippable_containers = [c for c in st.session_state.container_list if c.get('상태') == '선적중' and c.get('컨테이너 번호')]

    if not shippable_containers:
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        printer_ip = st.session_state.get("printer_ip", "")
        if not printer_ip:
            st.warning("프린터 IP 미설정 — 사이드바 '설정' 페이지에서 입력해주세요.")

        # --- 컨테이너 테이블 ---
        df = pd.DataFrame([{
            "선택": False,
            "컨테이너 번호": c.get("컨테이너 번호", ""),
            "출고처": c.get("출고처", ""),
            "피트수": c.get("피트수", ""),
            "씰번호": c.get("씰 번호", ""),
        } for c in shippable_containers])

        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            key="container_table",
            disabled=["컨테이너 번호", "출고처", "피트수", "씰번호"],
            column_config={
                "선택": st.column_config.CheckboxColumn("선택", default=False, width="small"),
            },
        )

        selected_cnos = edited[edited["선택"] == True]["컨테이너 번호"].tolist()

        cno_options = ["미리보기"] + [c.get("컨테이너 번호", "") for c in shippable_containers]
        preview_sel = st.selectbox("미리보기", cno_options, label_visibility="collapsed")
        preview_cno = None if preview_sel == "미리보기" else preview_sel

        if preview_cno:
            qr_bytes = generate_qrcode(preview_cno)
            b64 = base64.b64encode(qr_bytes).decode()
            st.markdown(f"""
            <div style="text-align:center; margin:20px 0 4px 0;">
                <img src="data:image/png;base64,{b64}" style="width:200px; max-width:80%; display:block; margin:0 auto;">
                <div style="font-size:22px; font-weight:bold; margin-top:-12px; letter-spacing:1px;">{preview_cno}</div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

        if selected_cnos:
            btn_label = f"🖨️ {len(selected_cnos)}개 출력 (각 2장)"
            if st.button(btn_label, use_container_width=True, type="primary", key="print_barcode_btn", disabled=not printer_ip):
                for i, cno in enumerate(selected_cnos):
                    zpl_code = make_zpl(cno)
                    send_zpl_to_printer(printer_ip, zpl_code, result_key=f"p{i}_1")
                    send_zpl_to_printer(printer_ip, zpl_code, result_key=f"p{i}_2")
                st.caption(f"전송 대상: {printer_ip}")
        else:
            st.caption("'선택' 체크박스로 출력할 컨테이너를 선택하세요.")

st.divider()

col_header, col_button = st.columns([0.8, 0.2])
with col_header:
    st.markdown("#### 📋 컨테이너 현황")
with col_button:
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.session_state.container_list = load_data_from_gsheet()
        st.rerun()

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

    display_df = df.copy()
    if '등록일시' in display_df.columns:
        display_df['등록일시'] = pd.to_datetime(display_df['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
    if '완료일시' in display_df.columns:
        display_df['완료일시'] = pd.to_datetime(display_df['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
    display_df.fillna('', inplace=True)

    column_order = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '등록일시', '완료일시', '선적완료']

    edited_df = st.data_editor(
        display_df,
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

    if not df['선적완료'].equals(edited_df['선적완료']):
        for i, (original_bool, edited_bool) in enumerate(zip(df['선적완료'], edited_df['선적완료'])):
            if original_bool != edited_bool:
                st.session_state.container_list[i]['상태'] = "선적완료" if edited_bool else "선적중"
                if edited_bool:
                    aware_completion_time = get_korea_now()
                    naive_completion_time = aware_completion_time.replace(tzinfo=None)
                    st.session_state.container_list[i]['완료일시'] = pd.to_datetime(naive_completion_time)
                else:
                    st.session_state.container_list[i]['완료일시'] = None

                update_row_in_gsheet(i, st.session_state.container_list[i])
                st.rerun()

if st.button("🚀 데이터 백업", use_container_width=True, type="primary"):
    completed_items_with_indices = [
        (i, item) for i, item in enumerate(st.session_state.container_list) if item.get('상태') == '선적완료'
    ]

    if not completed_items_with_indices:
        st.info("백업할 '선적완료' 상태의 데이터가 없습니다.")
    else:
        completed_data = [item for i, item in completed_items_with_indices]
        with st.spinner('데이터를 백업하는 중...'):
            success, error_msg = backup_data_to_new_sheet(completed_data)

        if success:
            st.success(f"'선적완료'된 {len(completed_data)}개 데이터를 일별/월별 백업했습니다!")

            with st.spinner('메인 시트를 정리하는 중...'):
                try:
                    indices_to_delete = sorted([i for i, item in completed_items_with_indices], reverse=True)

                    for index in indices_to_delete:
                        container_no_to_delete = st.session_state.container_list[index].get('컨테이너 번호')
                        delete_row_from_gsheet(index, container_no_to_delete)
                        st.session_state.container_list.pop(index)

                    log_message = f"데이터 백업: {len(completed_data)}개 백업 완료 후 메인 시트에서 삭제."
                    log_change(log_message)

                    st.success("메인 시트 정리가 완료되었습니다.")
                    st.rerun()

                except Exception as e:
                    st.error(f"메인 시트 정리 중 오류가 발생했습니다: {e}")
                    st.warning("데이터 백업은 완료되었으나, 메인 시트 정리에 실패했습니다. 잠시 후 '데이터 새로고침'을 누르고 다시 시도하거나, 수동으로 정리해주세요.")
        else:
            st.error(f"백업 중 오류 발생: {error_msg}")

st.divider()

st.markdown("#### 📝 신규 컨테이너 등록")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '타이닌', '기타']
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("4. 씰 번호", key="form_seal_no")

    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    if submitted:
        st.session_state["form_success_message"] = ""
        st.session_state["form_error_message"] = ""

        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        if not container_no or not seal_no:
            st.session_state["form_error_message"] = "컨테이너 번호와 씰 번호를 모두 입력해주세요."
        elif not pattern.match(container_no):
            st.session_state["form_error_message"] = "컨테이너 번호 형식이 올바르지 않습니다."
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list):
            st.session_state["form_error_message"] = f"이미 등록된 컨테이너 번호입니다: {container_no}"
        else:
            korea_now = get_korea_now()
            naive_datetime = korea_now.replace(tzinfo=None)

            new_container = {
                '컨테이너 번호': container_no, '출고처': destination, '피트수': feet,
                '씰 번호': seal_no, '상태': '선적중',
                '등록일시': pd.to_datetime(naive_datetime),
                '완료일시': None
            }

            with st.spinner('데이터를 저장하는 중...'):
                success, message = add_row_to_gsheet(new_container)

            if success:
                st.session_state.container_list.append(new_container)
                st.session_state.submission_success = True
                st.session_state.form_success_message = f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다."
                st.rerun()
            else:
                st.session_state["form_error_message"] = f"등록 실패: {message}. 잠시 후 다시 시도해주세요."

if st.session_state.get("form_success_message"):
    st.success(st.session_state.get("form_success_message"))
    st.session_state["form_success_message"] = ""
if st.session_state.get("form_error_message"):
    st.error(st.session_state.get("form_error_message"))
    st.session_state["form_error_message"] = ""