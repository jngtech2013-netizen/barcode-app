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
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from PIL import Image, ImageEnhance, ImageOps

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


def _sort_candidates(candidates: list) -> list:
    """체크디지트가 맞는 후보를 앞에, 그중 4번째 글자가 U(일반 화물용 컨테이너의
    카테고리 문자)인 것을 가장 앞에 둔다."""
    return sorted(candidates, key=lambda c: (not c[1], c[0][3] != "U"))


def extract_container_numbers(text: str) -> list:
    """OCR 텍스트에서 컨테이너 번호 후보를 추출한다.

    반환: (컨테이너번호, 체크디지트_일치여부) 튜플 목록 (체크디지트 일치 우선 정렬).
    """
    if not text:
        return []
    # 컨테이너 번호는 'CSQU 305438 3'처럼 띄어 찍히는 일이 많아 줄 단위로
    # 구분자만 제거해 이어붙인 뒤 11자 슬라이딩 윈도우로 훑는다.
    # 소유자코드(HDFU)와 일련번호(528014 4)를 OCR이 별개 줄로 읽는 일도 많아
    # 인접한 두 줄을 이어붙인 조합도 함께 훑는다. (잘못 이어진 조합에서 나온
    # 오탐은 체크디지트 검증이 걸러낸다)
    lines = [re.sub(r"[^A-Z0-9]", "", ln) for ln in text.upper().splitlines()]
    lines = [ln for ln in lines if ln]
    sequences = lines + [lines[i] + lines[i + 1] for i in range(len(lines) - 1)]
    candidates = []
    seen = set()
    for seq in sequences:
        for start in range(len(seq) - 10):
            coerced = _coerce_window(seq[start:start + 11])
            if coerced and coerced not in seen:
                seen.add(coerced)
                candidates.append((coerced, is_valid_check_digit(coerced)))

    # 실제 문짝 표기는 소유자코드(HDFU)·일련번호(528056)·체크디지트(6)가 서로
    # 떨어져 있어 OCR 줄 순서상 인접하지 않게 읽히는 일이 많다. 텍스트 전체에서
    # 4글자 토큰 × 6~7자리 숫자 (× 단독 한 자리 숫자) 조합을 만들어 체크디지트로
    # 검증한다 — 우연히 맞을 확률이 낮아 검증을 통과한 조합만 후보로 삼는다.
    owners, digit7, digit6, digit1 = [], [], [], []
    for ln in lines:
        for run in re.findall(r"[A-Z0-9]+", ln):
            if len(run) == 4:
                coerced = "".join(_DIGIT_TO_LETTER.get(c, c if c.isalpha() else "?")
                                  for c in run)
                if "?" not in coerced:
                    owners.append(coerced)
        for run in re.findall(r"\d+", ln):
            if len(run) == 7:
                digit7.append(run)
            elif len(run) == 6:
                digit6.append(run)
        if len(ln) == 1 and ln.isdigit():  # 체크디지트는 단독 박스로 찍힘
            digit1.append(ln)
    combos = ([o + d for o in owners for d in digit7]
              + [o + d + c for o in owners for d in digit6 for c in digit1])
    for cand in combos:
        if cand not in seen and is_valid_check_digit(cand):
            seen.add(cand)
            candidates.append((cand, True))
    return _sort_candidates(candidates)


def _load_image(image_bytes: bytes) -> Image.Image:
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)  # 스마트폰 세로 촬영 회전 반영
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _compress_pil(img: Image.Image, sides=(2000, 1600, 1280)) -> bytes:
    """무료 키 업로드 제한(1MB)에 맞게 축소/재압축한 JPEG 바이트를 반환.

    번호 글자가 작게 찍힌 사진이 많아 해상도를 최대한 지키는 쪽을 우선한다:
    큰 변부터 시도하며 품질을 낮춰 1MB에 맞추고, 안 되면 한 단계 줄인다.
    (상단 크롭처럼 픽셀이 적은 이미지는 sides를 키워 더 높은 해상도로 보낸다)
    """
    buf = BytesIO()
    for side in sides:
        scaled = img.copy()
        scaled.thumbnail((side, side))
        for quality in (85, 75, 65, 55):
            buf = BytesIO()
            scaled.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= _MAX_UPLOAD_BYTES:
                return buf.getvalue()
    return buf.getvalue()  # 최저 단계도 넘으면 그대로 전송(서버가 거부하면 오류 안내)


def compress_image_for_ocr(image_bytes: bytes) -> bytes:
    """사진 바이트를 업로드 제한에 맞는 JPEG 바이트로 변환."""
    return _compress_pil(_load_image(image_bytes))


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
                "detectOrientation": "true",  # 기울거나 돌아간 사진 자동 보정
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


def _enhance_for_ocr(img: Image.Image) -> Image.Image:
    """저대비 사진(밝은 색 문 + 흰 글씨) 대비 강화: 흑백 + 자동 대비 + 대비 증폭."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2)
    return ImageEnhance.Contrast(gray).enhance(1.6).convert("RGB")


def recognize_container_numbers(image_bytes: bytes, api_key: str):
    """사진 바이트 → 압축 → OCR → 컨테이너 번호 후보.

    반환: (후보 목록, 실패한 시도의 오류 메시지 목록).
    모든 시도가 실패해 후보가 하나도 없으면 OcrError.

    컨테이너 번호는 문 상단에 찍히므로 각 회전 방향의 상단 40% 크롭을 먼저
    시도한다 — 크롭은 픽셀이 적어 같은 1MB 제한에서 더 높은 해상도로 보낼 수
    있어 작은 글자 인식률이 올라간다. 크롭에서 검증 통과 후보를 못 찾으면
    전체 이미지로, 그래도 없으면 대비 강화 크롭으로 재시도한다.

    속도를 위해 시도를 3개(회전 3방향)씩 병렬 호출한다: 한 단계의 소요 시간이
    호출 3번의 합이 아니라 가장 느린 1번 수준이 된다. 검증 통과 후보가 나오면
    다음 단계로 넘어가지 않고, 한 단계에서 호출이 2번 이상 실패하면(호출 제한
    등) 중단한다. (API 최대 9회, 보통 첫 단계 3회로 끝)
    """
    img = _load_image(image_bytes)
    candidates = []
    seen = set()
    errors = []

    def try_variant(angle, region, enhance):
        variant = img if angle == 0 else img.rotate(angle, expand=True)
        if region == "top":
            variant = variant.crop((0, 0, variant.width, int(variant.height * 0.4)))
            sides = (3000, 2400, 2000, 1600)  # 크롭은 픽셀이 적어 고해상도 허용
        else:
            sides = (2000, 1600, 1280)
        if enhance:
            variant = _enhance_for_ocr(variant)
        return extract_container_numbers(
            ocr_space_parse(_compress_pil(variant, sides), api_key))

    # 단계 순서: 상단 크롭 → 전체 → 대비강화 상단 크롭 (각 단계 = 회전 3방향 병렬)
    stages = [[(a, "top", False) for a in (0, 270, 90)],
              [(a, "full", False) for a in (0, 270, 90)],
              [(a, "top", True) for a in (0, 270, 90)]]
    for stage in stages:
        with ThreadPoolExecutor(max_workers=len(stage)) as pool:
            futures = [pool.submit(try_variant, *attempt) for attempt in stage]
            for future in futures:  # 제출 순서대로 수집해 후보 순서를 결정적으로 유지
                try:
                    found = future.result()
                except OcrError as e:
                    errors.append(str(e))
                    continue
                for cand in found:
                    if cand[0] not in seen:
                        seen.add(cand[0])
                        candidates.append(cand)
        if any(ok for _, ok in candidates):
            break  # 검증 통과 후보를 찾았으면 다음 단계 불필요
        if len(errors) >= 2:
            break  # 반복 실패 = 호출 제한에 걸렸을 가능성이 높아 중단
    if not candidates and errors:
        raise OcrError(errors[-1])
    return _sort_candidates(candidates), errors
