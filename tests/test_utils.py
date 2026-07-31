"""utils.py의 순수 로직(UI/네트워크 비종속) 단위 테스트.

실행: 프로젝트 루트에서
    python -m pytest
"""
import os
import sys
from datetime import date

# 프로젝트 루트를 import 경로에 추가 (어떤 실행 방식에서도 utils를 찾도록)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from container_ocr import is_valid_check_digit
from utils import (
    is_valid_container_no,
    container_no_error,
    normalize_container_no,
    find_same_day_duplicate,
    overlapping_container_nos,
    backup_values_to_frame,
    merge_backup_frames,
    SHEET_HEADERS,
    filter_backup_sheets,
    make_zpl,
    find_row_by_container_no,
)


# --- is_valid_container_no ---
def test_valid_container_no():
    # 4번째 자리 U + 체크디지트까지 맞는 번호
    assert is_valid_container_no("ABCU1234560")
    assert is_valid_container_no("MSCU1234566")
    assert is_valid_container_no("TGHU7654320")


def test_invalid_container_no_lowercase():
    assert not is_valid_container_no("abcu1234560")


def test_invalid_container_no_too_few_letters():
    assert not is_valid_container_no("ABU1234560")


def test_invalid_container_no_too_many_digits():
    assert not is_valid_container_no("ABCU12345678")


def test_invalid_container_no_with_space():
    assert not is_valid_container_no("ABCU 1234560")


def test_invalid_container_no_empty_or_none():
    assert not is_valid_container_no("")
    assert not is_valid_container_no(None)


def test_invalid_container_no_fourth_char_not_u():
    # 체크디지트는 맞지만 4번째 자리가 U가 아니면 거부한다
    assert is_valid_check_digit("ABCD1234560")
    assert not is_valid_container_no("ABCD1234560")


def test_invalid_container_no_bad_check_digit():
    # 형식과 4번째 자리는 맞지만 마지막 자리가 틀린 경우
    assert not is_valid_container_no("ABCU1234561")


# --- container_no_error (사유별 메시지) ---
def test_container_no_error_none_when_valid():
    assert container_no_error("ABCU1234560") is None


def test_container_no_error_empty():
    assert "입력" in container_no_error("")
    assert "입력" in container_no_error(None)


def test_container_no_error_format():
    assert "형식" in container_no_error("AB1234560")


def test_container_no_error_mentions_u():
    msg = container_no_error("ABCD1234560")
    assert "U" in msg and "4번째" in msg


def test_container_no_error_mentions_expected_check_digit():
    msg = container_no_error("ABCU1234561")
    assert "체크디지트" in msg
    assert "'0'" in msg  # 기대값 0을 알려줘야 한다


# --- find_same_day_duplicate ---
TODAY = date(2026, 7, 30)


def _row(cno, when, pos="1", status="선적중"):
    return {'컨테이너 번호': cno, '등록일시': when, '상태': status, '위치': pos}


def test_same_day_duplicate_found():
    rows = [_row("ABCU1234560", pd.Timestamp("2026-07-30 09:12:00"))]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is not None


def test_yesterday_same_number_is_allowed():
    rows = [_row("ABCU1234560", pd.Timestamp("2026-07-29 23:59:00"))]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is None


def test_same_day_duplicate_ignores_status():
    # 상태와 무관하게 같은 날 등록분이면 중복으로 본다
    rows = [_row("ABCU1234560", pd.Timestamp("2026-07-30 08:00:00"), status="선적완료")]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is not None


def test_same_day_duplicate_handles_string_datetime():
    # 시트에서 문자열로 읽힌 등록일시도 인식해야 한다
    rows = [_row("ABCU1234560", "2026-07-30 10:00:00")]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is not None


def test_same_day_duplicate_normalizes_whitespace_and_case():
    rows = [_row(" abcu1234560 ", pd.Timestamp("2026-07-30 10:00:00"))]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is not None


def test_missing_registered_at_is_not_duplicate():
    # 등록일시가 없는 레거시 행은 날짜를 알 수 없으므로 막지 않는다
    rows = [_row("ABCU1234560", None), _row("ABCU1234560", pd.NaT)]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is None


def test_different_number_is_not_duplicate():
    rows = [_row("MSCU1234566", pd.Timestamp("2026-07-30 09:00:00"))]
    assert find_same_day_duplicate(rows, "ABCU1234560", TODAY) is None


def test_empty_input_is_not_duplicate():
    rows = [_row("ABCU1234560", pd.Timestamp("2026-07-30 09:00:00"))]
    assert find_same_day_duplicate(rows, "", TODAY) is None
    assert find_same_day_duplicate([], "ABCU1234560", TODAY) is None


def test_normalize_container_no():
    assert normalize_container_no(" abcu1234560 ") == "ABCU1234560"
    assert normalize_container_no(None) == ""
    assert normalize_container_no(float("nan")) == ""


# --- 백업 병합 (일별·월별 공통 규칙) ---
BACKUP_VALUES = [
    ['컨테이너 번호', '출고처', '피트수', '씰 번호', '상태', '등록일시', '완료일시', '위치'],
    ['MSCU1234566', '베트남', '40', 'S1', '선적완료', '2026-07-30 08:00:00', '2026-07-30 11:00:00', '2'],
    ['ABCU1234560', '박닌', '20', 'S2', '선적완료', '2026-07-30 09:00:00', '2026-07-30 12:00:00', '3'],
]


# --- backup_values_to_frame / merge_backup_frames / overlapping_container_nos ---
def _new_frame(rows):
    """백업에 새로 쓸 행들을 SHEET_HEADERS 순서 DataFrame으로 만든다."""
    df = pd.DataFrame(rows)
    for h in SHEET_HEADERS:
        if h not in df.columns:
            df[h] = ""
    return df[SHEET_HEADERS]


def test_backup_values_to_frame_aligns_columns():
    values = [['출고처', '컨테이너 번호'], ['박닌', 'ABCU1234560']]
    df = backup_values_to_frame(values)
    assert list(df.columns) == SHEET_HEADERS
    assert df.iloc[0]['컨테이너 번호'] == 'ABCU1234560'
    assert df.iloc[0]['위치'] == ''  # 없던 열은 빈 값으로 채운다


def test_merge_keeps_new_record_for_same_container():
    # 같은 번호가 이미 있으면 새 기록이 이긴다 (일별·월별 동일)
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'ABCU1234560', '출고처': '하택',
                       '완료일시': '2026-07-30 18:00:00'}])
    merged = merge_backup_frames(existing, new)
    rows = merged[merged['컨테이너 번호'] == 'ABCU1234560']
    assert len(rows) == 1
    assert rows.iloc[0]['출고처'] == '하택'
    assert rows.iloc[0]['완료일시'] == '2026-07-30 18:00:00'


def test_merge_keeps_untouched_existing_rows():
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'ABCU1234560', '출고처': '하택'}])
    merged = merge_backup_frames(existing, new)
    assert len(merged) == 2  # 기존 2건 중 1건만 갱신되고 나머지는 유지
    assert (merged['컨테이너 번호'] == 'MSCU1234566').any()


def test_merge_appends_when_no_overlap():
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'TGHU7654320', '출고처': '위해'}])
    merged = merge_backup_frames(existing, new)
    assert len(merged) == 3
    assert list(merged.columns) == SHEET_HEADERS


def test_overlapping_returns_numbers_that_will_be_overwritten():
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'ABCU1234560'}, {'컨테이너 번호': 'TGHU7654320'}])
    assert overlapping_container_nos(existing, new) == ['ABCU1234560']


def test_overlapping_empty_when_all_new():
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'TGHU7654320'}])
    assert overlapping_container_nos(existing, new) == []


def test_overlapping_reports_each_number_once():
    existing = backup_values_to_frame(BACKUP_VALUES)
    new = _new_frame([{'컨테이너 번호': 'ABCU1234560'}, {'컨테이너 번호': 'ABCU1234560'}])
    assert overlapping_container_nos(existing, new) == ['ABCU1234560']


# --- filter_backup_sheets ---
def test_filter_daily_returns_only_daily_sorted_desc():
    titles = [
        "현재 데이터", "업데이트 로그",
        "백업_2025-04-24", "백업_2025-04-25",
        "백업_2025-04",  # 월별 (제외)
        "로그_2025-Q2",  # 백업 아님 (제외)
    ]
    assert filter_backup_sheets(titles, "daily") == ["백업_2025-04-25", "백업_2025-04-24"]


def test_filter_monthly_returns_only_monthly_sorted_desc():
    titles = ["백업_2025-04-25", "백업_2025-03", "백업_2025-04"]
    assert filter_backup_sheets(titles, "monthly") == ["백업_2025-04", "백업_2025-03"]


def test_filter_daily_excludes_monthly():
    assert filter_backup_sheets(["백업_2025-04"], "daily") == []


def test_filter_monthly_excludes_daily():
    assert filter_backup_sheets(["백업_2025-04-25"], "monthly") == []


def test_filter_empty_input():
    assert filter_backup_sheets([], "daily") == []


# --- make_zpl ---
def test_make_zpl_embeds_container_no():
    zpl = make_zpl("ABCD1234567")
    assert "ABCD1234567" in zpl
    assert zpl.startswith("^XA")
    assert zpl.endswith("^XZ")


def test_make_zpl_default_copies_is_two():
    assert "^PQ2" in make_zpl("ABCD1234567")


def test_make_zpl_custom_copies():
    assert "^PQ5" in make_zpl("ABCD1234567", copies=5)


def test_make_zpl_dpi_203_dimensions():
    zpl = make_zpl("ABCD1234567", dpi=203)
    assert "^PW720" in zpl
    assert "^LL480" in zpl


def test_make_zpl_dpi_300_dimensions():
    zpl = make_zpl("ABCD1234567", dpi=300)
    assert "^PW1080" in zpl
    assert "^LL720" in zpl


# --- find_row_by_container_no ---
class FakeWorksheet:
    """col_values(1)만 흉내내는 최소 워크시트 스텁."""
    def __init__(self, column_a):
        self._column_a = column_a

    def col_values(self, col):
        assert col == 1
        return self._column_a


def test_find_row_returns_1based_row_accounting_for_header():
    ws = FakeWorksheet(["컨테이너 번호", "ABCD1111111", "ABCD2222222"])
    assert find_row_by_container_no(ws, "ABCD1111111") == 2
    assert find_row_by_container_no(ws, "ABCD2222222") == 3


def test_find_row_not_found_returns_none():
    ws = FakeWorksheet(["컨테이너 번호", "ABCD1111111"])
    assert find_row_by_container_no(ws, "ZZZZ9999999") is None


def test_find_row_empty_query_returns_none():
    ws = FakeWorksheet(["컨테이너 번호", "ABCD1111111"])
    assert find_row_by_container_no(ws, "") is None
    assert find_row_by_container_no(ws, None) is None
