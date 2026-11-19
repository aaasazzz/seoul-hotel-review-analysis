# 사전 파일

통합 전처리(`preprocess_merge.py`)에서 쓰는 사전 파일

| 파일 | 내용 |
|---|---|
| `hotel_alias.csv` | 호텔 이름 표기 → 표준 호텔명 |
| `hotel_keywords.csv` | 본문에서 호텔 언급을 확인할 때 쓰는 키워드 |
| `user_dict.csv` | Kiwi 형태소 분석기 사용자 사전 |
| `synonyms.csv` | 동의어 → 대표어 |
| `stopwords_hotel.csv` | 불용어 목록 (`build_stopwords.py`로 생성) |

## 출처 — 경영불용어사전

`stopwords_hotel.csv`에서 `출처`가 `교수님 사전`인 612개 항목은 **정재학 교수의 「경영불용어사전(공개용)」** 기반

- 원본 사전 파일은 저장소에 포함 X
- `stopwords_hotel.csv`에는 원본 단어와 함께 호텔 리뷰 분석에 맞게 조정한 결과(`적용형태`, `사용` 여부, `이유`)를 담음. 612개 중 216개를 불용어로 사용
- `preprocess_merge.py`는 원본 사전이 아니라 조정본인 `stopwords_hotel.csv`를 읽음.
  `build_stopwords.py`로 불용어 목록을 다시 만들려면 원본 사전을 `교수님_경영불용어사전_원본.csv`로 넣어야 함

나머지 항목(`호텔 도메인`, `호텔 이름`, `한 글자 기능어`, `데이터별(블로그)`, `데이터별(유튜브)`)은 직접 정함
