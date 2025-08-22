import streamlit as st
from barcode import Code128  # 바코드 종류 (Code128은 일반적으로 많이 사용됩니다)
from barcode.writer import ImageWriter
from io import BytesIO  # 바코드 이미지를 파일로 저장하지 않고 메모리에서 다루기 위함

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 바코드 생성기", layout="centered")

# --- 데이터 관리 ---
# 실제 앱에서는 이 부분을 데이터베이스(DB) 연동으로 대체해야 합니다.
# 여기서는 앱을 재실행해도 데이터가 유지되도록 st.session_state를 사용합니다.
if 'container_data' not in st.session_state:
    st.session_state.container_data = {
        'CNT-001': {'출고처': '부산항', '상태': '선적중'},
        'CNT-002': {'출고처': '인천항', '상태': '선적완료'},
        'CNT-003': {'출고처': '광양항', '상태': '선적중'},
        'CNT-004': {'출고처': '부산항', '상태': '선적완료'},
    }

# --- 화면 UI 구성 ---

st.title("📦 컨테이너 바코드 생성 시스템")

# 1. 컨테이너 선택
container_list = list(st.session_state.container_data.keys())
selected_container = st.selectbox("컨테이너 번호를 선택하세요:", container_list)

# 선택된 컨테이너의 정보 가져오기
if selected_container:
    data = st.session_state.container_data[selected_container]
    destination = data['출고처']
    current_status = data['상태']

    # 2. 출고처 정보 표시 (수정 불가)
    st.text_input("출고처:", value=destination, disabled=True)

    # 3. 상태 정보 표시 및 변경 기능
    st.write(f"**현재 상태: {current_status}**")

    # 상태 변경 UI
    col1, col2 = st.columns([3, 1])
    with col1:
        new_status = st.selectbox(
            "상태 변경:",
            options=['선적중', '선적완료'],
            index=0 if current_status == '선적중' else 1, # 현재 상태를 기본값으로
            label_visibility="collapsed" # 라벨 숨김
        )
    with col2:
        if st.button("상태 저장"):
            st.session_state.container_data[selected_container]['상태'] = new_status
            st.success(f"'{selected_container}'의 상태가 '{new_status}'(으)로 변경되었습니다.")
            # 페이지를 새로고침하여 변경사항 즉시 반영
            st.experimental_rerun()


    st.divider() # 구분선

    # 4. 바코드 생성 버튼 (조건부 활성화)
    # '선적중' 상태가 아닐 경우 버튼을 비활성화(disabled=True) 합니다.
    is_shippable = (current_status == '선적중')
    
    if st.button("바코드 생성", disabled=not is_shippable):
        # 바코드에 포함될 데이터 (출고처-컨테이너번호 형식)
        barcode_data = f"{destination}-{selected_container}"
        
        # 바코드 생성
        # 1. BytesIO 객체를 만들어 이미지를 메모리에 저장
        fp = BytesIO()
        # 2. Code128 바코드를 생성하고, ImageWriter를 통해 BytesIO 객체에 PNG 형식으로 씀
        Code128(barcode_data, writer=ImageWriter()).write(fp)
        
        # 3. 화면에 바코드 이미지 표시
        st.image(fp, caption=f"생성된 바코드: {barcode_data}")
        st.success("바코드가 성공적으로 생성되었습니다!")

    # '선적완료' 상태일 때 사용자에게 안내 메시지 표시
    if not is_shippable:
        st.warning("'선적완료' 상태의 컨테이너는 바코드를 생성할 수 없습니다. 상태를 '선적중'으로 변경해주세요.")