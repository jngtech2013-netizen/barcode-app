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
    update_row_in_gsheet,
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

POSITIONS = [str(i) for i in range(1, 10)]  # 위치 1~9 (창고 슬롯)

def clear_form_inputs():
    dests = get_destinations()
    st.session_state["form_container_no"] = ""
    st.session_state["form_position"] = "1"
    st.session_state["form_seal_no"] = "1"  # 씰 번호 기본값 = 위치
    st.session_state["form_destination"] = dests[0] if dests else ""
    st.session_state["form_feet"] = "40"

def on_position_change():
    # 위치를 바꾸면 씰 번호 기본값도 같은 값으로 자동 채운다.
    st.session_state["form_seal_no"] = st.session_state["form_position"]

def complete_and_backup_container(container_no):
    """컨테이너를 선적완료 처리해 일별/월별 백업으로 옮기고 메인 시트·세션에서 제거한다.
    (선적완료 = 자동 백업+제거. 데이터 백업 버튼을 대체한다.)"""
    idx = next((i for i, c in enumerate(st.session_state.container_list)
                if c.get('컨테이너 번호') == container_no), None)
    if idx is None:
        return False, "컨테이너를 찾을 수 없습니다."
    item = st.session_state.container_list[idx].copy()
    item['상태'] = '선적완료'
    item['완료일시'] = pd.to_datetime(get_korea_now().replace(tzinfo=None))
    with st.spinner(f"'{container_no}' 선적완료 백업 중..."):
        ok, err = backup_data_to_new_sheet([item])
        if not ok:
            return False, err
        dok, dres = delete_rows_by_container_nos([container_no])
        if not dok:
            return False, dres
    st.session_state.container_list.pop(idx)
    log_change(f"선적완료 자동 백업: {container_no} (위치 {item.get('위치')})")
    return True, None

def register_new_container(new_container):
    """신규 컨테이너를 시트에 추가하고 세션 목록에 반영한다."""
    with st.spinner('데이터를 저장하는 중...'):
        success, message = add_row_to_gsheet(new_container)
    if success:
        st.session_state.container_list.append(new_container)
        st.session_state.submission_success = True
        st.session_state.form_success_message = (
            f"컨테이너 '{new_container['컨테이너 번호']}'가 위치 {new_container['위치']}에 등록되었습니다."
        )
        st.rerun()
    else:
        st.session_state["form_error_message"] = f"등록 실패: {message}. 잠시 후 다시 시도해주세요."

@st.dialog("✏️ 컨테이너 정보 수정")
def edit_container_dialog(container_no):
    """현황 표의 ✏️ 칸을 체크했을 때 뜨는 수정 팝업.
    출고처/피트수/씰번호를 바로 수정한다. (위치는 등록 시에만 지정 — 여기선 표시만,
    선적완료는 표의 '선적완료' 체크로 처리하므로 상태는 다루지 않는다.)"""
    idx = next((i for i, c in enumerate(st.session_state.container_list)
                if c.get('컨테이너 번호') == container_no), None)
    if idx is None:
        st.error("컨테이너를 찾을 수 없습니다. 새로고침 후 다시 시도해주세요.")
        return
    data = st.session_state.container_list[idx]
    st.markdown(f"**{container_no}**")
    st.caption(f"위치: {data.get('위치') or '-'}")

    dest_options = get_destinations()
    current_dest = data.get('출고처', '') if pd.notna(data.get('출고처')) else ''
    if current_dest and current_dest not in dest_options:
        dest_options = [current_dest] + dest_options
    new_dest = st.radio("출고처", options=dest_options,
                        index=dest_options.index(current_dest) if current_dest in dest_options else 0,
                        horizontal=True)

    feet_options = ['40', '20']
    cur_feet = str(data.get('피트수', '40'))
    new_feet = st.radio("피트수", options=feet_options,
                        index=feet_options.index(cur_feet) if cur_feet in feet_options else 0,
                        horizontal=True)

    seal_val = data.get('씰 번호')
    seal_default = '' if seal_val is None or (isinstance(seal_val, float) and pd.isna(seal_val)) else str(seal_val)
    new_seal = st.text_input("씰 번호", value=seal_default)

    button_marker("primary")
    if st.button("💾 저장", use_container_width=True):
        updated = data.copy()
        updated.update({'출고처': new_dest, '피트수': new_feet, '씰 번호': str(new_seal)})
        with st.spinner('수정사항을 저장하는 중...'):
            ok, msg = update_row_in_gsheet(updated)
        if ok:
            st.session_state.container_list[idx] = updated
            st.session_state["form_success_message"] = f"'{container_no}' 정보가 수정되었습니다."
            st.rerun()
        else:
            st.error(f"수정 실패: {msg}")


@st.dialog("⚠️ 위치 사용 중")
def confirm_slot_takeover():
    """등록하려는 위치에 이미 선적중 컨테이너가 있을 때, 기존 것을 선적완료(백업)
    처리하고 새로 등록할지 확인한다."""
    new_c = st.session_state.get("pending_new_container")
    occ_no = st.session_state.get("pending_slot_occupant")
    if not new_c:
        return
    pos = new_c.get('위치')
    st.warning(f"위치 **{pos}** 에 이미 '{occ_no}'(이)가 있습니다.\n\n"
               f"기존 컨테이너를 **선적완료 처리(백업)** 하고 '{new_c.get('컨테이너 번호')}'를 등록할까요?")
    c1, c2 = st.columns(2)
    with c1:
        button_marker("primary")
        if st.button("선적완료 후 등록", use_container_width=True):
            ok, err = complete_and_backup_container(occ_no)
            if not ok:
                st.error(f"기존 컨테이너 처리 실패: {err}")
                return
            st.session_state.pop("pending_new_container", None)
            st.session_state.pop("pending_slot_occupant", None)
            register_new_container(new_c)  # 내부에서 rerun
    with c2:
        button_marker("neutral")
        if st.button("취소", use_container_width=True):
            st.session_state.pop("pending_new_container", None)
            st.session_state.pop("pending_slot_occupant", None)
            st.rerun()

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

    # --- 위치(1~9) 슬롯 매핑: 위치가 지정된 선적중 컨테이너만 슬롯에 표시 ---
    # 복구/레거시 등 위치값이 없는 컨테이너는 등록 슬롯에 들어오지 않으며,
    # 관리(수정) 페이지에서만 다룬다.
    slot_map = {}
    for c in st.session_state.container_list:
        if c.get('상태') != '선적중':
            continue
        pos = str(c.get('위치') or '').strip()
        if pos in POSITIONS and pos not in slot_map:
            slot_map[pos] = c

    # --- 사용 중 / 빈 자리 카드 ---
    used_count = len(slot_map)
    empty_count = max(0, 9 - used_count)
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
            <div style="flex:1"><div class="metric-card"><div class="metric-value red-value">{used_count}</div><div class="metric-label">사용 중</div></div></div>
            <div style="flex:1"><div class="metric-card"><div class="metric-value green-value">{empty_count}</div><div class="metric-label">빈 자리</div></div></div>
        </div>
        """, unsafe_allow_html=True
    )

    def _fmt_dt(v):
        t = pd.to_datetime(v, errors='coerce')
        return t.strftime('%Y-%m-%d %H:%M') if pd.notna(t) else ''

    def _seal_str(v):
        return '' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    def _txt(v):
        return str(v) if v is not None and pd.notna(v) else ''

    table_rows = []
    for pos in POSITIONS:
        c = slot_map.get(pos)
        if c:
            table_rows.append({
                '출력선택': False, '위치': pos,
                '컨테이너 번호': _txt(c.get('컨테이너 번호')),
                '출고처': _txt(c.get('출고처')),
                '피트수': _txt(c.get('피트수')),
                '씰 번호': _seal_str(c.get('씰 번호')),
                '등록일시': _fmt_dt(c.get('등록일시')),
                '선적완료': False, '수정': False,
            })
        else:
            table_rows.append({
                '출력선택': False, '위치': pos, '컨테이너 번호': '', '출고처': '',
                '피트수': '', '씰 번호': '', '등록일시': '', '선적완료': False, '수정': False,
            })

    display_df = pd.DataFrame(table_rows)
    column_order = ['출력선택', '위치', '컨테이너 번호', '출고처', '피트수', '씰 번호', '등록일시', '선적완료', '수정']

    # ✏️ 체크 후 팝업을 닫으면 체크가 남아 재오픈되는 것을 막기 위해 키를 바꿔 초기화
    editor_key = f"merged_editor_{st.session_state.get('editor_rev', 0)}"
    edited_df = st.data_editor(
        display_df,
        column_order=column_order,
        use_container_width=True,
        hide_index=True,
        height=(len(POSITIONS) + 1) * 35 + 3,  # 정확히 9개 행만 스크롤 없이 보이도록 (헤더 1 + 9행)
        key=editor_key,
        column_config={
            "출력선택": st.column_config.CheckboxColumn("출력선택", default=False, width="small", help="해당 위치의 컨테이너를 출력 대상으로 선택합니다."),
            "위치": st.column_config.TextColumn("위치", width=40, disabled=True),
            "수정": st.column_config.CheckboxColumn("✏️", width="small", help="체크하면 해당 컨테이너 수정 팝업이 열립니다."),
            "선적완료": st.column_config.CheckboxColumn("선적완료", width="small", help="체크하면 해당 컨테이너를 자동 백업하고 목록에서 제거합니다."),
            "컨테이너 번호": st.column_config.TextColumn(disabled=True),
            "출고처": st.column_config.TextColumn(disabled=True),
            "피트수": st.column_config.TextColumn(disabled=True),
            "씰 번호": st.column_config.TextColumn(disabled=True),
            "등록일시": st.column_config.TextColumn(disabled=True),
        }
    )

    # ✏️ 수정 체크 감지 (컨테이너가 있는 슬롯만) → 키를 회전해 표를 초기화한 뒤 팝업을 연다.
    newly_checked = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row.get('수정') and row.get('컨테이너 번호')
    ]
    if newly_checked:
        st.session_state['editor_rev'] = st.session_state.get('editor_rev', 0) + 1
        st.session_state['pending_edit'] = newly_checked[0]
        st.rerun()

    # 초기화된 표가 그려진 다음 런에서 팝업을 연다.
    if st.session_state.get('pending_edit'):
        edit_container_dialog(st.session_state.pop('pending_edit'))

    # 선적완료 체크 → 자동 백업 + 메인 시트/목록에서 제거 (데이터 백업 버튼 대체)
    to_complete = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row.get('선적완료') and row.get('컨테이너 번호')
    ]
    if to_complete:
        cno = to_complete[0]
        ok, err = complete_and_backup_container(cno)
        if ok:
            st.session_state["form_success_message"] = f"'{cno}' 선적완료 — 백업 후 목록에서 제거했습니다."
        else:
            st.session_state["form_error_message"] = f"선적완료 처리 실패: {err}"
        st.rerun()

    # 출력 대상: 컨테이너가 있는 슬롯 중 출력선택된 것
    selected_cnos = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row['출력선택'] and row.get('컨테이너 번호')
    ]

    # 미리보기 옵션은 선적중 컨테이너만
    shippable_cnos = [
        c.get('컨테이너 번호', '') for c in st.session_state.container_list
        if c.get('상태') == '선적중' and c.get('컨테이너 번호')
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
# 위치 변경 시 씰 번호가 즉시 따라오도록 st.form 대신 일반 위젯으로 구성한다.
with st.container(border=True):
    destinations = get_destinations()
    # 설정에서 삭제되어 세션에 남은 출고처가 현재 목록에 없으면 첫 항목으로 보정
    if destinations and st.session_state.get("form_destination") not in destinations:
        st.session_state["form_destination"] = destinations[0]
    st.session_state.setdefault("form_position", "1")
    st.session_state.setdefault("form_seal_no", st.session_state["form_position"])

    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    position = st.radio("2. 위치", options=POSITIONS, horizontal=True,
                        key="form_position", on_change=on_position_change)
    destination = st.radio("3. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("4. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("5. 씰 번호", key="form_seal_no")

    button_marker("success")
    submitted = st.button("➕ 등록", use_container_width=True, key="register_btn")
    if submitted:
        st.session_state["form_success_message"] = ""
        st.session_state["form_error_message"] = ""

        if not container_no or not seal_no:
            st.session_state["form_error_message"] = "컨테이너 번호와 씰 번호를 모두 입력해주세요."
        elif not is_valid_container_no(container_no):
            st.session_state["form_error_message"] = "컨테이너 번호 형식이 올바르지 않습니다."
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list):
            st.session_state["form_error_message"] = f"이미 등록된 컨테이너 번호입니다: {container_no}"
        else:
            naive_datetime = get_korea_now().replace(tzinfo=None)
            new_container = {
                '컨테이너 번호': container_no, '출고처': destination, '피트수': feet,
                '씰 번호': seal_no, '상태': '선적중',
                '등록일시': pd.to_datetime(naive_datetime),
                '완료일시': None, '위치': str(position),
            }

            # 같은 위치에 이미 컨테이너가 있으면(표에 표시된 슬롯 기준) 확인 다이얼로그를 띄운다.
            occupant = slot_map.get(str(position))
            if occupant:
                st.session_state["pending_new_container"] = new_container
                st.session_state["pending_slot_occupant"] = occupant.get('컨테이너 번호')
                st.rerun()
            else:
                register_new_container(new_container)  # 내부에서 rerun

# 위치 충돌 확인 대기 중이면 다이얼로그를 연다.
if st.session_state.get("pending_new_container"):
    confirm_slot_takeover()

if st.session_state.get("form_success_message"):
    st.success(st.session_state.get("form_success_message"))
    st.session_state["form_success_message"] = ""
if st.session_state.get("form_error_message"):
    st.error(st.session_state.get("form_error_message"))
    st.session_state["form_error_message"] = ""