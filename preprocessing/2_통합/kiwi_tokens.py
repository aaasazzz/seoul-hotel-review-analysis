# =============================================================
# 토큰화 공통 기능 (preprocess_merge.py, build_stopwords.py가 함께 씀)
#   - 공백 정리 · 반복 문자 줄이기
#   - Kiwi 준비 (사용자 사전 등록)
#   - 형태소 → 토큰: 남길 품사만, 동사·형용사는 원형("좋다"), 접두사 붙이기("불친절"), 부정어 묶기("안_좋다")
# =============================================================

import csv
import os
import re
from collections import namedtuple

from kiwipiepy import Kiwi

HERE = os.path.dirname(os.path.abspath(__file__))
DICT_DIR = os.path.join(HERE, "사전")

# ㅋㅋ·ㅎㅎ·ㅠㅠ·ㅜㅜ 같은 자모 표현 (키위는 기호(SW)로 분류하므로 따로 남긴다)
JAMO_EXPR = re.compile(r"[ㅋㅎㅠㅜ]+")


# -------------------------------------------------------------
# ② 공백 정리 · ③ 반복 문자 줄이기
# -------------------------------------------------------------
def normalize_text(text):
    """불필요한 공백만 정리하고, 같은 글자가 3번 이상 반복되면 2번으로 줄인다. (오탈자는 고치지 않음)"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t 　]+", " ", text)        # 여러 칸 공백·탭 → 한 칸
    text = re.sub(r" *\n *", "\n", text)                     # 줄 앞뒤 공백 제거
    text = re.sub(r"\n{3,}", "\n\n", text)                   # 빈 줄 여러 개 → 하나
    text = text.strip()
    # 숫자는 줄이지 않는다 (1000원 → 100원이 되면 안 되므로)
    text = re.sub(r"([^\d\s])\1{2,}", r"\1\1", text)         # ㅋㅋㅋㅋ→ㅋㅋ, !!!!→!!
    return text


# -------------------------------------------------------------
# ④ Kiwi 준비
# -------------------------------------------------------------
def make_kiwi():
    kiwi = Kiwi(num_workers=-1)        # 모든 CPU 코어 사용
    path = os.path.join(DICT_DIR, "user_dict.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            kiwi.add_user_word(row["단어"].strip(), row["품사"].strip() or "NNG", 0)
    return kiwi


def is_predicate(tok):
    """동사·형용사(불규칙 활용 포함)"""
    return tok.tag.startswith("VV") or tok.tag.startswith("VA")


def clean_form(form):
    """토큰 글자 안의 공백 제거 (키위 기본 사전의 '인피니티 풀' 같은 띄어 쓴 고유명사 → 인피니티풀)"""
    return form.replace(" ", "")


def base_form(tok):
    """동사·형용사는 원형으로 (맛있었어요 → 맛있다), 명사·어근은 그대로 (깔끔하다 → 깔끔)"""
    return clean_form(tok.form) + ("다" if is_predicate(tok) else "")


def keep_token(tok):
    """남길 품사면 토큰 글자를, 아니면 None을 돌려준다."""
    tag = tok.tag
    if tag in ("NNG", "NNP", "XR", "MAG"):
        return clean_form(tok.form)
    if is_predicate(tok):
        return base_form(tok)
    if tag == "SL":                                   # 영어
        return tok.form.lower()
    if tag == "SW" and JAMO_EXPR.fullmatch(tok.form):  # ㅋㅋ ㅎㅎ ㅠㅠ ㅜㅜ
        return tok.form
    if tag == "W_HASHTAG":                            # #호캉스 → 호캉스
        word = tok.form.lstrip("#").lower()
        return word or None
    return None                                       # 조사·어미·접사·문장부호·숫자·URL·타임스탬프 등


# 접두사를 붙인 형태소 (키위 Token 대신 쓰는 간단한 묶음: 글자와 품사만 있으면 됨)
Morph = namedtuple("Morph", ["form", "tag"])


def attach_prefixes(toks):
    """
    접두사(XPN)를 바로 뒤 명사·어근에 붙인다. 키위는 '불친절'을 불(접두사) + 친절로 나누는데,
    접두사는 품사 거르기에서 빠지므로 그대로 두면 뜻이 뒤집힌다.
      불친절 → 불친절 (안 붙이면 '친절')   무제한 → 무제한 (안 붙이면 '제한')   불가능 → 불가능 (안 붙이면 '가능')
      숫자 + 성급도 붙인다: 5성급 (안 붙이면 '성급')
      대만족 · 최고급 · 한복판 · 생맥주 · 재입장 도 한 단어로 남는다
    """
    out = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        # 숫자 + 성급: 5성급 (그대로 두면 숫자는 빠지고 '성급(하다)'만 남음)
        if t.tag == "SN" and i + 1 < n and toks[i + 1].form == "성급" \
                and getattr(t, "start", 0) + getattr(t, "len", 0) == getattr(toks[i + 1], "start", 0):
            out.append(Morph(t.form + "성급", "NNG"))
            i += 2
            continue
        if t.tag == "XPN" and i + 1 < n and toks[i + 1].tag in ("NNG", "NNP", "XR") \
                and getattr(t, "start", 0) + getattr(t, "len", 0) == getattr(toks[i + 1], "start", 0):
            out.append(Morph(t.form + toks[i + 1].form, toks[i + 1].tag))
            i += 2
            continue
        out.append(t)
        i += 1
    return out


# '안 되다'가 부정이 아닌 경우: 얼마 안 돼서(곧) · 몇 안 되는(적은) · 1시간밖에 안 돼서(겨우)
NOT_NEGATION_BEFORE = {("얼마", "NNG"), ("몇", "MM"), ("밖에", "JX"), ("오래", "MAG")}   # 오래되지 않았다(= 최근)도 포함
# 서술어 뒤에 붙는 보조용언: 잘되어 있지 않다 · 옮겨 주지 않다 · 켜지지 않다 · 오고 싶지 않다 → 본동사에 부정을 붙인다
AUX_ENDINGS = {"어", "아", "여", "게", "고"}
AUX_VERBS = {"있", "주", "보", "지", "버리", "놓", "두", "드리", "내", "싶", "가", "오", "계시"}
# '~ㄹ 수/것/데 … 없다'처럼 앞 서술어에 부정을 붙이는 말
#   수 → 못_X (먹을 수 없다),  나머지 → 안_X (나무랄 것 없다 · 흠잡을 데 없다 · 아쉬운 점이 없다 · 걱정할 필요 없다 · 갈 일 없다)
GENERIC_NOUNS = {"수", "것", "거", "데", "나위", "리", "점", "곳", "부분", "필요", "일", "적"}   # 적: 실망한 적 없다
# 반어(뜻은 긍정): 좋지 않을까 · 장점이지 않을까 · 좋지 않나 싶다 · ~하는 게 아닌가 싶다 · 이곳이 아닐까요
RHETORICAL_ENDINGS = {"을까", "ᆯ까", "ᆫ가", "는가"}


def is_josa(tok):
    return tok.tag.startswith("J")


def is_absent(tok):
    """없다 · 없이"""
    return (tok.form == "없" and tok.tag.startswith("VA")) or (tok.form == "없이" and tok.tag == "MAG")


def is_doeda(tok):
    """'되다' (키위는 붙여 쓴 '안돼서'의 되를 접미사(XSV·XSA)로 분류하기도 함)"""
    return tok.form == "되" and (tok.tag.startswith("VV") or tok.tag in ("XSV", "XSA"))


def skip_between(toks, j, josa=2, mag=2):
    """조사 · 부사 · '하나(도)'를 건너뛴 위치. 부정어(안 · 못 · 없이)는 건너뛰지 않는다.
       (이용료가 따로 없고 · 조식에는 없다 · 냄새 하나도 없다 · 재방문 의사 절대 없어요 · 불편함은 크게 없었다)"""
    n = len(toks)
    for _ in range(5):
        if j < n and josa and is_josa(toks[j]):
            josa -= 1
            j += 1
        elif j < n and mag and toks[j].tag == "MAG" and toks[j].form not in ("안", "못", "없이"):
            mag -= 1
            j += 1
        elif j + 1 < n and mag and toks[j].tag.startswith("VA") and toks[j].form != "없" \
                and toks[j + 1].form == "게" and toks[j + 1].tag.startswith("EC"):
            mag -= 1                                                # 크게 · 딱히 같은 부사형
            j += 2
        elif j < n and toks[j].tag == "NR" and toks[j].form == "하나":
            j += 1
        elif j + 1 < n and toks[j].tag == "SN" and toks[j].form in ("1", "0") and toks[j + 1].form == "도":
            j += 2                                                  # 1도 없다 (전혀 없다)
        else:
            break
    return j


def is_rhetorical(toks, e):
    """toks[e]부터(선어말어미는 건너뜀) 반어 어미가 오는지: ~지 않을까 · ~지 않나 싶다 · ~아닌가 싶다 · ~아닐까요"""
    n = len(toks)
    while e < n and toks[e].tag == "EP":
        e += 1
    if e >= n:
        return False
    if toks[e].form in RHETORICAL_ENDINGS:
        return True
    return toks[e].form == "나" and e + 1 < n and toks[e + 1].form == "싶"


def predicate_end(toks, i):
    """
    toks[i]에서 시작하는 서술어가 끝난 다음 위치. 서술어가 아니면 -1.
      좋 → 1칸 / 깔끔+하 → 2칸 / 친절+하+시 → 높임·시제(선어말어미)까지 / 되+어+있 → 보조용언까지
    """
    t, n = toks[i], len(toks)
    if is_predicate(t):
        j = i + 1
    elif t.tag in ("XR", "NNG") and i + 1 < n and toks[i + 1].tag.startswith("XS"):
        j = i + 2
    elif t.tag == "MAG" and t.form not in ("안", "못") and i + 1 < n and toks[i + 1].tag.startswith("XSA"):
        j = i + 2                                                   # 호락호락+하
    else:
        return -1
    while j < n:
        if toks[j].tag == "EP":
            j += 1
        elif j + 2 < n and toks[j].tag == "ETM" and toks[j + 1].form == "만" and toks[j + 1].tag == "NNB" \
                and toks[j + 2].form == "하" and toks[j + 2].tag.startswith("XS"):
            j += 3                                                  # 먹을 만하다 → 먹다 (먹을 만한 게 없다 → 안_먹다)
        elif j + 1 < n and toks[j].tag.startswith("EC") and toks[j].form in AUX_ENDINGS \
                and toks[j + 1].tag.startswith("VX") and toks[j + 1].form in AUX_VERBS:
            j += 2
        else:
            break
    return j


def negation_after_ji(toks, j):
    """
    toks[j]가 '지'이고 뒤에 부정이 오면 (접두, 끝 위치, 반어 여부), 아니면 None.
      좋지 않다 · 좋지는 않다 · 나오질 않다 · 알지 못하다 · 알지 못 하다 · 가지 마세요
    """
    n = len(toks)
    if j < n and toks[j].form == "지만" and toks[j].tag.startswith("EC") and j + 1 < n \
            and toks[j + 1].tag.startswith("VX") and toks[j + 1].form == "않":
        return "안_", j + 2, is_rhetorical(toks, j + 2)            # 예민하지만 않으시다면 (키위가 지+만을 '지만'으로 분석)
    if not (j < n and toks[j].form == "지" and toks[j].tag.startswith("EC")):
        return None
    k = j + 1
    if k < n and ((toks[k].tag in ("JX", "JKS", "Z_CODA") and toks[k].form in ("는", "ᆫ", "도", "만", "가"))
                  or (toks[k].tag == "JKO" and toks[k].form in ("ᆯ", "을", "를"))):
        k += 1
    if k < n and toks[k].tag.startswith("VX") and toks[k].form in ("않", "못하", "말"):
        prefix, end = ("못_" if toks[k].form == "못하" else "안_"), k + 1
    elif k + 1 < n and toks[k].tag == "MAG" and toks[k].form == "못" and toks[k + 1].form == "하" \
            and toks[k + 1].tag.startswith(("VV", "VX", "XS")):
        prefix, end = "못_", k + 2
    else:
        return None
    return prefix, end, is_rhetorical(toks, end)


def emit_negation(out, word, negation_counter):
    out.append(word)
    if negation_counter is not None:
        negation_counter[word] += 1


def tokens_with_negation(toks, negation_counter=None):
    """
    형태소 목록 → 토큰 목록. 따로 세면 뜻이 뒤집히는 표현은 하나로 묶는다.
      부정  안 좋았어요 · 좋지(는) 않았다 → 안_좋다      친절하시진 않으셨어요 → 안_친절
            청소가 잘되어 있지 않다 → 안_잘되다           옮겨 주지도 않는다 → 안_옮기다
            오고 싶지 않다 → 안_오다    가지 마세요 → 안_가다    먹을 수 없다 → 못_먹다
            수영장 이용 못 했다 → 못_이용    자극적이지 않다 → 안_자극    친절한 편은 아니다 → 안_친절
      없음  부담 없는 · 불편함 없이 · 이용료가 따로 없다 → 부담_없다 · 불편_없다 · 이용료_없다
            기다림 없이 → 안_기다리다   아쉬운 점이 없다 → 안_아쉽다   흠잡을 데 없다 → 안_흠잡다
      아님  무료가 아니다 · 장난 아니다 → 무료_아니다 · 장난_아니다
      긍정  만족할 수밖에 없다 → 만족   안 좋을 게 없다 → 좋다   맛이 없는 건 아니다 → 맛
            좋지 않을까 · 장점이지 않을까 · ~하는 게 아닌가 싶다 (반어) → 부정으로 묶지 않음
            더할 나위 없다 → 더할나위없다
    묶지 않는 것: 얼마 안 돼서 · 얼마 되지 않아 · 몇 안 되는 · 1시간밖에 안 돼서 (시간·수량 표현)
                  ~가 아니라 · ~뿐 아니라 · 아니면 (단순 부정이 아님)
    """
    toks = attach_prefixes(toks)
    out = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        # 0) 얼마 안 되다 · 몇 안 되다 · ~밖에 안 되다: 시간·수량 표현
        if t.tag == "MAG" and t.form == "안" and i > 0 and (toks[i - 1].form, toks[i - 1].tag) in NOT_NEGATION_BEFORE \
                and i + 1 < n and is_doeda(toks[i + 1]):
            i += 2
            continue
        if t.tag == "MAG" and t.form in ("안", "못") and i + 1 < n:
            nxt = toks[i + 1]
            # 1-0) 안 + 명사·어근 + 하다: 안 불편했다 → 안_불편
            if nxt.tag in ("NNG", "XR") and i + 2 < n and toks[i + 2].tag.startswith("XS"):
                emit_negation(out, f"{t.form}_{clean_form(nxt.form)}", negation_counter)
                i = predicate_end(toks, i + 1)
                continue
            # 1-1) 마음에 안 들다 (키위가 '들'을 보조용언으로 분류)
            if nxt.form == "들" and nxt.tag.startswith("VX"):
                emit_negation(out, f"{t.form}_들다", negation_counter)
                i += 2
                continue
            # 1-2) ~보다 못하다 (더 나쁘다): 모텔보다 못한 응대 → 못하다 / 못지 않다 (뒤지지 않다) → 못지않다
            if t.form == "못" and nxt.form == "하" and nxt.tag.startswith("XSA"):
                r = negation_after_ji(toks, i + 2)
                if r:
                    out.append("못지않다")
                    i = r[1]
                else:
                    out.append("못하다")
                    i += 2
                continue
            # 1) 안/못 + 동사·형용사 (안돼서처럼 붙여 쓴 '되'도 포함)
            if is_predicate(nxt) or nxt.tag == "XR" or is_doeda(nxt):
                base = "되다" if is_doeda(nxt) else base_form(nxt)
                e = predicate_end(toks, i + 1) if is_predicate(nxt) else i + 2
                # 이중 부정: 안 좋을 게 없다 → 좋다
                if e + 1 < n and toks[e].tag == "ETM" and toks[e + 1].form in ("것", "거", "데", "리"):
                    k = skip_between(toks, e + 2)
                    if k < n and is_absent(toks[k]):
                        out.append(base)
                        i = k + 1
                        continue
                emit_negation(out, f"{t.form}_{base}", negation_counter)
                i = e
                continue
        # 2) 명사 뒤의 부정·없음·아님
        if t.tag in ("NNG", "NNP", "XR"):
            noun = clean_form(t.form)
            j = i + 1
            if j < n and toks[j].tag == "XSN":                      # 자극+적, 사람+들, 진정+성
                j += 1
            # 2-0) 명사 + (을·를·은·는·도) + 안/못 + 하다: 수영장 이용 못 했다 → 못_이용  ('모텔보다 못한'은 제외)
            k = j
            if k < n and toks[k].tag in ("JKO", "JX") and toks[k].form in ("을", "를", "ᆯ", "은", "는", "ᆫ", "도"):
                k += 1
            if k + 1 < n and toks[k].tag == "MAG" and toks[k].form in ("안", "못") and toks[k + 1].form == "하" \
                    and toks[k + 1].tag.startswith(("XSV", "VV", "VX")):
                emit_negation(out, f"{toks[k].form}_{noun}", negation_counter)
                i = k + 2
                continue
            # 2-1) 명사 + 이다 + 지 않다: 자극적이지 않다 → 안_자극 (장점이지 않을까 = 반어 → 그대로)
            k = skip_between(toks, j, josa=1, mag=0)
            if k < n and toks[k].tag == "VCP":
                r = negation_after_ji(toks, k + 1)
                if r:
                    prefix, end, rhet = r
                    if rhet:
                        out.append(noun)
                    else:
                        emit_negation(out, prefix + noun, negation_counter)
                    i = end
                    continue
            # 2-1b) 명사 + 말다: 걱정 마세요 → 안_걱정
            if j < n and toks[j].form == "말" and toks[j].tag.startswith("VX"):
                emit_negation(out, "안_" + noun, negation_counter)
                i = j + 1
                continue
            # 2-2) 명사 + 아니다: 무료가 아니다 → 무료_아니다 ('~가 아니라' 제외, '~아닐까요' 반어는 명사만)
            k = j
            if k + 1 < n and toks[k].tag.startswith("XS") and toks[k + 1].tag == "ETN":   # 불편함까지는 아니다
                k += 2
            k = skip_between(toks, k, josa=2, mag=1)
            if k < n and toks[k].tag == "VCN" and not (k + 1 < n and toks[k + 1].form == "라" and toks[k + 1].tag.startswith("EC")):
                if is_rhetorical(toks, k + 1):
                    out.append(noun)
                else:
                    emit_negation(out, f"{noun}_아니다", negation_counter)
                i = k + 1
                continue
            # 2-3) 명사 + 없다/없이: 부담 없는 · 불편함 없이 · 이용료가 따로 없다 → 명사_없다
            k = j
            if k + 1 < n and toks[k].tag.startswith("XS") and toks[k + 1].tag == "ETN":   # 불편+하+ㅁ
                k += 2
            k = skip_between(toks, k)
            if k < n and is_absent(toks[k]):
                # 이중 부정 → 명사만 남김: 맛이 없는 건 (절대) 아니다 · 쇼핑몰에 없는 거 없다
                e = k + 1
                if toks[k].form == "없" and e + 1 < n and toks[e].tag == "ETM" and toks[e + 1].form in ("것", "거"):
                    e2 = skip_between(toks, e + 2, josa=2, mag=1)
                    if e2 < n and ((toks[e2].tag == "VCN" and not (e2 + 1 < n and toks[e2 + 1].form == "라")) or is_absent(toks[e2])):
                        out.append(noun)
                        i = e2 + 1
                        continue
                # 없지 않아 있다 (어느 정도 있다) → 명사만 남김
                r = negation_after_ji(toks, k + 1) if toks[k].form == "없" else None
                if r:
                    out.append(noun)
                    i = r[1]
                    continue
                emit_negation(out, f"{noun}_없다", negation_counter)
                i = k + 1
                continue
        # 3) 서술어 뒤의 부정
        j = predicate_end(toks, i)
        if j > 0:
            base = base_form(t) if t.tag != "MAG" else clean_form(t.form)
            # 얼마 되지 않아 · 몇 되지 않는: 시간·수량 표현 → 묶지 않음
            if t.form == "되" and i > 0 and (toks[i - 1].form, toks[i - 1].tag) in NOT_NEGATION_BEFORE:
                r = negation_after_ji(toks, j)
                i = r[1] if r else j
                continue
            # 없지 않아 (있다는 뜻) → 지움
            if t.form == "없":
                r = negation_after_ji(toks, j)
                if r:
                    i = r[1]
                    continue
            # 이루 말할 수 없이(아주): 강조 표현이라 부정으로 묶지 않고 지운다
            if t.form == "말" and j + 2 < n and toks[j].tag == "ETM" and toks[j + 1].form == "수" \
                    and is_absent(toks[j + 2]) and i > 0 and toks[i - 1].form == "이루":
                i = j + 3
                continue
            # 3-1) 명사형 + 없이: 기다림 없이 · 변함 없는 → 안_기다리다 · 안_변하다
            if j < n and toks[j].tag == "ETN":
                k = skip_between(toks, j + 1, josa=1, mag=1)
                if k < n and is_absent(toks[k]):
                    emit_negation(out, "안_" + base, negation_counter)
                    i = k + 1
                    continue
            if j + 1 < n and toks[j].tag == "ETM":
                noun_tok = toks[j + 1]
                # 3-2) ~ㄹ 수/것/데/점/필요 … 없다
                if noun_tok.form in GENERIC_NOUNS and noun_tok.tag in ("NNB", "NNG"):
                    k = j + 2
                    must = k < n and toks[k].form == "밖에"
                    k = skip_between(toks, k)
                    if k < n and is_absent(toks[k]):
                        if base == "없다":
                            pass                                       # 없는 거 없다 = 다 있다
                        elif noun_tok.form == "나위":
                            out.append("더할나위없다")
                        elif must:
                            out.append(base)                           # 만족할 수밖에 없다 = 긍정
                        else:
                            # 이중 부정: 할 수 없는 게 없다 → 하다
                            e = k + 1
                            if toks[k].form == "없" and e + 1 < n and toks[e].tag == "ETM" and toks[e + 1].form in ("것", "거"):
                                e2 = skip_between(toks, e + 2)
                                if e2 < n and is_absent(toks[e2]):
                                    out.append(base)
                                    i = e2 + 1
                                    continue
                            emit_negation(out, ("못_" if noun_tok.form == "수" else "안_") + base, negation_counter)
                        i = k + 1
                        continue
                # 3-3) ~ㄴ 편(것·정도·맛 …)은 아니다 → 안_X   (~아닌가 싶다 = 반어 → X)
                if noun_tok.tag in ("NNB", "NNG"):
                    k = skip_between(toks, j + 2, josa=2, mag=1)
                    if k < n and toks[k].tag == "VCN" and not (k + 1 < n and toks[k + 1].form == "라" and toks[k + 1].tag.startswith("EC")):
                        if is_rhetorical(toks, k + 1):
                            out.append(base)
                        else:
                            emit_negation(out, "안_" + base, negation_counter)
                        kept = keep_token(noun_tok) if noun_tok.form not in GENERIC_NOUNS else None
                        if kept:
                            out.append(kept)                           # 특별한 맛은 아니다 → 안_특별 맛
                        i = k + 1
                        continue
            # 3-4) 지 + 않다 / 못하다 / 말다   (좋지 않을까 = 반어 → 좋다)
            r = negation_after_ji(toks, j)
            if r:
                prefix, end, rhet = r
                if rhet:
                    out.append(base)
                else:
                    emit_negation(out, prefix + base, negation_counter)
                i = end
                continue
        # 4) ~했으면 좋겠다 · ~면 좋을 것 같다: 바람(아쉬움)이라 칭찬의 '좋다'와 구분해 '좋겠다'로 남긴다
        #    (좋겠다는 거의 항상 바람: '개선이 됐음 좋겠습니다'처럼 '면' 없이 쓰기도 함)
        if t.form == "좋" and t.tag.startswith("VA") and i + 1 < n and (toks[i + 1].form == "겠" or (
                i > 0 and toks[i - 1].form in ("면", "으면") and toks[i - 1].tag.startswith("EC")
                and toks[i + 1].tag == "ETM" and i + 2 < n and toks[i + 2].form in ("것", "거"))):
            out.append("좋겠다")
            i += 1
            continue
        word = keep_token(t)
        if word:
            out.append(word)
        i += 1
    # 이중 부정 = 긍정: 추천하지 않을 이유가 없다 → 추천, 안 갈 이유가 없다 → 가다
    fixed = []
    for w in out:
        if w == "이유_없다" and fixed and fixed[-1].startswith(("안_", "못_")):
            fixed[-1] = fixed[-1].split("_", 1)[1]
            continue
        fixed.append(w)
    return fixed


# -------------------------------------------------------------
# 재방문 표현 묶기 (부정어 묶기 다음에 적용)
#   '다시·또' + '오다·방문·가다·찾다·묵다·투숙·이용' → 재방문
#   '다시·또' + '안_오다·못_가다' 등                   → 안_재방문 (부정적인 재방문 의사)
#   ('또', '오다', '방문'은 불용어라 묶지 않으면 재방문 의사가 통째로 사라진다)
# -------------------------------------------------------------
REVISIT_ADVERBS = {"다시", "또"}
REVISIT_VERBS = {"오다", "방문", "가다", "찾다", "묵다", "투숙", "이용", "재방문"}
# '재방문' 뒤에 부정이 오면 안_재방문:  재방문 의사 없음 · 다시 올 일은 없을 듯 · 재방문은 안 할 것 같다 · 다시 갈 생각은 안 든다
#   사이에 올 수 있는 말 (이 말들만 건너뛰고 부정을 찾는다 — 다른 말이 끼면 다른 내용이라 보고 묶지 않음)
REVISIT_BETWEEN = {"의사", "생각", "마음", "맘", "의향", "계획", "일", "절대", "전혀", "딱히", "굳이", "아직", "별로", "글쎄"}
REVISIT_NEGATIONS = {"없다", "안_하다", "못_하다", "안_들다", "안_있다"}


def negated_after(tokens, i):
    """tokens[i] 뒤에 REVISIT_BETWEEN 말만 거쳐 부정(없다·안 하다 등)이 나오면 그 위치를, 아니면 None"""
    j = i + 1
    while j < len(tokens) and j <= i + 4:
        if tokens[j] in REVISIT_NEGATIONS or (tokens[j].endswith("_없다") and tokens[j][:-3] in REVISIT_BETWEEN):
            return j
        if tokens[j] not in REVISIT_BETWEEN:
            return None
        j += 1
    return None


def merge_revisit(tokens, counter=None):
    out = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        word = None
        if t in REVISIT_ADVERBS and i + 1 < n:
            nxt = tokens[i + 1]
            base = nxt.split("_", 1)[1] if nxt.startswith(("안_", "못_")) else nxt
            if base in REVISIT_VERBS:
                word = "안_재방문" if nxt.startswith(("안_", "못_")) else "재방문"
                i += 2
        elif t == "재방문":
            word = "재방문"
            i += 1
        elif t == "재방문_없다":                       # 재방문은 없을 듯
            word = "안_재방문"
            i += 1
        if word:
            # 재방문 뒤의 부정: 재방문 의사 없음 → 안_재방문 (부정을 나타낸 '없다' 등은 안_재방문에 합쳐 지운다)
            if word == "재방문":
                j = negated_after(tokens, i - 1)
                if j is not None:
                    word = "안_재방문"
                    tokens = tokens[:j] + tokens[j + 1:]
                    n -= 1
            out.append(word)
            if counter is not None and (word != "재방문" or t != "재방문"):
                counter[word] += 1
            continue
        out.append(t)
        i += 1
    return out
