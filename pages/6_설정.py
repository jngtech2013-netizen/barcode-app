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

if "printer_ip" not in st.session_state:
    st.session_state["printer_ip"] = load_config().get("printer_ip", DEFAULT_PRINTER_IP)

st.markdown("#### ⚙️ 설정")

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
        if st.button("저장", use_container_width=True):
            ip = printer_ip_input.strip()
            st.session_state["printer_ip"] = ip
            save_config({"printer_ip": ip})
            st.success(f"저장됨: {ip}")

    if st.session_state.get("printer_ip"):
        st.caption(f"현재 IP: {st.session_state['printer_ip']}")

st.markdown("##### 📍 출고처 관리")
with st.container(border=True):
    destinations = get_destinations()
    st.caption("현재 출고처: " + ", ".join(destinations))

    # --- 추가 ---
    col_add, col_add_btn = st.columns([4, 1], vertical_alignment="bottom")
    with col_add:
        new_dest_input = st.text_input(
            "출고처 추가",
            key="new_dest_input",
            placeholder="추가할 출고처명 입력",
            label_visibility="collapsed",
        )
    with col_add_btn:
        if st.button("➕ 추가", use_container_width=True):
            name = new_dest_input.strip()
            if not name:
                st.warning("출고처명을 입력하세요.")
            elif name in destinations:
                st.warning(f"이미 존재하는 출고처입니다: {name}")
            else:
                save_destinations(destinations + [name])
                st.success(f"'{name}' 출고처를 추가했습니다.")
                st.rerun()

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
        if st.button("🗑️ 삭제", use_container_width=True):
            if len(destinations) <= 1:
                st.warning("최소 1개의 출고처는 남아 있어야 합니다.")
            else:
                save_destinations([d for d in destinations if d != dest_to_delete])
                st.success(f"'{dest_to_delete}' 출고처를 삭제했습니다.")
                st.rerun()
