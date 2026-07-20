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


def test_extract_serial_split_multiline():
    # 실사진 레이아웃: HLHU / 8376 / 88 / [1] / 45G1 — 일련번호가 여러 조각
    # 줄로 나뉘어 읽혀도 11자가 완성될 때까지 이어붙여 인식해야 한다
    assert extract_container_numbers("HLHU\n8376\n88\n1\n45G1") == [("HLHU8376881", True)]
    assert extract_container_numbers("HLHU\n8376 88 1\n45G1") == [("HLHU8376881", True)]


def test_extract_combo_dropped_when_contiguous_valid_exists():
    # 이어 읽힌 검증 통과 번호(CSQU3054383)가 있으면, 떨어진 토큰을 짜맞춘 조합
    # (TARE+1234560 — 사진에 실제로 없는 번호)이 우연히 체크디지트를 통과해도
    # 화면에 나오지 않도록 버려야 한다
    text = "CSQU 305438 3\nTARE\n1234560"
    valid = [c for c, ok in extract_container_numbers(text) if ok]
    assert valid == ["CSQU3054383"]


def test_extract_column_layout_with_labels_between():
    # 실사진 OCR 원문 그대로: 열 단위로 읽혀 번호 조각(HLHU/8376/88 11) 사이에
    # 라벨 줄이 끼고, 체크디지트 상자가 '11'로 겹쳐 읽힌 레이아웃
    text = ("Com\nHLHU\n8376\nMAX. GROSS\nTARE\nPAYLOAD\nCU. CAP.\n88 11\n"
            "45G1\n32,500\n71,650\n3,700\n8.160\nKG.\nLB.\nKG.\nLB.\n28,800\n"
            "KG.\n63.490\nLB.\n76.4 CU.M.\n2.700 CU.FT.")
    assert extract_container_numbers(text) == [("HLHU8376881", True)]


def test_extract_column_layout_rejects_mixed_lines():
    # 같은 사진의 다른 시도: '3 KL', '88 M'처럼 글자 섞인 줄의 숫자로 조립한
    # 가짜(HLHU8376388 — 체크디지트 우연 통과)는 후보가 되면 안 된다
    text = ("G A\ncom\nHLHU\n8376\nMAX. GROSS\nTARE\nPAYLOAD\nCU. CAP.\n"
            "3 KL\n88 M\n45G1\n32,500\n71.650\n3.700\n8.160\n28,800\nKG.\n"
            "63.490\nLB.\n76.4\nCU.M.\n2.700 CU.FT.")
    assert extract_container_numbers(text) == []


def test_extract_check_digit_read_as_two_digits():
    # 실사진(HDGU) OCR 원문: 체크디지트 상자 [1]이 테두리와 겹쳐 '11'로,
    # 그것도 무게 표기 뒤 한참 아래 줄에서 읽힌 경우
    text = "KR\nHYUNDAI\nGLOVIS\nHDGU\nMAX. GROSS\n500057\n45G1\n32.500\nKGS\n11"
    valid = [c for c, ok in extract_container_numbers(text) if ok]
    assert valid == ["HDGU5000571"]


def test_extract_requires_category_u():
    # 실사진 오탐 사례: 단위 표기 조각(CU.CAP → CAPB, LB/KG → LBKG)이 숫자
    # 나열과 이어붙어 체크디지트를 우연히 통과한 가짜 번호 — 화물 컨테이너의
    # 카테고리 문자(4번째 글자)는 항상 U이므로 후보에서 제외해야 한다
    assert extract_container_numbers("CAPB8114561") == []
    assert extract_container_numbers("LBKG1828800") == []


def test_extract_no_match():
    assert extract_container_numbers("아무 번호도 없는 텍스트") == []
    assert extract_container_numbers("") == []
