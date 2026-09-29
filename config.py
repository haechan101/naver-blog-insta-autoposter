# -*- coding: utf-8 -*-
"""설정값. 경로/모델/API 키를 여기서 관리합니다."""
import json
import os
from pathlib import Path

# ── 경로 ─────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent          # .../Naver_blog/auto_poster
BLOG_DIR   = BASE_DIR.parent                            # .../Naver_blog
XLSX_PATH  = BLOG_DIR / "navercafe_면접+필기_통합.xlsx"  # (구) 후기 통합 데이터
DRAFTS_DIR = BASE_DIR / "drafts"                        # 생성된 초안 저장 폴더
SHEET_NAME = "통합데이터"

# (구) 101개 공기업 필기시험 전용 프로필. "안쓰는 데이터/"로 이동됨.
PROFILES_PATH = BLOG_DIR / "안쓰는 데이터" / "company_exam_profiles.json"

# 현재 사용하는 메인 데이터: 67개 기업 채용설명회·직무백서 원문
# (서류·자소서·필기·면접·인턴까지 전체를 다룸. md_loader.py 가 읽음)
MD_PROFILES_DIR = BLOG_DIR / "공기업 분석"

# ── API 키 ───────────────────────────────────────────
# 키는 .env 에 두고 코드에는 두지 않습니다. .env 는 git 에 올라가지 않습니다.
# 처음 받으셨다면 .env.example 을 .env 로 복사한 뒤 값을 채우세요.
def _load_dotenv(path: Path) -> None:
    """.env 를 환경변수로 읽어들입니다.

    python-dotenv 를 쓰지 않은 이유: 이 한 가지 때문에 의존성을 늘리고 싶지 않았습니다.
    이미 설정된 환경변수가 있으면 그쪽을 우선합니다(서버에서 주입하는 경우).
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── 인스타그램 (톰슨에듀AI 계정) ─────────────────────
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USERNAME     = os.environ.get("INSTAGRAM_USERNAME", "")
INSTA_DIR       = BLOG_DIR / "auto_insta"
INSTA_ASSET_DIR = INSTA_DIR / "insta_images"     # 기업별 로고·건물 사진 (사람이 넣음)
INSTA_BRAND_DIR = INSTA_ASSET_DIR / "_톰슨에듀AI"  # 톰슨에듀AI 로고·기능 캡처
INSTA_OUT_DIR   = INSTA_DIR / "insta_out"        # 만든 카드 이미지
# 반자동 발행 시각. [확인 완료]한 카드가 이 시각들에 하나씩 배정되고, 작업 스케줄러가 이 시각마다 올립니다.
INSTA_POST_TIMES = ["08:30", "19:00"]

# ── 모델 ─────────────────────────────────────────────
# 품질 우선: claude-opus-5 / 비용 절감(대량): claude-sonnet-5
RESEARCH_MODEL = "claude-sonnet-5"   # 웹 검색으로 기업 정보 수집 (검색은 sonnet으로 충분)
GEN_MODEL      = "claude-opus-5"     # 블로그 본문 생성 (품질 우선. 비용 절감 시 claude-sonnet-5)

# 웹 검색 도구 버전 (최신 모델용). 구형 모델이면 "web_search_20250305" 로 교체
WEB_SEARCH_TOOL = "web_search_20260209"

# ── 후기 추출 상한 (토큰/비용 관리) ──────────────────
MAX_REVIEWS_PER_KIND = 15      # 면접/필기 각각 최대 몇 건까지 넣을지
MAX_CHARS_PER_KIND   = 12000   # 면접/필기 각각 글자 수 상한

# ── 네이버 발행(Playwright) 설정 ─────────────────────
# 네이버 블로그 아이디.
# 계정을 바꾸면 save_login.py --switch 가 account.json 에 새 아이디를 적고,
# 아래 기본값 대신 그 값을 씁니다. (config.py 를 직접 고칠 필요 없음)
BLOG_ID      = "blog_id_2"
ACCOUNT_PATH = BASE_DIR / "account.json"
if ACCOUNT_PATH.exists():
    try:
        _acct = json.loads(ACCOUNT_PATH.read_text(encoding="utf-8"))
        BLOG_ID = _acct.get("blog_id") or BLOG_ID
    except Exception:
        pass

SESSION_PATH  = BASE_DIR / "naver_session.json"        # (보조) 쿠키 백업
# 로그인 유지의 핵심: 브라우저 프로필 폴더를 통째로 재사용합니다.
# 쿠키만 저장하면 매번 '새 기기'로 인식돼 네이버가 세션을 빨리 끊습니다.
# 계정별로 폴더를 나눠, 계정을 바꿔도 이전 로그인이 서로 덮어쓰이지 않습니다.
PROFILES_ROOT = BASE_DIR / "browser_profile"
USER_DATA_DIR = PROFILES_ROOT / BLOG_ID
WRITE_URL     = f"https://blog.naver.com/{BLOG_ID}?Redirect=Write&"  # 글쓰기 진입 URL
LOGIN_URL     = "https://nid.naver.com/nidlogin.login"
BROWSER_CHANNEL = "chrome"   # PC에 설치된 실제 크롬 사용. 문제 시 None 으로 두면 내장 크롬


def set_account(blog_id: str) -> None:
    """실행 중에 발행 계정을 바꿉니다 (글마다 다른 계정에 올릴 때).

    publisher·browser_util 은 config.BLOG_ID / USER_DATA_DIR / WRITE_URL 을
    호출 시점에 읽으므로, 여기서 세 값을 함께 갈아끼우면 그대로 반영됩니다.
    account.json(기본 계정)은 건드리지 않습니다 — 이건 이번 발행에만 적용됩니다.
    """
    global BLOG_ID, USER_DATA_DIR, WRITE_URL
    blog_id = (blog_id or "").strip()
    if not blog_id:
        return
    BLOG_ID = blog_id
    USER_DATA_DIR = PROFILES_ROOT / blog_id
    WRITE_URL = f"https://blog.naver.com/{blog_id}?Redirect=Write&"


#: 더 이상 쓰지 않는 계정. 로그인 폴더는 남겨두고 앱·일괄 발행 목록에서만 뺍니다.
RETIRED_ACCOUNTS = {"gocks8322"}


def list_accounts() -> list[str]:
    """로그인 정보가 저장돼 있는 계정 목록 (browser_profile/ 하위 폴더). 쓰지 않는 계정은 뺍니다."""
    if not PROFILES_ROOT.exists():
        return [BLOG_ID]
    names = sorted(p.name for p in PROFILES_ROOT.iterdir()
                   if p.is_dir() and p.name not in RETIRED_ACCOUNTS)
    if BLOG_ID not in names and BLOG_ID not in RETIRED_ACCOUNTS:
        names.insert(0, BLOG_ID)
    return names

# ── 이미지 / 글자크기 ────────────────────────────────
IMAGES_DIR = BASE_DIR / "images"                 # 이미지 폴더
# (구) 단일 홍보 이미지
TOMPSONAI_IMAGE = IMAGES_DIR / "tompsonai.png"

# 마무리(6번) 섹션에서 소개할 수 있는 톰슨AI 기능들.
# 한 줄에 나란히 붙는 묶음은 리스트 안의 리스트로 표현합니다.
#
# ⚠ 매 글에 이걸 다 넣지는 않습니다. 5개를 전부 넣으면 마무리가 본문의 20%를 차지하고
#   이미지 9장이 모든 글에 똑같이 들어가, 글끼리 유사문서로 묶일 위험이 커집니다.
#   실제로 넣을 2개는 글 주제에 따라 topics.py 의 cta 가 정합니다.
TOMPSONAI_FEATURES = {
    "analysis": ("공기업 분석 서비스", ["공기업 분석_톰슨ai", "공기업 분석_예시"]),
    "mock":     ("기업별 NCS 실전 모의고사", ["NCS_봉투모의고사"]),
    "theory":   ("유형별 NCS 이론 학습", ["유형별NCS이론", "의사소통1"]),
    "aiquiz":   ("AI 추천 유형별 문제 풀이", ["유형별NCS문제풀이1", "유형별NCS문제풀이2"]),
    # 자기소개서 클리닉은 2026-09-15부터 소개하지 않습니다.
}

# (구) 4개를 항상 넣던 시절의 목록. 주제별 선택으로 바뀌어 더 이상 쓰지 않습니다.
TOMPSONAI_BLOCKS = [TOMPSONAI_FEATURES[k]
                    for k in ("analysis", "mock", "theory", "aiquiz")]
# (구) 마무리 고정 이미지 2장. TOMPSONAI_BLOCKS 의 첫 묶음과 같습니다.
TOMPSONAI_IMAGES = TOMPSONAI_BLOCKS[0][1]

# 사진 2장 이상을 한 번에 올릴 때 네이버가 묻는 '사진 첨부 방식'
#   "콜라주"   = 한 줄에 나란히 (실측: 블로그의 se-imageStrip)
#   "개별사진" = 세로로 하나씩
#   "슬라이드" = 넘겨보기
IMAGE_LAYOUT = "콜라주"

# ── 매일 자동 발행 (run_daily.py) ────────────────────
# 예약 발행 시각을 이 구간 안에서 매일 다르게 뽑습니다.
# 같은 시각에 못박으면 프로그램 발행 패턴으로 보이기 쉽습니다.
SCHEDULE_FROM = "09:00"
SCHEDULE_TO   = "11:30"

# ── 발행 설정 ────────────────────────────────────────
# 카테고리 이름. "" 로 두면 네이버 기본 카테고리를 그대로 씁니다.
CATEGORY = ""          # 예: "공기업 필기 분석"
# 공개 범위: 2=전체공개 1=이웃공개 3=서로이웃공개 0=비공개 / None=건드리지 않음
OPEN_TYPE = 2
# 기업 이미지: images/기업명_용도.(png|jpg) 를 [[IMG:기업명_용도]] 로 참조
# 실측 기준(사양서 §9): 본문 fs16 / 소제목 fs19
HEADING_FONT_SIZE = "fs19"   # 소제목 글자 크기
BODY_FONT_SIZE    = "fs16"   # 본문 기본 크기
# 문단 정렬. 실측: 사장님 블로그 본문은 가운데 530 / 왼쪽 76 → 가운데가 기본
BODY_ALIGN        = "center"  # None 으로 두면 정렬을 건드리지 않음

# ── 강조 색상 (실측: 파랑 29회 / 빨강 12회) ───────────
COLOR_KEY  = "#4a90e2"   # 핵심 키워드·직렬·배점
COLOR_WARN = "#ff0010"   # 경고·감점·마감
# 형광펜(글자 배경). 네이버 기본 팔레트에 있는 노랑이라 '더보기' 없이 바로 찍힙니다.
COLOR_MARK = "#fff8b2"

# ── 본문 분량 목표 (사양서 §10) ──────────────────────
# 마무리를 주제별 2개로 줄이면서 마무리가 약 200자 짧아졌습니다.
# 실측(최근 10편) 본문 1,355~1,955자, 평균 1,588자 — 하한 1600 은 너무 높아
# 멀쩡한 글이 3번씩 재생성되며 비용만 3배 들었습니다.
# 하한은 넉넉하게 1000 으로 둡니다. 이 검사는 '토막글'만 걸러내는 용도이고,
# 적정 분량은 프롬프트가 안내합니다. 여기서 조이면 재생성 비용만 늘어납니다.
BODY_MIN_CHARS = 1000
BODY_MAX_CHARS = 2800

# ── 사용자 설정 오버라이드 (GUI 설정 탭에서 저장) ──────
# run_app.py 의 설정 탭에서 값을 바꾸면 이 파일이 아니라 settings_override.json 에
# 저장됩니다. config.py 소스는 건드리지 않아 항상 되돌릴 수 있고 diff 가 깨끗합니다.
SETTINGS_OVERRIDE_PATH = BASE_DIR / "settings_override.json"
# GUI 설정 탭에 노출되는 키 목록 (이 안에 있는 키만 오버라이드 허용 — 안전장치)
SETTINGS_EDITABLE_KEYS = [
    "GEN_MODEL", "CATEGORY", "OPEN_TYPE", "SCHEDULE_FROM", "SCHEDULE_TO",
    "INSTA_POST_TIMES",      # 인스타 발행 대기열 탭에서 바꿉니다
]
if SETTINGS_OVERRIDE_PATH.exists():
    try:
        _ov = json.loads(SETTINGS_OVERRIDE_PATH.read_text(encoding="utf-8"))
        for _k, _v in _ov.items():
            if _k in SETTINGS_EDITABLE_KEYS:
                globals()[_k] = _v
    except Exception:
        pass
