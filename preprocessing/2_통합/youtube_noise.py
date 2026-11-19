# =============================================================
# 유튜브 노이즈 댓글 판정 (is_noise)
#
# 실행:  python preprocessing/2_통합/youtube_noise.py   → 규칙 판정과 최종 판정 비교표 출력 (발표 자료용)
#        (통합 전처리 preprocess_merge.py가 이 파일의 기능을 불러 씀)
#
# 왜 필요한가
#   유튜브 댓글은 호텔 리뷰 영상에 달린 글이라, 호텔 이야기가 아닌 댓글이 많다.
#   ("영상 잘 봤어요", "구독했어요", "신라면 먹으면서 봅니다", "언젠가 가보고 싶네요")
#
# 판정 기준 (2026-10-18 팀 결정)
#   노이즈 ─ 채널 반응 : 영상·유튜버·구독·퀴즈·이벤트에 대한 말만 있고 호텔 내용이 없음
#          ─ 무관      : 호텔과 관계없는 이야기 (집밥·다른 식당·농담·잡담)
#          ─ 미경험 희망: "가보고 싶다", "맛있겠다", "대리만족" 같은 희망·감탄만 있고 경험이나 구체적 평가가 없음
#   유지   ─ 호텔(객실·식음·서비스·시설·가격·위치 등)에 대한 경험, 평가, 정보, 의견 (호텔 일반론 포함)
#          ─ 가격·가치 이야기는 경험이 없어도 유지 ("19만원은 너무 비싸다") — 과제 주제(가격만큼의 가치)와 직결
#          ─ 채널 말이 섞여 있어도 호텔 내용이 있으면 유지
#
# 판정 방법
#   1) 규칙(아래 키워드)으로 1차 판정: 유지 / 노이즈 / 애매
#   2) Claude가 2,641건을 모두 읽고 위 기준으로 최종 판정 → 사전/yt_labels.csv 에 고정
#      (규칙이 틀린 것은 고치고, 애매한 것은 판정. 판정 방법 칼럼에 어느 경우인지 남김)
#   → 같은 입력이면 매번 같은 결과. 라벨 파일에 없는 새 댓글은 규칙으로만 판정(애매 → 유지)하고 경고를 출력한다.
# =============================================================

import csv
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LABEL_FILE = os.path.join(HERE, "사전", "yt_labels.csv")
INPUT_FILE = os.path.join(HERE, "입력", "YT_유튜브_CH.csv")

# 호텔 요소 (객실·시설·식음·서비스·가격)
ASPECT = re.compile(
    r"객실|룸|침대|침구|베개|욕실|화장실|욕조|어메니티|전망|야경|수영장|인피니티|피트니스|헬스장|사우나|스파|라운지|조식"
    r"|체크인|체크아웃|컨시어지|발렛|주차|로비|청결|깨끗|더럽|냄새|소음|방음|시끄|직원|서비스|친절|응대|호캉스|투숙|숙박"
    r"|1박|묵었|묵어|머물|스위트|업그레이드|인테리어|시설|위치|가격|비싸|비쌈|가성비|가심비|요금|뷔페|부페|음식|맛있|맛없"
    r"|맛이|레스토랑|다이닝|식당|메뉴|디저트|리뉴얼|리모델링|좁|넓")
# 채널·유튜버에게 하는 말
CHANNEL = re.compile(
    r"영상|구독|알림|편집|썸네일|브이로그|채널|조회수|유튜브|유튜버|축하|ㅊㅋ|응원|화이팅|파이팅|팬이|목소리|자막|브금|BGM"
    r"|[가-힣]{1,4}님|[가-힣]{1,3}형(이|은|님|아|\b)|언니|누나|1등|첫\s?댓|잘 ?보고|잘 ?봤|보고 ?갑니다|기다렸|업로드"
    r"|다음 ?편|컨텐츠|콘텐츠|리뷰 ?(해|부탁|감사)")
# 희망·감탄 (미경험)
WISH = re.compile(
    r"가보고 ?싶|가 보고 ?싶|가봐야|가 봐야|가고 ?싶|먹어 ?보고 ?싶|먹고 ?싶|언젠가|죽기 ?전에|대리만족|보기만 해도|군침"
    r"|배고프|배고파|부럽|좋아 ?보이|맛있어 ?보|맛있겠")
# 직접 경험
EXPERIENCE = re.compile(
    r"가봤|가 봤|가보니|가 보니|다녀왔|다녀옴|다녀온|갔었|갔는데|갔다가|갔을 ?때|가봄|갔다 ?왔|묵었|투숙했|숙박했|머물렀"
    r"|먹어 ?봤|먹었는데|먹었어|먹었습|먹고 ?왔|이용했|이용해 ?봤|예약했|결혼식|돌잔치|상견례|근무|일했|직원입니다|직원이었|직원이였")
MIN_LEN = 15                     # 이보다 짧고 호텔 요소·경험이 없으면 노이즈


def one_line(text):
    return re.sub(r"\s+", " ", text or "").strip()


def rule_label(text):
    """규칙 1차 판정: '유지' / '노이즈' / '애매'"""
    t = one_line(text)
    aspect, channel, wish, exper = (bool(p.search(t)) for p in (ASPECT, CHANNEL, WISH, EXPERIENCE))
    if aspect and not channel and not wish and len(t) >= MIN_LEN:
        return "유지"
    if (channel or wish) and not aspect and not exper:
        return "노이즈"
    if len(t) < MIN_LEN and not aspect and not exper:
        return "노이즈"
    return "애매"


def snippet(text, n=40):
    return one_line(text)[:n]


def load_labels():
    """사전/yt_labels.csv → {review_id: 라벨 행}"""
    if not os.path.exists(LABEL_FILE):
        return {}
    with open(LABEL_FILE, encoding="utf-8-sig", newline="") as f:
        return {r["review_id"]: r for r in csv.DictReader(f)}


def judge(review_id, text, labels):
    """
    유튜브 댓글 1건 판정 → (is_noise 'Y'/'N', 노이즈 유형, 판정 방법)
    라벨 파일에 있고 본문이 같으면 라벨을, 없으면 규칙을 쓴다.
    """
    lab = labels.get(review_id)
    if lab and lab["본문_앞부분"] == snippet(text):
        return ("Y" if lab["최종_판정"] == "노이즈" else "N"), lab["노이즈_유형"], lab["판정_방법"]
    rule = rule_label(text)
    if rule == "노이즈":
        return "Y", "규칙", "규칙만(라벨 없음)"
    return "N", "", "규칙만(라벨 없음)"


def main():
    """규칙 1차 판정과 최종 판정 비교 (발표 자료용)"""
    labels = load_labels()
    with open(INPUT_FILE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    table = Counter()
    for r in rows:
        lab = labels.get(r["review_id"])
        final = lab["최종_판정"] if lab and lab["본문_앞부분"] == snippet(r["review_text_raw"]) else "(라벨 없음)"
        table[(rule_label(r["review_text_raw"]), final)] += 1
    print(f"유튜브 댓글 {len(rows):,}건 — 규칙 1차 판정 × 최종 판정")
    print(f"{'규칙':<6}{'최종 유지':>10}{'최종 노이즈':>12}{'라벨 없음':>10}")
    for rule in ("유지", "노이즈", "애매"):
        print(f"{rule:<6}{table[(rule, '유지')]:>10,}{table[(rule, '노이즈')]:>12,}{table[(rule, '(라벨 없음)')]:>10,}")
    decided = sum(table[(r, f)] for r in ("유지", "노이즈") for f in ("유지", "노이즈"))
    agree = table[("유지", "유지")] + table[("노이즈", "노이즈")]
    if decided:
        print(f"규칙이 유지/노이즈로 정한 {decided:,}건 중 최종과 같은 것 {agree:,}건 ({agree / decided:.0%})")
    kinds = Counter(lab["노이즈_유형"] for lab in labels.values() if lab["최종_판정"] == "노이즈")
    print("노이즈 유형:", dict(kinds))


if __name__ == "__main__":
    main()
