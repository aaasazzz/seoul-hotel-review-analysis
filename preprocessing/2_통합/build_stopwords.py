# =============================================================
# 불용어 목록 만들기 → 사전/stopwords_hotel.csv
#
# 실행:  python preprocessing/2_통합/build_stopwords.py
#
# 하는 일
#   1) 교수님 경영 불용어사전 원본(수정하지 않음)을 읽어 우리 토큰 형태에 맞게 조정한다
#      - 앞뒤 공백 제거, 중복 제거
#      - 활용형은 Kiwi로 분석해 토큰 형태로 바꾼다 (있었습니다 → 있다, 같아요 → 같다)
#      - 조사·어미만으로 된 항목(에, 을, 습니까)은 품사 거르기에서 이미 빠지므로 '불필요'로 표시
#      - 여러 단어 구절(그렇게 함으로써)은 토큰과 형태가 달라 '적용 불가'로 표시
#      - 자동 변환이 잘못됐거나 지우면 안 되는 말이 되면(BLOCKED_FORMS), 또는 한 글자가 되면(게나 → 게) 적용하지 않는다
#      - 분석에 필요한 단어(KEEP_WORDS)는 '제외'로 표시하고 이유를 남긴다
#   2) 호텔 도메인 불용어, 데이터별 불용어, 호텔 이름을 덧붙인다
#   → 결과: 단어(원본), 적용형태, 출처, 사용(Y/N), 이유
#
# 목록을 바꾸고 싶으면 아래 KEEP_WORDS / DOMAIN_WORDS / SOURCE_WORDS / HOTEL_NAME_WORDS를 고치고 다시 실행한다.
# =============================================================

import csv
import os
import re

from kiwi_tokens import DICT_DIR, make_kiwi, tokens_with_negation

ORIGINAL = os.path.join(DICT_DIR, "교수님_경영불용어사전_원본.csv")
OUTPUT = os.path.join(DICT_DIR, "stopwords_hotel.csv")

# 교수님 사전에 있지만 호텔 리뷰 분석에 필요해서 남기는 단어 (토큰 형태 → 이유)
KEEP_WORDS = {
    "아이": "가족 여행('아이와 함께') 주제 — 지도·구글 리뷰에만 986회",
    "다시": "재방문 의사('다시 방문하고 싶다') — 만족도의 직접 지표",
    "소리": "방음·소음 불만('기침소리까지 다 들리는')",
    "공기": "객실 공기·환기 불만",
    "못하다": "부정 표현 — 지우면 의미가 뒤집힘",
    "특히": "강조 — 무엇이 특히 좋았/나빴는지",
    "정말": "강조 — 감성 강도",
    "훨씬": "비교 — 다른 호텔·기대와의 비교",
    "다소": "약한 불만('다소 아쉬웠다')",
    "걸리다": "대기 시간 불만('체크인이 오래 걸렸다')",
    "비교적": "비교 평가('비교적 깨끗')",
    "겨우": "불만·아쉬움('겨우 체크인했다')",
    "가득": "혼잡 불만('사람이 가득')",
    "바로": "위치·접근성('역과 바로 연결', '바로 앞')",
}

# 교수님 사전 항목을 Kiwi로 토큰 형태로 바꿨을 때 잘못 바뀌었거나, 지우면 의미 있는 말까지 사라지는 경우
BLOCKED_FORMS = {
    "거들다": "'거든'을 잘못 분석한 결과",
    "슬다": "'습니까'를 잘못 분석한 결과",
    "기여": "'어기여차'를 잘못 분석한 결과 — '기여'(공헌)가 지워짐",
    "멀다": "'먼가'에서 나온 형태 — 위치 불만('역에서 멀다')이 지워짐",
    "들다": "'드네·듭니다'에서 나온 형태 — 만족 표현('마음에 들다')과 비용('돈이 들다')이 지워짐",
    "이상": "'이상'(~보다 많음)을 지우면 불만 표현('이상한 냄새')까지 지워짐",
    "다르다": "실망 표현('사진과 다르다', '기대와 다르다')이 지워짐",
    "입장": "'입장에서'의 입장을 지우면 시설 이용('수영장 입장 제한')까지 지워짐",
}

# 호텔 리뷰 어디에나 나와서 의미가 없는 말
DOMAIN_WORDS = ["호텔", "숙박", "투숙", "방문", "이용", "서울", "박", "원", "숙소"]

# 한 글자라 교수님 사전에서는 안전 규칙으로 빠졌지만, 1차 실행 결과 상위에 남은 기능어 (직접 확인해서 고름)
# 방·물·바·풀·창·향·층·킹처럼 뜻이 있는 한 글자는 넣지 않는다
ONE_CHAR_WORDS = ["인", "전", "후", "점", "일", "말", "속", "위", "다", "더", "및", "또", "때", "곳", "안", "날", "분", "건"]

# 데이터별로 나오는 군더더기 말
SOURCE_WORDS = {
    "블로그": ["포스팅", "이웃", "공감", "블로그", "댓글", "구독", "사진", "후기", "찍다", "참고", "정보", "글"],
    "유튜브": ["영상", "구독", "님", "채널", "유튜버", "브이로그"],
}

# 호텔 이름 (어느 호텔인지는 hotel_std 컬럼에 남으므로 토큰에서는 뺀다)
# '그랜드', '파크', '코엑스', '롯데월드'처럼 일반 단어·장소로도 쓰이는 말은 넣지 않는다
HOTEL_NAME_WORDS = [
    "신라", "신라호텔", "서울신라호텔", "롯데", "롯데호텔", "더그랜드롯데", "플라자", "더플라자", "웨스틴", "조선", "조선호텔", "앰버서더",
    "조선팰리스", "반얀트리", "앰배서더", "풀만", "포시즌스", "포시즌", "메리어트", "jw", "하얏트", "그랜드하얏트", "파크하얏트",
    "그랜드", "몬드리안", "머큐어", "그랜드머큐어", "노보텔", "드래곤시티", "안다즈", "인터컨티넨탈", "파르나스", "임피리얼", "임피리얼팰리스",
    "오크우드", "시그니엘", "소피텔", "워커힐", "이스트폴", "콘래드", "페어몬트", "메이필드",
    "shilla", "lotte", "signiel", "hyatt", "marriott", "westin", "pullman", "sofitel", "novotel", "conrad", "fairmont", "andaz",
]


def main():
    kiwi = make_kiwi()
    with open(ORIGINAL, encoding="utf-8-sig", newline="") as f:
        original = [r["word"] for r in csv.DictReader(f)]

    rows, seen_word, applied = [], set(), {}
    for raw in original:
        word = raw.strip()
        if not word:
            continue
        if word in seen_word:
            rows.append({"단어": raw, "적용형태": "", "출처": "교수님 사전", "사용": "N", "이유": "중복 항목"})
            continue
        seen_word.add(word)
        note = "끝 공백 정리 · " if raw != word else ""

        if " " in word:
            rows.append({"단어": raw, "적용형태": "", "출처": "교수님 사전", "사용": "N",
                         "이유": note + "여러 단어 구절 — 토큰과 형태가 달라 적용 불가"})
            continue
        toks = tokens_with_negation(kiwi.tokenize(word))
        if not toks:
            rows.append({"단어": raw, "적용형태": "", "출처": "교수님 사전", "사용": "N",
                         "이유": note + "조사·어미·기호 — 품사 거르기에서 이미 빠짐"})
            continue
        if len(toks) > 1:
            rows.append({"단어": raw, "적용형태": " ".join(toks), "출처": "교수님 사전", "사용": "N",
                         "이유": note + "토큰 여러 개로 나뉨 — 그대로 적용하면 다른 단어까지 지워짐"})
            continue
        form = toks[0]
        if form.startswith(("안_", "못_")):
            rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "N",
                         "이유": note + "부정 표현은 지우지 않음 (의미가 뒤집힘)"})
            continue
        if form in BLOCKED_FORMS:
            rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "N",
                         "이유": note + "자동 변환 결과를 쓰지 않음: " + BLOCKED_FORMS[form]})
            continue
        if len(form) == 1:
            rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "N",
                         "이유": note + "한 글자 토큰 — 뜻이 여러 개라(게=꽃게, 다=모두) 적용하면 다른 뜻까지 지워짐"})
            continue
        if form in KEEP_WORDS:
            rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "N",
                         "이유": note + "분석에 필요해 제외: " + KEEP_WORDS[form]})
            continue
        if form in applied:
            rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "N",
                         "이유": note + f"같은 토큰 형태가 이미 있음 ('{applied[form]}')"})
            continue
        applied[form] = word
        rows.append({"단어": raw, "적용형태": form, "출처": "교수님 사전", "사용": "Y",
                     "이유": note + ("활용형 → 토큰 형태로 변환" if form != word else "")})

    def add(words, source, reason):
        for w in words:
            if w in applied:
                continue
            applied[w] = w
            rows.append({"단어": w, "적용형태": w, "출처": source, "사용": "Y", "이유": reason})

    add(DOMAIN_WORDS, "호텔 도메인", "호텔 리뷰 어디에나 나와 의미 없음")
    add(ONE_CHAR_WORDS, "한 글자 기능어", "1차 실행 결과 상위에 남은 뜻 없는 한 글자 (직접 확인)")
    # 데이터별 불용어는 그 데이터에만 적용된다 (예: 블로그의 '사진'은 지우고, 리뷰의 '사진과 다르다'는 남김)
    for src, words in SOURCE_WORDS.items():
        for w in words:
            if w in applied and not applied[w].startswith("데이터별"):
                continue
            rows.append({"단어": w, "적용형태": w, "출처": f"데이터별({src})", "사용": "Y",
                         "이유": f"{src} 글의 군더더기 표현 — {src}에만 적용"})
            applied.setdefault(w, f"데이터별({src})")
    add(HOTEL_NAME_WORDS, "호텔 이름", "호텔은 hotel_std 컬럼에 남으므로 토큰에서 제외")

    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["단어", "적용형태", "출처", "사용", "이유"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    prof = [r for r in rows if r["출처"] == "교수님 사전"]
    print(f"교수님 사전 {len(original)}개 → 사용 {sum(r['사용'] == 'Y' for r in prof)}개")
    for reason, n in Counter(re.sub(r"^끝 공백 정리 · ", "", r["이유"]).split(":")[0].split(" — ")[0] or "그대로 사용"
                             for r in prof).most_common():
        print(f"  {reason}: {n}")
    print(f"추가: 도메인·데이터별·호텔 이름 {len(rows) - len(prof)}개 / 최종 사용 {sum(r['사용'] == 'Y' for r in rows)}개 → {OUTPUT}")


if __name__ == "__main__":
    main()
