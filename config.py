# =============================================================
# 설정 파일 — 크롤러를 돌리기 전에 바꿀 값은 전부 여기에 있음
# =============================================================

# 수집자 이니셜 (review_id, 이미지 폴더 이름에 들어감)
COLLECTOR_INITIAL = "DH"

# 호텔 목록 파일 (지역, 검색명, 공식명, 주소, 구글 검색 보정값 등)
HOTELS_FILE = "hotels_seoul.csv"      # 팀 호텔 리스트(2026-10-15) 롱리스트 중 서울 32곳
                                      # (1차 대상 목록은 _archive_round1/hotels.csv = 관광호텔업 5성 61곳, hotels_all.csv = 공식 5성 전체 71곳)

# 결과 저장 위치
OUTPUT_DIR = "output"                      # 리뷰 CSV가 저장되는 폴더
COLLECT_LOG_FILE = "collect_log.csv"       # 실행마다 수집 건수를 기록하는 파일
DATE_LOG_FILE = "date_expression_log.csv"  # "3개월 전" 같은 상대 날짜 표기를 기록하는 파일

# 요청 사이 대기 시간(초). 이 범위 안에서 랜덤으로 쉰다. (수집 윤리: 2~3초 이상)
SLEEP_MIN = 2.0
SLEEP_MAX = 3.5

# 샘플 모드: True면 SAMPLE_HOTEL 한 곳에서 SAMPLE_LIMIT 건까지만 수집
SAMPLE_MODE = False
SAMPLE_HOTEL = "서울신라호텔"   # 대상 호텔 목록의 search_name 값 (1차 크롤러용)
SAMPLE_LIMIT = 300

# 본 수집 때 호텔 1곳당 최대 수집 건수 (None이면 끝까지)
MAX_REVIEWS_PER_HOTEL = None

# 언어 판별 기준 (한국어·영어만 수집, 그 외 언어는 수집하지 않음)
#   - 글자 중 한글 비율이 KOREAN_RATIO_THRESHOLD 이상 → 한국어
#   - 아니면서 영문 알파벳 비율이 ENGLISH_RATIO_THRESHOLD 이상 → 영어 (별도 파일에 저장)
#   - 둘 다 아니면 → 기타 언어 (수집 안 함, 건수만 로그에 기록)
KOREAN_RATIO_THRESHOLD = 0.2
ENGLISH_RATIO_THRESHOLD = 0.9

# 2차 수집 기준 (2026-10-15 팀 결정)
#   - KOREAN_ONLY: True면 한국어로 쓴 원문 리뷰만 저장 (영어 리뷰도 저장하지 않음, 건수만 '기타 언어'로 기록)
#   - REVIEW_SINCE: 이 날짜 이후에 쓴 리뷰만 저장 (2025년·2026년 리뷰만). None이면 기간 제한 없음
KOREAN_ONLY = True
REVIEW_SINCE = "2025-01-01"

# 브라우저 창을 띄울지 여부 (False면 창이 보이고, True면 백그라운드에서 실행)
HEADLESS = False

# 오류가 났을 때 화면 캡처를 output/에 남길지 여부
# (캡처에는 리뷰 작성자 이름이 찍힐 수 있으므로 기본은 꺼 둠. 문제를 조사할 때만 True로 켜고, 다 보면 지울 것)
SAVE_DEBUG_SCREENSHOTS = False

# =============================================================
# 아고다 전용 설정 (1차 크롤러 _archive_round1/crawl_agoda.py용, 2차 수집에서는 안 씀)
# =============================================================
# 리뷰 페이지(5건 단위)를 불러오는 간격(초). 아고다는 짧은 간격으로 반복하면 응답이 멈추므로 넉넉하게.
AGODA_WAIT_MIN = 15
AGODA_WAIT_MAX = 20

# 호텔과 호텔 사이에 쉬는 시간(초)
AGODA_HOTEL_WAIT_MIN = 60
AGODA_HOTEL_WAIT_MAX = 90

# 응답이 없을 때(속도 제한 의심) 쉬었다가 다시 시도하는 시간(초). 두 번째도 실패하면 수집을 멈춘다.
AGODA_BACKOFF_SECONDS = 600

# 수집 언어: 아고다 리뷰의 '작성 언어' 필터 이름 기준
#   ko → 한국어 리뷰 (agoda_reviews.csv), en → 영어 리뷰 (agoda_reviews_en.csv, 'English…'로 시작하는 모든 영어 항목)
AGODA_LANGUAGES = ["ko", "en"]

# 정렬 방식: 아고다는 정렬마다 앞쪽 일정 페이지까지만 보여주므로, 여러 정렬로 나눠서 최대한 많이 모은다
#   1 = 최신순, 3 = 낮은 평점 우선, 2 = 높은 평점 우선
AGODA_SORTS = [1, 3, 2]

# 테스트 실행(python crawl_agoda.py --test) 때 정렬·언어 조합마다 불러올 페이지 수
AGODA_TEST_PAGES = 2
