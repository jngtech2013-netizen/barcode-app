import streamlit as st
import json
from pathlib import Path
from utils import apply_sidebar_style, render_app_title, DEFAULT_PRINTER_IP

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

def save_config(data: dict):
    cfg = load_config()
    cfg.update(data)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

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
