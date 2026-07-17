"""컨테이너 사진에서 컨테이너 번호(ISO 6346)를 추출하는 OCR 모듈.

OCR 엔진은 OCR.space 무료 API를 사용한다 (월 25,000건 무료, 카드 등록 불필요).
- API 키는 .streamlit/secrets.toml 의 `ocrspace_api_key` 로 설정한다.
  키가 없으면 데모용 공용 키('helloworld')를 쓰지만 호출 제한이 매우 빡빡하므로
  실사용 전 https://ocr.space/ocrapi 에서 무료 키를 발급받아야 한다.
- 무료 키는 업로드 1MB 제한이 있어 전송 전에 이미지를 압축한다.

OCR 오인식(O↔0, I↔1 등)은 위치별 보정 + ISO 6346 체크디지트 검증으로 걸러낸다.
이 모듈은 streamlit에 의존하지 않는다(단위 테스트 용이).
"""
import re
from io import BytesIO

import requests
from PIL import Image, ImageOps

OCR_SPACE_URL = "https://api.ocr.space/parse/image"
OCR_SPACE_DEMO_KEY = "helloworld"  # 공용 데모 키 (호출 제한 큼 — 테스트 전용)
_MAX_UPLOAD_BYTES = 1000 * 1024  # 무료 키 업로드 제한(1MB)보다 약간 작게

# ISO 6346 문자 값 테이블: A=10부터 시작하되 11의 배수(11, 22, 33)는 건너뛴다.
_LETTER_VALUES = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1

# OCR이 헷갈리는 글자 보정: 앞 4자리(영문 자리)에 숫자가 오면 비슷한 영문으로,
# 뒤 7자리(숫자 자리)에 영문이 오면 비슷한 숫자로 바꿔 후보를 만든다.
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
_LETTER_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                    "Z": "2", "S": "5", "G": "6", "B": "8"}


class OcrError(Exception):
    """OCR API 호출 실패(네트워크/키/서버 오류)."""


def compute_check_digit(cno10: str) -> int:
    """앞 10자리(영문 4 + 숫자 6)로 ISO 6346 체크디지트를 계산한다."""
    total = 0
    for i, ch in enumerate(cno10):
        val = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    return total % 11 % 10


def is_valid_check_digit(container_no: str) -> bool:
    """컨테이너 번호(11자리)의 마지막 자리가 ISO 6346 체크디지트와 일치하는지 검증."""
    if not re.fullmatch(r"[A-Z]{4}\d{7}", container_no or ""):
        return False
    return compute_check_digit(container_no[:10]) == int(container_no[10])


def _coerce_window(window: str):
    """11자 알파넘 조각을 '영문4+숫자7' 형태로 위치별 보정. 불가능하면 None."""
    out = []
    for i, ch in enumerate(window):
        if i < 4:
            if ch.isdigit():
                ch = _DIGIT_TO_LETTER.get(ch)
        else:
            if ch.isalpha():
                ch = _LETTER_TO_DIGIT.get(ch)
        if ch is None:
            return None
        out.append(ch)
    return "".join(out)


def extract_container_numbers(text: str) -> list:
    """OCR 텍스트에서 컨테이너 번호 후보를 추출한다.

    반환: (컨테이너번호, 체크디지트_일치여부) 튜플 목록.
    체크디지트가 맞는 후보를 앞에, 그중에서도 4번째 글자가 U(일반 화물용
    컨테이너의 카테고리 문자)인 것을 가장 앞에 둔다.
    """
    if not text:
        return []
    # 컨테이너 번호는 'CSQU 305438 3'처럼 띄어 찍히는 일이 많아
    # 줄 단위로 구분자만 제거해 이어붙인 뒤 11자 슬라이딩 윈도우로 훑는다.
    candidates = []
    seen = set()
    for line in text.upper().splitlines():
        squashed = re.sub(r"[^A-Z0-9]", "", line)
        for start in range(len(squashed) - 10):
            coerced = _coerce_window(squashed[start:start + 11])
            if coerced and coerced not in seen:
                seen.add(coerced)
                candidates.append((coerced, is_valid_check_digit(coerced)))
    candidates.sort(key=lambda c: (not c[1], c[0][3] != "U"))
    return candidates


def compress_image_for_ocr(image_bytes: bytes) -> bytes:
    """무료 키 업로드 제한(1MB)에 맞게 이미지를 축소/재압축한 JPEG 바이트를 반환."""
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)  # 스마트폰 세로 촬영 회전 반영
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    for quality in (85, 70, 55, 40):
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= _MAX_UPLOAD_BYTES:
            return buf.getvalue()
    return buf.getvalue()  # 최저 품질도 넘으면 그대로 전송(서버가 거부하면 오류 안내)


def ocr_space_parse(image_bytes: bytes, api_key: str) -> str:
    """OCR.space에 이미지를 보내 인식된 전체 텍스트를 돌려받는다. 실패 시 OcrError."""
    try:
        resp = requests.post(
            OCR_SPACE_URL,
            files={"file": ("container.jpg", image_bytes, "image/jpeg")},
            data={
                "apikey": api_key,
                "OCREngine": "2",  # 엔진2가 영숫자 혼합(컨테이너 번호)에 더 정확
                "scale": "true",
                "language": "eng",
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        raise OcrError(f"OCR 서버 연결 실패: {e}") from e
    except ValueError as e:
        raise OcrError("OCR 서버 응답을 해석할 수 없습니다.") from e

    if result.get("IsErroredOnProcessing"):
        msg = result.get("ErrorMessage") or result.get("ErrorDetails") or "알 수 없는 오류"
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        raise OcrError(f"OCR 처리 실패: {msg}")
    parsed = result.get("ParsedResults") or []
    return "\n".join(p.get("ParsedText", "") for p in parsed)


def recognize_container_numbers(image_bytes: bytes, api_key: str) -> list:
    """사진 바이트 → 압축 → OCR → 컨테이너 번호 후보 목록. 실패 시 OcrError."""
    compressed = compress_image_for_ocr(image_bytes)
    text = ocr_space_parse(compressed, api_key)
    return extract_container_numbers(text)
