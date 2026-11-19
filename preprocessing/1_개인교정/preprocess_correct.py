# =============================================================
# 개별 전처리: 오탈자·띄어쓰기 교정
#
# 실행:  python preprocessing/1_개인교정/preprocess_correct.py   (어느 폴더에서 실행해도 됨)
#
# 하는 일
#   1) 프로젝트의 output/naver_map_reviews.csv, output/google_map_reviews.csv 를 읽는다 (원본은 건드리지 않음)
#   2) 리뷰마다
#      ① 오탈자 교정: 리뷰에 자주 나오는 "확실한" 오타만 아래 TYPO_RULES 규칙으로 고친다
#         (사투리·줄임말·신조어(넘, 강추, ㅋㅋ 등)는 오타가 아니므로 그대로 둔다)
#      ② 띄어쓰기 교정: 한글이 8자 이상 붙어 있는 어절만 형태소 분석기 Kiwi(kiwipiepy)의 space()로 띄운다
#         (이미 있는 띄어쓰기는 지우지 않고, 빠진 곳만 넣는다. 붙여 써도 되는 말은 건드리지 않는다)
#      ③ 수동 교정: 담당자가 교정본을 읽고 찾은 잘못된 띄어쓰기·오타를 manual_fixes.csv(이 파일과 같은 폴더) 목록대로 고친다
#      ④ 이모티콘 제거: 그림 이모지(👍❤️🥰 등)와 문자 이모티콘(^^, :) 등)을 지운다
#         (ㅋㅋ·ㅎㅎ·ㅠㅠ 같은 자음·모음 표현은 이모티콘이 아니라서 남긴다 → 불용어 단계에서 정함)
#   3) 결과 저장
#      - 결과/naver_map_reviews_pre-processed.csv, 결과/google_map_reviews_pre-processed.csv  (이 파일과 같은 폴더의 '결과')
#        → 팀 공통 9개 칼럼 + text_clean(전처리한 본문). 원문(review_text_raw)은 그대로 두어 전후 비교 가능
#      - 같은 파일을 통합 단계 입력 폴더(2_통합/입력/)에도 NM_네이버지도_DH.csv, GM_구글맵_DH.csv 이름으로 복사한다
#        (팀원 파일과 같은 이름 규칙. 다시 실행하면 복사본도 새로 바뀐다)
#      - 결과/correction_log.csv → 바뀐 곳 1개마다 1줄: 규칙, 바꾸기 전·후, 그 부분이 들어 있는 문장(교정 전·후)
#        (발표 자료용 전후 비교. 규칙은 위에서부터 차례로 적용되므로, 한 문장에 여러 규칙이 걸리면 단계별로 남는다)
#
# 다음 단계(전체 데이터 합친 뒤): 불용어 제거, 토큰화, 동의어 통일 → 이 파일에서는 하지 않음
# =============================================================

import csv
import os
import re
import shutil
from collections import Counter

from kiwipiepy import Kiwi

# 경로: 이 파일 위치를 기준으로 잡아서, 어느 폴더에서 실행해도 같은 파일을 읽고 쓴다
HERE = os.path.dirname(os.path.abspath(__file__))                      # preprocessing/1_개인교정
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))                  # 프로젝트 맨 위 폴더
RESULT_DIR = os.path.join(HERE, "결과")
INPUT_FILES = [os.path.join(PROJECT_ROOT, "output", "naver_map_reviews.csv"),
               os.path.join(PROJECT_ROOT, "output", "google_map_reviews.csv")]
LOG_FILE = os.path.join(RESULT_DIR, "correction_log.csv")
# 통합 단계 입력 폴더에 복사할 이름 (팀 규칙: 플랫폼약어_플랫폼명_이니셜.csv)
MERGE_INPUT_DIR = os.path.join(os.path.dirname(HERE), "2_통합", "입력")
MERGE_INPUT_NAMES = {"naver_map_reviews.csv": "NM_네이버지도_DH.csv",
                     "google_map_reviews.csv": "GM_구글맵_DH.csv"}
MANUAL_FIXES_FILE = os.path.join(HERE, "manual_fixes.csv")   # 수동 교정 목록 (review_id, 바꾸기_전, 바꾼_후, 메모) — 엑셀로 줄을 추가하면 됨

# -------------------------------------------------------------
# Kiwi 사용자 사전: 띄어쓰기 교정 때 잘못 쪼개지지 않게 할 호텔·여행 용어
# (예: 사전에 없으면 '키즈프렌들리'가 '키즈프렌들 리'로 나뉨)
# -------------------------------------------------------------
USER_WORDS = [
    "호캉스", "키즈프렌들리", "인피니티풀", "릴랙세이션풀", "레이트체크아웃", "얼리체크인", "체크인", "체크아웃",
    "이그제큐티브", "라운지", "해피아워", "턴다운", "어메니티", "웰컴드링크", "룸서비스", "인룸다이닝", "피트니스",
    "스위트룸", "디럭스", "키즈클럽", "키즈카페", "루프탑", "오션뷰", "시티뷰", "리버뷰", "한강뷰", "남산뷰", "파크뷰",
    "조식뷔페", "뷔페", "레지던스", "발렛", "발레파킹", "업그레이드", "컨시어지", "프론트",
    "반얀트리", "시그니엘", "워커힐", "파르나스", "앰배서더", "이스트폴", "드래곤시티", "콘래드", "포시즌스",
    "메리어트", "하얏트", "안다즈", "몬드리안", "소피텔", "노보텔", "페어몬트", "메이필드", "오크우드", "웨스틴",
    "인터컨티넨탈", "더플라자", "롯데월드", "롯데호텔", "조선팰리스", "그랜드머큐어", "임피리얼팰리스",
]

# -------------------------------------------------------------
# 오탈자 규칙 (위에서부터 차례로 적용)
#   (규칙 이름, 찾을 패턴(정규식), 바꿀 내용)
#   - 뜻이 애매한 표현은 넣지 않았다. 예: '어떻게'와 '어떡해'가 모두 가능한 경우 등
# -------------------------------------------------------------
TYPO_RULES = [
    ("않+되/좋 → 안 되/좋", r"않\s?(?=[되돼좋])", "안 "),            # 방음이 않되요 → 방음이 안 되요(→ 아래 규칙으로 돼요)
    ("됬 → 됐", r"됬", "됐"),
    ("되있 → 돼 있", r"되\s?있", "돼 있"),                          # 청소가 안되있어서 → 안돼 있어서
    ("되요 → 돼요", r"되요", "돼요"),
    ("되서 → 돼서", r"되서", "돼서"),
    ("몇일 → 며칠", r"몇\s?일(?=[이을은에도간째]|\s|$|[.,!?~])", "며칠"),
    ("햇 → 했", r"(?<=[가-힣])햇(?=[어고는다던지습음으])", "했"),       # 친절햇어요 → 친절했어요 (햇살·햇빛은 안 바뀜)
    ("셧 → 셨", r"(?<=[가-힣])셧(?=[어고는다던지습음])", "셨"),         # 하셧어요 → 하셨어요
    ("앗 → 았", r"(?<=[가-힣])(?<!빼)앗(?=[어고는다던지습음])", "았"),   # 좋앗고 → 좋았고 (빼앗다는 제외)
    ("엇 → 었", r"(?<=[가-힣])(?<!무)엇(?=[어고는다던지습음])", "었"),   # 있엇어요 → 있었어요 (무엇은 제외)
    ("왓 → 왔", r"(?<=[가-힣])왓(?=[어고는다던지습음])", "왔"),           # 다녀왓어요 → 다녀왔어요
    ("잇 → 있", r"(?<=[가-힣])(?<!줄)잇(?=[어고는다던지습음])", "있"),   # 맛잇어요 → 맛있어요 (줄잇다 제외)
    ("밋 → 밌", r"(?<=[가-힣])밋(?=[어고는다던게지습음])", "밌"),         # 재밋게 → 재밌게
    ("어떻해 → 어떡해", r"어떻해", "어떡해"),
    ("오랫만 → 오랜만", r"오랫만", "오랜만"),
    ("금새 → 금세", r"금새", "금세"),
    ("웬지 → 왠지", r"웬지", "왠지"),
    ("왠만 → 웬만", r"왠만", "웬만"),
    ("왠일 → 웬일", r"왠일", "웬일"),
    ("어의없 → 어이없", r"어의\s?없", "어이없"),
    ("희안 → 희한", r"희안", "희한"),
    ("깨끗히 → 깨끗이", r"깨끗히", "깨끗이"),
    ("일일히 → 일일이", r"일일히", "일일이"),
    ("갯수 → 개수", r"갯수", "개수"),
    ("역활 → 역할", r"역활", "역할"),
    ("문안하 → 무난하", r"문안하", "무난하"),
    ("뵈요 → 봬요", r"뵈요", "봬요"),
    ("습니당 → 습니다", r"습니당", "습니다"),                           # 있습니당 → 있습니다 (담당자 검토로 추가)
    ("으루 → 으로", r"(?<=[가-힣])으루(?![가-힣])", "으로"),             # 정기적으루 → 정기적으로 (담당자 검토로 추가)
]


def has_rieul_batchim(syllable):
    """한글 한 글자의 받침이 'ㄹ'인지 (예: 올, 갈, 할 → True)"""
    code = ord(syllable) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 8


def has_batchim(syllable):
    code = ord(syllable) - 0xAC00
    return 0 <= code < 11172 and code % 28 != 0


# -------------------------------------------------------------
# 교정 기록: 바뀐 곳 1개마다 한 줄씩, 그 부분이 들어 있는 문장을 교정 전·후로 함께 남긴다
# -------------------------------------------------------------
SENTENCE_END = re.compile(r"[.!?\n]")
MAX_SENTENCE = 160   # 문장이 이보다 길면 바뀐 곳 앞뒤 60자만 보여 줌


def sentence_span(text, start, end):
    """text[start:end]가 들어 있는 문장의 시작·끝 위치 (마침표·물음표·느낌표·줄바꿈 기준)"""
    left = 0
    for m in SENTENCE_END.finditer(text, 0, start):
        left = m.end()
    m = SENTENCE_END.search(text, end)
    right = m.end() if m else len(text)
    if right - left > MAX_SENTENCE:
        left, right = max(left, start - 60), min(right, end + 60)
    return left, right


def record(changes, kind, rule, text, start, end, new):
    """바뀐 곳 1개를 기록한다. text는 이번 규칙을 적용하기 직전의 본문"""
    left, right = sentence_span(text, start, end)
    prefix = "…" if left > 0 and text[left - 1] not in ".!?\n" else ""
    suffix = "…" if right < len(text) and text[right - 1] not in ".!?\n" else ""
    changes.append({
        "종류": kind,
        "규칙": rule,
        "바꾸기_전": text[start:end],
        "바꾼_후": new,
        "문장_교정전": prefix + text[left:right].strip() + suffix,
        "문장_교정후": prefix + (text[left:start] + new + text[end:right]).strip() + suffix,
    })


def fix_lkke(text, changes):
    """'올께요·할께·갈꺼에요'처럼 ㄹ받침 뒤의 '께/꺼'를 '게/거'로 (선생님께 같은 조사는 받침이 ㄹ이 아니라 안 바뀜, '불꺼'·'분들께'는 제외)"""
    def repl(m):
        if m.group(2) == "꺼" and m.group(1) == "불":      # '불꺼 주세요'(불 끄다)는 오타가 아님
            return m.group(0)
        if m.group(2) == "께" and m.group(1) == "들":      # '분들께·손님들께'의 '께'는 높임 조사 (교정 기록 점검으로 발견)
            return m.group(0)
        if has_rieul_batchim(m.group(1)):
            new = m.group(1) + ("게" if m.group(2) == "께" else "거")
            record(changes, "오탈자", "ㄹ께/ㄹ꺼 → ㄹ게/ㄹ거", text, m.start(), m.end(), new)
            return new
        return m.group(0)
    return re.sub(r"([가-힣])(께|꺼)(?=요|\s|$|[.,!?~에])", repl, text)


def fix_eyo(text, changes):
    """받침 없는 명사 뒤 '에요'를 '예요'로 (최고에요 → 최고예요, 거에요 → 거예요). '아니에요·이에요'는 맞는 말이라 제외"""
    def repl(m):
        prev = m.group(1)
        if not has_batchim(prev) and prev not in ("니", "이"):
            new = prev + "예요"
            record(changes, "오탈자", "받침 없는 말 + 에요 → 예요", text, m.start(), m.end(), new)
            return new
        return m.group(0)
    return re.sub(r"([가-힣])에요", repl, text)


def fix_typos(text, changes):
    for name, pattern, new in TYPO_RULES:
        def repl(m, name=name, new=new, current=text):
            record(changes, "오탈자", name, current, m.start(), m.end(), new)
            return new
        text = re.sub(pattern, repl, text)
    text = fix_lkke(text, changes)
    text = fix_eyo(text, changes)
    return text


# 띄어쓰기 교정은 "한글이 이만큼 이상 띄어쓰기 없이 이어진 어절"에만 적용한다.
#   - 처음에 모든 어절에 적용했더니 '직원분들 → 직원 분들', '1층 → 1 층', '5성급 → 5 성급'처럼
#     붙여 써도 맞는 말이나 한 단어까지 쪼개는 경우가 많았다 (2026-10-15 점검)
#   - 띄어쓰기가 정말 문제인 경우는 '아이와겨울이용하기좋은수영장'처럼 길게 붙여 쓴 글이라 이것만 고친다
SPACING_MIN_HANGUL = 8

# Kiwi가 잘못 띄운 것을 다시 붙이는 목록 (띄어 쓴 모양 → 원래 모양)
REJOIN = [
    (r"(\d) (?=(층|성급|성|박|일|인|시|분|년|월|번|개|명|살|평|원|만원|호|동|번째)(?![가-힣]))", r"\1"),   # 1 층 → 1층
    (r"(\d) (?=[십백천만억])", r"\1"),                                       # 2 백만 원 → 2백만 원
    (r"(감사|추천|말씀|축하|부탁|인사|사과) 드(?=[리립렸려릴])", r"\1드"),   # '-드리다'는 붙여 씀 (추천드립니다)
    (r"해피 아워", "해피아워"), (r"애프터 눈", "애프터눈"), (r"끝 판", "끝판"),
    (r"고급 지", "고급지"), (r"굿 굿", "굿굿"), (r"룸 컨디션", "룸컨디션"), (r"클럽 라운지", "클럽라운지"),
]


def fix_spacing(kiwi, text, changes):
    """길게 붙여 쓴 어절만 띄어쓰기 교정 (줄바꿈·기존 띄어쓰기는 그대로)"""
    def fix_word(m):
        word = m.group(0)
        if not re.search("[가-힣]{%d,}" % SPACING_MIN_HANGUL, word):
            return word
        fixed = kiwi.space(word, reset_whitespace=False)
        for pattern, repl in REJOIN:
            fixed = re.sub(pattern, repl, fixed)
        if fixed != word:
            record(changes, "띄어쓰기", f"붙여 쓴 어절 띄우기 (+{fixed.count(' ')}칸)", text, m.start(), m.end(), fixed)
        return fixed
    return re.sub(r"\S+", fix_word, text)


def load_manual_fixes():
    """manual_fixes.csv → {review_id: [(바꾸기_전, 바꾼_후), ...]}"""
    fixes = {}
    if os.path.exists(MANUAL_FIXES_FILE):
        with open(MANUAL_FIXES_FILE, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                fixes.setdefault(row["review_id"], []).append((row["바꾸기_전"], row["바꾼_후"]))
    return fixes


def apply_manual_fixes(review_id, text, fixes, changes, not_found):
    """담당자가 지정한 부분을 그대로 바꾼다. 찾지 못하면 not_found에 남긴다 (자동 교정이 바뀌면 생길 수 있음)"""
    for before, after in fixes.get(review_id, []):
        start = text.find(before)
        if start < 0:
            not_found.append((review_id, before))
            continue
        record(changes, "수동 교정", "담당자 검토 목록 (manual_fixes.csv)", text, start, start + len(before), after)
        text = text[:start] + after + text[start + len(before):]
    return text


# 그림 이모지: 얼굴·손·하트·사물(1F000~1FAFF), 기호·딩뱃(☀♡★✨❤ 등, 2600~27BF),
#            화살표·별(⭐ 등), 시계(⌚ 등), 이모지 모양 바꾸는 보이지 않는 글자(FE0F, 200D, 20E3)
EMOJI = "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\u3030\u303D\u3297\u3299\uFE0F\u200D\u20E3\U000E0020-\U000E007F]"
# 문자 이모티콘: ^^ ^_^ ^-^ ^ㅡ^ (^^) :) :-) ;) :D <3
TEXT_EMOTICON = r"\(?\^[_\-ㅡ.ㅇo]?\^+\)?|(?<![0-9A-Za-z])[:;]-?[)(DP]+(?![0-9A-Za-z가-힣])|<3"
EMOTICON_RE = re.compile(f"(?:{EMOJI}|{TEXT_EMOTICON})+")


def remove_emoticons(text, changes):
    """이모티콘을 지운다. 지운 자리 양쪽이 글자로 붙어 버리면 띄어쓰기 한 칸을 남기고, 생긴 겹칸·줄 끝 칸은 정리한다"""
    def repl(m):
        removed = m.group(0)
        kind_rule = "그림 이모지" if re.search(EMOJI, removed) else "문자 이모티콘 (^^, :) 등)"
        left = text[m.start() - 1] if m.start() > 0 else " "
        right = text[m.end()] if m.end() < len(text) else " "
        rest = text[m.end():m.end() + 3]
        # 뒤가 조사로 시작하면 붙인다 (Sidecar🍸는 → Sidecar는). 그 밖에 양쪽이 글자로 붙으면 한 칸 띄운다 (좋아요👍최고 → 좋아요 최고)
        particle = re.match(r"(에서|에게|으로|까지|부터|처럼|이랑|[은는이가을를도에의와과로랑만])(?![가-힣])", rest)
        keep = " " if (not left.isspace() and not right.isspace() and not particle) else ""
        record(changes, "이모티콘 제거", kind_rule, text, m.start(), m.end(), keep)
        return keep
    new = EMOTICON_RE.sub(repl, text)
    if new == text:
        return text
    # 이모티콘이 있던 줄만 겹친 칸과 앞뒤 칸을 정리 (다른 줄의 원래 띄어쓰기는 그대로)
    old_lines, new_lines = text.split("\n"), new.split("\n")
    return "\n".join(re.sub(r"[ \t]{2,}", " ", n).strip() if n != o else n for o, n in zip(old_lines, new_lines))


LOG_FIELDS = ["review_id", "platform", "hotel_name", "종류", "규칙", "바꾸기_전", "바꾼_후", "문장_교정전", "문장_교정후"]


def main():
    kiwi = Kiwi()
    for word in USER_WORDS:
        kiwi.add_user_word(word, "NNP")

    manual_fixes = load_manual_fixes()
    not_found = []
    emptied = []
    log_rows = []
    for path in INPUT_FILES:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        os.makedirs(RESULT_DIR, exist_ok=True)
        out_path = os.path.join(RESULT_DIR, os.path.basename(path).replace(".csv", "_pre-processed.csv"))
        by_rule = Counter()
        spaces = 0
        changed = 0
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames + ["text_clean"])
            writer.writeheader()
            for row in rows:
                changes = []
                text = fix_typos(row["review_text_raw"], changes)
                text = fix_spacing(kiwi, text, changes)
                text = apply_manual_fixes(row["review_id"], text, manual_fixes, changes, not_found)
                text = remove_emoticons(text, changes)
                if not text.strip():
                    emptied.append(row["review_id"])      # 이모티콘만 있던 리뷰 (빈 본문이 됨)
                is_changed = text != row["review_text_raw"]
                changed += is_changed
                writer.writerow({**row, "text_clean": text})
                for c in changes:
                    if c["종류"] == "띄어쓰기":
                        by_rule["띄어쓰기: 붙여 쓴 어절 띄우기"] += 1
                        spaces += c["바꾼_후"].count(" ")
                    elif c["종류"] in ("수동 교정", "이모티콘 제거"):
                        by_rule[c["종류"] + ": " + c["규칙"]] += 1
                    else:
                        by_rule[c["규칙"]] += 1
                    log_rows.append({"review_id": row["review_id"], "platform": row["platform"],
                                     "hotel_name": row["hotel_name"], **c})

        print(f"[{os.path.basename(path)}] {len(rows)}건 중 {changed}건 교정 → {out_path}")
        # 통합 단계 입력 폴더에도 같은 파일을 복사
        os.makedirs(MERGE_INPUT_DIR, exist_ok=True)
        copy_path = os.path.join(MERGE_INPUT_DIR, MERGE_INPUT_NAMES[os.path.basename(path)])
        shutil.copyfile(out_path, copy_path)
        print(f"    통합 입력 폴더에 복사 → {copy_path}")
        for rule, n in by_rule.most_common():
            print(f"    {rule}: {n}곳" + (f" (띄어쓰기 {spaces}칸 추가)" if rule.startswith("띄어쓰기") else ""))

    with open(LOG_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(log_rows)
    print(f"\n교정 기록: {LOG_FILE} (바뀐 곳 {len(log_rows)}개, 1곳당 1줄)")
    if not_found:
        print(f"!! 수동 교정 목록에서 찾지 못한 부분 {len(not_found)}개: {not_found}")
    if emptied:
        print(f"!! 이모티콘을 지웠더니 본문이 비어 버린 리뷰 {len(emptied)}건: {emptied}")


if __name__ == "__main__":
    main()
