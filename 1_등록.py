import streamlit as st
import pandas as pd
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components

from utils import (
    load_data_from_gsheet,
    add_row_to_gsheet,
    backup_data_to_new_sheet,
    log_change,
    delete_rows_by_container_nos,
    apply_sidebar_style,
    render_app_title,
    get_destinations,
    make_zpl,
    is_valid_container_no,
    DEFAULT_PRINTER_IP,
    load_config,
    button_marker
)

if "printer_ip" not in st.session_state:
    st.session_state["printer_ip"] = load_config().get("printer_ip", DEFAULT_PRINTER_IP)

st.set_page_config(page_title="등록 페이지", layout="wide", initial_sidebar_state="expanded")

def get_korea_now():
    return datetime.now(timezone(timedelta(hours=9)))

LOCATION_OPTIONS = ['1', '2', '3', '4', '5', '6', '7']

def container_slot(c):
    """컨테이너의 위치(1~7) 슬롯 문자열 반환, 없으면 None."""
    v = c.get('위치')
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s if s in LOCATION_OPTIONS else None

@st.cache_data
def generate_qrcode(data: str) -> bytes:
    img = qrcode.make(data)
    fp = BytesIO()
    img.save(fp, format="PNG")
    fp.seek(0)
    return fp.getvalue()

def send_zpl_to_printer(printer_ip, zpl_code, result_key):
    """브라우저(스마트폰)가 직접 ZT411로 ZPL을 전송 (사내 로컬 네트워크 전용)

    주의: 프린터의 9100 포트는 HTTP/CORS를 지원하지 않으므로 fetch는 'no-cors'로
    보낼 수밖에 없고, 그 응답 본문은 읽을 수 없다. 따라서 .then()이 실행돼도
    '프린터가 실제로 출력했다'는 보장은 아니며 '네트워크로 신호를 내보냈다' 수준이다.
    실제 출력 여부는 라벨이 나오는지 눈으로 확인해야 한다. (5초 내 무응답=연결 실패로 간주)
    """
    zpl_escaped = zpl_code.replace("`", "\\`")
    components.html(f"""
    <style>body{{margin:0;padding:0;}}</style>
    <div style="font-family:sans-serif;font-size:14px;background:#E8F0FE;padding:6px 10px;border-radius:6px;">
        <div style="color:#555;">🖨️ 전송 대상: {printer_ip}</div>
        <div id="print-status-{result_key}" style="color:#28A745;margin-top:4px;">📤 출력 신호를 보냈습니다. <span style="color:#888;">라벨이 나오는지 확인하세요.</span></div>
    </div>
    <script>
    (function() {{
        // 포트 9100은 raw TCP라 HTTP 응답이 없음 — fire-and-forget으로 전송
        fetch('http://{printer_ip}:9100', {{
            method: 'POST',
            body: `{zpl_escaped}`,
            mode: 'no-cors'
        }}).catch(function() {{}});
    }})();
    </script>
    """, height=65)

def clear_form_inputs():
    dests = get_destinations()
    st.session_state["form_container_no"] = ""
    st.session_state["form_seal_no"] = ""
    st.session_state["form_destination"] = dests[0] if dests else ""
    st.session_state["form_feet"] = "40"

if st.session_state.get("submission_success", False):
    clear_form_inputs()
    st.session_state.submission_success = False

apply_sidebar_style('[data-testid="stForm"] label, [data-testid="stForm"] p { font-size: 15px !important; }')

if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

render_app_title()

st.markdown("#### 📋 컨테이너 현황")
with st.container(border=True):
    printer_ip = st.session_state.get("printer_ip", "")

    # --- 선적중 / 선적완료 카드 ---
    # 등록 페이지 지표는 위치 슬롯에 있는 컨테이너만 집계 (복원된 위치 없는 항목 제외)
    slot_items = [item for item in st.session_state.container_list if container_slot(item)]
    completed_count = len([item for item in slot_items if item.get('상태') == '선적완료'])
    pending_count = len([item for item in slot_items if item.get('상태') == '선적중'])
    st.markdown(
        f"""
        <style>
        .metric-card {{ padding: 1rem; border: 1px solid #DCDCDC; border-radius: 10px; text-align: center; margin-bottom: 10px; }}
        .metric-value {{ font-size: 2.5rem; font-weight: bold; }}
        .metric-label {{ font-size: 1rem; color: #555555; }}
        .red-value {{ color: #FF4B4B; }}
        .green-value {{ color: #28A745; }}
        </style>
        <div style="display:flex; gap:12px;">
            <div style="flex:1"><div class="metric-card"><div class="metric-value red-value">{pending_count}</div><div class="metric-label">선적중</div></div></div>
            <div style="flex:1"><div class="metric-card"><div class="metric-value green-value">{completed_count}</div><div class="metric-label">선적완료</div></div></div>
        </div>
        """, unsafe_allow_html=True
    )

    # 위치(1~7) 슬롯 기준으로 컨테이너 매핑 (위치 없는 컨테이너는 등록 페이지에서 숨김)
    SLOT_NUMBERS = ['1', '2', '3', '4', '5', '6', '7']

    def _slot_of(c):
        v = c.get('위치')
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s if s in SLOT_NUMBERS else None

    def _fmt_dt(v):
        t = pd.to_datetime(v, errors='coerce')
        return t.strftime('%Y-%m-%d %H:%M') if pd.notna(t) else ''

    slot_map = {}
    for c in st.session_state.container_list:
        s = _slot_of(c)
        if s and s not in slot_map:
            slot_map[s] = c

    rows = []
    for s in SLOT_NUMBERS:
        c = slot_map.get(s)
        if c:
            rows.append({
                '위치': s, '출력선택': False,
                '컨테이너 번호': c.get('컨테이너 번호', ''),
                '출고처': c.get('출고처', '') if pd.notna(c.get('출고처')) else '',
                '피트수': c.get('피트수', '') if pd.notna(c.get('피트수')) else '',
                '씰 번호': c.get('씰 번호', '') if pd.notna(c.get('씰 번호')) else '',
                '등록일시': _fmt_dt(c.get('등록일시')),
                '완료일시': _fmt_dt(c.get('완료일시')),
                '선적완료': False,
            })
        else:
            rows.append({
                '위치': s, '출력선택': False, '컨테이너 번호': '', '출고처': '',
                '피트수': '', '씰 번호': '', '등록일시': '', '완료일시': '', '선적완료': False,
            })

    display_df = pd.DataFrame(rows)
    column_order = ['위치', '출력선택', '컨테이너 번호', '출고처', '피트수', '씰 번호', '등록일시', '완료일시', '선적완료']

    edited_df = st.data_editor(
        display_df,
        column_order=column_order,
        use_container_width=True,
        hide_index=True,
        height=300,  # 7행 고정 표시
        key="merged_editor",
        column_config={
            "위치": st.column_config.TextColumn("위치", disabled=True, width="small"),
            "출력선택": st.column_config.CheckboxColumn("출력선택", default=False, width="small", help="빈 슬롯은 출력 대상에서 제외됩니다."),
            "선적완료": st.column_config.CheckboxColumn("선적완료", width="small", help="체크 시 즉시 백업되고 슬롯이 비워집니다."),
            "컨테이너 번호": st.column_config.TextColumn(disabled=True),
            "출고처": st.column_config.TextColumn(disabled=True),
            "피트수": st.column_config.TextColumn(disabled=True),
            "씰 번호": st.column_config.TextColumn(disabled=True),
            "등록일시": st.column_config.TextColumn(disabled=True),
            "완료일시": st.column_config.TextColumn(disabled=True),
        }
    )

    # 선적완료 체크 → 즉시 백업 + 메인시트에서 삭제(슬롯 비움)
    to_complete = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row['컨테이너 번호'] and row['선적완료']
    ]
    if to_complete:
        any_done = False
        for cno in to_complete:
            item = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == cno), None)
            if not item:
                continue
            item = item.copy()
            item['상태'] = '선적완료'
            item['완료일시'] = pd.to_datetime(get_korea_now().replace(tzinfo=None))
            with st.spinner(f"'{cno}' 백업 중..."):
                ok_b, msg_b = backup_data_to_new_sheet([item])
            if not ok_b:
                st.session_state["form_error_message"] = f"'{cno}' 백업 실패: {msg_b}"
                continue
            ok_d, msg_d = delete_rows_by_container_nos([cno])
            if ok_d:
                st.session_state.container_list = [
                    c for c in st.session_state.container_list if c.get('컨테이너 번호') != cno
                ]
                log_change(f"선적완료 즉시 백업: {cno}")
                any_done = True
            else:
                st.session_state["form_error_message"] = f"'{cno}' 백업됐으나 메인시트 삭제 실패: {msg_d}"
        if any_done:
            st.session_state["form_success_message"] = "선적완료 처리 및 백업이 완료되었습니다."
        st.rerun()

    # 출력 대상: 슬롯에 컨테이너가 있고 출력선택된 행만
    selected_cnos = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row['출력선택'] and row['컨테이너 번호']
    ]

    # 미리보기 옵션은 선적중 컨테이너만
    shippable_cnos = [
        c.get('컨테이너 번호', '') for c in st.session_state.container_list
        if c.get('상태') == '선적중' and c.get('컨테이너 번호') and _slot_of(c)
    ]
    cno_options = ["미리보기"] + shippable_cnos
    preview_sel = st.selectbox("미리보기", cno_options, label_visibility="collapsed")
    preview_cno = None if preview_sel == "미리보기" else preview_sel

    if preview_cno:
        qr_bytes = generate_qrcode(preview_cno)
        b64 = base64.b64encode(qr_bytes).decode()
        st.markdown(f"""
        <div style="text-align:center; margin:-10px 0 4px 0;">
            <img src="data:image/png;base64,{b64}" style="width:200px; max-width:80%; display:block; margin:0 auto;">
            <div style="font-size:22px; font-weight:bold; margin-top:-12px; letter-spacing:1px;">{preview_cno}</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

    btn_label = f"🖨️ {len(selected_cnos)}개 출력 (각 2장)" if selected_cnos else "🖨️ 출력"
    if selected_cnos:
        button_marker("primary")
    if st.button(btn_label, use_container_width=True, key="print_barcode_btn", disabled=not selected_cnos):
        if not printer_ip:
            st.warning("프린터 IP를 먼저 설정 페이지에서 입력해주세요.")
        else:
            for i, cno in enumerate(selected_cnos):
                zpl_code = make_zpl(cno, copies=2)
                send_zpl_to_printer(printer_ip, zpl_code, result_key=f"p{i}")

st.divider()

st.markdown("#### 📝 신규 컨테이너 등록")
with st.form(key="new_container_form"):
    destinations = get_destinations()
    # 설정에서 삭제되어 세션에 남은 출고처가 현재 목록에 없으면 첫 항목으로 보정
    if destinations and st.session_state.get("form_destination") not in destinations:
        st.session_state["form_destination"] = destinations[0]
    # 현재 차있는 위치 슬롯 → {위치: 컨테이너번호}
    occupied_slots = {
        container_slot(c): c.get('컨테이너 번호')
        for c in st.session_state.container_list if container_slot(c)
    }
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    location = st.radio(
        "2. 위치", options=LOCATION_OPTIONS, horizontal=True, key="form_location",
        format_func=lambda s: f"{s} 🔴" if s in occupied_slots else s,
        help="🔴 위치는 이미 차있으며, 등록 시 기존 컨테이너가 자동으로 선적완료·백업 처리됩니다."
    )
    destination = st.radio("3. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("4. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("5. 씰 번호 (선택)", key="form_seal_no")

    button_marker("success")
    submitted = st.form_submit_button("➕ 등록", use_container_width=True)
    if submitted:
        st.session_state["form_success_message"] = ""
        st.session_state["form_error_message"] = ""

        if not container_no:
            st.session_state["form_error_message"] = "컨테이너 번호를 입력해주세요."
        elif not is_valid_container_no(container_no):
            st.session_state["form_error_message"] = "컨테이너 번호 형식이 올바르지 않습니다."
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list):
            st.session_state["form_error_message"] = f"이미 등록된 컨테이너 번호입니다: {container_no}"
        else:
            # 선택한 위치에 기존 컨테이너가 있으면 자동 선적완료(백업+메인시트 삭제) 후 슬롯 재사용
            proceed = True
            if location in occupied_slots:
                old_cno = occupied_slots[location]
                old_item = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == old_cno), None)
                if old_item:
                    old_item = old_item.copy()
                    old_item['상태'] = '선적완료'
                    old_item['완료일시'] = pd.to_datetime(get_korea_now().replace(tzinfo=None))
                    with st.spinner(f"위치 {location}번 기존 컨테이너 '{old_cno}' 선적완료 처리 중..."):
                        ok_b, msg_b = backup_data_to_new_sheet([old_item])
                        ok_d, msg_d = delete_rows_by_container_nos([old_cno]) if ok_b else (False, msg_b)
                    if ok_b and ok_d:
                        st.session_state.container_list = [
                            c for c in st.session_state.container_list if c.get('컨테이너 번호') != old_cno
                        ]
                        log_change(f"위치 {location}번 재등록: 기존 '{old_cno}' 자동 선적완료/백업")
                    else:
                        proceed = False
                        st.session_state["form_error_message"] = (
                            f"위치 {location}번 기존 컨테이너 자동 선적완료 실패: {msg_b if not ok_b else msg_d}"
                        )

            if proceed:
                korea_now = get_korea_now()
                naive_datetime = korea_now.replace(tzinfo=None)

                new_container = {
                    '컨테이너 번호': container_no, '출고처': destination, '피트수': feet,
                    '씰 번호': seal_no, '상태': '선적중',
                    '등록일시': pd.to_datetime(naive_datetime),
                    '완료일시': None, '위치': location
                }

                with st.spinner('데이터를 저장하는 중...'):
                    success, message = add_row_to_gsheet(new_container)

                if success:
                    st.session_state.container_list.append(new_container)
                    st.session_state.submission_success = True
                    st.session_state.form_success_message = f"컨테이너 '{container_no}'가 위치 {location}번에 등록되었습니다."
                    st.rerun()
                else:
                    st.session_state["form_error_message"] = f"등록 실패: {message}. 잠시 후 다시 시도해주세요."

if st.session_state.get("form_success_message"):
    st.success(st.session_state.get("form_success_message"))
    st.session_state["form_success_message"] = ""
if st.session_state.get("form_error_message"):
    st.error(st.session_state.get("form_error_message"))
    st.session_state["form_error_message"] = ""