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

def clear_form_inputs():
    dests = get_destinations()
    st.session_state["form_container_no"] = ""
    st.session_state["form_seal_no"] = ""
    st.session_state["form_destination"] = dests[0] if dests else ""
    st.session_state["form_feet"] = "40"

@st.dialog("✏️ 컨테이너 정보 수정")
def edit_container_dialog(container_no):
    """현황 표의 ✏️ 칸을 체크했을 때 뜨는 수정 팝업.
    페이지 이동 없이 출고처/피트수/씰번호/상태를 바로 수정한다."""
    idx = next((i for i, c in enumerate(st.session_state.container_list)
                if c.get('컨테이너 번호') == container_no), None)
    if idx is None:
        st.error("컨테이너를 찾을 수 없습니다. 새로고침 후 다시 시도해주세요.")
        return
    data = st.session_state.container_list[idx]
    st.markdown(f"**{container_no}**")

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

    status_options = ['선적중', '선적완료']
    cur_status = data.get('상태', '선적중')
    new_status = st.radio("상태", options=status_options,
                          index=status_options.index(cur_status) if cur_status in status_options else 0,
                          horizontal=True)

    button_marker("primary")
    if st.button("💾 저장", use_container_width=True):
        updated = data.copy()
        updated.update({'출고처': new_dest, '피트수': new_feet, '씰 번호': str(new_seal), '상태': new_status})
        if new_status == '선적완료':
            if cur_status == '선적중':
                updated['완료일시'] = pd.to_datetime(get_korea_now().replace(tzinfo=None))
        else:
            updated['완료일시'] = None
        with st.spinner('수정사항을 저장하는 중...'):
            ok, msg = update_row_in_gsheet(updated)
        if ok:
            st.session_state.container_list[idx] = updated
            st.session_state["form_success_message"] = f"'{container_no}' 정보가 수정되었습니다."
            st.rerun()
        else:
            st.error(f"수정 실패: {msg}")

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
    completed_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적완료'])
    pending_count = len([item for item in st.session_state.container_list if item.get('상태') == '선적중'])
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

    if not st.session_state.container_list:
        st.info("등록된 컨테이너가 없습니다.")
    else:
        df = pd.DataFrame(st.session_state.container_list)
        df['선적완료'] = df['상태'].apply(lambda x: x == '선적완료')
        df.insert(0, '출력선택', False)

        display_df = df.copy()
        if '등록일시' in display_df.columns:
            display_df['등록일시'] = pd.to_datetime(display_df['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
        if '완료일시' in display_df.columns:
            display_df['완료일시'] = pd.to_datetime(display_df['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
        display_df.fillna('', inplace=True)
        display_df['수정'] = False

        column_order = ['출력선택', '컨테이너 번호', '수정', '출고처', '피트수', '씰 번호', '등록일시', '완료일시', '선적완료']

        # ✏️ 체크 후 팝업을 닫으면 체크가 남아 재오픈되는 것을 막기 위해 키를 바꿔 초기화
        editor_key = f"merged_editor_{st.session_state.get('editor_rev', 0)}"
        edited_df = st.data_editor(
            display_df,
            column_order=column_order,
            use_container_width=True,
            hide_index=True,
            key=editor_key,
            column_config={
                "출력선택": st.column_config.CheckboxColumn("출력선택", default=False, width="small", help="선적완료 항목은 출력 대상에서 제외됩니다."),
                "수정": st.column_config.CheckboxColumn("✏️", width="small", help="체크하면 해당 컨테이너 수정 팝업이 열립니다."),
                "선적완료": st.column_config.CheckboxColumn("선적완료", width="small"),
                "컨테이너 번호": st.column_config.TextColumn(disabled=True),
                "출고처": st.column_config.TextColumn(disabled=True),
                "피트수": st.column_config.TextColumn(disabled=True),
                "씰 번호": st.column_config.TextColumn(disabled=True),
                "등록일시": st.column_config.TextColumn(disabled=True),
                "완료일시": st.column_config.TextColumn(disabled=True),
            }
        )

        # ✏️ 수정 체크 → 해당 컨테이너 수정 팝업 열기 (다음 렌더에서 체크 초기화)
        rows_to_edit = [
            row['컨테이너 번호'] for _, row in edited_df.iterrows()
            if row.get('수정') and row['컨테이너 번호']
        ]
        if rows_to_edit:
            st.session_state['editor_rev'] = st.session_state.get('editor_rev', 0) + 1
            edit_container_dialog(rows_to_edit[0])

        # 선적완료 체크 토글 → 상태/완료일시 갱신 후 저장
        if not df['선적완료'].equals(edited_df['선적완료']):
            for i, (original_bool, edited_bool) in enumerate(zip(df['선적완료'], edited_df['선적완료'])):
                if original_bool != edited_bool:
                    st.session_state.container_list[i]['상태'] = "선적완료" if edited_bool else "선적중"
                    if edited_bool:
                        st.session_state.container_list[i]['완료일시'] = pd.to_datetime(get_korea_now().replace(tzinfo=None))
                    else:
                        st.session_state.container_list[i]['완료일시'] = None
                    ok, msg = update_row_in_gsheet(st.session_state.container_list[i])
                    if not ok:
                        st.session_state["form_error_message"] = f"상태 변경 실패: {msg}"
                    st.rerun()

        # 출력 대상: 선적중이면서 출력선택된 행만 (선적완료 행은 제외)
        selected_cnos = [
            row['컨테이너 번호'] for _, row in edited_df.iterrows()
            if row['출력선택'] and not row['선적완료']
        ]

        # --- 데이터 백업 (미리보기 위) ---
        button_marker("primary")
        if st.button("🚀 데이터 백업", use_container_width=True):
            completed_items_with_indices = [
                (i, item) for i, item in enumerate(st.session_state.container_list) if item.get('상태') == '선적완료'
            ]
            if not completed_items_with_indices:
                st.info("백업할 '선적완료' 상태의 데이터가 없습니다.")
            else:
                completed_data = [item for _, item in completed_items_with_indices]
                with st.spinner('데이터를 백업하는 중...'):
                    success, error_msg = backup_data_to_new_sheet(completed_data)
                if success:
                    st.success(f"'선적완료'된 {len(completed_data)}개 데이터를 일별/월별 백업했습니다!")
                    with st.spinner('메인 시트를 정리하는 중...'):
                        try:
                            container_nos_to_delete = [
                                item.get('컨테이너 번호') for _, item in completed_items_with_indices
                            ]
                            del_success, del_result = delete_rows_by_container_nos(container_nos_to_delete)
                            if not del_success:
                                raise Exception(del_result)
                            for index in sorted([i for i, _ in completed_items_with_indices], reverse=True):
                                st.session_state.container_list.pop(index)
                            log_change(f"데이터 백업: {len(completed_data)}개 백업 완료 후 메인 시트에서 삭제.")
                            st.success("메인 시트 정리가 완료되었습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"메인 시트 정리 중 오류가 발생했습니다: {e}")
                            st.warning("데이터 백업은 완료되었으나, 메인 시트 정리에 실패했습니다. 잠시 후 다시 시도하거나 수동으로 정리해주세요.")
                else:
                    st.error(f"백업 중 오류 발생: {error_msg}")

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
with st.form(key="new_container_form"):
    destinations = get_destinations()
    # 설정에서 삭제되어 세션에 남은 출고처가 현재 목록에 없으면 첫 항목으로 보정
    if destinations and st.session_state.get("form_destination") not in destinations:
        st.session_state["form_destination"] = destinations[0]
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567", key="form_container_no")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True, key="form_destination")
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True, key="form_feet")
    seal_no = st.text_input("4. 씰 번호", key="form_seal_no")

    button_marker("success")
    submitted = st.form_submit_button("➕ 등록", use_container_width=True)
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