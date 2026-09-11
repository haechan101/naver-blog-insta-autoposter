# -*- coding: utf-8 -*-
"""브라우저 실행 공통 헬퍼.

로그인 유지 전략:
  쿠키만 저장(storage_state)하면 실행할 때마다 빈 프로필로 뜨기 때문에
  네이버가 매번 '새로운 기기'로 보고 세션을 일찍 만료시킵니다.
  그래서 user_data_dir(프로필 폴더)를 통째로 재사용합니다.
  이렇게 하면 쿠키뿐 아니라 기기 식별 정보·localStorage 까지 남습니다.
"""
import subprocess
import time

import config


def _profile_in_use() -> bool:
    """이 계정 프로필을 쓰는 브라우저가 이미 떠 있는지 확인합니다.

    같은 user_data_dir 로는 크롬을 두 개 못 띄우는데, 이때 나오는 오류 메시지가
    엉뚱하게 '브라우저 미설치' 안내라서 원인을 못 찾게 됩니다. 그래서 따로 봅니다.
    """
    marker = config.USER_DATA_DIR.name          # 예: blog_id_5
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    return marker in (out or "")


# 자동화 흔적을 줄이는 실행 옵션
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=IsolateOrigins,site-per-process",
]
# --no-sandbox 를 빼야 상단의 '지원되지 않는 명령줄 플래그' 경고 띠가 안 뜹니다.
_IGNORE_ARGS = ["--enable-automation", "--no-sandbox"]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# navigator.webdriver 등 자동화 신호를 숨기는 스크립트
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = { runtime: {} };
"""


def open_context(p, fresh: bool = False):
    """프로필을 재사용하는 브라우저 컨텍스트를 엽니다.

    fresh=True 면 프로필을 쓰지 않고 빈 상태로 엽니다(로그인 새로 할 때).
    반환: playwright BrowserContext (close() 로 종료)
    """
    config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(config.USER_DATA_DIR),
        headless=False,
        args=_STEALTH_ARGS,
        ignore_default_args=_IGNORE_ARGS,
        user_agent=_UA,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 1440, "height": 900},
    )
    channel = config.BROWSER_CHANNEL
    ctx = None
    first_err = None
    if channel:
        # 앞서 쓰던 크롬이 완전히 내려가기 전에 다시 띄우면 프로필이 잠깐 잠겨 있습니다.
        # 진짜로 창이 열려 있는 경우와 구분이 안 되므로, 몇 초 기다렸다 두 번 더 해봅니다.
        for attempt in range(3):
            try:
                ctx = p.chromium.launch_persistent_context(channel=channel, **kwargs)
                break
            except Exception as e:
                first_err = e
                if attempt < 2 and not _profile_in_use():
                    print(f"  ⏳ 프로필이 아직 잠겨 있습니다. 3초 후 재시도… "
                          f"({attempt + 1}/2)")
                    time.sleep(3)
                    continue
                print(f"⚠ 시스템 크롬('{channel}') 실행 실패({str(e)[:60]}). "
                      "내장 크롬으로 시도합니다.")
                break
    if ctx is None:
        try:
            ctx = p.chromium.launch_persistent_context(**kwargs)
        except Exception as e:
            # 이 지점에서 나오는 메시지는 대개 원인을 못 짚어 줍니다.
            # 실제로 가장 흔한 원인은 '앞서 띄운 창이 아직 안 닫혀서 프로필이 잠긴 것'인데,
            # 플레이라이트는 그걸 브라우저 미설치 안내로 보여줘 헷갈립니다.
            if _profile_in_use():
                raise RuntimeError(
                    "이 계정 프로필을 쓰는 브라우저 창이 이미 열려 있습니다.\n"
                    "   같은 프로필로는 두 개를 동시에 열 수 없습니다.\n"
                    f"   → 먼저 열려 있는 자동화 브라우저 창을 닫고 다시 실행하세요.\n"
                    f"   (프로필: {config.USER_DATA_DIR})") from e
            if "Executable doesn't exist" in str(e):
                raise RuntimeError(
                    "브라우저를 실행할 수 없습니다.\n"
                    f"   시스템 크롬 실행 실패: {str(first_err)[:80]}\n"
                    "   내장 브라우저도 없습니다. 아래를 1회 실행해 주세요:\n"
                    "   venv\\Scripts\\python.exe -m playwright install chromium") from e
            raise

    ctx.add_init_script(_STEALTH_JS)
    return ctx


def is_logged_in(page) -> bool:
    """네이버 로그인 상태인지 확인합니다.

    쿠키 존재 여부를 먼저 봅니다 — 이게 가장 신뢰도 높은 신호입니다.
    DOM의 '로그인 버튼 없음'만으로 판단하면, 새 프로필에서 네이버가
    동의 배너 등 다른 화면을 보여줄 때 셀렉터가 우연히 안 잡혀
    로그인된 것으로 오판할 수 있습니다(실제로 발생했던 문제).
    """
    try:
        cookies = page.context.cookies("https://www.naver.com")
        if not any(c["name"] == "NID_AUT" for c in cookies):
            return False   # 로그인 쿠키 자체가 없으면 100% 로그아웃 상태

        page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1200)
        # 쿠키가 있어도 만료됐을 수 있으니 DOM으로 한 번 더 확인
        return page.locator("a.link_login, #account .link_login").count() == 0
    except Exception:
        return False


def save_cookies(ctx) -> None:
    """프로필이 깨졌을 때를 대비한 쿠키 백업."""
    try:
        ctx.storage_state(path=str(config.SESSION_PATH))
    except Exception:
        pass


# ── 구버전 호환 (기존 코드가 launch/new_context 를 부르는 경우) ──
def launch(p):
    raise RuntimeError(
        "browser_util.launch() 는 더 이상 쓰지 않습니다. open_context(p) 를 사용하세요.")


def new_context(browser, **kwargs):
    raise RuntimeError(
        "browser_util.new_context() 는 더 이상 쓰지 않습니다. open_context(p) 를 사용하세요.")
