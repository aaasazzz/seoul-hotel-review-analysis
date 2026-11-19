# =============================================================
# Apify 구글맵 리뷰 결과 → 팀 공통 스키마로 변환
#
# 사용 도구: Apify "Google Maps Reviews Scraper" (compass/Google-Maps-Reviews-Scraper)
#   - 입력값: apify/google_step1_test_shilla.json  (신라호텔 시험용)
#             apify/google_step2_full_61.json      (61곳 본 수집)
#   - Apify 웹 콘솔에서 실행하고, 결과를 JSON으로 내려받아
#     apify/results/google/ 폴더에 넣는다
#
# 실행:  python import_apify_google.py                 → apify/results/google/*.json 전부 변환
#        python import_apify_google.py 파일.json        → 지정한 파일만 변환
#
# 하는 일
#   1) 장소 주소를 hotels.csv의 공식 주소와 비교해 '대상 5성급 호텔'이 맞는지 확인
#   2) 리뷰마다 언어 확인 → 원문이 한국어면 google_map_reviews.csv, 영어면 _en.csv, 그 외 언어는 제외
#      (구글 자동 번역문 textTranslated는 쓰지 않고, 원문 text만 저장)
#   3) 기존 크롤러(crawl_google.py)로 모은 리뷰와 겹치면 건너뜀 (google_map_seen.csv의 구글 리뷰 ID로 확인)
#      → review_id는 기존 GM_DH_ 번호 다음부터 이어서 매김
#   4) 작성자 닉네임은 해시로만 저장하고, 변환이 끝나면 원본 JSON에서도 개인정보 칸을 지운다
#   5) 사장님 답글(responseFromOwnerText)은 본문에 넣지 않는다
# =============================================================

import csv
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import config
from common import (
    DateExpressionLogger,
    ReviewWriter,
    address_key,
    address_matches,
    anonymize,
    append_collect_log,
    detect_language,
)

PLATFORM_NAME = "구글맵"
PLATFORM_CODE = "GM"
SOURCE_NOTE = "Apify(compass/Google-Maps-Reviews-Scraper) 이용"

# 기존 크롤러와 같은 파일에 이어서 저장한다 (번호·중복 확인을 함께 하기 위해)
REVIEW_CSV = os.path.join(config.OUTPUT_DIR, "google_map_reviews.csv")         # 한국어 리뷰
ENGLISH_CSV = os.path.join(config.OUTPUT_DIR, "google_map_reviews_en.csv")     # 영어 리뷰 (별도 보관)
SEEN_CSV = os.path.join(config.OUTPUT_DIR, "google_map_seen.csv")              # 이미 저장한 구글 리뷰 ID
RESULT_DIR = os.path.join("apify", "results", "google")

# 원본 JSON에서 지울 개인정보 칸 (작성자 이름·프로필·사진, 리뷰 주소에 작성자 ID가 들어 있음)
PERSONAL_FIELDS = ["name", "reviewerId", "reviewerUrl", "reviewerPhotoUrl", "reviewUrl"]

# 같은 건물에 다른 호텔이 있을 때 걸러 내는 말 (장소 이름에 있는데 대상 호텔 이름에는 없으면 다른 호텔)
OTHER_BRAND_WORDS = [("스위트", "suites"), ("머큐어", "mercure"), ("이비스", "ibis")]

KST = timezone(timedelta(hours=9))   # 구글 날짜는 세계 표준시(UTC)로 오므로 한국 시간으로 바꿔서 날짜를 정한다


def normalize(text):
    return re.sub(r"[\s()\-·.,&']", "", (text or "")).lower()


# -------------------------------------------------------------
# 1. 장소 → 대상 호텔 매칭
# -------------------------------------------------------------
def match_hotel(place, hotels):
    """장소 정보(이름·주소)로 hotels.csv의 어느 호텔인지 찾는다. 못 찾으면 (None, 이유)."""
    name = place.get("title") or ""
    # '청파로20길 95 1F'처럼 층 표시가 붙으면 공백을 지웠을 때 '951F'가 되어 번지가 달라 보이므로 층 표시를 먼저 뺀다
    address = re.sub(r"(?<=\s)B?\d+\s*(?:F|층)(?=\s|$)", "", place.get("address") or "")
    address = re.sub(r"\s+", "", address)

    candidates = []
    for h in hotels:
        # 공식 주소의 '도로명+번호', 또는 구글 주소가 다르게 적힌 호텔은 직접 확인해 둔 값(google_address_key)
        keys = [k for k in (address_key(h["address"]), re.sub(r"\s+", "", h.get("google_address_key", ""))) if k]
        if any(address_matches(k, address) for k in keys):
            candidates.append(h)

    def name_fits(h):
        # 같은 건물에 호텔이 여럿이라 이름으로 확인하는 곳 (예: 노보텔 용산 ↔ 같은 건물의 머큐어·이비스)
        names = [h.get("google_name_key", ""), h["search_name"], h["official_name"]]
        return any(normalize(n) and normalize(n) in normalize(name) for n in names)

    if len(candidates) > 1:
        candidates = [h for h in candidates if name_fits(h)] or candidates
    if len(candidates) > 1:
        return None, f"'{name}' — 같은 주소의 대상 호텔이 여러 곳이라 구분 불가"
    if not candidates:
        return None, f"'{name}'({address[:30]})이(가) 대상 호텔 목록에 없음"

    hotel = candidates[0]
    if hotel.get("google_name_key") and not name_fits(hotel):
        return None, f"'{name}'의 이름이 '{hotel['google_name_key']}'와 달라 같은 건물의 다른 호텔로 보임"
    target = f"{hotel['search_name']} {hotel['official_name']}".lower()
    for words in OTHER_BRAND_WORDS:
        if any(w in name.lower() for w in words) and not any(w in target for w in words):
            return None, f"'{name}'은(는) '{hotel['search_name']}'와 같은 건물의 다른 호텔로 보임"
    return hotel, ""


# -------------------------------------------------------------
# 2. 리뷰 1건 변환
# -------------------------------------------------------------
def review_language(item, text):
    """
    리뷰 원문의 언어를 "ko" / "en" / "other"로 돌려준다.
    구글이 알려 주는 원문 언어(originalLanguage)와 본문 글자 비율이 **둘 다** 맞아야 그 언어로 본다.
      - 구글 표시는 한국어인데 본문이 영어인 경우가 있었다 (2차 수집에서 1건) → 본문 기준
      - 구글 표시는 일본어인데 본문에 한글이 섞인 경우는 여러 언어를 함께 쓴 글이었다 (3건) → 기타 언어
    """
    lang = detect_language(text, config.KOREAN_RATIO_THRESHOLD, config.ENGLISH_RATIO_THRESHOLD)
    original = (item.get("originalLanguage") or "").lower()
    if not original or lang == "other":     # 구글 표시가 없거나, 이모지·기호뿐인 글
        return lang
    if original.startswith("ko"):
        return "ko" if lang == "ko" else lang
    if original.startswith("en"):
        return "en" if lang == "en" else "other"
    return "other"


def korean_date(published_at):
    """'2026-10-14T16:52:42.414Z'(UTC) → 한국 시간 기준 날짜 '2026-10-15'"""
    if not published_at:
        return ""
    moment = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return moment.astimezone(KST).date().isoformat()


def handle_review(item, hotel_name, source_url, writer, date_logger, counts):
    if (item.get("reviewOrigin") or "Google") != "Google":
        counts["other_source"] += 1          # 트립닷컴 등 다른 사이트에서 가져온 리뷰
        return
    key = str(item.get("reviewId") or "")
    if not key or writer.is_seen(key):
        counts["duplicate"] += 1             # 기존 크롤러로 이미 모은 리뷰 포함
        return
    text = item.get("text") or ""            # 원문 (자동 번역문은 textTranslated 칸에 따로 옴 → 쓰지 않음)
    if not text.strip():
        counts["empty"] += 1                 # 별점만 남긴 리뷰
        return
    language = review_language(item, text)
    if language == "other" or (config.KOREAN_ONLY and language != "ko"):
        counts["other_language"] += 1
        return

    # 화면에는 "3개월 전"처럼 나오지만(publishAt), 정확한 작성 시각(publishedAtDate)을 쓴다
    review_date = korean_date(item.get("publishedAtDate"))
    if not review_date:
        date_logger.log(hotel_name, item.get("publishAt") or "", "", "unknown")
    if config.REVIEW_SINCE and review_date and review_date < config.REVIEW_SINCE:
        counts["too_old"] += 1               # 기준일(config.REVIEW_SINCE, 2025-01-01)보다 오래된 리뷰
        return

    rating = item.get("stars")
    review_id = writer.next_review_id()

    writer.write({
        "review_id": review_id,
        "platform": PLATFORM_NAME,
        "hotel_name": hotel_name,
        "review_date": review_date,
        "rating": float(rating) if rating is not None else "",
        "rating_scale": 5 if rating is not None else "",
        "review_text_raw": text,                                   # 사장님 답글은 넣지 않음
        "reviewer_id": anonymize(item.get("name") or ""),
        "source_url": source_url,
    }, key, english=(language == "en"))
    counts["english" if language == "en" else "saved"] += 1


def place_url(item):
    """입력에 넣은 장소 주소 (기존 크롤러 결과의 source_url과 같은 형식)"""
    search = item.get("searchString") or ""
    if search.startswith("Direct Detail URL:"):
        return search.split(":", 1)[1].strip()
    return item.get("url") or ""


# -------------------------------------------------------------
# 3. 원본 JSON에서 개인정보 칸 지우기
# -------------------------------------------------------------
def strip_personal_data(path, items):
    for item in items:
        for k in PERSONAL_FIELDS:
            item.pop(k, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def load_items(path):
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]   # JSON Lines


# -------------------------------------------------------------
# 4. 전체 실행
# -------------------------------------------------------------
def main():
    files = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(glob.glob(os.path.join(RESULT_DIR, "*.json")))
    if not files:
        sys.exit(f"변환할 파일이 없습니다. Apify 결과(JSON)를 {RESULT_DIR}/ 에 넣어 주세요.")

    with open(config.HOTELS_FILE, encoding="utf-8-sig", newline="") as f:
        hotels = list(csv.DictReader(f))
    writer = ReviewWriter(REVIEW_CSV, ENGLISH_CSV, SEEN_CSV, PLATFORM_CODE, config.COLLECTOR_INITIAL)
    date_logger = DateExpressionLogger(config.DATE_LOG_FILE, PLATFORM_NAME)
    print(f"변환 시작 — 파일 {len(files)}개, 다음 review_id: {writer.next_review_id()}")

    for path in files:
        items = load_items(path)
        print(f"\n[{os.path.basename(path)}] 리뷰 {len(items)}건")

        # 장소별로 묶기 (fid = 구글 장소 고유 번호)
        places = {}
        for item in items:
            places.setdefault(item.get("fid") or item.get("placeId") or "?", []).append(item)

        for place_items in places.values():
            first = place_items[0]
            name = first.get("title") or "?"
            hotel, why = match_hotel(first, hotels)
            counts = {"saved": 0, "english": 0, "other_language": 0, "other_source": 0, "empty": 0, "duplicate": 0, "too_old": 0}
            if hotel is None:
                print(f"  !! 제외: {why} ({len(place_items)}건)")
                append_collect_log(config.COLLECT_LOG_FILE, config.COLLECTOR_INITIAL, PLATFORM_NAME,
                                   name, counts, f"{SOURCE_NOTE} / 대상 아님으로 제외: {why}")
                continue
            source_url = place_url(first)
            for item in place_items:
                handle_review(item, name, source_url, writer, date_logger, counts)
            print(f"  {hotel['search_name']} ← '{name}': 한국어 {counts['saved']} / 영어 {counts['english']} "
                  f"(제외: 다른 사이트 {counts['other_source']}, 기타 언어 {counts['other_language']}, "
                  f"별점만 {counts['empty']}, 중복 {counts['duplicate']}, 기준일 이전 {counts['too_old']})")
            append_collect_log(config.COLLECT_LOG_FILE, config.COLLECTOR_INITIAL, PLATFORM_NAME,
                               hotel["search_name"], counts, f"{SOURCE_NOTE} / 구글 장소명: {name}")

        strip_personal_data(path, items)
        print(f"  원본 파일의 개인정보 칸({', '.join(PERSONAL_FIELDS)})을 지웠습니다.")

    print(f"\n완료. 결과 파일: {REVIEW_CSV}")


if __name__ == "__main__":
    main()
