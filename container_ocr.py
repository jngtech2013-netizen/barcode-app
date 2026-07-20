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


def _coerce_window(window: str, max_owner_fixes: int = 4):
    """11자 알파넘 조각을 '영문4+숫자7' 형태로 위치별 보정. 불가능하면 None.

    max_owner_fixes: 앞 4자리(영문 자리)에서 허용하는 숫자→영문 보정 개수.
    실제 소유자코드는 영문으로 찍혀 있어 보정이 거의 필요 없으므로, 신뢰가
    낮은 짜맞춤 후보는 1로 제한해 숫자 나열을 통째로 영문화한 가짜를 막는다.

    화물 컨테이너의 카테고리 문자(4번째 글자)는 ISO 6346상 항상 U이므로
    4번째 글자가 U가 아니면 후보에서 제외한다 — 단위 표기 조각(LB/KG,
    CU.CAP 등)이 숫자와 이어붙어 체크디지트를 우연히 통과하는 가짜
    (CAPB8114561, LBKG1828800 같은 실사진 오탐)를 구조적으로 막는다.
    """
    out = []
    owner_fixes = 0
    for i, ch in enumerate(window):
        if i < 4:
            if ch.isdigit():
                owner_fixes += 1
                if owner_fixes > max_owner_fixes:
                    return None
                ch = _DIGIT_TO_LETTER.get(ch)
        else:
            if ch.isalpha():
                ch = _LETTER_TO_DIGIT.get(ch)
        if ch is None:
            return None
        out.append(ch)
    if out[3] != "U":
        return None
    return "".join(out)


def _sort_candidates(candidates: list) -> list:
    """체크디지트가 맞는 후보를 앞에, 그중 4번째 글자가 U(일반 화물용 컨테이너의
    카테고리 문자)인 것을 가장 앞에 둔다."""
    return sorted(candidates, key=lambda c: (not c[1], c[0][3] != "U"))


def _extract_split(text: str):
    """OCR 텍스트에서 후보를 '직접(한 줄에서 이어 읽힘)'과 '짜맞춤(줄 결합·토큰
    조합)'으로 나눠 추출한다.

    반환: (직접 후보 목록, 짜맞춤 후보 목록). 각 항목은 (번호, 체크디지트_일치여부).
    짜맞춤 후보는 사진에 그대로 이어 찍혀 있지 않은 번호를 만들어내는 방식이라
    우연히 체크디지트를 통과하는 오탐(약 10%/조합)이 가능하다 — 호출 측에서
    직접 후보 중 검증 통과가 있으면 짜맞춤 후보를 버리는 식으로 써야 한다.
    """
    if not text:
        return [], []
    # 컨테이너 번호는 'CSQU 305438 3'처럼 띄어 찍히는 일이 많아 줄 단위로
    # 구분자만 제거해 이어붙인 뒤 11자 슬라이딩 윈도우로 훑는다.
    lines = [re.sub(r"[^A-Z0-9]", "", ln) for ln in text.upper().splitlines()]
    lines = [ln for ln in lines if ln]
    candidates = []   # 한 줄 안에서 이어 읽힌 후보 (가장 신뢰)
    assembled = []    # 줄 결합·토큰 조합으로 짜맞춘 후보 (예비)
    seen = set()

    def scan(seq, out, max_owner_fixes=4):
        for start in range(len(seq) - 10):
            coerced = _coerce_window(seq[start:start + 11], max_owner_fixes)
            if coerced and coerced not in seen:
                seen.add(coerced)
                out.append((coerced, is_valid_check_digit(coerced)))

    for ln in lines:
        # 실제 소유자코드가 4자 모두 숫자로 오인식되는 일은 없다시피 하므로
        # 보정은 2자까지만 — 숫자 나열(무게 등)을 통째로 영문화한 가짜를 막는다
        scan(ln, candidates, max_owner_fixes=2)
    # 소유자코드/일련번호가 여러 조각(HLHU / 8376 / 88 / 1)으로 나뉘어 읽히는
    # 일이 많아, 인접한 줄들을 순서대로 이어붙이며 훑는다. 11자(영문4+숫자7)가
    # 완성될 만큼 모이면 그 즉시 멈춘다 — 더 이어붙이면 무관한 표기(45G1 등)까지
    # 끌려 들어와 가짜 후보만 늘기 때문. 잘못 이어진 조합에서 나온 가짜 번호가
    # 체크디지트를 우연히 통과할 수 있어 짜맞춤(예비) 후보로 분류한다.
    for i, ln in enumerate(lines):
        joined = ln[-10:]  # 줄 경계를 걸치는 윈도우에는 앞줄의 끝 10자만 관여
        appended = False
        for nxt in lines[i + 1:]:
            if len(joined) >= 11:
                break
            joined += nxt
            appended = True
        if appended and len(joined) >= 11:
            scan(joined, assembled, max_owner_fixes=1)

    # 실제 문짝 표기는 소유자코드(HDFU)·일련번호(528056)·체크디지트(6)가 서로
    # 떨어져 있어 OCR 줄 순서상 인접하지 않게 읽히는 일이 많다. 텍스트 전체에서
    # 4글자 토큰 × 6~7자리 숫자 (× 단독 한 자리 숫자) 조합을 만들어 체크디지트로
    # 검증한다 — 우연히 맞을 확률이 낮아 검증을 통과한 조합만 후보로 삼는다.
    owners, digit7, digit6, digit1 = [], [], [], []
    for ln in lines:
        for run in re.findall(r"[A-Z0-9]+", ln):
            # 소유자코드 후보도 같은 이유로 숫자→영문 보정을 1자까지만 허용하고
            # 카테고리 문자 U(4번째 글자)가 아니면 제외한다
            if len(run) == 4 and sum(c.isdigit() for c in run) <= 1:
                coerced = "".join(_DIGIT_TO_LETTER.get(c, c if c.isalpha() else "?")
                                  for c in run)
                if "?" not in coerced and coerced[3] == "U":
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
            assembled.append((cand, True))

    # 열 단위 읽힘 대응: OCR이 사진을 열로 훑으면 소유자코드/일련번호 조각
    # (HLHU / 8376) 뒤에 라벨 줄(MAX. GROSS 등)이 끼고 나머지 조각(88 11)이
    # 한참 아래에 나온다. 소유자코드 바로 아랫줄이 숫자로 시작하면 이후의
    # '순수 숫자 줄'만 순서대로 이어붙여 7자리(일련번호6+체크디지트)를 만든다.
    # - 글자가 섞인 줄('3 KL', '8,160 LB.')의 숫자는 조각으로 신뢰하지 않는다
    # - 마지막 조각은 필요한 자릿수만 앞에서 취한다(체크디지트 상자가 '11'처럼
    #   겹쳐 읽히는 경우 대비)
    # - 번호 블록의 끝을 뜻하는 규격코드(45G1 등)를 만나면 중단한다
    # 체크디지트 검증을 통과해야만 후보가 된다.
    for i, ln in enumerate(lines[:-1]):
        if not (len(ln) == 4 and ln.isalpha() and ln[3] == "U"):
            continue
        if not lines[i + 1][:1].isdigit():
            continue
        serial = ""
        for later in lines[i + 1:]:
            if re.fullmatch(r"\d{2}[A-Z]\d", later):  # 45G1 같은 규격코드
                break
            if not later.isdigit():
                continue
            serial += later[:7 - len(serial)]
            if len(serial) >= 7:
                break
        cand = ln + serial
        if len(serial) == 7 and cand not in seen and is_valid_check_digit(cand):
            seen.add(cand)
            assembled.append((cand, True))
    return candidates, assembled


def extract_container_numbers(text: str) -> list:
    """OCR 텍스트에서 컨테이너 번호 후보를 추출한다.

    반환: (컨테이너번호, 체크디지트_일치여부) 튜플 목록 (체크디지트 일치 우선 정렬).
    한 줄에서 그대로 이어 읽힌 후보 중 검증 통과가 있으면 그것만 쓰고, 없을
    때만 흩어진 문짝 표기용 짜맞춤 후보를 예비로 포함한다.
    """
    direct, assembled = _extract_split(text)
    if any(ok for _, ok in direct):
        return _sort_candidates(direct)
    return _sort_candidates(direct + assembled)


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

    반환: (후보 목록, 실패한 시도의 오류 메시지 목록, OCR 원문 텍스트 목록).
    원문 텍스트는 인식 실패 시 원인 파악(디버그 표시)용이다.
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
    direct_cands, assembled_cands = [], []
    seen_d, seen_a = set(), set()
    errors = []
    texts = []

    def try_variant(angle, region, enhance):
        variant = img if angle == 0 else img.rotate(angle, expand=True)
        if region == "top":
            variant = variant.crop((0, 0, variant.width, int(variant.height * 0.4)))
            sides = (3000, 2400, 2000, 1600)  # 크롭은 픽셀이 적어 고해상도 허용
        else:
            sides = (2000, 1600, 1280)
        if enhance:
            variant = _enhance_for_ocr(variant)
        text = ocr_space_parse(_compress_pil(variant, sides), api_key)
        return _extract_split(text), text

    # 단계 순서: 상단 크롭 → 전체 → 대비강화 상단 크롭 (각 단계 = 회전 3방향 병렬)
    stages = [[(a, "top", False) for a in (0, 270, 90)],
              [(a, "full", False) for a in (0, 270, 90)],
              [(a, "top", True) for a in (0, 270, 90)]]
    for stage in stages:
        with ThreadPoolExecutor(max_workers=len(stage)) as pool:
            futures = [pool.submit(try_variant, *attempt) for attempt in stage]
            for future in futures:  # 제출 순서대로 수집해 후보 순서를 결정적으로 유지
                try:
                    (direct, assembled), text = future.result()
                except OcrError as e:
                    errors.append(str(e))
                    continue
                if text.strip():
                    texts.append(text)
                for cand in direct:
                    if cand[0] not in seen_d:
                        seen_d.add(cand[0])
                        direct_cands.append(cand)
                for cand in assembled:
                    if cand[0] not in seen_a:
                        seen_a.add(cand[0])
                        assembled_cands.append(cand)
        if any(ok for _, ok in direct_cands + assembled_cands):
            break  # 검증 통과 후보를 찾았으면 다음 단계 불필요
        if len(errors) >= 2:
            break  # 반복 실패 = 호출 제한에 걸렸을 가능성이 높아 중단

    # 한 줄에서 그대로 이어 읽힌 검증 통과 후보가 있으면 그것만 신뢰한다.
    # 줄 결합·토큰 조합으로 짜맞춘 후보는 흩어진 문짝 표기용 예비 수단으로,
    # 우연히 체크디지트를 통과한 가짜 번호가 실제 번호와 나란히 화면에
    # 노출되는 것을 막는다.
    if any(ok for _, ok in direct_cands):
        candidates = direct_cands
    else:
        candidates = direct_cands + [c for c in assembled_cands if c[0] not in seen_d]
    if not candidates and errors:
        raise OcrError(errors[-1])
    return _sort_candidates(candidates), errors, texts
