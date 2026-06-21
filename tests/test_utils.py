"""utils.py의 순수 로직(UI/네트워크 비종속) 단위 테스트.

실행: 프로젝트 루트에서
    python -m pytest
"""
import os
import sys

# 프로젝트 루트를 import 경로에 추가 (어떤 실행 방식에서도 utils를 찾도록)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import (
    is_valid_container_no,
    filter_backup_sheets,
    make_zpl,
    find_row_by_container_no,
)


# --- is_valid_container_no ---
def test_valid_container_no():
    assert is_valid_container_no("ABCD1234567")


def test_invalid_container_no_lowercase():
    assert not is_valid_container_no("abcd1234567")


def test_invalid_container_no_too_few_letters():
    assert not is_valid_container_no("ABC1234567")


def test_invalid_container_no_too_many_digits():
    assert not is_valid_container_no("ABCD12345678")


def test_invalid_container_no_with_space():
    assert not is_valid_container_no("ABCD 1234567")


def test_invalid_container_no_empty_or_none():
    assert not is_valid_container_no("")
    assert not is_valid_container_no(None)


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
