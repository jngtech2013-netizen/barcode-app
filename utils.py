import streamlit as st
from datetime import datetime, timezone, timedelta
import re
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 상수 정의 (공용) ---
MAIN_SHEET_NAME = "현재 데이터"
SHEET_HEADERS = ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시', '위치']
LOG_SHEET_NAME = "업데이트 로그"
KST = timezone(timedelta(hours=9))
BACKUP_PREFIX = "백업_"
RESTORE_SLOT = "복원"  # 관리 페이지에서 개별 복원한 컨테이너가 들어가는 등록 페이지 전용 슬롯 위치값
DEFAULT_DESTINATIONS = ['베트남', '박닌', '하택', '위해', '중원', '영성', '베트남전장', '흥옌', '북경', '락릉', '타이닌', '기타']
DEFAULT_PRINTER_IP = "192.168.0.99"

# --- 설정 입출력 (공용) ---
# Streamlit Cloud는 재부팅 시 컨테이너를 새로 만들어 로컬 파일(config.json)이 사라진다.
# 따라서 출고처/프린터IP 등 설정은 Google Sheets의 '설정' 시트에 영구 저장한다.
CONFIG_SHEET_NAME = "설정"
_CONFIG_CACHE_KEY = "_app_config_cache"

def _read_config_from_sheet():
    """'설정' 시트를 읽어 dict로 반환. 시트/연결이 없으면 빈 dict."""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return {}
    try:
        ws = spreadsheet.worksheet(CONFIG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return {}
    except Exception:
        return {}
    try:
        values = ws.get_all_values()
        cfg = {}
        for row in values[1:]:  # 1행은 헤더(키, 값)
            if not row or not row[0].strip():
                continue
            key = row[0].strip()
            raw = row[1] if len(row) > 1 else ""
            try:
                cfg[key] = json.loads(raw)  # 값은 JSON 문자열로 저장됨(리스트/문자열 공통 처리)
            except (json.JSONDecodeError, TypeError):
                cfg[key] = raw
        return cfg
    except Exception:
        return {}

def load_config():
    """앱 설정을 '설정' 시트에서 읽는다. 매 rerun마다 시트를 읽지 않도록 세션 단위로 캐시한다."""
    cached = st.session_state.get(_CONFIG_CACHE_KEY)
    if cached is not None:
        return dict(cached)
    cfg = _read_config_from_sheet()
    st.session_state[_CONFIG_CACHE_KEY] = dict(cfg)
    return dict(cfg)

def save_config(data: dict):
    """설정을 시트의 기존 값과 병합해 '설정' 시트에 저장한다. 시트가 없으면 생성."""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        st.error("Google Sheets에 연결되지 않아 설정을 저장하지 못했습니다.")
        return
    cfg = _read_config_from_sheet()
    cfg.update(data)
    try:
        try:
            ws = spreadsheet.worksheet(CONFIG_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=CONFIG_SHEET_NAME, rows=50, cols=2)
        rows = [["키", "값"]] + [[k, json.dumps(v, ensure_ascii=False)] for k, v in cfg.items()]
        ws.clear()
        # JSON 문자열을 시트가 재해석하지 않도록 RAW로 기록
        ws.update('A1', rows, value_input_option='RAW')
        st.session_state[_CONFIG_CACHE_KEY] = dict(cfg)  # 캐시 즉시 갱신
    except Exception as e:
        st.error(f"설정 저장 실패: {e}")

def get_destinations():
    """출고처 목록을 '설정' 시트에서 읽는다. 미설정 시 기본값 사본을 반환(원본 상수 보호)."""
    dests = load_config().get("destinations")
    if isinstance(dests, list) and dests:
        return list(dests)
    return list(DEFAULT_DESTINATIONS)

def save_destinations(destinations):
    save_config({"destinations": list(destinations)})

# --- 공용 UI 헬퍼 ---
def apply_sidebar_style(extra_css: str = ""):
    """모든 페이지 공통 사이드바 스타일을 적용한다. (페이지별 추가 CSS는 extra_css로 전달)"""
    st.markdown(
        f"""
        <style>
        [data-testid="stSidebar"] {{ width: 150px !important; }}
        [data-testid="stSidebar"] * {{ font-size: 22px !important; font-weight: bold !important; }}
        [data-testid="stSidebar"] a {{ font-size: 22px !important; font-weight: bold !important; }}
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] div,
        [data-testid="stSidebar"] span, [data-testid="stSidebar"] button {{ font-size: 22px !important; font-weight: bold !important; }}
        @media (max-width: 768px) {{
            [data-testid="stSidebar"] * {{ font-size: 22px !important; font-weight: bold !important; }}
            [data-testid="stSidebar"] a {{ font-size: 22px !important; font-weight: bold !important; }}
        }}
        {extra_css}
        </style>
        """,
        unsafe_allow_html=True,
    )
    apply_button_styles()

def apply_button_styles():
    """모던·세만틱 버튼 색상(호버 포함)을 정의한다.
    버튼 바로 앞에 button_marker(kind)로 마커를 두면 해당 색이 적용된다.
    kind: 'primary'(블루) | 'success'(에메랄드) | 'danger'(레드) | 'neutral'(아웃라인)
    """
    st.markdown("""
    <style>
    .element-container:has(.btn-primary-mk) + .element-container button {
        background-color:#2563EB !important; border-color:#2563EB !important; color:#fff !important;
    }
    .element-container:has(.btn-primary-mk) + .element-container button:hover {
        background-color:#1D4ED8 !important; border-color:#1D4ED8 !important;
    }
    .element-container:has(.btn-success-mk) + .element-container button {
        background-color:#059669 !important; border-color:#059669 !important; color:#fff !important;
    }
    .element-container:has(.btn-success-mk) + .element-container button:hover {
        background-color:#047857 !important; border-color:#047857 !important;
    }
    .element-container:has(.btn-danger-mk) + .element-container button {
        background-color:#DC2626 !important; border-color:#DC2626 !important; color:#fff !important;
    }
    .element-container:has(.btn-danger-mk) + .element-container button:hover {
        background-color:#B91C1C !important; border-color:#B91C1C !important;
    }
    .element-container:has(.btn-neutral-mk) + .element-container button {
        background-color:#fff !important; border-color:#CBD5E1 !important; color:#475569 !important;
    }
    .element-container:has(.btn-neutral-mk) + .element-container button:hover {
        border-color:#94A3B8 !important; color:#1E293B !important;
    }
    </style>
    """, unsafe_allow_html=True)

def button_marker(kind: str):
    """바로 다음에 오는 버튼에 색상을 입히는 마커. kind: primary|success|danger|neutral."""
    st.markdown(f'<div class="btn-{kind}-mk" style="display:none"></div>', unsafe_allow_html=True)

def render_app_title():
    """모든 페이지 공통 상단 타이틀."""
    st.markdown("""
        <div style="margin-top: -3rem;">
            <h3 style='text-align: center; margin-bottom: 25px;'>🚢 컨테이너 관리 시스템</h3>
        </div>
    """, unsafe_allow_html=True)

# --- 공용 순수 헬퍼 (UI/네트워크 비종속, 단위 테스트 대상) ---
CONTAINER_NO_PATTERN = re.compile(r'^[A-Z]{4}\d{7}$')

def is_valid_container_no(container_no) -> bool:
    """컨테이너 번호 형식 검증: 영문 대문자 4자리 + 숫자 7자리 (예: ABCD1234567)."""
    return bool(container_no) and CONTAINER_NO_PATTERN.match(container_no) is not None

def filter_backup_sheets(sheet_titles, kind="daily"):
    """시트 제목 목록에서 일별/월별 백업 시트만 골라 최신순으로 반환한다.

    kind="daily"   → 백업_YYYY-MM-DD (접두사 뒤 10자)
    kind="monthly" → 백업_YYYY-MM    (접두사 뒤 7자)
    """
    suffix_len = 10 if kind == "daily" else 7
    return sorted(
        [s for s in sheet_titles
         if s.startswith(BACKUP_PREFIX) and len(s) == len(BACKUP_PREFIX) + suffix_len],
        reverse=True,
    )

def make_zpl(container_no, copies=2, dpi=203):
    """QR코드 + 컨테이너 번호 텍스트 ZPL (90mm × 60mm 기준)

    ZPL 표준 좌표: x = 가로(PW, 좌→우), y = 세로(LL, 위→아래)
    레이아웃: QR(상단) + 텍스트(하단), 두 요소 모두 가로 중앙 정렬,
    QR+텍스트 블록을 세로 중앙 정렬
    """
    pw = 720 if dpi == 203 else 1080   # 라벨 가로 (90mm)
    ll = 480 if dpi == 203 else 720    # 라벨 세로 (60mm)
    font_h = 50 if dpi == 203 else 75
    font_w = 35 if dpi == 203 else 52
    # 컨테이너 번호는 11자(영문4+숫자7) → QR version1(21모듈), 배율 8 → 168 dots
    qr_mag = 8
    qr_size = 21 * qr_mag
    gap = 40   # QR ↔ 텍스트 세로 여백
    # 프린터 인쇄 원점이 라벨 좌측 끝과 어긋난 경우 보정값(+면 오른쪽으로 이동)
    x_off = 20 if dpi == 203 else 30
    # QR(상단) + gap + 텍스트(하단) 블록을 세로 중앙 정렬
    block = qr_size + gap + font_h
    block_top_y = (ll - block) // 2
    qr_y = block_top_y
    text_y = block_top_y + qr_size + gap
    # QR은 가로 중앙 정렬, 텍스트는 ^FB로 라벨 전체폭 기준 자동 중앙 정렬
    qr_x = (pw - qr_size) // 2 + x_off
    return (
        "^XA"
        f"^PW{pw}"
        f"^LL{ll}"
        f"^FO{qr_x},{qr_y}"
        f"^BQN,2,{qr_mag}"
        f"^FDQA,{container_no}^FS"
        f"^FO{x_off},{text_y}"
        f"^A0N,{font_h},{font_w}"
        f"^FB{pw},1,0,C"
        f"^FD{container_no}^FS"
        f"^PQ{copies}"
        "^XZ"
    )

# --- Google Sheets 연동 (공용) ---
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

@st.cache_resource
def get_stable_worksheet(title):
    """삭제·이름변경되지 않는 고정 시트(현재 데이터/업데이트 로그)의 워크시트 객체를 캐시한다.
    spreadsheet.worksheet(title)은 호출마다 시트 목록을 다시 읽어 Sheets 읽기 요청을
    유발하므로, 자주 쓰는 고정 시트는 캐시해 반복 조회를 없앤다.
    연결/조회 실패 시 예외를 던져 캐시되지 않게 한다(다음 호출에서 재시도)."""
    return connect_to_gsheet().worksheet(title)

# --- 시트 읽기 세션 캐시 (읽기 쿼터 절약) ---
# Streamlit은 위젯을 건드릴 때마다 페이지 전체를 재실행하므로, 재실행마다
# spreadsheet.worksheets()나 get_all_values()를 다시 부르면 Sheets 읽기 쿼터
# (분당 60회)를 금방 초과한다(예: 관리 페이지에서 씰 번호 연속 수정 시 429).
# 데이터를 바꾸지 않는 재실행에서는 세션에 캐시한 값을 재사용하고, 실제 쓰기가
# 일어나면 invalidate_sheet_caches()로 캐시를 비워 다음 읽기에서 최신값을 다시
# 가져온다. → "내가 방금 한 수정"은 항상 즉시 반영된다.
_WS_MAP_CACHE_KEY = "_ws_map_cache"
_SHEET_VALUES_CACHE_KEY = "_sheet_values_cache"

def get_worksheets_map(spreadsheet=None):
    """{시트명: Worksheet} 맵을 세션에 캐시해 반환한다.
    worksheets()는 호출당 읽기 1회이므로 재실행마다 다시 부르지 않도록 캐시한다."""
    cache = st.session_state.get(_WS_MAP_CACHE_KEY)
    if cache is None:
        if spreadsheet is None:
            spreadsheet = connect_to_gsheet()
        if spreadsheet is None:
            return {}
        cache = {w.title: w for w in spreadsheet.worksheets()}
        st.session_state[_WS_MAP_CACHE_KEY] = cache
    return cache

def get_worksheet_titles(spreadsheet=None):
    """캐시된 워크시트 목록(제목 리스트)을 반환한다."""
    return list(get_worksheets_map(spreadsheet).keys())

def get_sheet_values_cached(title, spreadsheet=None):
    """시트의 get_all_values() 결과를 세션에 캐시해 반환한다. 시트가 없으면 None."""
    cache = st.session_state.setdefault(_SHEET_VALUES_CACHE_KEY, {})
    if title not in cache:
        ws = get_worksheets_map(spreadsheet).get(title)
        if ws is None:
            return None
        cache[title] = ws.get_all_values()
    return cache[title]

def invalidate_sheet_caches():
    """시트를 변경하는 쓰기 작업 후 호출해 세션 읽기 캐시를 무효화한다."""
    st.session_state.pop(_WS_MAP_CACHE_KEY, None)
    st.session_state.pop(_SHEET_VALUES_CACHE_KEY, None)

# --- 서식 강제 함수 ---
def ensure_text_format(worksheet, column_name):
    # TEXT 서식은 시트에 영구 적용되므로, 매 load/add/update마다 다시 적용할 필요가 없다.
    # 세션 단위로 한 번만 호출하여 불필요한 읽기·쓰기 API 호출(작업당 2회)을 제거한다.
    cache_key = f"_text_format_done::{worksheet.title}::{column_name}"
    if st.session_state.get(cache_key):
        return
    try:
        headers = worksheet.row_values(1)
        if column_name in headers:
            col_index = headers.index(column_name) + 1
            col_letter = gspread.utils.rowcol_to_a1(1, col_index)[0]
            worksheet.format(f"{col_letter}:{col_letter}", {"numberFormat": {"type": "TEXT"}})
        st.session_state[cache_key] = True
    except Exception as e:
        st.warning(f"'{worksheet.title}' 시트의 '{column_name}' 열 서식을 강제하는 중 오류 발생: {e}")

def _last_col_letter():
    """SHEET_HEADERS 길이에 맞는 마지막 열 문자(예: 8개 → 'H')."""
    return chr(ord('A') + len(SHEET_HEADERS) - 1)

def ensure_sheet_headers(worksheet):
    """시트 1행 헤더가 SHEET_HEADERS와 어긋나면(예: '위치' 열 누락) 헤더 행을 보정한다.
    기존 데이터(A~G)는 그대로 두고 누락된 뒤쪽 헤더(H='위치')만 채워진다.
    세션 단위로 한 번만 실행해 불필요한 쓰기 호출을 막는다."""
    cache_key = f"_headers_ok::{worksheet.title}"
    if st.session_state.get(cache_key):
        return
    try:
        current = worksheet.row_values(1)
        if current[:len(SHEET_HEADERS)] != SHEET_HEADERS:
            worksheet.update(f'A1:{_last_col_letter()}1', [SHEET_HEADERS], value_input_option='RAW')
        st.session_state[cache_key] = True
    except Exception:
        # 헤더 보정 실패는 치명적이지 않으므로 조용히 넘어간다(다음 세션에서 재시도).
        pass

def force_text_seal(value):
    """씰 번호의 선행 0(예: '0123')이 USER_ENTERED 저장 시 숫자(123)로 해석돼
    사라지는 것을 막는다. 앞에 작은따옴표를 붙이면 시트가 강제로 텍스트로 저장하고,
    get_all_values()로 읽을 때는 따옴표가 빠진 원본 문자열('0123')이 반환된다.
    빈 값/NaN은 빈 문자열로 둔다."""
    if value is None:
        return ""
    s = str(value)
    if s == "" or s.lower() == "nan":
        return ""
    if s.startswith("'"):  # 이미 처리된 값은 중복 적용하지 않음
        return s
    return "'" + s

# --- 행 조회 헬퍼 (공용) ---
def find_row_by_container_no(worksheet, container_no):
    """컨테이너 번호로 시트의 실제 행 번호(1-based)를 찾는다. 없으면 None.

    세션의 리스트 인덱스는 다른 기기의 추가/삭제로 시트 행 순서와 어긋날 수 있으므로,
    고유값인 컨테이너 번호(A열)로 직접 행을 찾아 잘못된 행을 덮어쓰는 사고를 방지한다.
    """
    if not container_no:
        return None
    col_values = worksheet.col_values(1)  # A열 전체 (1행=헤더)
    for i, val in enumerate(col_values):
        if val == container_no:
            return i + 1  # 1-based 행 번호
    return None

# --- 로그 기록 함수 (공용) ---
def log_change(action):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return
    try:
        log_sheet = get_stable_worksheet(LOG_SHEET_NAME)
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        log_sheet.append_row([timestamp, action])
    except Exception as e:
        st.warning(f"로그 기록 중 오류 발생: {e}")

# --- 데이터 관리 함수들 (공용) ---
def load_data_from_gsheet():
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return []
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        ensure_sheet_headers(worksheet)

        all_values = worksheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        data = all_values[1:]

        df = pd.DataFrame(data, columns=headers, dtype=str)
        df.replace('', pd.NA, inplace=True)

        if '위치' not in df.columns:
            df['위치'] = pd.NA

        if '등록일시' in df.columns:
            df['등록일시'] = pd.to_datetime(df['등록일시'], errors='coerce')
        if '완료일시' in df.columns:
            df['완료일시'] = pd.to_datetime(df['완료일시'], errors='coerce')

        if '상태' in df.columns and '완료일시' in df.columns:
            inconsistent_rows = (df['상태'] == '선적중') & (df['완료일시'].notna())
            df.loc[inconsistent_rows, '완료일시'] = pd.NaT

        return df.to_dict('records')
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"'{MAIN_SHEET_NAME}' 시트를 찾을 수 없습니다.")
        return []
    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
        return []


def add_row_to_gsheet(data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        ensure_sheet_headers(worksheet)
        data_copy = data.copy()
        # NaT는 datetime의 서브클래스라 strftime에서 죽으므로 isna를 먼저 거른다
        if data_copy.get('등록일시') is None or pd.isna(data_copy.get('등록일시')):
            data_copy['등록일시'] = ''
        elif isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
        if data_copy.get('완료일시') is None or pd.isna(data_copy.get('완료일시')):
            data_copy['완료일시'] = ''
        elif isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_insert = [
            force_text_seal(data_copy.get(header, "")) if header == '씰 번호'
            else data_copy.get(header, "")
            for header in SHEET_HEADERS
        ]
        worksheet.append_row(row_to_insert, value_input_option='USER_ENTERED')
        log_change(f"신규 등록: {data_copy.get('컨테이너 번호')}")
        invalidate_sheet_caches()
        return True, "성공"
    except Exception as e:
        return False, str(e)


def add_rows_to_gsheet_batch(data_list):
    """여러 행을 한 번의 API 호출로 일괄 추가 (복구 시 사용)"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        ensure_sheet_headers(worksheet)

        rows_to_insert = []
        container_nos = []
        for data in data_list:
            data_copy = data.copy()
            # NaT는 datetime의 서브클래스라 strftime에서 죽으므로 isna를 먼저 거른다
            if data_copy.get('등록일시') is None or pd.isna(data_copy.get('등록일시')):
                data_copy['등록일시'] = ''
            elif isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
                data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
            if data_copy.get('완료일시') is None or pd.isna(data_copy.get('완료일시')):
                data_copy['완료일시'] = ''
            elif isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
                data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')
            rows_to_insert.append([
                force_text_seal(data_copy.get(header, "")) if header == '씰 번호'
                else data_copy.get(header, "")
                for header in SHEET_HEADERS
            ])
            container_nos.append(data_copy.get('컨테이너 번호', ''))

        worksheet.append_rows(rows_to_insert, value_input_option='USER_ENTERED')
        log_change(f"일괄 복구: {len(data_list)}개 ({', '.join(container_nos)})")
        invalidate_sheet_caches()
        return True, "성공"
    except Exception as e:
        return False, str(e)


def update_row_in_gsheet(data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        ensure_text_format(worksheet, '씰 번호')
        ensure_sheet_headers(worksheet)
        container_no = data.get('컨테이너 번호')
        row_num = find_row_by_container_no(worksheet, container_no)
        if row_num is None:
            return False, f"'{container_no}' 컨테이너를 시트에서 찾을 수 없습니다. '데이터 새로고침' 후 다시 시도해주세요."

        data_copy = data.copy()
        # NaT는 datetime의 서브클래스라 strftime에서 죽으므로 isna를 먼저 거른다
        if data_copy.get('등록일시') is None or pd.isna(data_copy.get('등록일시')):
            data_copy['등록일시'] = ''
        elif isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')

        if data_copy.get('완료일시') is None or pd.isna(data_copy.get('완료일시')):
            data_copy['완료일시'] = ''
        elif isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_update = [
            force_text_seal(data_copy.get(header, "")) if header == '씰 번호'
            else data_copy.get(header, "")
            for header in SHEET_HEADERS
        ]
        worksheet.update(f'A{row_num}:{_last_col_letter()}{row_num}', [row_to_update], value_input_option='USER_ENTERED')
        log_change(f"데이터 수정: {container_no}")
        invalidate_sheet_caches()
        return True, "성공"
    except Exception as e:
        return False, str(e)


def delete_row_from_gsheet(container_no):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        row_num = find_row_by_container_no(worksheet, container_no)
        if row_num is None:
            return False, f"'{container_no}' 컨테이너를 시트에서 찾을 수 없습니다. '데이터 새로고침' 후 다시 시도해주세요."
        worksheet.delete_rows(row_num)
        log_change(f"데이터 삭제: {container_no}")
        invalidate_sheet_caches()
        return True, "성공"
    except Exception as e:
        return False, str(e)


def delete_rows_by_container_nos(container_nos):
    """여러 컨테이너 행을 A열 1회 조회 + batch_update 1회로 일괄 삭제한다.

    행마다 삭제 API를 호출하던 방식(N개 → 2N회 호출)을 2회 호출로 줄여
    백업 정리 시 gspread 분당 쿼터 초과 위험을 없앤다.
    """
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        worksheet = get_stable_worksheet(MAIN_SHEET_NAME)
        target = set(container_nos)
        col_values = worksheet.col_values(1)  # A열 한 번만 읽기
        # 0-based 행 인덱스(헤더=0). 삭제 시 인덱스가 밀리므로 내림차순으로 처리해야 안전.
        row_indices = sorted(
            [i for i, val in enumerate(col_values) if val in target],
            reverse=True
        )
        if not row_indices:
            return True, 0

        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": worksheet.id,
                        "dimension": "ROWS",
                        "startIndex": idx,      # 0-based, 포함
                        "endIndex": idx + 1,    # 미포함
                    }
                }
            }
            for idx in row_indices
        ]
        spreadsheet.batch_update({"requests": requests})
        log_change(f"데이터 삭제(일괄): {len(row_indices)}개 ({', '.join(container_nos)})")
        invalidate_sheet_caches()
        return True, len(row_indices)
    except Exception as e:
        return False, str(e)


def delete_from_backup_sheets(container_nos, source_sheet_name):
    """복구된 컨테이너를 해당 일별/월별 백업 시트에서만 삭제
    source_sheet_name: 복구한 시트명 (예: 백업_2025-04-25 또는 백업_2025-04)
    """
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        container_nos_set = set(container_nos)

        # 복구한 시트명에서 날짜 추출 후 관련 시트 목록 결정
        date_part = source_sheet_name.replace(BACKUP_PREFIX, '')  # 예: 2025-04-25 or 2025-04

        if len(date_part) == 10:
            # 일별 시트에서 복구한 경우 → 해당 일별 + 해당 월별 시트
            month_part = date_part[:7]  # 2025-04
            target_sheets = [
                f"{BACKUP_PREFIX}{date_part}",   # 백업_2025-04-25
                f"{BACKUP_PREFIX}{month_part}",  # 백업_2025-04
            ]
        elif len(date_part) == 7:
            # 월별 시트에서 복구한 경우 → 해당 월별 시트만 (일별은 이미 정리됐을 수 있음)
            target_sheets = [f"{BACKUP_PREFIX}{date_part}"]  # 백업_2025-04
        else:
            return False, f"시트명 형식을 인식할 수 없습니다: {source_sheet_name}"

        total_deleted = 0
        ws_map = get_worksheets_map(spreadsheet)

        for sheet_name in target_sheets:
            ws = ws_map.get(sheet_name)
            if ws is None:
                continue
            try:
                all_values = ws.get_all_values()
                if len(all_values) < 2:
                    continue

                headers = all_values[0]
                if '컨테이너 번호' not in headers:
                    continue

                col_idx = headers.index('컨테이너 번호')

                # 삭제할 행 번호를 역순으로 수집
                rows_to_delete = [
                    i + 2  # 헤더(1행) + 0-index 보정
                    for i, row in enumerate(all_values[1:])
                    if len(row) > col_idx and row[col_idx] in container_nos_set
                ]

                for row_num in sorted(rows_to_delete, reverse=True):
                    ws.delete_rows(row_num)
                    total_deleted += 1

            except Exception:
                continue

        log_change(f"백업 시트 정리: {len(container_nos)}개 복구 후 {target_sheets}에서 {total_deleted}행 삭제")
        invalidate_sheet_caches()
        return True, total_deleted

    except Exception as e:
        return False, str(e)


def update_row_in_backup_sheets(data, source_sheet_name):
    """백업 시트에서 특정 컨테이너 행을 수정한다.

    복구 화면에서 ✏️ 수정으로 변경한 내용을 원본 백업 시트(일별+월별)에 반영한다.
    source_sheet_name: 복구 중인 시트명 (예: 백업_2025-04-25 또는 백업_2025-04)
    대상 시트 결정 규칙은 delete_from_backup_sheets와 동일하다.
    """
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        container_no = data.get('컨테이너 번호')
        if not container_no:
            return False, "컨테이너 번호가 없습니다."

        # 복구한 시트명에서 날짜 추출 후 관련 시트 목록 결정
        date_part = source_sheet_name.replace(BACKUP_PREFIX, '')  # 예: 2025-04-25 or 2025-04
        if len(date_part) == 10:
            month_part = date_part[:7]
            target_sheets = [
                f"{BACKUP_PREFIX}{date_part}",   # 백업_2025-04-25
                f"{BACKUP_PREFIX}{month_part}",  # 백업_2025-04
            ]
        elif len(date_part) == 7:
            target_sheets = [f"{BACKUP_PREFIX}{date_part}"]  # 백업_2025-04
        else:
            return False, f"시트명 형식을 인식할 수 없습니다: {source_sheet_name}"

        # 저장용 값 정규화 (update_row_in_gsheet와 동일 규칙)
        data_copy = data.copy()
        # NaT는 datetime의 서브클래스라 strftime에서 죽으므로 isna를 먼저 거른다
        if data_copy.get('등록일시') is None or pd.isna(data_copy.get('등록일시')):
            data_copy['등록일시'] = ''
        elif isinstance(data_copy.get('등록일시'), (datetime, pd.Timestamp)):
            data_copy['등록일시'] = pd.to_datetime(data_copy['등록일시']).strftime('%Y-%m-%d %H:%M:%S')
        if data_copy.get('완료일시') is None or pd.isna(data_copy.get('완료일시')):
            data_copy['완료일시'] = ''
        elif isinstance(data_copy.get('완료일시'), (datetime, pd.Timestamp)):
            data_copy['완료일시'] = pd.to_datetime(data_copy['완료일시']).strftime('%Y-%m-%d %H:%M:%S')

        row_to_update = [
            force_text_seal(data_copy.get(header, "")) if header == '씰 번호'
            else data_copy.get(header, "")
            for header in SHEET_HEADERS
        ]

        ws_map = get_worksheets_map(spreadsheet)
        updated_count = 0
        for sheet_name in target_sheets:
            ws = ws_map.get(sheet_name)
            if ws is None:
                continue
            ensure_text_format(ws, '씰 번호')
            ensure_sheet_headers(ws)
            row_num = find_row_by_container_no(ws, container_no)
            if row_num is None:
                continue
            ws.update(f'A{row_num}:{_last_col_letter()}{row_num}', [row_to_update], value_input_option='USER_ENTERED')
            updated_count += 1

        if updated_count == 0:
            return False, f"'{container_no}'를 백업 시트에서 찾을 수 없습니다."

        log_change(f"백업 데이터 수정: {container_no} ({', '.join(target_sheets)})")
        invalidate_sheet_caches()
        return True, updated_count
    except Exception as e:
        return False, str(e)


def backup_data_to_new_sheet(container_data):
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "스프레드시트 연결 안됨"
    try:
        df_new = pd.DataFrame(container_data)

        if '등록일시' in df_new.columns:
            df_new['등록일시'] = pd.to_datetime(df_new['등록일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '완료일시' in df_new.columns:
            df_new['완료일시'] = pd.to_datetime(df_new['완료일시'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
        if '씰 번호' in df_new.columns:
            df_new['씰 번호'] = df_new['씰 번호'].apply(force_text_seal)
        for header in SHEET_HEADERS:
            if header not in df_new.columns:
                df_new[header] = ""
        df_new = df_new[SHEET_HEADERS]

        kst_now = datetime.now(KST)

        # --- 1. 일별 백업 (Daily Report & Restore Point) ---
        today_str = kst_now.date().isoformat()
        daily_backup_name = f"{BACKUP_PREFIX}{today_str}"
        try:
            backup_sheet = spreadsheet.worksheet(daily_backup_name)
            ensure_text_format(backup_sheet, '씰 번호')
            existing_values = backup_sheet.get_all_values()
            if len(existing_values) > 1:
                df_existing = pd.DataFrame(existing_values[1:], columns=existing_values[0], dtype=str)
                if '씰 번호' in df_existing.columns:
                    df_existing['씰 번호'] = df_existing['씰 번호'].apply(force_text_seal)
                df_combined = pd.concat([df_existing, df_new])
                df_final = df_combined.drop_duplicates(subset=['컨테이너 번호'], keep='last')
                backup_sheet.clear()
                backup_sheet.update('A1', [SHEET_HEADERS] + df_final.values.tolist(), value_input_option='USER_ENTERED')
            else:
                # 헤더만 있거나 빈 시트인 경우 A1부터 명시적으로 덮어쓰기
                backup_sheet.update('A1', [SHEET_HEADERS] + df_new.values.tolist(), value_input_option='USER_ENTERED')
        except gspread.exceptions.WorksheetNotFound:
            new_sheet = spreadsheet.add_worksheet(title=daily_backup_name, rows=len(df_new) + 50, cols=len(SHEET_HEADERS))
            new_sheet.update('A1', [SHEET_HEADERS], value_input_option='USER_ENTERED')
            ensure_text_format(new_sheet, '씰 번호')
            if not df_new.empty:
                new_sheet.update('A2', df_new.values.tolist(), value_input_option='USER_ENTERED')

        # --- 2. 월별 통합 백업 (Monthly Aggregation) ---
        month_str = kst_now.date().strftime('%Y-%m')
        monthly_backup_name = f"{BACKUP_PREFIX}{month_str}"
        try:
            backup_sheet = spreadsheet.worksheet(monthly_backup_name)
            ensure_text_format(backup_sheet, '씰 번호')
            existing_values = backup_sheet.get_all_values()
            if len(existing_values) > 1:
                existing_df = pd.DataFrame(existing_values[1:], columns=existing_values[0], dtype=str)
                new_unique_df = df_new[~df_new['컨테이너 번호'].isin(existing_df['컨테이너 번호'])]
            else:
                new_unique_df = df_new
            if not new_unique_df.empty:
                backup_sheet.append_rows(new_unique_df.values.tolist(), value_input_option='USER_ENTERED')
        except gspread.exceptions.WorksheetNotFound:
            # 월별 시트는 한 달 누적 데이터를 담으므로 넉넉하게 1000행으로 고정
            new_sheet = spreadsheet.add_worksheet(title=monthly_backup_name, rows=1000, cols=len(SHEET_HEADERS))
            new_sheet.update('A1', [SHEET_HEADERS], value_input_option='USER_ENTERED')
            ensure_text_format(new_sheet, '씰 번호')
            if not df_new.empty:
                new_sheet.update('A2', df_new.values.tolist(), value_input_option='USER_ENTERED')

        invalidate_sheet_caches()
        return True, None
    except Exception as e:
        return False, str(e)


def move_containers_between_backup_sheets(container_nos, source_sheet_name, target_date_str, update_completion_date):
    """백업 시트 간 컨테이너 데이터 이동
    
    container_nos: 이동할 컨테이너 번호 리스트
    source_sheet_name: 원본 시트명 (예: 백업_2025-04-28)
    target_date_str: 대상 날짜 문자열 (예: 2025-04-27)
    update_completion_date: True면 완료일시를 target_date로 수정
    """
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        container_nos_set = set(container_nos)
        source_date_str = source_sheet_name.replace(BACKUP_PREFIX, '')
        target_daily_name = f"{BACKUP_PREFIX}{target_date_str}"
        target_month_str = target_date_str[:7]
        target_monthly_name = f"{BACKUP_PREFIX}{target_month_str}"
        source_month_str = source_date_str[:7] if len(source_date_str) == 10 else source_date_str
        source_monthly_name = f"{BACKUP_PREFIX}{source_month_str}"

        all_sheet_titles = [s.title for s in spreadsheet.worksheets()]

        # ① 원본 시트에서 이동할 행 추출
        source_ws = spreadsheet.worksheet(source_sheet_name)
        source_values = source_ws.get_all_values()
        if len(source_values) < 2:
            return False, "원본 시트에 데이터가 없습니다."

        headers = source_values[0]
        if '컨테이너 번호' not in headers:
            return False, "원본 시트에 컨테이너 번호 컬럼이 없습니다."

        col_idx = headers.index('컨테이너 번호')
        completion_col_idx = headers.index('완료일시') if '완료일시' in headers else None
        seal_col_idx = headers.index('씰 번호') if '씰 번호' in headers else None

        rows_to_move = []
        rows_to_delete = []
        for i, row in enumerate(source_values[1:]):
            if len(row) > col_idx and row[col_idx] in container_nos_set:
                row_data = list(row)
                # 선행 0 보존을 위해 씰 번호를 강제 텍스트로 (USER_ENTERED 재기록 대비)
                if seal_col_idx is not None and seal_col_idx < len(row_data):
                    row_data[seal_col_idx] = force_text_seal(row_data[seal_col_idx])
                # 완료일시 수정 옵션
                if update_completion_date and completion_col_idx is not None:
                    row_data[completion_col_idx] = f"{target_date_str} 00:00:00"
                rows_to_move.append(row_data)
                rows_to_delete.append(i + 2)  # 헤더 + 0-index 보정

        if not rows_to_move:
            return False, "원본 시트에서 해당 컨테이너를 찾을 수 없습니다."

        # ② 원본 일별 시트에서 삭제 (역순)
        for row_num in sorted(rows_to_delete, reverse=True):
            source_ws.delete_rows(row_num)

        # 삭제 후 원본 시트에 데이터가 없으면 시트 자체 삭제
        remaining = source_ws.get_all_values()
        if len(remaining) <= 1:  # 헤더만 남은 경우
            spreadsheet.del_worksheet(source_ws)

        # ③ 대상 일별 시트에 추가
        if target_daily_name in all_sheet_titles:
            target_daily_ws = spreadsheet.worksheet(target_daily_name)
        else:
            target_daily_ws = spreadsheet.add_worksheet(
                title=target_daily_name, rows=len(rows_to_move) + 50, cols=len(SHEET_HEADERS)
            )
            target_daily_ws.update('A1', [headers], value_input_option='USER_ENTERED')
            ensure_text_format(target_daily_ws, '씰 번호')

        target_daily_ws.append_rows(rows_to_move, value_input_option='USER_ENTERED')

        # ④ 월별 시트 완료일시 업데이트
        # 원본 월별 시트가 대상 월별 시트와 다를 경우 이동 처리
        if source_monthly_name != target_monthly_name:
            # 원본 월별 시트에서 삭제
            if source_monthly_name in all_sheet_titles:
                source_monthly_ws = spreadsheet.worksheet(source_monthly_name)
                monthly_values = source_monthly_ws.get_all_values()
                if len(monthly_values) >= 2:
                    monthly_col_idx = monthly_values[0].index('컨테이너 번호') if '컨테이너 번호' in monthly_values[0] else None
                    if monthly_col_idx is not None:
                        monthly_rows_to_delete = [
                            i + 2 for i, row in enumerate(monthly_values[1:])
                            if len(row) > monthly_col_idx and row[monthly_col_idx] in container_nos_set
                        ]
                        for row_num in sorted(monthly_rows_to_delete, reverse=True):
                            source_monthly_ws.delete_rows(row_num)

            # 대상 월별 시트에 추가
            if target_monthly_name in all_sheet_titles:
                target_monthly_ws = spreadsheet.worksheet(target_monthly_name)
                target_monthly_ws.append_rows(rows_to_move, value_input_option='USER_ENTERED')
            else:
                target_monthly_ws = spreadsheet.add_worksheet(
                    title=target_monthly_name, rows=1000, cols=len(SHEET_HEADERS)
                )
                target_monthly_ws.update('A1', [headers], value_input_option='USER_ENTERED')
                ensure_text_format(target_monthly_ws, '씰 번호')
                target_monthly_ws.append_rows(rows_to_move, value_input_option='USER_ENTERED')

        else:
            # 같은 월이면 완료일시만 업데이트
            if update_completion_date and target_monthly_name in all_sheet_titles:
                monthly_ws = spreadsheet.worksheet(target_monthly_name)
                monthly_values = monthly_ws.get_all_values()
                if len(monthly_values) >= 2:
                    m_headers = monthly_values[0]
                    if '컨테이너 번호' in m_headers and '완료일시' in m_headers:
                        m_col_idx = m_headers.index('컨테이너 번호')
                        m_done_idx = m_headers.index('완료일시')
                        for i, row in enumerate(monthly_values[1:]):
                            if len(row) > m_col_idx and row[m_col_idx] in container_nos_set:
                                monthly_ws.update_cell(i + 2, m_done_idx + 1, f"{target_date_str} 00:00:00")

        log_change(f"백업 이동: {container_nos} → '{source_sheet_name}'에서 '{target_daily_name}'으로 이동" +
                   (" (완료일시 수정)" if update_completion_date else ""))
        invalidate_sheet_caches()
        return True, len(rows_to_move)

    except Exception as e:
        return False, str(e)


def cleanup_old_daily_sheets(months=3):
    """3개월 이상 된 일별 백업 시트 삭제 (월별 시트는 보존)"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        cutoff_date = datetime.now(KST).date() - timedelta(days=months * 30)

        all_sheets = [s.title for s in spreadsheet.worksheets()]
        # 일별 시트만 대상: 백업_YYYY-MM-DD
        daily_sheets = filter_backup_sheets(all_sheets, "daily")

        deleted_sheets = []
        for sheet_name in daily_sheets:
            date_part = sheet_name.replace(BACKUP_PREFIX, '')
            try:
                sheet_date = datetime.strptime(date_part, '%Y-%m-%d').date()
                if sheet_date < cutoff_date:
                    spreadsheet.del_worksheet(spreadsheet.worksheet(sheet_name))
                    deleted_sheets.append(sheet_name)
            except ValueError:
                continue

        if deleted_sheets:
            log_change(f"일별 백업 정리: {len(deleted_sheets)}개 시트 삭제 ({', '.join(deleted_sheets)})")
            invalidate_sheet_caches()

        return True, deleted_sheets

    except Exception as e:
        return False, str(e)


def archive_log_sheet(keep_rows=200):
    """로그 시트가 1000행 초과 시 오래된 로그를 분기별 아카이브 시트로 이관"""
    spreadsheet = connect_to_gsheet()
    if spreadsheet is None:
        return False, "Google Sheets에 연결되지 않았습니다."
    try:
        log_sheet = get_stable_worksheet(LOG_SHEET_NAME)
        all_values = log_sheet.get_all_values()
        total_rows = len(all_values)

        if total_rows <= 1000:
            return False, f"현재 {total_rows}행으로 아카이브 기준(1000행) 미만입니다."

        # 이관할 행: 최근 keep_rows행을 제외한 나머지
        rows_to_archive = all_values[:total_rows - keep_rows]
        rows_to_keep = all_values[total_rows - keep_rows:]

        if not rows_to_archive:
            return False, "이관할 데이터가 없습니다."

        # 분기 계산 (첫 번째 이관 행의 날짜 기준)
        try:
            first_date = datetime.strptime(rows_to_archive[0][0][:10], '%Y-%m-%d')
            quarter = (first_date.month - 1) // 3 + 1
            archive_name = f"로그_{first_date.year}-Q{quarter}"
        except Exception:
            archive_name = f"로그_아카이브_{datetime.now(KST).strftime('%Y%m%d')}"

        # 아카이브 시트에 저장 (기존 시트가 있으면 이어붙이기)
        all_sheet_titles = [s.title for s in spreadsheet.worksheets()]
        if archive_name in all_sheet_titles:
            archive_sheet = spreadsheet.worksheet(archive_name)
            archive_sheet.append_rows(rows_to_archive, value_input_option='USER_ENTERED')
        else:
            archive_sheet = spreadsheet.add_worksheet(title=archive_name, rows=len(rows_to_archive) + 50, cols=2)
            archive_sheet.update('A1', rows_to_archive, value_input_option='USER_ENTERED')

        # 메인 로그 시트는 최근 keep_rows행만 남기기
        log_sheet.clear()
        log_sheet.update('A1', rows_to_keep, value_input_option='USER_ENTERED')

        log_change(f"로그 아카이브: {len(rows_to_archive)}행 → '{archive_name}'으로 이관, {len(rows_to_keep)}행 유지")
        invalidate_sheet_caches()
        return True, (archive_name, len(rows_to_archive))

    except Exception as e:
        return False, str(e)
