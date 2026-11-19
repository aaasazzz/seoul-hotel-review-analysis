# =============================================================
# 공통 도구 모음 — 크롤러들이 함께 쓰는 기능
#   - 닉네임 익명화
#   - 날짜 변환 (상대 날짜 포함)
#   - 한국어 판별
#   - CSV 저장 + 이어하기 (ReviewWriter)
#   - 수집 로그 기록
# =============================================================

import calendar
import csv
import hashlib
import os
import random
import re
import time
from datetime import date, datetime, timedelta

# 팀 공통 출력 스키마 (순서·이름 변경 금지)
FIELDNAMES = [
    "review_id",
    "platform",
    "hotel_name",
    "review_date",
    "rating",
    "rating_scale",
    "review_text_raw",
    "reviewer_id",
    "source_url",
]


class BlockedError(Exception):
    """사이트가 접속을 차단했을 때 발생시키는 오류. 이 오류가 나면 수집을 즉시 멈춘다."""


# -------------------------------------------------------------
# 대기
# -------------------------------------------------------------
def polite_sleep(min_sec, max_sec):
    """요청 사이에 랜덤으로 쉰다. (서버에 부담을 주지 않기 위해)"""
    time.sleep(random.uniform(min_sec, max_sec))


# -------------------------------------------------------------
# 익명화
# -------------------------------------------------------------
def anonymize(nickname):
    """닉네임을 SHA-256 해시 앞 16자리로 바꾼다. 닉네임 원문은 어디에도 저장하지 않는다."""
    if not nickname:
        return ""
    return hashlib.sha256(nickname.encode("utf-8")).hexdigest()[:16]


# -------------------------------------------------------------
# 언어 판별 (한국어 / 영어 / 기타)
# -------------------------------------------------------------
HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
ALPHABET = re.compile(r"[A-Za-z]")
LETTER = re.compile(r"[^\W\d_]")  # 숫자·기호·공백·이모지를 뺀 '글자'


def detect_language(text, korean_threshold, english_threshold):
    """글자 비율로 언어를 판별해 "ko" / "en" / "other" 중 하나를 돌려준다."""
    letters = LETTER.findall(text or "")
    if not letters:
        return "other"
    hangul = sum(1 for ch in letters if HANGUL.match(ch))
    alphabet = sum(1 for ch in letters if ALPHABET.match(ch))
    if hangul / len(letters) >= korean_threshold:
        return "ko"
    if alphabet / len(letters) >= english_threshold:
        return "en"
    return "other"


# -------------------------------------------------------------
# 날짜 변환
# -------------------------------------------------------------
# 한글 숫자 표기 ("한 달 전", "두 달 전" 등) 대응
KOREAN_NUMBERS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6,
                  "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}


def _months_ago(today, n):
    """today에서 n개월 전 날짜. (3월 31일의 1개월 전 → 2월 28/29일처럼 말일로 맞춤)"""
    year, month = today.year, today.month - n
    while month <= 0:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]  # 그 달의 마지막 날
    return date(year, month, min(today.day, last_day))


def parse_review_date(raw, today=None):
    """
    여러 형태의 날짜 표기를 YYYY-MM-DD로 바꾼다.
    반환값: (변환된 날짜 문자열 또는 None, 표기 종류)
      표기 종류: "absolute"(정확한 날짜) / "relative_exact"(오늘·N일 전 등)
                / "relative_approx"(N주·N개월·N년 전처럼 부정확) / "unknown"(변환 실패)
    """
    today = today or date.today()
    s = (raw or "").strip()
    if not s:
        return None, "unknown"

    # 1) 2024-10-14, 2024.10.14, 2024/10/14 (뒤에 요일·시간이 붙어도 됨)
    m = re.match(r"^(\d{4})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat(), "absolute"

    # 2) 24.10.14.월 (연도 두 자리 형식)
    m = re.match(r"^(\d{2})\.(\d{1,2})\.(\d{1,2})\.", s)
    if m:
        return date(2000 + int(m[1]), int(m[2]), int(m[3])).isoformat(), "absolute"

    # 3) 10.14.월 (연도 없음 → 올해. 올해로 치면 미래가 되면 작년으로)
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.", s)
    if m:
        d = date(today.year, int(m[1]), int(m[2]))
        if d > today:
            d = date(today.year - 1, int(m[1]), int(m[2]))
        return d.isoformat(), "absolute"

    # 4) 상대 날짜
    if s in ("오늘", "방금", "방금 전") or re.search(r"\d+\s*(초|분|시간)\s*전", s):
        return today.isoformat(), "relative_exact"
    if s == "어제":
        return (today - timedelta(days=1)).isoformat(), "relative_exact"

    m = re.search(r"(\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(일|주|달|개월|년)\s*전", s)
    if m:
        n = int(m[1]) if m[1].isdigit() else KOREAN_NUMBERS[m[1]]
        unit = m[2]
        if unit == "일":
            return (today - timedelta(days=n)).isoformat(), "relative_exact"
        if unit == "주":
            return (today - timedelta(weeks=n)).isoformat(), "relative_approx"
        if unit in ("달", "개월"):
            return _months_ago(today, n).isoformat(), "relative_approx"
        if unit == "년":
            return _months_ago(today, 12 * n).isoformat(), "relative_approx"

    # 5) ISO 형식 (2024-10-14T12:34:56+09:00 등)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat(), "absolute"
    except ValueError:
        pass

    return None, "unknown"


# -------------------------------------------------------------
# 주소 비교 (검색으로 열린 장소가 대상 호텔이 맞는지 확인할 때 사용)
# -------------------------------------------------------------
def address_key(address):
    """공식 주소에서 '도로명 + 건물번호'만 뽑는다. 예: '서울특별시 중구 동호로 249' → '동호로249'"""
    m = re.search(r"(\S+(?:로|길))\s*(\d+(?:-\d+)?)", address or "")
    return (m.group(1) + m.group(2)) if m else ""


def address_matches(road_key, page_address):
    """
    구글 주소가 공식 주소와 같은 곳인지 판단한다.
      - '동호로249'가 그대로 들어 있으면 일치
      - 순서가 뒤집혀 있어도('26_H,백현로,분당구…') 도로명과 건물번호가 둘 다 있으면 일치
    같은 도로의 다른 건물(번호가 다름)은 일치로 보지 않는다.
    """
    if re.search(re.escape(road_key) + r"(?![\d-])", page_address):  # 번호 뒤에 숫자가 더 붙으면 다른 번지
        return True
    m = re.match(r"^(.*?(?:로|길))(\d+(?:-\d+)?)$", road_key)
    if not m:
        return False
    road, number = m.groups()
    return road in page_address and re.search(rf"(?<![\d-]){re.escape(number)}(?![\d-])", page_address) is not None


def _append_csv(path, fieldnames, row):
    """CSV 파일 끝에 한 줄을 덧붙인다. 파일이 없으면 헤더부터 쓴다."""
    is_new = not os.path.exists(path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


class DateExpressionLogger:
    """상대 날짜 표기("3개월 전" 등)를 date_expression_log.csv에 기록한다. 같은 표기는 실행당 1번만."""

    FIELDS = ["run_date", "platform", "hotel_name", "raw_expression", "converted", "kind"]

    def __init__(self, path, platform):
        self.path = path
        self.platform = platform
        self.seen = set()

    def log(self, hotel_name, raw, converted, kind):
        if kind == "absolute":
            return
        key = (hotel_name, raw)
        if key in self.seen:
            return
        self.seen.add(key)
        _append_csv(self.path, self.FIELDS, {
            "run_date": date.today().isoformat(),
            "platform": self.platform,
            "hotel_name": hotel_name,
            "raw_expression": raw,
            "converted": converted or "",
            "kind": kind,
        })


# -------------------------------------------------------------
# 리뷰 저장 + 이어하기
# -------------------------------------------------------------
class ReviewWriter:
    """
    리뷰를 한 줄씩 CSV에 append 한다.
    - 한국어 리뷰는 csv_path, 영어 리뷰는 english_csv_path에 저장한다.
      (일련번호는 두 파일이 함께 이어서 매김 → review_id가 겹치지 않음)
    - 이미 저장된 리뷰는 건너뛸 수 있도록, 플랫폼 내부 리뷰 ID를 별도 파일(seen 파일)에 기록한다.
      (팀 공통 스키마를 바꾸지 않기 위해 따로 저장)
    - 재실행하면 기존 CSV에서 가장 큰 일련번호를 찾아 그 다음 번호부터 매긴다.
    """

    SEEN_FIELDS = ["review_id", "platform_review_key"]

    def __init__(self, csv_path, english_csv_path, seen_path, platform_code, initial):
        self.csv_path = csv_path
        self.english_csv_path = english_csv_path
        self.seen_path = seen_path
        self.prefix = f"{platform_code}_{initial}_"
        self.seen_keys = set()
        self.last_serial = 0

        # 기존 리뷰 CSV(한국어·영어 둘 다)에서 마지막 일련번호 찾기
        for path in (csv_path, english_csv_path):
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    rid = row.get("review_id", "")
                    if rid.startswith(self.prefix):
                        self.last_serial = max(self.last_serial, int(rid[len(self.prefix):]))

        # 이미 수집한 플랫폼 리뷰 ID 불러오기
        # (제외·삭제된 리뷰의 번호도 여기 남아 있으므로, 일련번호는 이 파일까지 보고 이어서 매긴다 → 번호 재사용 방지)
        if os.path.exists(seen_path):
            with open(seen_path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    self.seen_keys.add(row["platform_review_key"])
                    rid = row.get("review_id", "")
                    if rid.startswith(self.prefix):
                        self.last_serial = max(self.last_serial, int(rid[len(self.prefix):]))

    def is_seen(self, key):
        return key in self.seen_keys

    def next_review_id(self):
        """다음에 쓸 review_id (아직 확정 아님 — write() 할 때 확정)"""
        return f"{self.prefix}{self.last_serial + 1:06d}"

    def write(self, row, key, english=False):
        """리뷰 1건 저장. row의 review_id는 next_review_id()로 받은 값이어야 한다."""
        assert row["review_id"] == self.next_review_id()
        _append_csv(self.english_csv_path if english else self.csv_path, FIELDNAMES, row)
        _append_csv(self.seen_path, self.SEEN_FIELDS,
                    {"review_id": row["review_id"], "platform_review_key": key})
        self.seen_keys.add(key)
        self.last_serial += 1


# -------------------------------------------------------------
# 수집 로그 (발표 자료용)
# -------------------------------------------------------------
COLLECT_LOG_FIELDS = ["날짜", "담당", "플랫폼", "호텔명", "수집건수",
                      "영어_수집건수", "제외_기타언어", "제외_타사이트", "제외_빈본문", "제외_중복", "제외_기간", "비고"]


def append_collect_log(path, initial, platform, hotel_name, counts, note=""):
    _append_csv(path, COLLECT_LOG_FIELDS, {
        "날짜": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "담당": initial,
        "플랫폼": platform,
        "호텔명": hotel_name,
        "수집건수": counts.get("saved", 0),
        "영어_수집건수": counts.get("english", 0),
        "제외_기타언어": counts.get("other_language", 0),
        "제외_타사이트": counts.get("other_source", 0),
        "제외_빈본문": counts.get("empty", 0),
        "제외_중복": counts.get("duplicate", 0),
        "제외_기간": counts.get("too_old", 0),
        "비고": note,
    })
