import streamlit as st
from utils import (
    apply_sidebar_style,
    render_app_title,
    DEFAULT_PRINTER_IP,
    load_config,
    save_config,
    get_destinations,
    save_destinations,
)

st.set_page_config(page_title="설정", layout="wide", initial_sidebar_state="expanded")

apply_sidebar_style()

render_app_title()


@st.dialog("출고처 삭제 확인")
def confirm_delete_destination(name, current_list):
    st.warning(f"'{name}' 출고처를 삭제하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ 삭제", use_container_width=True, type="primary"):
        save_destinations([d for d in current_list if d != name])
        st.session_state["dest_delete_msg"] = f"'{name}' 출고처를 삭제했습니다."
        st.rerun()
    if c2.button("취소", use_container_width=True):
        st.rerun()


def add_destination_cb():
    # 콜백 안에서는 위젯 키(new_dest_input)를 비울 수 있어, 추가 후 입력창이 초기화된다.
    name = st.session_state.get("new_dest_input", "").strip()
    current = get_destinations()
    if not name:
        st.session_state["dest_add_msg"] = ("warning", "출고처명을 입력하세요.")
    elif name in current:
        st.session_state["dest_add_msg"] = ("warning", f"이미 존재하는 출고처입니다: {name}")
    else:
        save_destinations(current + [name])
        st.session_state["new_dest_input"] = ""
        st.session_state["dest_add_msg"] = ("success", f"'{name}' 출고처를 추가했습니다.")


if "printer_ip" not in st.session_state:
    st.session_state["printer_ip"] = load_config().get("printer_ip", DEFAULT_PRINTER_IP)

st.markdown("#### ⚙️ 설정")

# --- 버튼 색상 (마커-CSS): 저장=파랑, 추가=녹색, 삭제=빨강 ---
st.markdown("""
<style>
.element-container:has(#save-ip-marker) + .element-container button {
    background-color:#0068C9 !important; border-color:#0068C9 !important; color:white !important;
}
.element-container:has(#add-dest-marker) + .element-container button {
    background-color:#28A745 !important; border-color:#28A745 !important; color:white !important;
}
.element-container:has(#del-dest-marker) + .element-container button {
    background-color:#FF4B4B !important; border-color:#FF4B4B !important; color:white !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("##### 🖨️ 프린터 IP")
with st.container(border=True):
    col_ip, col_save = st.columns([4, 1], vertical_alignment="bottom")
    with col_ip:
        printer_ip_input = st.text_input(
            "ip",
            value=st.session_state.get("printer_ip", ""),
            placeholder="예: 192.168.0.50",
            label_visibility="collapsed",
        )
    with col_save:
        st.markdown('<div id="save-ip-marker" style="display:none"></div>', unsafe_allow_html=True)
        if st.button("저장", use_container_width=True):
            ip = printer_ip_input.strip()
            st.session_state["printer_ip"] = ip
            save_config({"printer_ip": ip})
            st.success(f"저장됨: {ip}")

    if st.session_state.get("printer_ip"):
        st.caption(f"현재 IP: {st.session_state['printer_ip']}")

st.markdown("##### 📍 출고처 관리")

_dest_msg = st.session_state.pop("dest_delete_msg", None)
if _dest_msg:
    st.success(_dest_msg)
_add_msg = st.session_state.pop("dest_add_msg", None)
if _add_msg:
    getattr(st, _add_msg[0])(_add_msg[1])

with st.container(border=True):
    destinations = get_destinations()
    st.caption("현재 출고처: " + ", ".join(destinations))

    # --- 추가 ---
    col_add, col_add_btn = st.columns([4, 1], vertical_alignment="bottom")
    with col_add:
        st.text_input(
            "출고처 추가",
            key="new_dest_input",
            placeholder="추가할 출고처명 입력",
            label_visibility="collapsed",
        )
    with col_add_btn:
        st.markdown('<div id="add-dest-marker" style="display:none"></div>', unsafe_allow_html=True)
        st.button("➕ 추가", use_container_width=True, on_click=add_destination_cb)

    # --- 삭제 ---
    # 직전에 선택돼 있던 출고처가 삭제되어 목록에 없으면 selectbox 오류가 나므로 보정
    if st.session_state.get("del_dest_select") not in destinations:
        st.session_state["del_dest_select"] = destinations[0]
    col_del, col_del_btn = st.columns([4, 1], vertical_alignment="bottom")
    with col_del:
        dest_to_delete = st.selectbox(
            "삭제할 출고처",
            destinations,
            key="del_dest_select",
            label_visibility="collapsed",
        )
    with col_del_btn:
        st.markdown('<div id="del-dest-marker" style="display:none"></div>', unsafe_allow_html=True)
        if st.button("🗑️ 삭제", use_container_width=True):
            if len(destinations) <= 1:
                st.warning("최소 1개의 출고처는 남아 있어야 합니다.")
            else:
                confirm_delete_destination(dest_to_delete, destinations)
