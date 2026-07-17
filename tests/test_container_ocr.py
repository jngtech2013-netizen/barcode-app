"""container_ocr.py의 순수 로직(체크디지트/후보 추출) 단위 테스트.

실행: 프로젝트 루트에서
    python -m pytest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from container_ocr import (
    compute_check_digit,
    is_valid_check_digit,
    extract_container_numbers,
)


# --- 체크디지트 (ISO 6346 공식 예시: CSQU3054383) ---
def test_compute_check_digit_known_example():
    assert compute_check_digit("CSQU305438") == 3


def test_valid_check_digit():
    assert is_valid_check_digit("CSQU3054383")


def test_invalid_check_digit():
    assert not is_valid_check_digit("CSQU3054384")


def test_check_digit_rejects_bad_format():
    assert not is_valid_check_digit("CSQ3054383")   # 영문 3자리
    assert not is_valid_check_digit("")
    assert not is_valid_check_digit("csqu3054383")  # 소문자


# --- OCR 텍스트에서 후보 추출 ---
def test_extract_plain_number():
    result = extract_container_numbers("CSQU3054383")
    assert result[0] == ("CSQU3054383", True)


def test_extract_with_spaces_and_noise():
    # 실제 도장 표기처럼 소유자코드/일련번호/체크디지트가 띄어 찍힌 경우
    text = "MAERSK LINE\nCSQU 305438 3\n22G1"
    numbers = [c for c, ok in extract_container_numbers(text) if ok]
    assert "CSQU3054383" in numbers


def test_extract_corrects_ocr_confusion():
    # 숫자 자리의 O→0, 영문 자리의 0→O 오인식을 보정해야 한다
    numbers = [c for c, ok in extract_container_numbers("CSQU3O54383") if ok]
    assert "CSQU3054383" in numbers


def test_extract_valid_candidates_first():
    # 체크디지트가 맞는 후보가 틀린 후보보다 앞에 와야 한다
    text = "ABCD1111111\nCSQU3054383"
    result = extract_container_numbers(text)
    assert result[0][0] == "CSQU3054383"
    assert result[0][1] is True


def test_extract_across_two_lines():
    # OCR이 소유자코드와 일련번호를 별개 줄로 읽는 경우 (실제 컨테이너 문 표기)
    text = "HDFU\n528014 4\n45G1"
    result = extract_container_numbers(text)
    assert result[0] == ("HDFU5280144", True)


def test_extract_scattered_door_layout():
    # 실제 문짝 표기: 소유자코드/일련번호/체크디지트가 서로 떨어진 줄로 읽힘
    # (실사진 OCR 결과 그대로 — HDFU 528056 [6])
    text = ("HDFU\nMAX. WT.\nTARE WT.\nPAYLOAD\nCU. CAP.\n528056\n45G1\n6\n"
            "32,500 KGS\n71,650 LBS\n3,700 KGS\n8,160 LBS\n28,800 KGS")
    valid = [c for c, ok in extract_container_numbers(text) if ok]
    assert valid == ["HDFU5280566"]


def test_extract_scattered_wdfu_layout():
    valid = [c for c, ok in extract_container_numbers("WDFU\n120850\n6\n22G1") if ok]
    assert valid == ["WDFU1208506"]


def test_extract_scattered_wrong_check_digit_rejected():
    # 단독 숫자가 체크디지트와 다르면 조합이 만들어지지 않아야 한다
    valid = [c for c, ok in extract_container_numbers("WDFU\n120850\n7\n22G1") if ok]
    assert valid == []


def test_extract_no_match():
    assert extract_container_numbers("아무 번호도 없는 텍스트") == []
    assert extract_container_numbers("") == []
