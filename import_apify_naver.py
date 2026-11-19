# =============================================================
# Apify 네이버지도 리뷰 결과 → 팀 공통 스키마로 변환
#
# 사용 도구: Apify "Naver Maps Reviews Scraper" (hgservices/naver-maps-reviews-scraper)
#   - 입력값: apify/naver_step1_test_shilla.json   (신라호텔 시험용)
#             apify/naver_step2_place_check.json   (61곳 장소 확인)
#             apify/naver_step3_full_by_ids.json   (61곳 본 수집, apify_make_full_input.py가 만듦)
#   - Apify에서 실행 후 결과를 JSON으로 내려받아 apify/results/naver/ 폴더에 넣는다
#     (구글 결과는 apify/results/google/ — 섞이지 않게 폴더를 나눔)
#
# 실행:  python import_apify_naver.py                 → apify/results/naver/*.json 전부 변환
#        python import_apify_naver.py 파일.json        → 지정한 파일만 변환
#
# 하는 일
#   1) 장소마다 주소를 hotels.csv의 공식 주소와 비교해 '대상 5성급 호텔'이 맞는지 확인
#      (같은 건물에 호텔이 여러 개면 이름으로 구분, 아니면 제외하고 로그에 기록)
#   2) 방문자 리뷰만 사용 (블로그·카페 글은 네이버블로그 담당 팀원 몫이라 제외)
#   3) 리뷰마다 중복·빈 본문·언어 검사 → 한국어는 naver_map_reviews.csv, 영어는 _en.csv
#   4) 작성자 닉네임은 해시로만 저장하고, 변환이 끝나면 원본 JSON에서도 개인정보 칸을 지운다
#   5) 사장님 답글(ownerReply)은 본문에 넣지 않는다
# =============================================================

import csv
import glob
import json
import os
import re
import sys

import config
from common import (
    DateExpressionLogger,
    ReviewWriter,
    address_key,
    address_matches,
    anonymize,
    append_collect_log,
    detect_language,
    parse_review_date,
)

PLATFORM_NAME = "네이버지도"
PLATFORM_CODE = "NM"
SOURCE_NOTE = "Apify(hgservices/naver-maps-reviews-scraper) 이용"

REVIEW_CSV = os.path.join(config.OUTPUT_DIR, "naver_map_reviews.csv")        # 한국어 리뷰
ENGLISH_CSV = os.path.join(config.OUTPUT_DIR, "naver_map_reviews_en.csv")    # 영어 리뷰 (별도 보관)
SEEN_CSV = os.path.join(config.OUTPUT_DIR, "naver_map_seen.csv")             # 이어하기용 (네이버 리뷰 ID)
RESULT_DIR = os.path.join("apify", "results", "naver")

# 원본 JSON에서 지울 개인정보 칸
PERSONAL_FIELDS = ["reviewerName", "reviewerProfileUrl", "reviewerImageUrl", "blogName"]

# 같은 건물·같은 주소에 다른 호텔이 있을 때 걸러 내는 말 묶음
# (장소 이름에 있는데 매칭된 대상 호텔 이름에는 없으면 다른 호텔로 봄. 예: 노보텔 ↔ 노보텔 스위트·그랜드 머큐어)
OTHER_BRAND_WORDS = [("스위트", "suites"), ("머큐어", "mercure"), ("이비스", "ibis")]


def pick(item, *keys):
    """여러 이름 후보 중 값이 있는 첫 번째 칸을 돌려준다 (도구 버전에 따라 칸 이름이 다를 수 있어서)"""
    for k in keys:
        v = item.get(k)
        if v not in (None, "", []):
            return v
    return None


def normalize(text):
    return re.sub(r"[\s()\-·.,&']", "", (text or "")).lower()


# -------------------------------------------------------------
# 1. 장소 → 대상 호텔 매칭
# -------------------------------------------------------------
def match_hotel(place, hotels):
    """장소 정보(이름·주소)로 hotels.csv의 어느 호텔인지 찾는다. 못 찾으면 (None, 이유)."""
    name = pick(place, "placeName", "name") or ""
    address = re.sub(r"\s+", "", f"{pick(place, 'roadAddress') or ''} {pick(place, 'address') or ''}")

    hotel, why = _match_by_address_or_name(name, address, hotels)
    if hotel is None:
        return None, why
    target = f"{hotel['search_name']} {hotel['official_name']}".lower()
    for words in OTHER_BRAND_WORDS:
        if any(w in name.lower() for w in words) and not any(w in target for w in words):
            return None, f"'{name}'은(는) '{hotel['search_name']}'와 같은 건물의 다른 호텔로 보임"
    return hotel, why


def _match_by_address_or_name(name, address, hotels):
    by_address = [h for h in hotels
                  if address_key(h["address"]) and address_matches(address_key(h["address"]), address)]
    if len(by_address) == 1:
        return by_address[0], ""
    if len(by_address) > 1:
        # 같은 주소에 대상 호텔이 여럿 (예: 그랜드 워커힐 / 비스타 워커힐, 서울드래곤시티의 노보텔 / 노보텔 스위트)
        # → 호텔 이름의 낱말이 장소 이름에 많이 들어 있고, 빠진 낱말은 적은 쪽
        #   (예: 장소 '노보텔 앰배서더 서울 용산'은 '노보텔 스위트 …'의 '스위트'가 빠져 있으므로 노보텔 쪽)
        def overlap(h):
            words = h["search_name"].split()
            hit = sum(1 for t in words if normalize(t) in normalize(name))
            return hit - (len(words) - hit)
        best = sorted(by_address, key=overlap, reverse=True)
        if overlap(best[0]) > overlap(best[1]):
            return best[0], ""
        return None, f"'{name}' — 같은 주소의 대상 호텔이 여러 곳이라 구분 불가"

    # 주소가 안 맞으면 이름이 거의 같은 경우만 인정
    for h in hotels:
        if normalize(h["search_name"]) and normalize(h["search_name"]) in normalize(name):
            return h, "주소 표기가 달라 이름으로 확인"
    return None, f"'{name}'({address[:30]})이(가) 대상 호텔 목록에 없음"


# -------------------------------------------------------------
# 2. 리뷰 1건 변환
# -------------------------------------------------------------
def handle_review(item, hotel_name, writer, date_logger, counts):
    if (pick(item, "reviewSource") or "visitor") != "visitor":
        counts["other_source"] += 1          # 블로그·카페 글
        return
    key = str(pick(item, "reviewId", "id") or "")
    if not key or writer.is_seen(key):
        counts["duplicate"] += 1
        return
    text = pick(item, "text", "body") or ""
    if not text.strip():
        counts["empty"] += 1
        return
    # 번역문이 따로 오는 경우 원문을 우선 사용 (칸이 없으면 그대로)
    original = pick(item, "originalText", "textOriginal")
    if original:
        text = original
    language = detect_language(text, config.KOREAN_RATIO_THRESHOLD, config.ENGLISH_RATIO_THRESHOLD)
    item_lang = pick(item, "language", "lang")
    if item_lang and str(item_lang).lower() not in ("ko", "en", "kor", "eng"):
        language = "other"
    if language == "other" or (config.KOREAN_ONLY and language != "ko"):
        counts["other_language"] += 1
        return

    date_raw = str(pick(item, "createdDate", "created", "date") or "")
    review_date, kind = parse_review_date(date_raw)
    date_logger.log(hotel_name, date_raw, review_date, kind)
    if config.REVIEW_SINCE and review_date and review_date < config.REVIEW_SINCE:
        counts["too_old"] += 1               # 기준일(config.REVIEW_SINCE, 2025-01-01)보다 오래된 리뷰
        return

    rating = pick(item, "rating")
    try:
        rating = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating = None

    review_id = writer.next_review_id()
    writer.write({
        "review_id": review_id,
        "platform": PLATFORM_NAME,
        "hotel_name": hotel_name,
        "review_date": review_date or "",
        "rating": rating if rating is not None else "",
        "rating_scale": 5 if rating is not None else "",
        "review_text_raw": text,                                   # 사장님 답글은 넣지 않음
        "reviewer_id": anonymize(pick(item, "reviewerName", "authorNickname") or ""),
        "source_url": pick(item, "placeUrl") or "",
    }, key, english=(language == "en"))
    counts["english" if language == "en" else "saved"] += 1


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

        # 장소별로 묶기
        places = {}
        for item in items:
            places.setdefault(str(pick(item, "placeId") or pick(item, "placeUrl") or "?"), []).append(item)

        for place_id, place_items in places.items():
            hotel, why = match_hotel(place_items[0], hotels)
            name = pick(place_items[0], "placeName", "name") or place_id
            counts = {"saved": 0, "english": 0, "other_language": 0, "other_source": 0, "empty": 0, "duplicate": 0, "too_old": 0}
            if hotel is None:
                print(f"  !! 제외: {why} ({len(place_items)}건)")
                append_collect_log(config.COLLECT_LOG_FILE, config.COLLECTOR_INITIAL, PLATFORM_NAME,
                                   name, counts, f"{SOURCE_NOTE} / 대상 아님으로 제외: {why}")
                continue
            for item in place_items:
                handle_review(item, name, writer, date_logger, counts)
            print(f"  {hotel['search_name']} ← '{name}': 한국어 {counts['saved']} / 영어 {counts['english']} "
                  f"(제외: 블로그·카페 {counts['other_source']}, 기타 언어 {counts['other_language']}, "
                  f"빈 본문 {counts['empty']}, 중복 {counts['duplicate']}, 기준일 이전 {counts['too_old']})")
            note = f"{SOURCE_NOTE} / 네이버 장소명: {name}" + (f" / {why}" if why else "")
            append_collect_log(config.COLLECT_LOG_FILE, config.COLLECTOR_INITIAL, PLATFORM_NAME,
                               hotel["search_name"], counts, note)

        strip_personal_data(path, items)
        print(f"  원본 파일의 개인정보 칸({', '.join(PERSONAL_FIELDS)})을 지웠습니다.")

    print(f"\n완료. 결과 파일: {REVIEW_CSV}")


if __name__ == "__main__":
    main()
