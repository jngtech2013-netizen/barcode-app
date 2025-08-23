import streamlit as st
import pandas as pd
from barcode import Code128
from barcode.writer import ImageWriter
from io import BytesIO
from datetime import date, datetime, timezone, timedelta
import re
import gspread
from google.oauth2.service_account import Credentials

# --- 앱 초기 설정 ---
st.set_page_config(page_title="컨테이너 관리 시스템", layout="wide")

# --- 상수 정의 ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '작업일자']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))

# --- Google Sheets 연동 ---
@st.cache_resource
def connect_to_gsheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open("Container_Data_DB")
        return spreadsheet
    except Exception as e:
        st.error(f"Google Sheets 연결에 실패했습니다: {e}")
        return None

spreadsheet = connect_to_gsheet()

# --- 로그 기록 함수 ---
def log_change(action):
    if spreadsheet is None: 
        return
    try:
        log_sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")

# --- 데이터 관리 함수들 ---
def load_data_from_gsheet():
    if spreadsheet is None: 
        return []
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        all_values = worksheet.get_all_values()
        if len(all_values) < 2: 
            return []
        data = all_values[1:]  # 헤더 제외
        df = pd.DataFrame(data, columns=SHEET_HEADERS)
        
        # 빈 값을 빈 문자열로 처리
        df = df.fillna('')
        
        # 작업일자 처리 개선
        if '작업일자' in df.columns:
            def parse_date(date_str):
                if not date_str or date_str == '':
                    return None
                try:
                    return pd.to_datetime(date_str, errors='coerce').date()
                except:
                    return None
            df['작업일자'] = df['작업일자'].apply(parse_date)
        
        return df.to_dict('records')
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"'{MAIN_SHEET_NAME}' 시트를 찾을 수 없습니다.")
        try:
            worksheet = spreadsheet.add_worksheet(title=MAIN_SHEET_NAME, rows=100, cols=20)
            worksheet.update('A1', [SHEET_HEADERS])
            return []
        except: 
            return []
    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
        return []

def add_row_to_gsheet(data):
    if spreadsheet is None: 
        return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        if isinstance(data.get('작업일자'), date): 
            data['작업일자'] = data['작업일자'].isoformat()
        row_to_insert = [str(data.get(header, "")) for header in SHEET_HEADERS]
        worksheet.append_row(row_to_insert)
        log_change(f"신규 등록: {data.get('컨테이너 번호')}")
    except Exception as e:
        st.error(f"데이터 추가 중 오류 발생: {e}")

def update_row_in_gsheet(index, data):
    if spreadsheet is None: 
        return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        if isinstance(data.get('작업일자'), date): 
            data['작업일자'] = data['작업일자'].isoformat()
        row_to_update = [str(data.get(header, "")) for header in SHEET_HEADERS]
        worksheet.update(f'A{index+2}:F{index+2}', [row_to_update])
        log_change(f"데이터 수정: {data.get('컨테이너 번호')}")
    except Exception as e:
        st.error(f"데이터 수정 중 오류 발생: {e}")

def delete_row_from_gsheet(index, container_no):
    if spreadsheet is None: 
        return
    try:
        worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        worksheet.delete_rows(index + 2)
        log_change(f"데이터 삭제: {container_no}")
    except Exception as e:
        st.error(f"데이터 삭제 중 오류 발생: {e}")

def backup_data_to_new_sheet(container_data):
    try:
        if spreadsheet is None: 
            raise Exception("스프레드시트 연결 안됨")
        
        today_str = date.today().isoformat()
        backup_sheet_name = f"백업_{today_str}"
        
        df_to_save = pd.DataFrame(container_data)
        
        # 날짜 형식 처리 개선
        if '작업일자' in df_to_save.columns:
            def format_date(date_val):
                if date_val is None or date_val == '':
                    return ''
                if isinstance(date_val, date):
                    return date_val.strftime('%Y-%m-%d')
                try:
                    return pd.to_datetime(date_val).strftime('%Y-%m-%d')
                except:
                    return str(date_val)
            
            df_to_save['작업일자'] = df_to_save['작업일자'].apply(format_date)
        
        try:
            backup_sheet = spreadsheet.worksheet(backup_sheet_name)
            backup_sheet.append_rows(df_to_save.values.tolist())
            log_change(f"데이터 추가 백업: '{backup_sheet_name}' 시트에 {len(df_to_save)}개 행 추가")
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=backup_sheet_name, rows=100, cols=20)
            new_sheet.update('A1', [SHEET_HEADERS])
            new_sheet.update('A2', df_to_save.values.tolist())
            log_change(f"데이터 신규 백업: '{backup_sheet_name}' 시트 생성")
        
        return True, None
    except Exception as e:
        return False, str(e)

# --- 데이터 초기화 ---
if 'container_list' not in st.session_state:
    st.session_state.container_list = load_data_from_gsheet()

# --- 화면 UI 구성 ---
st.subheader("🚢 컨테이너 관리 시스템")

with st.expander("🔳 바코드 생성", expanded=True):
    shippable_containers = [c['컨테이너 번호'] for c in st.session_state.container_list 
                           if c.get('상태') == '선적중' and c.get('컨테이너 번호')]
    
    if not shippable_containers: 
        st.info("바코드를 생성할 수 있는 '선적중' 상태의 컨테이너가 없습니다.")
    else:
        selected_for_barcode = st.selectbox("컨테이너를 선택하면 바코드가 자동 생성됩니다:", shippable_containers)
        container_info = next((c for c in st.session_state.container_list 
                             if c.get('컨테이너 번호') == selected_for_barcode), None)
        
        if container_info: 
            st.info(f"**출고처:** {container_info.get('출고처', 'N/A')} / **피트수:** {container_info.get('피트수', 'N/A')}")
        
        if selected_for_barcode:
            try:
                barcode_data = selected_for_barcode
                fp = BytesIO()
                Code128(barcode_data, writer=ImageWriter()).write(fp)
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2: 
                    st.image(fp)
            except Exception as e:
                st.error(f"바코드 생성 중 오류 발생: {e}")

st.divider()

st.markdown("#### 📋 컨테이너 목록")
if not st.session_state.container_list:
    st.info("등록된 컨테이너가 없습니다.")
else:
    # DataFrame을 사용하되 스타일링 적용
    df_display = pd.DataFrame(st.session_state.container_list)
    
    # 빈 값 처리
    df_display = df_display.fillna('')
    
    # 작업일자 형식 처리
    if '작업일자' in df_display.columns:
        def format_display_date(date_val):
            if date_val is None or date_val == '':
                return ''
            if isinstance(date_val, date):
                return date_val.strftime('%Y-%m-%d')
            try:
                return pd.to_datetime(date_val).strftime('%Y-%m-%d')
            except:
                return str(date_val)
        
        df_display['작업일자'] = df_display['작업일자'].apply(format_display_date)
    
    # 컬럼 순서 정렬
    column_order = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '작업일자']
    df_display = df_display.reindex(columns=column_order)
    
    # HTML 테이블로 변환하여 정렬 적용
    def make_clickable(val):
        return f'<div style="text-align: center;">{val}</div>'
    
    # 스타일 적용
    df_styled = df_display.copy()
    
    # HTML 테이블 직접 생성
    html = '<div style="overflow-x: auto;">'
    html += '<table style="width: 100%; border-collapse: collapse; font-size: 14px;">'
    
    # 헤더
    html += '<thead><tr style="background-color: #f0f2f6;">'
    html += '<th style="border: 1px solid #ddd; padding: 10px; text-align: center; font-weight: bold;">번호</th>'
    for col in df_display.columns:
        html += f'<th style="border: 1px solid #ddd; padding: 10px; text-align: center; font-weight: bold;">{col}</th>'
    html += '</tr></thead>'
    
    # 데이터
    html += '<tbody>'
    for i, (idx, row) in enumerate(df_display.iterrows()):
        bg_color = '#fafafa' if i % 2 == 0 else '#ffffff'
        html += f'<tr style="background-color: {bg_color};">'
        
        # 번호 (가운데 정렬)
        html += f'<td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{i+1}</td>'
        
        for j, (col, value) in enumerate(row.items()):
            # 모든 컬럼 가운데 정렬
            html += f'<td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{value}</td>'
        
        html += '</tr>'
    
    html += '</tbody></table></div>'
    
    st.markdown(html, unsafe_allow_html=True)

st.divider()

st.markdown("#### 📝 신규 컨테이너 등록하기")
with st.form(key="new_container_form"):
    destinations = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
    
    container_no = st.text_input("1. 컨테이너 번호", placeholder="예: ABCD1234567")
    destination = st.radio("2. 출고처", options=destinations, horizontal=True)
    feet = st.radio("3. 피트수", options=['40', '20'], horizontal=True)
    seal_no = st.text_input("4. 씰 번호")
    work_date = st.date_input("5. 작업일자", value=date.today())
    
    submitted = st.form_submit_button("➕ 등록하기", use_container_width=True)
    
    if submitted:
        # 입력 검증
        pattern = re.compile(r'^[A-Z]{4}\d{7}$')
        
        if not container_no or not seal_no: 
            st.error("컨테이너 번호와 씰 번호를 모두 입력해주세요.")
        elif not pattern.match(container_no): 
            st.error("컨테이너 번호 형식이 올바르지 않습니다. (예: ABCD1234567)")
        elif any(c.get('컨테이너 번호') == container_no for c in st.session_state.container_list): 
            st.warning(f"이미 등록된 컨테이너 번호입니다: {container_no}")
        else:
            new_container = {
                '컨테이너 번호': container_no, 
                '출고처': destination, 
                '피트수': feet, 
                '씰 번호': seal_no, 
                '작업일자': work_date, 
                '상태': '선적중'
            }
            st.session_state.container_list.append(new_container)
            add_row_to_gsheet(new_container)
            st.success(f"컨테이너 '{container_no}'가 성공적으로 등록되었습니다.")
            st.rerun()

st.divider()

st.markdown("#### ✏️ 개별 데이터 수정 및 삭제")
if not st.session_state.container_list: 
    st.warning("수정할 데이터가 없습니다.")
else:
    container_numbers_for_edit = [c.get('컨테이너 번호', '') for c in st.session_state.container_list 
                                 if c.get('컨테이너 번호')]
    
    if not container_numbers_for_edit:
        st.warning("수정할 수 있는 컨테이너가 없습니다.")
    else:
        selected_for_edit = st.selectbox("수정 또는 삭제할 컨테이너를 선택하세요:", 
                                       container_numbers_for_edit, key="edit_selector")
        
        selected_data = next((c for c in st.session_state.container_list 
                            if c.get('컨테이너 번호') == selected_for_edit), None)
        selected_idx = next((i for i, c in enumerate(st.session_state.container_list) 
                           if c.get('컨테이너 번호') == selected_for_edit), -1)
        
        if selected_data and selected_idx >= 0:
            with st.form(key=f"edit_form_{selected_for_edit}"):
                st.write(f"**'{selected_for_edit}' 정보 수정**")
                
                dest_options = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '기타']
                current_dest = selected_data.get('출고처', dest_options[0])
                current_dest_idx = dest_options.index(current_dest) if current_dest in dest_options else 0
                new_dest = st.radio("출고처 수정", options=dest_options, index=current_dest_idx, horizontal=True)
                
                feet_options = ['40', '20']
                current_feet = str(selected_data.get('피트수', '40'))
                current_feet_idx = feet_options.index(current_feet) if current_feet in feet_options else 0
                new_feet = st.radio("피트수 수정", options=feet_options, index=current_feet_idx, horizontal=True)
                
                new_seal = st.text_input("씰 번호 수정", value=selected_data.get('씰 번호', ''))
                
                status_options = ['선적중', '선적완료']
                current_status = selected_data.get('상태', status_options[0])
                current_status_idx = status_options.index(current_status) if current_status in status_options else 0
                new_status = st.radio("상태 변경", options=status_options, index=current_status_idx, horizontal=True)
                
                # 작업일자 처리 개선
                work_date_value = selected_data.get('작업일자', date.today())
                if work_date_value is None or work_date_value == '':
                    work_date_value = date.today()
                elif not isinstance(work_date_value, date):
                    try: 
                        work_date_value = datetime.strptime(str(work_date_value), '%Y-%m-%d').date()
                    except (ValueError, TypeError): 
                        work_date_value = date.today()
                
                new_work_date = st.date_input("작업일자 수정", value=work_date_value)
                
                if st.form_submit_button("💾 수정사항 저장", use_container_width=True):
                    if not new_seal:
                        st.error("씰 번호를 입력해주세요.")
                    else:
                        updated_data = {
                            '컨테이너 번호': selected_for_edit, 
                            '출고처': new_dest, 
                            '피트수': new_feet, 
                            '씰 번호': new_seal, 
                            '상태': new_status, 
                            '작업일자': new_work_date
                        }
                        st.session_state.container_list[selected_idx] = updated_data
                        update_row_in_gsheet(selected_idx, updated_data)
                        st.success(f"'{selected_for_edit}'의 정보가 성공적으로 수정되었습니다.")
                        st.rerun()
            
            st.error("⚠️ 주의: 아래 버튼은 데이터를 영구적으로 삭제합니다.")
            if st.button("🗑️ 이 컨테이너 삭제", use_container_width=True):
                delete_row_from_gsheet(selected_idx, selected_for_edit)
                st.session_state.container_list.pop(selected_idx)
                st.success(f"'{selected_for_edit}' 컨테이너 정보가 삭제되었습니다.")
                st.rerun()

st.divider()

st.markdown("#### 📁 하루 마감 및 데이터 관리")
st.info("데이터는 모든 사용자가 공유하는 중앙 데이터베이스에 실시간으로 저장됩니다.")

if st.button("🚀 오늘 데이터 백업 및 새로 시작 (하루 마감)", use_container_width=True, type="primary"):
    if not st.session_state.container_list:
        st.warning("마감할 데이터가 없습니다.")
    else:
        success, error_msg = backup_data_to_new_sheet(st.session_state.container_list)
        if success:
            st.success("현재 데이터를 백업 시트에 성공적으로 저장(또는 추가)했습니다!")
            
            # 메인 시트 초기화
            if spreadsheet:
                try:
                    worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
                    worksheet.clear() 
                    worksheet.update('A1', [SHEET_HEADERS])
                except Exception as e:
                    st.error(f"메인 시트 초기화 중 오류: {e}")
            
            st.session_state.container_list = []
            log_change("하루 마감 (데이터 초기화)")
            st.success("중앙 데이터베이스를 초기화했습니다. 새로운 하루를 시작하세요!")
            st.rerun()
        else:
            st.error(f"최종 백업 중 오류가 발생했습니다: {error_msg}")
            st.warning("백업에 실패하여 데이터를 초기화하지 않았습니다.")

st.write("---")
with st.expander("⬆️ (필요시 사용) 백업 시트에서 데이터 복구"):
    st.info("실수로 데이터를 초기화했을 경우, 이전 백업 시트를 선택하여 현재 데이터로 덮어쓸 수 있습니다.")
    
    if spreadsheet:
        try:
            all_sheets = [s.title for s in spreadsheet.worksheets()]
            backup_sheets = sorted([s for s in all_sheets if s.startswith("백업_")], reverse=True)
            
            if not backup_sheets:
                st.warning("복구할 백업 시트가 없습니다.")
            else:
                selected_backup_sheet = st.selectbox("복구할 백업 시트를 선택하세요:", backup_sheets)
                
                st.error("⚠️ 주의: 이 작업은 현재 데이터를 **완전히 덮어씁니다.**")
                if st.button(f"'{selected_backup_sheet}' 시트로 복구하기", use_container_width=True):
                    try:
                        backup_worksheet = spreadsheet.worksheet(selected_backup_sheet)
                        backup_values = backup_worksheet.get_all_values()
                        
                        main_worksheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
                        main_worksheet.clear()
                        main_worksheet.update('A1', backup_values)
                        
                        # 세션 상태도 업데이트
                        st.session_state.container_list = load_data_from_gsheet()
                        
                        log_change(f"데이터 복구: '{selected_backup_sheet}' 시트의 내용으로 덮어씀")
                        st.success(f"'{selected_backup_sheet}' 시트의 데이터로 성공적으로 복구했습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"복구 중 오류가 발생했습니다: {e}")
        except Exception as e:
            st.error(f"시트 목록 조회 중 오류가 발생했습니다: {e}")
    else:
        st.error("Google Sheets 연결이 필요합니다.")