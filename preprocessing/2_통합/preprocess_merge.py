# =============================================================
# 통합 전처리: 6개 데이터 병합 → 불용어 제거 · 토큰화 · 동의어 통일
#
# 실행:  python preprocessing/2_통합/preprocess_merge.py      (어느 폴더에서 실행해도 됨, 약 1분)
#
# 처리 순서 (계획서 PREPROCESSING_PLAN.md 2장)
#   ① 병합 · 중복 제거(같은 플랫폼 안에서 reviewer_id + review_date + review_text_raw가 같으면 처음 것만 남김)
#     · 표시 컬럼 추가 (hotel_std, in_period, rating_5, is_ad, is_noise(유튜브 노이즈 댓글 — youtube_noise.py))
#   ② 공백 정리   ③ 반복 문자 줄이기 (ㅋㅋㅋㅋ→ㅋㅋ)          → text_norm
#   ④ 문장 나누기 + 토큰화 (사용자 사전, 품사 거르기, 원형)
#   ⑤ 부정어 묶기 (안_좋다) · 재방문 표현 묶기 (다시 방문 → 재방문)   ⑥ 동의어 통일   ⑦ 불용어 제거   → tokens
#
# 결과 (결과/ 폴더)
#   - merged_preprocessed.csv / .xlsx : 글(리뷰) 단위 — 리뷰 1건 = 1줄, 분석용 13개 칼럼
#   - merged_sentences.csv            : 문장 단위 — 문장 1개 = 1줄 (6종 전체, 블로그는 글 1편이 수십 줄)
#   - 결과_설명.md                     : 결과 파일·칼럼 설명과 표시 기준·호텔명 대응표·통계 (실행할 때마다 새로 만듦)
#   - top300_tokens.csv               : 토큰 빈도 상위 300개
#   - 로그/ : duplicate_log(지운 중복), ad_log(광고 판단 이유), noise_log(유튜브 노이즈 판정),
#            stopword_log, synonym_log, expression_log(부정어·재방문 묶음)
#
# 사전 파일(사전/)만 고치고 다시 실행하면 반영된다:
#   hotel_alias.csv, hotel_keywords.csv, user_dict.csv, stopwords_hotel.csv(build_stopwords.py로 생성), synonyms.csv,
#   yt_labels.csv(유튜브 노이즈 판정)
# =============================================================

import csv
import os
import re
import sys
import time
from collections import Counter, defaultdict

from kiwi_tokens import DICT_DIR, HERE, make_kiwi, merge_revisit, normalize_text, tokens_with_negation
from youtube_noise import judge as judge_youtube, load_labels as load_youtube_labels

csv.field_size_limit(sys.maxsize)

# -------------------------------------------------------------
# 설정
# -------------------------------------------------------------
INPUT_DIR = os.path.join(HERE, "입력")
RESULT_DIR = os.path.join(HERE, "결과")
LOG_DIR = os.path.join(RESULT_DIR, "로그")     # 처리 기록(_log 파일)은 따로 모아 둔다

# (약어, 데이터 이름, 파일 경로, 담당)
SOURCES = [
    ("NM", "네이버지도", os.path.join(INPUT_DIR, "NM_네이버지도_DH.csv"), "DH"),
    ("GM", "구글맵", os.path.join(INPUT_DIR, "GM_구글맵_DH.csv"), "DH"),
    ("NB", "네이버블로그", os.path.join(INPUT_DIR, "NB_네이버블로그_JY.csv"), "JY"),
    ("YT", "유튜브", os.path.join(INPUT_DIR, "YT_유튜브_CH.csv"), "CH"),
    ("YG", "여기어때", os.path.join(INPUT_DIR, "YG_여기어때_WS.csv"), "WS"),
    ("AG", "아고다", os.path.join(INPUT_DIR, "AG_아고다_WS.csv"), "WS"),
]
RATED_SOURCES = {"NM", "GM", "YG", "AG"}      # 평점이 있는 데이터 (모두 5점 기준. 여기어때·아고다는 WS가 5점 환산해 둠)

PERIOD_START = "2024-10-01"   # 이 날짜 이전 글은 in_period = N (지우지 않고 표시만)
SHORT_LEN = 10                # text_norm이 이 글자 수보다 짧으면 is_short = Y
# 광고·협찬 표시 (is_ad) — 블로그에만 적용.
#   지도·숙박앱 리뷰에서 '제공받다'는 대부분 호텔 서비스('업그레이드를 제공받았다')라서 적용하지 않는다.
#   예시를 직접 확인하며 기준을 좁혔다: '정부 지원 받아', '아기 용품을 제공받은'(호텔 서비스), '광고 글만 나와서'(언급일 뿐),
#   '문의 전화'(호텔 정보), '취소 수수료' 같은 문장은 걸리지 않게 함
#   (2026-10-19) 팀원 검수: 판단을 1차 교정본(text_clean)이 아니라 원문(review_text_raw)으로 한다.
#   블로그 1차 교정본에서는 '#협찬' 해시태그와 글머리의 광고 고지문이 지워져 있어 놓치고 있었다.
SPONSOR_PATTERN = re.compile(
    r"협찬|체험단|원고료|체험\s?(으로|을 위해)\s?.{0,15}제공\s?받|(업체|호텔|브랜드|측)(로|으로)?부터\s?.{0,30}(제공|지원)\s?받"
    r"|무상\s?(으로)?\s?제공\s?받|(제공|지원)\s?받아\s?(작성|솔직|체험)|(본|이)\s?(포스팅|글|리뷰|게시물)은\s?.{0,20}광고|유료\s?광고"
    r"|[\(\[]\s?광고\s?[\)\]]|#\s?광고(?![가-힣])|플랫폼\s?협업|소정의\s?(원고료|대가|제작비)")
# '협찬 없이', '광고 협찬 없는', '협찬 아닙니다'처럼 부정하는 문장은 제외 (오히려 내돈내산 표시)
SPONSOR_NEGATION = re.compile(r"^.{0,10}(없|아니|아닙|아님|않|[Xx]\b)")
# 제휴 수수료 고지, 최저가 예약·할인 코드 홍보
AFFILIATE_PATTERN = re.compile(
    r"파트너스\s?활동|소정의\s?수수료|수수료[를을]?\s?(제공|지급)\s?받|판매\s?(발생|시)\s?.{0,10}수수료|쇼핑\s?커넥트"
    r"|일정\s?(비율의\s?)?수수료|커미션|제휴\s?(사의?\s?)?(링크|활동|마케팅)|마케팅\s?파트너십"
    r"|최저가\s?(예약|링크|보러|확인)|할인\s?코드|프로모션\s?코드|할인\s?쿠폰\s?정리|예약\s?바로\s?가기|할인\s?링크"
    r"|숙박\s?후기를\s?통합해서\s?제작")
# 반복 템플릿 (블로그): 같은 홍보 문장을 여러 글에 붙여 쓴 글 (택시·카드·자동차 홍보, 호텔 뉴스 계정, 예약 커미션 템플릿 등)
#   문장(공백 빼고 20자 이상)이 TEMPLATE_MIN_POSTS개 이상의 글에 똑같이 나오고,
#   ① 서로 다른 작성자 2~TEMPLATE_MAX_AUTHORS명이 썼거나(퍼다 쓴 템플릿) ② 한 작성자가 호텔 3곳 이상에 썼으면 '템플릿 문장'.
#   글 하나에 템플릿 문장이 TEMPLATE_MIN_SENTS개 이상이면 표시. 주소·전화·체크인 시간·해시태그·호텔명 같은 정보 문장은 뺀다.
#   (여러 작성자가 모두 같이 쓰는 문장 = 호텔 공식 안내문 복사는 홍보로 보지 않음)
TEMPLATE_MIN_POSTS = 3
TEMPLATE_MAX_AUTHORS = 3
TEMPLATE_MIN_SENTS = 3
TEMPLATE_INFO = re.compile(r"(시|구|군|동|로|길)\s?\d|\d{2,4}-\d{3,4}|체크\s?(인|아웃)|입실|퇴실|#|all\s?rights|copyright"
                           r"|\d{1,2}:\d{2}|krw|원\)|주소|전화|tel", re.I)
COPY_MIN_LEN = 20             # 같은 작성자가 이 글자 수 이상의 같은 글을 여러 호텔에 올리면 '복붙 의심'으로 is_ad 표시

# 입력 파일에서 읽는 팀 공통 칼럼
TEAM_COLUMNS = ["review_id", "platform", "hotel_name", "review_date", "rating", "rating_scale",
                "review_text_raw", "reviewer_id", "source_url"]

# 결과 칼럼 (2026-10-18 팀 결정: 메인 파일은 분석에 쓰는 칼럼만. 부가 정보는 결과_설명.md와 로그/로)
#   hotel_name = 표준 호텔명, rating = 5점 기준 평점, text_clean = 공백·반복 문자를 정리한 본문,
#   in_period·is_ad·is_noise = TRUE/FALSE (필터용)
MAIN_COLUMNS = ["review_id", "platform", "hotel_name", "review_date", "rating", "review_text_raw", "reviewer_id",
                "source_url", "text_clean", "tokens", "in_period", "is_ad", "is_noise"]
SENTENCE_COLUMNS = ["sentence_id", "review_id", "platform", "hotel_name", "review_date", "rating", "sent_no",
                    "sentence", "tokens", "in_period", "is_ad", "is_noise"]
BOOL_COLUMNS = {"in_period", "is_ad", "is_noise"}

EXCEL_CELL_LIMIT = 32767      # 엑셀 한 칸 최대 글자 수


# -------------------------------------------------------------
# 사전 읽기
# -------------------------------------------------------------
def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def one_line(text):
    return re.sub(r"\s+", " ", text or "").strip()


def nospace(text):
    return re.sub(r"\s+", "", text or "").lower()


def load_dictionaries():
    alias = {r["표기"]: r["hotel_std"] for r in read_csv(os.path.join(DICT_DIR, "hotel_alias.csv"))}
    keywords = {r["hotel_std"]: [nospace(k) for k in r["본문_검색어"].split("|") if k.strip()]
                for r in read_csv(os.path.join(DICT_DIR, "hotel_keywords.csv"))}
    stop_rows = read_csv(os.path.join(DICT_DIR, "stopwords_hotel.csv"))
    # 데이터별 불용어('데이터별(블로그)')는 그 데이터에만, 나머지는 모든 데이터에 적용
    source_of = {"데이터별(블로그)": "NB", "데이터별(유튜브)": "YT"}
    stopwords = defaultdict(dict)                     # 데이터 약어(또는 '*') → {토큰: 출처}
    for r in stop_rows:
        if r["사용"] == "Y" and r["적용형태"]:
            stopwords[source_of.get(r["출처"], "*")][r["적용형태"]] = r["출처"]
    synonyms = {r["원래단어"].strip(): r["대표어"].strip() for r in read_csv(os.path.join(DICT_DIR, "synonyms.csv"))
                if r["원래단어"].strip() and r["대표어"].strip() and r.get("사용", "Y").strip() != "N"}
    return alias, keywords, stopwords, synonyms


# -------------------------------------------------------------
# ① 병합 · 표시 컬럼
# -------------------------------------------------------------
def build_row(code, row, alias, keywords, yt_labels, unmapped):
    out = {c: (row.get(c) or "") for c in TEAM_COLUMNS}
    out["source"] = code
    rating = (row.get("rating") or "").strip()
    if code in RATED_SOURCES and rating and not out["rating_scale"]:
        out["rating_scale"] = "5"                     # 여기어때·아고다 파일에는 rating_scale 칼럼이 없음 (5점 환산값)
    out["rating_5"] = rating if code in RATED_SOURCES else ""

    hotel_std = alias.get(out["hotel_name"].strip(), "")
    if out["hotel_name"].strip() and not hotel_std:
        unmapped[(code, out["hotel_name"])] += 1
    out["hotel_std"] = hotel_std

    date = out["review_date"].strip()
    out["in_period"] = ("Y" if date >= PERIOD_START else "N") if date else ""

    out["text_clean"] = row.get("text_clean") or ""
    out["text_norm"] = normalize_text(out["text_clean"])
    out["is_short"] = "Y" if len(out["text_norm"]) < SHORT_LEN else "N"

    # 광고·협찬 (블로그만, 복붙 의심은 병합 뒤 전체에서 따로 표시)
    reasons = []
    if code == "NB":
        raw_norm = normalize_text(out["review_text_raw"])        # 원문 기준 (1차 교정본에는 광고 고지·해시태그가 지워져 있음)
        if any(not SPONSOR_NEGATION.match(raw_norm[m.end():m.end() + 12])
               for m in SPONSOR_PATTERN.finditer(raw_norm)):
            reasons.append("협찬")
        if AFFILIATE_PATTERN.search(raw_norm):
            reasons.append("제휴·예약 홍보")
    out["ad_reason"] = "; ".join(reasons)
    # 블로그·유튜브만: 본문에 해당 호텔이 나오는지 (지도·숙박앱 리뷰는 호텔 페이지에 달린 글이라 해당 없음)
    if code in ("NB", "YT") and hotel_std:
        body = nospace(out["text_norm"])
        out["hotel_mentioned"] = "Y" if any(k in body for k in keywords.get(hotel_std, [])) else "N"
    else:
        out["hotel_mentioned"] = ""
    # 유튜브만: 호텔 이야기가 아닌 댓글 (채널 반응·무관·미경험 희망) → is_noise (기준은 youtube_noise.py)
    if code == "YT":
        out["is_noise"], out["noise_type"], out["noise_how"] = judge_youtube(out["review_id"], out["review_text_raw"],
                                                                             yt_labels)
    else:
        out["is_noise"], out["noise_type"], out["noise_how"] = "N", "", ""
    return out


def template_sentences(text, hotel_names):
    """글의 문장 중 템플릿 판정에 쓸 문장 (공백 제거·소문자, 20자 이상, 주소·호텔명 같은 정보 문장 제외)"""
    found = set()
    for sent in re.split(r"[.!?\n…]+", re.sub(r"https?://\S+", " ", text or "")):
        key = re.sub(r"\s+", "", sent).lower()
        if len(key) < 20 or TEMPLATE_INFO.search(sent):
            continue
        if any(name in key and len(key) < len(name) + 15 for name in hotel_names):   # 호텔 이름만 있는 문장
            continue
        found.add(key)
    return found


def mark_templates(blog_rows, alias):
    """반복 템플릿 글 목록 (설명은 TEMPLATE_* 설정 주석 참고)"""
    hotel_names = {re.sub(r"\s+", "", x).lower() for pair in alias.items() for x in pair if x}
    sents = {id(r): template_sentences(r["review_text_raw"], hotel_names) for r in blog_rows}
    posts, authors, hotels = Counter(), defaultdict(set), defaultdict(set)
    for r in blog_rows:
        for s in sents[id(r)]:
            posts[s] += 1
            authors[s].add(r["reviewer_id"])
            hotels[s].add(r["hotel_std"])

    def is_template(s):
        return posts[s] >= TEMPLATE_MIN_POSTS and (2 <= len(authors[s]) <= TEMPLATE_MAX_AUTHORS
                                                   or (len(authors[s]) == 1 and len(hotels[s]) >= 3))
    return [r for r in blog_rows if sum(is_template(s) for s in sents[id(r)]) >= TEMPLATE_MIN_SENTS]


# -------------------------------------------------------------
# ⑥ 동의어 · ⑦ 불용어
# -------------------------------------------------------------
def stop_source(tok, code, stopwords):
    """tok이 이 데이터(code)의 불용어면 그 출처를, 아니면 None"""
    return stopwords["*"].get(tok) or stopwords.get(code, {}).get(tok)


def finish_tokens(raw_tokens, code, synonyms, stopwords, logs):
    final = []
    for tok in raw_tokens:
        if tok in synonyms:
            logs["synonym"][(tok, synonyms[tok])] += 1
            tok = synonyms[tok]
        else:
            # 부정으로 묶인 토큰은 안쪽 단어만 동의어로 바꾼다 (안_청결 → 안_깨끗, 룸_없다 → 객실_없다)
            m = re.fullmatch(r"(안_|못_)?(.+?)(_없다)?", tok)
            head, base, tail = m.group(1) or "", m.group(2), m.group(3) or ""
            if (head or tail) and base in synonyms:
                logs["synonym"][(base, synonyms[base])] += 1
                tok = head + synonyms[base] + tail
        src = stop_source(tok, code, stopwords)
        if src:
            logs["stopword"][(tok, src, code)] += 1
            continue
        final.append(tok)
    return final


# -------------------------------------------------------------
# 결과 저장 도우미
# -------------------------------------------------------------
def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def tf(flag):
    """내부 표시 Y/N → TRUE/FALSE (해당 없음은 빈칸)"""
    return {"Y": "TRUE", "N": "FALSE"}.get(flag, "")


def main_row(r):
    return {"review_id": r["review_id"], "platform": r["platform"], "hotel_name": r["hotel_std"],
            "review_date": r["review_date"], "rating": r["rating_5"], "review_text_raw": r["review_text_raw"],
            "reviewer_id": r["reviewer_id"], "source_url": r["source_url"], "text_clean": r["text_norm"],
            "tokens": r["tokens"], "in_period": tf(r["in_period"]), "is_ad": tf(r["is_ad"]),
            "is_noise": tf(r["is_noise"])}


def write_excel(path, fieldnames, rows):
    """
    텍스트 칸은 '텍스트' 형식으로 저장 → 엑셀에서 열고 저장해도 reviewer_id·날짜·수식 문제가 생기지 않음.
    in_period·is_ad·is_noise는 엑셀의 참/거짓 값으로 저장 → 필터에서 TRUE/FALSE로 바로 고를 수 있음.
    """
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE   # 엑셀이 받지 않는 제어 문자 (블로그 본문에 섞여 있음)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("merged")
    ws.append(fieldnames)
    cut = 0
    for row in rows:
        cells = []
        for k in fieldnames:
            if k in BOOL_COLUMNS and row.get(k) in ("TRUE", "FALSE"):
                cells.append(WriteOnlyCell(ws, value=row[k] == "TRUE"))
                continue
            v = ILLEGAL_CHARACTERS_RE.sub("", str(row.get(k, "")))
            if len(v) > EXCEL_CELL_LIMIT:
                v = v[:EXCEL_CELL_LIMIT - 40] + " …(엑셀 칸 글자 수 제한으로 잘림, 전체는 CSV)"
                cut += 1
            c = WriteOnlyCell(ws, value=v)
            c.number_format = "@"
            cells.append(c)
        ws.append(cells)
    wb.save(path)
    return cut


# -------------------------------------------------------------
# 결과 설명 문서 (결과_설명.md) — 실행할 때마다 지금 결과로 새로 만든다
# -------------------------------------------------------------
def md_table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def write_summary(path, rows, stats):
    names = {c: n for c, n, *_ in SOURCES}
    codes = [c for c, *_ in SOURCES]
    by = defaultdict(list)
    for r in rows:
        by[r["source"]].append(r)

    def n(cond, rs=rows):
        return sum(1 for r in rs if cond(r))

    def counts(counter):
        return [[k, f"{v:,}"] for k, v in counter.most_common()]

    def base(r):
        return r["in_period"] == "Y" and r["is_ad"] == "N" and r["is_noise"] == "N"

    out = ["# 통합 전처리 결과 설명", "",
           "> 이 문서는 `preprocess_merge.py`를 실행할 때마다 지금 결과로 새로 만들어집니다 (직접 고치지 마세요).",
           "> 처리 규칙과 판단 근거는 `../PREPROCESSING_PLAN.md`에 있습니다.", "",
           "## 1. 파일", "",
           md_table(["파일", "내용", "줄 수"], [
               ["merged_preprocessed.csv / .xlsx", "★ 글 단위 — 리뷰 1건 = 1줄", f"{len(rows):,}"],
               ["merged_sentences.csv", "★ 문장 단위 — 문장 1개 = 1줄", f"{stats['n_sentences']:,}"],
               ["top300_tokens.csv", "불용어를 뺀 뒤 동의어 통일 전 토큰 빈도 상위 300개 (데이터별 횟수)", "300"],
               ["로그/duplicate_log.csv", "중복으로 지운 글 (지운 번호 ↔ 남긴 번호)", f"{len(stats['dup_rows']):,}"],
               ["로그/ad_log.csv", "is_ad = TRUE인 글과 판단 이유", f"{n(lambda r: r['is_ad'] == 'Y'):,}"],
               ["로그/noise_log.csv", "is_noise = TRUE인 유튜브 댓글과 유형·판정 방법",
                f"{n(lambda r: r['is_noise'] == 'Y'):,}"],
               ["로그/stopword_log.csv", "불용어별·데이터별 제거 횟수", f"{len(stats['logs']['stopword']):,}"],
               ["로그/synonym_log.csv", "동의어로 바꾼 단어와 횟수", f"{len(stats['logs']['synonym']):,}"],
               ["로그/expression_log.csv", "부정어(안_·못_)·재방문으로 묶은 표현과 횟수",
                f"{len(stats['logs']['negation']):,}"],
           ]), "",
           "## 2. 메인 파일 칼럼 (merged_preprocessed)", "",
           md_table(["칼럼", "설명"], [
               ["review_id", "글 번호 (플랫폼약어_이니셜_일련번호) — 원본 파일과 연결하는 키"],
               ["platform", "수집 출처 — 입력 파일 값 그대로 (" + ", ".join(dict.fromkeys(
                   r["platform"] for c in codes for r in by[c][:1])) + ")"],
               ["hotel_name", "**표준 호텔명** (`hotels_seoul.csv` 이름). 호텔을 특정할 수 없는 유튜브 댓글은 빈칸 — 6장 참고"],
               ["review_date", "작성일 (YYYY-MM-DD)"],
               ["rating", "**5점 기준 평점**. 블로그·유튜브는 빈칸, 네이버지도는 별점을 남기지 않은 글이 빈칸"],
               ["review_text_raw", "수집한 원문 그대로"],
               ["reviewer_id", "작성자 닉네임의 SHA-256 해시 앞 16자리 (닉네임 원문은 저장하지 않음)"],
               ["source_url", "원본 주소"],
               ["text_clean", "각자 1차 전처리한 본문에 공백 정리 + 반복 문자 줄이기(ㅋㅋㅋㅋ→ㅋㅋ)를 적용한 본문"],
               ["tokens", "최종 토큰 (띄어쓰기로 구분). 불용어 제거·토큰화·동의어 통일·부정어/재방문 묶기를 거침"],
               ["in_period", f"TRUE = {PERIOD_START} 이후 글"],
               ["is_ad", "TRUE = 협찬·제휴 홍보·복붙 의심·반복 템플릿 글 — 5장 참고"],
               ["is_noise", "TRUE = 호텔 이야기가 아닌 유튜브 댓글 — 5장 참고 (유튜브 외 데이터는 모두 FALSE)"],
           ]), "",
           "## 3. 문장 파일 칼럼 (merged_sentences)", "",
           "글 하나를 Kiwi로 문장 단위로 나눈 파일입니다. 블로그처럼 긴 글에서 \"어느 문장이 무엇을 말하는지\" 볼 때 씁니다.",
           "`sentence_id`(= review_id_S문장번호), `sent_no`(글 안의 문장 번호), `sentence`(문장 본문), `tokens`(그 문장의 토큰)과",
           "메인 파일의 review_id · platform · hotel_name · review_date · rating · in_period · is_ad · is_noise가 들어 있습니다.",
           "한 글의 문장 토큰을 차례로 이으면 메인 파일의 `tokens`와 같습니다.", "",
           "## 4. 데이터별 건수와 기본 필터", "",
           f"**기본 분석 대상** = `in_period`가 TRUE이고 `is_ad`·`is_noise`가 FALSE인 글 → **{n(base):,}건**", "",
           md_table(["데이터", "전체", "in_period FALSE", "is_ad TRUE", "is_noise TRUE", "기본 분석 대상", "평점 있음"],
                    [[f"{names[c]}({c})", f"{len(by[c]):,}", f"{n(lambda r: r['in_period'] == 'N', by[c]):,}",
                      f"{n(lambda r: r['is_ad'] == 'Y', by[c]):,}", f"{n(lambda r: r['is_noise'] == 'Y', by[c]):,}",
                      f"{n(base, by[c]):,}", f"{n(lambda r: r['rating_5'], by[c]):,}"] for c in codes]
                    + [["**합계**", f"**{len(rows):,}**", f"**{n(lambda r: r['in_period'] == 'N'):,}**",
                        f"**{n(lambda r: r['is_ad'] == 'Y'):,}**", f"**{n(lambda r: r['is_noise'] == 'Y'):,}**",
                        f"**{n(base):,}**", f"**{n(lambda r: r['rating_5']):,}**"]]), "",
           "- 엑셀: 데이터 → 필터에서 세 칼럼을 각각 TRUE / FALSE / FALSE로 고릅니다.",
           "- 파이썬: `df[df.in_period & ~df.is_ad & ~df.is_noise]`", "",
           "## 5. 표시 기준", "",
           f"### in_period — {PERIOD_START} 이전 글 표시",
           "지우지 않고 표시만 합니다. 데이터별 건수는 4장 표의 'in_period FALSE' 칸을 보세요.", "",
           "### is_ad — 광고·협찬 표시",
           "- 협찬·제휴 홍보: **네이버블로그에만** 적용 (지도·숙박앱의 '제공받았다'는 대부분 호텔 서비스 이야기라서).",
           "  '협찬 없이', '광고 아닙니다'처럼 부정하는 문장은 제외합니다.",
           f"- 복붙 의심: 같은 작성자가 같은 글({COPY_MIN_LEN}자 이상)을 여러 호텔에 올린 경우 (모든 데이터).",
           f"- 반복 템플릿 (블로그): 같은 홍보 문장(20자 이상)이 {TEMPLATE_MIN_POSTS}개 이상의 글에 그대로 나오고, 서로 다른 작성자 2~{TEMPLATE_MAX_AUTHORS}명이"
           f" 썼거나 한 작성자가 호텔 3곳 이상에 쓴 문장이 글 하나에 {TEMPLATE_MIN_SENTS}개 이상인 경우 (택시·카드·자동차 홍보, 호텔 뉴스 계정, 예약 커미션 템플릿 등).",
           "  호텔 공식 안내문처럼 여러 작성자가 모두 같이 쓰는 문장과 주소·체크인 시간 같은 정보 문장은 세지 않습니다.",
           "- 협찬·제휴 판단은 원문(review_text_raw) 기준입니다 (블로그 1차 교정본에는 '#협찬'과 광고 고지문이 지워져 있음).",
           "- 글마다 판단 이유는 `로그/ad_log.csv`에 있습니다.", "",
           md_table(["이유", "건수"], counts(Counter(reason for r in rows for reason in r["ad_reason"].split("; ")
                                                  if reason))), "",
           "### is_noise — 유튜브 노이즈 댓글",
           "- 노이즈: **채널 반응**(영상·유튜버·구독·퀴즈 이야기만), **무관**(집밥·다른 식당·잡담), "
           "**미경험 희망**('가보고 싶다', '맛있겠다'만 있고 경험·평가 없음)",
           "- 유지: 호텔 경험·평가·정보·의견(일반론 포함). 가격·가치 이야기는 경험이 없어도 유지합니다.",
           "- 판정 방법: 키워드 규칙으로 1차 판정(유지/노이즈/애매) → Claude가 전체를 읽고 최종 판정해 `../사전/yt_labels.csv`에 고정.",
           "  규칙만으로는 오판이 많아(예: '리뷰 한번만 해주세요'를 유지로, '다 자리값이지'를 노이즈로) 전부 확인했습니다.",
           "- 댓글마다 유형·판정 방법은 `로그/noise_log.csv`, 규칙과 최종 판정 비교는 `python preprocessing/2_통합/youtube_noise.py`.", "",
           md_table(["노이즈 유형", "건수"], counts(Counter(r["noise_type"] for r in rows if r["is_noise"] == "Y"))), "",
           md_table(["판정 방법 (유튜브 전체)", "건수"], counts(Counter(r["noise_how"] for r in by["YT"]))), "",
           "## 6. 호텔명 표준화 (hotel_name)", "",
           "데이터마다 같은 호텔을 다르게 적어서 `../사전/hotel_alias.csv`로 표준 호텔명에 맞췄습니다. "
           "아래는 원래 표기 → 표준 호텔명과 글 수입니다.", ""]
    mapping = Counter((r["hotel_std"], r["source"], r["hotel_name"]) for r in rows)
    out.append(md_table(["표준 호텔명", "데이터", "원래 표기", "건수"],
                        [[std or "(빈칸)", names[c], orig or "(빈칸)", f"{cnt:,}"]
                         for (std, c, orig), cnt in sorted(mapping.items(),
                                                           key=lambda x: (x[0][0] == "", x[0][0], codes.index(x[0][1]),
                                                                          -x[1], x[0][2]))]))
    if stats["unmapped"]:
        out += ["", "표준 호텔명을 찾지 못한 표기: " + ", ".join(f"{o}({c}) {k}건" for (c, o), k
                                                       in stats["unmapped"].most_common())]
    out += ["", "## 7. 참고 통계", "",
            md_table(["데이터", "평균 문장 수", "평균 토큰 수", "짧은 글(10자 미만)", "본문에 호텔 이름이 나옴"],
                     [[f"{names[c]}({c})", f"{sum(r['n_sentences'] for r in by[c]) / max(len(by[c]), 1):.1f}",
                       f"{sum(r['n_tokens'] for r in by[c]) / max(len(by[c]), 1):.1f}",
                       f"{n(lambda r: r['is_short'] == 'Y', by[c]):,}",
                       (f"{n(lambda r: r['hotel_mentioned'] == 'Y', by[c]):,} / "
                        f"{n(lambda r: r['hotel_mentioned'] in ('Y', 'N'), by[c]):,}")
                       if c in ("NB", "YT") else "해당 없음"] for c in codes]), "",
            "- 본문에 호텔 이름이 나옴: 블로그·유튜브는 검색어·영상으로 호텔을 정해서, 본문에 그 호텔이 실제로 나오는지 확인한 값입니다"
            " (`../사전/hotel_keywords.csv`). 지도·숙박앱 리뷰는 호텔 페이지에 달린 글이라 해당 없습니다.",
            "- 평점은 모두 5점 기준입니다 (여기어때·아고다는 수집 담당이 5점으로 환산해 둠).", "",
            "## 8. 처리 수치", "",
            md_table(["항목", "값"], [
                ["중복으로 지운 글 (같은 플랫폼 안에서 reviewer_id + review_date + review_text_raw가 같음)",
                 f"{len(stats['dup_rows']):,}건 (" + ", ".join(f"{names[c]} {k}" for c, k in Counter(
                     d["source"] for d in stats["dup_rows"]).most_common()) + ")"],
                ["토큰 수 (토큰화·묶기 직후 → 최종)", f"{stats['n_before']:,} → {stats['n_after']:,}"],
                ["불용어 제거", f"{sum(stats['logs']['stopword'].values()):,}회"],
                ["부정어 묶음 (안_좋다 등)", f"{sum(k for t, k in stats['logs']['negation'].items() if '재방문' not in t):,}회"],
                ["재방문 묶음 (다시 오다 → 재방문)", f"{sum(k for t, k in stats['logs']['negation'].items() if '재방문' in t):,}회"],
                ["동의어 변환", f"{sum(stats['logs']['synonym'].values()):,}회"],
                ["엑셀에서 잘린 칸 (한 칸 32,767자 제한, 전체는 CSV에 있음)", f"{stats['cut']:,}개"],
            ]), ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


# -------------------------------------------------------------
# 전체 실행
# -------------------------------------------------------------
def main():
    start = time.time()
    os.makedirs(LOG_DIR, exist_ok=True)
    alias, keywords, stopwords, synonyms = load_dictionaries()
    yt_labels = load_youtube_labels()
    print(f"사전: 호텔 표기 {len(alias)}개, 불용어 {sum(len(v) for v in stopwords.values())}개, 동의어 {len(synonyms)}개,"
          f" 유튜브 판정 {len(yt_labels):,}건")

    # ① 병합
    unmapped = Counter()
    rows = []
    for code, name, path, _ in SOURCES:
        src = read_csv(path)
        rows += [build_row(code, r, alias, keywords, yt_labels, unmapped) for r in src]
        print(f"  {name}({code}): {len(src):,}건")
    if unmapped:
        print("  !! 표준 호텔명을 못 찾은 표기:", unmapped.most_common(10))
    print(f"병합: {len(rows):,}건")

    # 중복 제거 (팀 기준): reviewer_id + review_date + review_text_raw가 같으면 같은 리뷰로 보고 처음 것만 남긴다.
    # 같은 플랫폼 안에서만 비교한다 — 아고다·여기어때처럼 닉네임이 가려지는 플랫폼이 있어,
    # 플랫폼이 다르면 다른 사람의 같은 닉네임 해시가 같은 작성자로 보일 수 있기 때문.
    first_of, kept, dup_rows = {}, [], []
    for r in rows:
        key = (r["source"], r["reviewer_id"], r["review_date"], r["review_text_raw"])
        if key in first_of:
            dup_rows.append({"지운_review_id": r["review_id"], "남긴_review_id": first_of[key], "source": r["source"],
                             "hotel_std": r["hotel_std"], "review_date": r["review_date"],
                             "review_text_raw": r["review_text_raw"][:200]})
            continue
        first_of[key] = r["review_id"]
        kept.append(r)
    rows = kept
    print(f"  중복 제거: {len(dup_rows)}건 지움 → {len(rows):,}건 {dict(Counter(d['source'] for d in dup_rows))}")

    # 복붙 의심: 같은 작성자가 같은 글(공백 무시, COPY_MIN_LEN자 이상)을 여러 호텔에 올린 경우
    hotels_of = defaultdict(set)
    for r in rows:
        body = re.sub(r"\s+", "", r["text_norm"])
        if len(body) >= COPY_MIN_LEN:
            hotels_of[(r["reviewer_id"], body)].add(r["hotel_std"])
    for r in rows:
        body = re.sub(r"\s+", "", r["text_norm"])
        if len(body) >= COPY_MIN_LEN and len(hotels_of[(r["reviewer_id"], body)]) > 1:
            r["ad_reason"] = "; ".join(x for x in [r["ad_reason"], "복붙 의심(같은 글을 여러 호텔에)"] if x)
    # 반복 템플릿 (블로그)
    for r in mark_templates([r for r in rows if r["source"] == "NB"], alias):
        r["ad_reason"] = "; ".join(x for x in [r["ad_reason"], "반복 템플릿(같은 홍보 문장을 여러 글에)"] if x)
    for r in rows:
        r["is_ad"] = "Y" if r["ad_reason"] else "N"
    ad = Counter(reason for r in rows for reason in r["ad_reason"].split("; ") if reason)
    print(f"  is_ad = Y: {sum(r['is_ad'] == 'Y' for r in rows):,}건 {dict(ad)}")
    noise = Counter(r["noise_type"] for r in rows if r["is_noise"] == "Y")
    print(f"  is_noise = Y: {sum(noise.values()):,}건 {dict(noise)}")
    unlabeled = sum(r["noise_how"] == "규칙만(라벨 없음)" for r in rows)
    if unlabeled:
        print(f"  !! 판정 파일(사전/yt_labels.csv)에 없는 유튜브 댓글 {unlabeled}건 — 규칙으로만 판정함 (애매한 것은 유지)")

    # ④~⑦ 문장 나누기 + 토큰화 (한 번에 여러 글을 넣어 빠르게)
    kiwi = make_kiwi()
    logs = {"stopword": Counter(), "synonym": Counter(), "negation": Counter()}
    middle = defaultdict(Counter)        # ⑦ 불용어 뒤, ⑥ 동의어 앞 — 동의어 초안용(top300_tokens)
    n_before = n_after = 0               # 토큰 수: 토큰화·묶기 직후 / 최종
    sentence_rows = []
    texts = [r["text_norm"] for r in rows]
    for idx, sents in enumerate(kiwi.split_into_sents(texts, return_tokens=True)):
        row = rows[idx]
        code = row["source"]
        doc_tokens = []
        for no, sent in enumerate(sents, start=1):
            raw = merge_revisit(tokens_with_negation(sent.tokens, logs["negation"]), logs["negation"])
            middle[code].update(t for t in raw if not stop_source(t, code, stopwords))
            final = finish_tokens(raw, code, synonyms, stopwords, logs)
            n_before += len(raw)
            n_after += len(final)
            doc_tokens += final
            sentence_rows.append({
                "sentence_id": f"{row['review_id']}_S{no:03d}", "review_id": row["review_id"],
                "platform": row["platform"], "hotel_name": row["hotel_std"], "review_date": row["review_date"],
                "rating": row["rating_5"], "sent_no": no, "sentence": sent.text.strip(), "tokens": " ".join(final),
                "in_period": tf(row["in_period"]), "is_ad": tf(row["is_ad"]), "is_noise": tf(row["is_noise"]),
            })
        row["tokens"] = " ".join(doc_tokens)
        row["n_sentences"] = len(sents)
        row["n_tokens"] = len(doc_tokens)
        if (idx + 1) % 5000 == 0:
            print(f"  토큰화 {idx + 1:,}/{len(rows):,} ({time.time() - start:.0f}초)")

    # 결과 저장
    write_csv(os.path.join(LOG_DIR, "duplicate_log.csv"),
              ["지운_review_id", "남긴_review_id", "source", "hotel_std", "review_date", "review_text_raw"], dup_rows)
    main_rows = [main_row(r) for r in rows]
    write_csv(os.path.join(RESULT_DIR, "merged_preprocessed.csv"), MAIN_COLUMNS, main_rows)
    write_csv(os.path.join(RESULT_DIR, "merged_sentences.csv"), SENTENCE_COLUMNS, sentence_rows)
    cut = write_excel(os.path.join(RESULT_DIR, "merged_preprocessed.xlsx"), MAIN_COLUMNS, main_rows)

    # 로그
    codes = [c for c, *_ in SOURCES]
    write_csv(os.path.join(LOG_DIR, "ad_log.csv"), ["review_id", "platform", "hotel_name", "ad_reason", "본문_앞부분"],
              [{"review_id": r["review_id"], "platform": r["platform"], "hotel_name": r["hotel_std"],
                "ad_reason": r["ad_reason"], "본문_앞부분": one_line(r["text_norm"])[:150]}
               for r in rows if r["is_ad"] == "Y"])
    write_csv(os.path.join(LOG_DIR, "noise_log.csv"),
              ["review_id", "hotel_name", "노이즈_유형", "판정_방법", "본문_앞부분"],
              [{"review_id": r["review_id"], "hotel_name": r["hotel_std"], "노이즈_유형": r["noise_type"],
                "판정_방법": r["noise_how"], "본문_앞부분": one_line(r["text_norm"])[:150]}
               for r in rows if r["is_noise"] == "Y"])
    write_csv(os.path.join(LOG_DIR, "stopword_log.csv"), ["불용어", "출처", "데이터", "제거_횟수"],
              [{"불용어": t, "출처": s, "데이터": c, "제거_횟수": n} for (t, s, c), n in logs["stopword"].most_common()])
    write_csv(os.path.join(LOG_DIR, "synonym_log.csv"), ["원래단어", "대표어", "바뀐_횟수"],
              [{"원래단어": a, "대표어": b, "바뀐_횟수": n} for (a, b), n in logs["synonym"].most_common()])
    write_csv(os.path.join(LOG_DIR, "expression_log.csv"), ["묶은_토큰", "종류", "횟수"],
              [{"묶은_토큰": t, "종류": "재방문" if "재방문" in t else "부정어", "횟수": n}
               for t, n in logs["negation"].most_common()])

    total_mid = sum(middle.values(), Counter())
    write_csv(os.path.join(RESULT_DIR, "top300_tokens.csv"), ["순위", "토큰", "전체"] + codes,
              [{"순위": i, "토큰": t, "전체": n, **{c: middle[c][t] for c in codes}}
               for i, (t, n) in enumerate(total_mid.most_common(300), start=1)])

    stats = {"dup_rows": dup_rows, "cut": cut, "n_sentences": len(sentence_rows), "n_before": n_before,
             "n_after": n_after, "logs": logs, "unmapped": unmapped}
    write_summary(os.path.join(RESULT_DIR, "결과_설명.md"), rows, stats)

    # 요약
    print(f"\n완료 ({time.time() - start:.0f}초)")
    print(f"  글 단위: {len(rows):,}건 → merged_preprocessed.csv / .xlsx (엑셀에서 잘린 칸 {cut}개), 설명 → 결과_설명.md")
    print(f"  문장 단위: {len(sentence_rows):,}문장 → merged_sentences.csv")
    print(f"  토큰 수: 토큰화 직후 {n_before:,}개 → 최종 {n_after:,}개 (불용어 제거 {sum(logs['stopword'].values()):,}회)")
    neg = sum(n for t, n in logs["negation"].items() if "재방문" not in t)
    rev = sum(n for t, n in logs["negation"].items() if "재방문" in t)
    print(f"  부정어 묶음 {neg:,}회 / 재방문 묶음 {rev:,}회 / 동의어 변환 {sum(logs['synonym'].values()):,}회")


if __name__ == "__main__":
    main()
