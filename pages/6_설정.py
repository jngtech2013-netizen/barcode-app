import streamlit as st

st.set_page_config(page_title="설정", layout="wide", initial_sidebar_state="expanded")

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
            st.session_state["printer_ip"] = printer_ip_input.strip()
            st.success(f"저장됨: {printer_ip_input.strip()}")

    if st.session_state.get("printer_ip"):
        st.caption(f"현재 IP: {st.session_state['printer_ip']}")
