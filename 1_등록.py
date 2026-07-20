import streamlit as st
import pandas as pd
import qrcode
import base64
import hashlib
from io import BytesIO
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageOps
import streamlit.components.v1 as components

from container_ocr import (
    recognize_container_numbers,
    OcrError,
    OCR_SPACE_DEMO_KEY,
)
from utils import (
    load_data_from_gsheet,
    add_row_to_gsheet,
    update_row_in_gsheet,
    backup_data_to_new_sheet,
    delete_from_backup_sheets,
    BACKUP_PREFIX,
    RESTORE_SLOT,
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

def run_container_ocr(image_bytes: bytes):
    """사진 OCR 결과를 세션에 캐시해 rerun마다 API를 재호출하지 않는다.

    반환: ("ok", (후보목록, 실패시도 오류목록)) 또는 ("error", 오류메시지).
    오류도 캐시해 실패한 호출이 rerun마다 반복되지 않게 하고,
    '다시 인식' 버튼이 해당 캐시를 지워 재호출한다.
    """
    key = hashlib.md5(image_bytes).hexdigest()
    cache = st.session_state.setdefault("ocr_results", {})
    if key not in cache:
        api_key = st.secrets.get("ocrspace_api_key", OCR_SPACE_DEMO_KEY)
        try:
            cache[key] = ("ok", recognize_container_numbers(image_bytes, api_key))
        except OcrError as e:
            cache[key] = ("error", str(e))
    return key, cache[key]

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
UNDECIDED = '미정'  # 출고처 미지정 표시값 (선적완료/백업 차단 대상)

def clear_form_inputs():
    dests = get_destinations()
    st.session_state["form_container_no"] = ""
    st.session_state["form_position"] = "1"
    st.session_state["form_seal_no"] = ""  # 씰 번호 기본값은 공백(선택 입력)
    st.session_state["form_destination"] = dests[0] if dests else ""
    st.session_state["form_feet"] = "40"

def complete_and_backup_container(container_no, record_undo=True):
    """컨테이너를 선적완료 처리해 일별/월별 백업으로 옮기고 메인 시트·세션에서 제거한다.
    (선적완료 = 자동 백업+제거. 데이터 백업 버튼을 대체한다.)
    record_undo=True면 '방금 선적완료 되돌리기'용 스냅샷을 저장한다."""
    idx = next((i for i, c in enumerate(st.session_state.container_list)
                if c.get('컨테이너 번호') == container_no), None)
    if idx is None:
        return False, "컨테이너를 찾을 수 없습니다."
    original = st.session_state.container_list[idx].copy()  # 선적중 원본(되돌리기용)
    item = original.copy()
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
    if record_undo:
        today_str = get_korea_now().date().isoformat()
        st.session_state['last_completed'] = {
            'item': original,
            'backup_sheet': f"{BACKUP_PREFIX}{today_str}",
        }
    log_change(f"선적완료 자동 백업: {container_no} (위치 {item.get('위치')})")
    return True, None

def undo_last_completed():
    """방금 선적완료한 컨테이너를 백업에서 빼내 다시 선적중 상태로 되돌린다."""
    snap = st.session_state.get('last_completed')
    if not snap:
        return False, "되돌릴 선적완료 항목이 없습니다."
    original = snap['item']
    cno = original.get('컨테이너 번호')
    pos = str(original.get('위치') or '').strip()
    if any(c.get('컨테이너 번호') == cno for c in st.session_state.container_list):
        st.session_state.pop('last_completed', None)
        return False, "이미 목록에 있어 되돌릴 수 없습니다."
    # 원래 위치가 다른 선적중 컨테이너에 점유됐으면 막는다.
    occupied = {
        str(c.get('위치') or '').strip()
        for c in st.session_state.container_list if c.get('상태') == '선적중'
    }
    note = None
    restore = original.copy()
    restore['상태'] = '선적중'
    restore['완료일시'] = None
    if pos and pos != RESTORE_SLOT and pos in occupied:  # 복원 슬롯은 여러 개 허용
        # 원래 위치가 차있으면 차단하지 않고 위치 없이 복원한다.
        # → 등록 페이지 슬롯엔 안 보이고 관리 페이지 목록에서만 보인다.
        restore['위치'] = ''
        note = (f"'{cno}' 선적완료를 되돌렸습니다. 위치 {pos}이(가) 사용 중이라 "
                f"위치 없이 복원했습니다 — 관리 페이지에서 확인 후 위치를 지정하세요.")
    with st.spinner(f"'{cno}' 되돌리는 중..."):
        ok, msg = add_row_to_gsheet(restore)
        if not ok:
            return False, msg
        delete_from_backup_sheets([cno], snap['backup_sheet'])  # 백업 중복 제거(베스트에포트)
    st.session_state.container_list.append(restore)
    st.session_state.pop('last_completed', None)
    log_change(f"선적완료 되돌리기: {cno} (위치 {restore.get('위치') or '없음'})")
    return True, note

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
    위치/출고처/피트수/씰번호를 바로 수정한다.
    (선적완료는 표의 '선적완료' 체크로 처리하므로 상태는 다루지 않는다.)"""
    idx = next((i for i, c in enumerate(st.session_state.container_list)
                if c.get('컨테이너 번호') == container_no), None)
    if idx is None:
        st.error("컨테이너를 찾을 수 없습니다. 새로고침 후 다시 시도해주세요.")
        return
    data = st.session_state.container_list[idx]
    st.markdown(f"**{container_no}**")

    cur_pos = str(data.get('위치') or '').strip()
    # 복원 슬롯에 있는 컨테이너는 '복원' 유지 또는 1~9로 이동을 선택할 수 있다.
    # (일반 슬롯 컨테이너에게는 복원 슬롯 옵션을 노출하지 않는다 — 복원 전용)
    pos_options = POSITIONS + [RESTORE_SLOT] if cur_pos == RESTORE_SLOT else POSITIONS
    pos_index = pos_options.index(cur_pos) if cur_pos in pos_options else 0
    new_pos = st.radio("위치", options=pos_options, index=pos_index, horizontal=True)

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
        # 다른 선적중 컨테이너가 이미 점유한 위치로는 옮길 수 없다.
        occupied = {
            str(c.get('위치') or '').strip()
            for c in st.session_state.container_list
            if c.get('상태') == '선적중' and c.get('컨테이너 번호') != container_no
        }
        if new_pos != RESTORE_SLOT and new_pos in occupied:  # 복원 슬롯은 여러 개 허용
            st.error(f"위치 {new_pos}은(는) 이미 사용 중입니다. 다른 위치를 선택하세요.")
        else:
            updated = data.copy()
            updated.update({'출고처': new_dest, '피트수': new_feet,
                            '씰 번호': str(new_seal), '위치': new_pos})
            with st.spinner('수정사항을 저장하는 중...'):
                ok, msg = update_row_in_gsheet(updated)
            if ok:
                st.session_state.container_list[idx] = updated
                # 수정 완료 안내는 현황 표(되돌리기 버튼) 아래에 표시한다.
                st.session_state["table_action_msg"] = ("success", f"'{container_no}' 정보가 수정되었습니다.")
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
            # 기존(점유) 컨테이너 출고처가 미정이면 선적완료(백업)할 수 없으므로 차단한다.
            occupant = next((c for c in st.session_state.container_list
                             if c.get('컨테이너 번호') == occ_no), None)
            if occupant and str(occupant.get('출고처') or '').strip() == UNDECIDED:
                st.error(
                    f"기존 컨테이너 '{occ_no}'의 출고처가 '{UNDECIDED}'입니다.\n"
                    f"먼저 출고처를 지정해야 선적완료(백업)하고 등록할 수 있습니다."
                )
                return
            ok, err = complete_and_backup_container(occ_no, record_undo=False)
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


@st.dialog("📷 번호 인식")
def ocr_dialog():
    """컨테이너 번호 입력칸 옆 OCR 버튼으로 여는 팝업.
    촬영/업로드 → 인식 → 번호 버튼을 누르면 입력칸에 채워지고 팝업이 닫힌다.
    (위젯 키 충돌을 피하려고 값은 ocr_apply_no에 담아 다음 런에서 반영한다)
    모바일 브라우저는 파일 선택 시 '카메라 촬영'도 함께 제공하므로
    별도 카메라 탭 없이 업로더 하나로 촬영·업로드를 모두 처리한다."""
    ocr_img = st.file_uploader("사진을 촬영하거나 선택하세요 (번호가 크고 정면으로 보이게)",
                               type=["jpg", "jpeg", "png"], key="ocr_upload")
    if ocr_img is not None:
        # 휴대폰 사진은 EXIF에 회전 정보만 담고 실제 픽셀은 눕혀 저장되는 경우가 많아
        # exif_transpose로 보정한 뒤 인식된 번호 아래에 미리보기로 보여준다
        # (인식은 원본 바이트로 그대로 수행).
        preview_img = ImageOps.exif_transpose(Image.open(BytesIO(ocr_img.getvalue())))
        with st.spinner("사진에서 컨테이너 번호를 인식하는 중..."):
            cache_key, (ocr_status, ocr_payload) = run_container_ocr(ocr_img.getvalue())
        if ocr_status == "error":
            st.error(f"인식 실패: {ocr_payload}")
            st.image(preview_img, caption="촬영/업로드한 사진", use_container_width=True)
            if st.button("🔄 다시 시도", key="ocr_retry"):
                st.session_state.get("ocr_results", {}).pop(cache_key, None)
                st.rerun(scope="fragment")
        else:
            ocr_candidates, ocr_errors, ocr_texts = ocr_payload
            # 등록 데이터는 정확해야 하므로 체크디지트(ISO 6346) 검증까지
            # 통과한 번호만 보여준다.
            valid_candidates = [cno for cno, ok in ocr_candidates if ok]
            if valid_candidates:
                st.success("번호를 누르면 입력칸에 채워집니다.")
                for cno in valid_candidates[:3]:
                    if st.button(f"✅ {cno}", key=f"ocr_pick_{cno}", use_container_width=True):
                        st.session_state["ocr_apply_no"] = cno
                        st.rerun()  # 전체 rerun → 팝업이 닫히고 입력칸에 반영
            else:
                st.warning("컨테이너 번호를 정확히 인식하지 못했습니다. "
                           "번호 부분이 크고 선명하게 보이도록 가까이서 다시 촬영해 주세요.")
            st.image(preview_img, caption="촬영/업로드한 사진 — 인식 결과와 대조하세요", use_container_width=True)
            if ocr_texts:
                with st.expander("📄 사진에서 읽힌 글자 보기 (오인식 원인 확인용)"):
                    st.text("\n──────────\n".join(t.strip() for t in ocr_texts))
            if ocr_errors:
                st.warning(f"인식 재시도 호출 {len(ocr_errors)}회가 실패했습니다: {ocr_errors[-1]}")
            if st.button("🔄 다시 인식", key="ocr_retry_ok",
                         help="캐시된 결과를 지우고 이 사진을 다시 인식합니다."):
                st.session_state.get("ocr_results", {}).pop(cache_key, None)
                st.rerun(scope="fragment")
    if st.secrets.get("ocrspace_api_key", OCR_SPACE_DEMO_KEY) == OCR_SPACE_DEMO_KEY:
        st.caption("⚠️ 지금은 데모용 공용 키로 동작 중입니다 — ocr.space/ocrapi 에서 "
                   "무료 키를 발급받아 secrets에 `ocrspace_api_key`로 넣어주세요.")


@st.dialog("⚠️ 출고처 미정")
def undecided_block_dialog(container_no):
    """출고처가 미정인 컨테이너의 선적완료(백업)를 막고 안내하는 팝업."""
    st.warning(
        f"**{container_no}** 의 출고처가 '{UNDECIDED}'입니다.\n\n"
        f"출고처를 먼저 지정해야 선적완료(백업)할 수 있습니다.\n"
        f"표의 ✏️ 칸을 체크해 출고처를 변경하세요."
    )
    button_marker("primary")
    if st.button("확인", use_container_width=True):
        st.rerun()

if st.session_state.get("submission_success", False):
    clear_form_inputs()
    st.session_state.submission_success = False

# OCR 팝업에서 선택한 번호를 위젯 생성 전에 입력칸에 반영한다.
if st.session_state.get("ocr_apply_no"):
    st.session_state["form_container_no"] = st.session_state.pop("ocr_apply_no")

apply_sidebar_style('''
.element-container:has(.reg-section-mk) ~ .element-container * { font-size: 17px !important; }
/* 컨테이너 번호 입력창 + OCR 버튼 행(key=cno_row): 폼과 같은 17px 글씨 유지 */
.st-key-cno_row * { font-size: 17px !important; }
/* 좁은 화면에서 Streamlit이 컬럼을 세로로 쌓는 것(flex-direction: column)을 막고
   입력창(가변폭) + 버튼(내용폭)이 항상 같은 줄에 있도록 고정 */
.st-key-cno_row div[data-testid="stHorizontalBlock"] { flex-direction: row !important; flex-wrap: nowrap !important; }
.st-key-cno_row div[data-testid="stColumn"]:first-child { flex: 1 1 auto !important; width: auto !important; min-width: 0 !important; }
.st-key-cno_row div[data-testid="stColumn"]:last-child { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
/* OCR 팝업: 파일 업로더의 영문 안내(드래그/용량 제한) 숨김 */
.st-key-ocr_upload [data-testid="stFileUploaderDropzoneInstructions"] { display: none !important; }
/* OCR 팝업: 사진 선택 후 파일 칩 옆에 뜨는 "＋"(파일 추가, Add files) 버튼 숨김.
   컨테이너 사진은 한 장만 인식하면 되므로 추가 업로드는 막는다.
   (다른 사진으로 바꾸려면 파일 칩의 ✕로 지우고 다시 선택) */
.st-key-ocr_upload button[data-testid="stBaseButton-borderlessIcon"] { display: none !important; }
/* OCR 팝업: "Browse files" 버튼 글자를 "📷 카메라/파일"로 교체 (Streamlit이 버튼 문구를 커스터마이즈하는 옵션을 제공하지 않아
   버튼 내부 텍스트(자식 요소 포함)를 전부 숨기고 ::after로 새 글자를 덧씌운다).
   absolute 오버레이 대신 흐름 안에 두어 버튼 크기가 새 글자 폭에 맞게 줄어들도록 한다. */
.st-key-ocr_upload button[data-testid="stBaseButton-secondary"] {
    display: flex !important;
    justify-content: flex-start !important;
    width: fit-content !important;
    min-width: 0 !important;
    padding: 0 20px !important;
    font-size: 0 !important;
}
/* font-size:0만으로는 자식 요소 자신의 padding/margin이 남아 보이지 않는 여백을 만들 수 있으므로
   원본 아이콘·텍스트 자식 요소를 아예 display:none으로 완전히 제거한다 */
.st-key-ocr_upload button[data-testid="stBaseButton-secondary"] > * { display: none !important; }
.st-key-ocr_upload button[data-testid="stBaseButton-secondary"]::after {
    content: "📷 카메라/파일";
    font-size: 14px;
}
/* 텍스트 입력 시 우측 하단에 뜨는 "Press Enter to apply" 영문 안내 숨김 */
[data-testid="InputInstructions"] { display: none !important; }
/* OCR 팝업: 안내 메시지 여백 축소 */
[data-testid="stDialog"] [data-testid="stAlert"] { padding: 0.4rem 0.75rem; }
''')

if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

render_app_title()

st.markdown("#### 📋 컨테이너 현황")
with st.container(border=True):
    printer_ip = st.session_state.get("printer_ip", "")

    # --- 위치(1~9) 슬롯 매핑: 위치가 지정된 선적중 컨테이너만 슬롯에 표시 ---
    # 위치가 '복원'인 컨테이너(관리 페이지에서 개별 복원한 것)는 복원 전용 슬롯에 표시한다.
    # 그 외 위치값이 없는 레거시 컨테이너는 관리(수정) 페이지에서만 다룬다.
    slot_map = {}
    restore_slot_containers = []  # 복원 슬롯은 여러 개가 동시에 들어올 수 있다
    for c in st.session_state.container_list:
        if c.get('상태') != '선적중':
            continue
        pos = str(c.get('위치') or '').strip()
        if pos in POSITIONS and pos not in slot_map:
            slot_map[pos] = c
        elif pos == RESTORE_SLOT:
            restore_slot_containers.append(c)

    def _fmt_dt(v):
        t = pd.to_datetime(v, errors='coerce')
        return t.strftime('%Y-%m-%d %H:%M') if pd.notna(t) else ''

    def _seal_str(v):
        return '' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    def _txt(v):
        return str(v) if v is not None and pd.notna(v) else ''

    def _slot_row(pos, c):
        if not c:
            return {
                '출력선택': False, '위치': pos, '컨테이너 번호': '', '출고처': '',
                '피트수': '', '씰 번호': '', '등록일시': '', '선적완료': False, '수정': False,
            }
        dest_val = _txt(c.get('출고처'))
        return {
            '출력선택': False, '위치': pos,
            '컨테이너 번호': _txt(c.get('컨테이너 번호')),
            # 출고처가 미정이면 셀에서도 눈에 띄게 경고 표시
            '출고처': (f"⚠️ {UNDECIDED}" if dest_val == UNDECIDED else dest_val),
            '피트수': _txt(c.get('피트수')),
            '씰 번호': _seal_str(c.get('씰 번호')),
            '등록일시': _fmt_dt(c.get('등록일시')),
            '선적완료': False, '수정': False,
        }

    table_rows = [_slot_row(pos, slot_map.get(pos)) for pos in POSITIONS]
    # 복원 전용 슬롯: 관리 페이지에서 개별 복원한 컨테이너가 있을 때만 행이 나타난다
    table_rows.extend(_slot_row(RESTORE_SLOT, c) for c in restore_slot_containers)

    display_df = pd.DataFrame(table_rows)
    column_order = ['출력선택', '위치', '컨테이너 번호', '출고처', '피트수', '씰 번호', '등록일시', '선적완료', '수정']

    # ✏️ 체크 후 팝업을 닫으면 체크가 남아 재오픈되는 것을 막기 위해 키를 바꿔 초기화
    editor_key = f"merged_editor_{st.session_state.get('editor_rev', 0)}"
    edited_df = st.data_editor(
        display_df,
        column_order=column_order,
        use_container_width=True,
        hide_index=True,
        height=(len(table_rows) + 1) * 35 + 3,  # 모든 슬롯 행(1~9 + 복원)이 스크롤 없이 보이도록 (헤더 1 + 행 수)
        key=editor_key,
        column_config={
            "출력선택": st.column_config.CheckboxColumn("🖨️", default=False, width=50, help="해당 위치의 컨테이너를 출력 대상으로 선택합니다."),
            # TextColumn에 alignment 공개 인자가 없어, 반환 dict에 직접 'center'를 주입해 가운데 정렬한다.
            "위치": {**st.column_config.TextColumn("위치", width=35, disabled=True), "alignment": "center"},
            "수정": st.column_config.CheckboxColumn("✏️", width="small", help="체크하면 해당 컨테이너 수정 팝업이 열립니다."),
            "선적완료": st.column_config.CheckboxColumn("선적완료", width="small", help="체크하면 해당 컨테이너를 자동 백업하고 목록에서 제거합니다."),
            "컨테이너 번호": {**st.column_config.TextColumn(disabled=True), "alignment": "center"},
            "출고처": st.column_config.TextColumn(disabled=True, width=70),
            "피트수": {**st.column_config.TextColumn(disabled=True), "alignment": "center"},
            "씰 번호": {**st.column_config.TextColumn(disabled=True), "alignment": "center"},
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
        target = next((c for c in st.session_state.container_list if c.get('컨테이너 번호') == cno), None)
        if target and str(target.get('출고처') or '').strip() == UNDECIDED:
            # 출고처 미정이면 백업 차단 → 팝업으로 안내 (체크는 키 회전으로 초기화)
            st.session_state['editor_rev'] = st.session_state.get('editor_rev', 0) + 1
            st.session_state['undecided_block'] = cno
        else:
            ok, err = complete_and_backup_container(cno)
            if ok:
                st.session_state["table_action_msg"] = ("success", f"'{cno}' 선적완료 — 백업 후 목록에서 제거했습니다.")
            else:
                st.session_state["table_action_msg"] = ("error", f"선적완료 처리 실패: {err}")
        st.rerun()

    # 출고처 미정으로 선적완료가 차단된 경우 팝업 안내
    if st.session_state.get('undecided_block'):
        undecided_block_dialog(st.session_state.pop('undecided_block'))

    # 출력 대상: 컨테이너가 있는 슬롯 중 출력선택된 것
    selected_cnos = [
        row['컨테이너 번호'] for _, row in edited_df.iterrows()
        if row['출력선택'] and row.get('컨테이너 번호')
    ]

    # 현황 표 관련 안내(수정 완료/선적완료/되돌리기 등)는 되돌리기 버튼 바로 위에 표시한다.
    _tbl_msg = st.session_state.pop("table_action_msg", None)
    if _tbl_msg:
        getattr(st, _tbl_msg[0])(_tbl_msg[1])

    # 방금 선적완료한 컨테이너 되돌리기 (백업에서 다시 선적중으로 복원)
    last_snap = st.session_state.get('last_completed')
    undo_label = (f"↩️ 방금 선적완료 되돌리기 ({last_snap['item'].get('컨테이너 번호')})"
                  if last_snap else "↩️ 되돌리기 (최근 선적완료 없음)")
    if st.button(undo_label, use_container_width=True, disabled=not last_snap, key="undo_complete_btn"):
        _undo_cno = last_snap['item'].get('컨테이너 번호')
        ok, note = undo_last_completed()
        if ok:
            if note:
                st.session_state["table_action_msg"] = ("warning", note)
            else:
                st.session_state["table_action_msg"] = ("success", f"'{_undo_cno}' 선적완료를 되돌렸습니다.")
        else:
            st.session_state["table_action_msg"] = ("error", f"되돌리기 실패: {note}")
        st.rerun()

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
with st.container(border=True):
    st.markdown('<div class="reg-section-mk" style="display:none"></div>', unsafe_allow_html=True)
    destinations = get_destinations()
    # '미정'(출고처 미지정)을 항상 선택할 수 있도록 옵션 앞에 추가
    dest_options = destinations if UNDECIDED in destinations else [UNDECIDED] + destinations
    # 설정에서 삭제되어 세션에 남은 출고처가 현재 옵션에 없으면 첫 실제 출고처로 보정
    if dest_options and st.session_state.get("form_destination") not in dest_options:
        st.session_state["form_destination"] = destinations[0] if destinations else UNDECIDED
    st.session_state.setdefault("form_position", "1")
    st.session_state.setdefault("form_seal_no", "")

    with st.container(key="cno_row"):
        col_no, col_ocr = st.columns([4, 1], vertical_alignment="bottom")
        with col_no:
            container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
        with col_ocr:
            if st.button("📷 OCR", key="ocr_open_btn",
                         help="사진을 찍거나 올려서 컨테이너 번호를 자동 인식합니다."):
                ocr_dialog()
    position = st.radio("2. 위치", options=POSITIONS, horizontal=True, key="form_position")
    destination = st.radio("3. 출고처", options=dest_options, horizontal=True, key="form_destination")
    feet = st.radio("4. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("5. 씰 번호 (선택)", key="form_seal_no")

    button_marker("success")
    submitted = st.button("➕ 등록", use_container_width=True, key="register_btn")
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