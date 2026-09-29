# -*- coding: utf-8 -*-
"""인스타그램 카드뉴스 발행 — 서버 없이 이 컴퓨터에서 올립니다.

■ 왜 임시 공개 주소가 필요한가
인스타 API 는 사진 파일을 받지 않습니다. 인스타 서버가 '공개 주소'에서 JPEG 를 직접 가져갑니다
(공식 문서: 로컬 파일 업로드는 동영상만 지원). 그래서 발행하는 1~2분 동안만
  1) 카드 폴더의 card*.jpg 만 내보내는 작은 웹서버를 127.0.0.1 에 띄우고
  2) cloudflared 임시 터널로 https://<무작위>.trycloudflare.com 주소를 받아
  3) 그 주소로 캐러셀을 만들어 게시한 뒤
  4) 터널과 웹서버를 닫습니다.
터널은 이 컴퓨터에서 바깥으로 나가는 연결이라 공유기·방화벽 설정이 필요 없습니다.

■ 필요한 것
  tools/cloudflared.exe           github.com/cloudflare/cloudflared 공식 배포 파일
  .env 의 INSTAGRAM_ACCESS_TOKEN   톰슨에듀AI(tompsoneduai) 계정 토큰

■ 인스타 제한 (어기면 API 가 거절합니다)
  캐러셀 2~10장, JPEG 만, 장당 8MB 이하, 캡션 2,200자·해시태그 30개 이하, 24시간 100건

실행 (인스타에는 아무것도 보내지 않는 임시 주소 시험):
  venv\\Scripts\\python.exe insta_publish.py --test 국민건강보험공단
"""
from __future__ import annotations
import contextlib
import datetime as dt
import functools
import http.server
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import config
import insta_cards

GRAPH = "https://graph.instagram.com/v21.0"
CLOUDFLARED = config.BASE_DIR / "tools" / "cloudflared.exe"
RECORD = config.INSTA_OUT_DIR / "_published.json"

MIN_CARDS, MAX_CARDS = 2, 10
MAX_BYTES = 8 * 1024 * 1024
CAPTION_MAX, HASHTAG_MAX = 2200, 30

# 오류 줄에 나오는 api.trycloudflare.com 은 공개 주소가 아니므로 뺍니다
_TUNNEL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")
_CARD_RE = re.compile(r"card\d{2}\.jpg")


class InstaError(RuntimeError):
    """발행을 멈춰야 하는 문제. 메시지는 화면에 그대로 보여줍니다."""


# ── 점검 ─────────────────────────────────────────────
def problems(company: str, caption: str) -> list[str]:
    """발행 전에 걸러낼 문제 목록. 비어 있으면 발행할 수 있습니다."""
    out = []
    if not config.INSTAGRAM_ACCESS_TOKEN:
        out.append(".env 에 INSTAGRAM_ACCESS_TOKEN 이 없습니다.")
    if not CLOUDFLARED.exists():
        out.append(f"임시 주소 프로그램이 없습니다: {CLOUDFLARED}")
    return out + content_problems(company, caption)


def content_problems(company: str, caption: str) -> list[str]:
    """카드·캡션만 보고 거르는 문제. [확인 완료] 때도 씁니다 (발행 환경은 그때 없어도 되므로 따로 둡니다)."""
    out = []
    cards = insta_cards.made_cards(company)
    if not MIN_CARDS <= len(cards) <= MAX_CARDS:
        out.append(f"카드는 {MIN_CARDS}~{MAX_CARDS}장이어야 합니다 (지금 {len(cards)}장).")
    big = [p.name for p in cards if p.stat().st_size > MAX_BYTES]
    if big:
        out.append("8MB 넘는 카드: " + ", ".join(big))
    if not caption.strip():
        out.append("캡션이 비어 있습니다.")
    if len(caption) > CAPTION_MAX:
        out.append(f"캡션이 {len(caption):,}자입니다 ({CAPTION_MAX:,}자 이하).")
    if len(hashtags(caption)) > HASHTAG_MAX:
        out.append(f"해시태그가 {len(hashtags(caption))}개입니다 ({HASHTAG_MAX}개 이하).")
    return out


def hashtags(caption: str) -> list[str]:
    return re.findall(r"#[^\s#]+", caption)


# ── 기록 · 캡션 ──────────────────────────────────────
def _load() -> dict:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except Exception:
        return {}


def published(company: str) -> dict:
    """이 기업 카드뉴스를 올린 기록 {media_id, permalink, cards, published_at}. 없으면 {}."""
    return _load().get(company) or {}


def _mark(company: str, rec: dict) -> None:
    data = _load()
    data[company] = rec
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _caption_path(company: str) -> Path:
    # 카드를 다시 만들어도 card*.jpg 만 지우므로 캡션은 남습니다
    return config.INSTA_OUT_DIR / company / "caption.txt"


def load_caption(company: str) -> str:
    p = _caption_path(company)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def save_caption(company: str, text: str) -> None:
    p = _caption_path(company)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── 인스타 API ───────────────────────────────────────
def _api(method: str, path: str, base: str = GRAPH, **params) -> dict:
    """graph.instagram.com 호출. 토큰은 주소가 아니라 헤더로 보냅니다 (주소는 로그에 남기 쉬워서)."""
    url = f"{base}/{path}"
    data = None
    if method == "GET":
        if params:
            url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {config.INSTAGRAM_ACCESS_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error") or {}
        except Exception:
            err = {}
        msg = err.get("error_user_msg") or err.get("message") or f"HTTP {e.code}"
        raise InstaError(f"인스타 API 오류 ({path.rsplit('/', 1)[-1]}): {msg}") from None


# ── 토큰 만료 관리 ───────────────────────────────────
# 인스타 장기 토큰은 60일이면 만료됩니다. 발급 24시간 뒤부터 만료 전까지 갱신하면 다시 60일이 됩니다.
# 갱신 시각과 만료 예정일만 기록하고, 토큰 값은 .env 에만 둡니다.
TOKEN_INFO = config.INSTA_OUT_DIR / "_token.json"
REFRESH_BEFORE_DAYS = 15


def token_info() -> dict:
    try:
        return json.loads(TOKEN_INFO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def token_status() -> str:
    if not config.INSTAGRAM_ACCESS_TOKEN:
        return "토큰 없음"
    exp = token_info().get("expires_at")
    if not exp:
        return "만료일 모름 (첫 갱신 전)"
    left = (dt.datetime.fromisoformat(exp) - dt.datetime.now()).days
    return f"{exp[:10]} 만료 (D-{left})"


def _write_env_token(token: str) -> None:
    """.env 의 INSTAGRAM_ACCESS_TOKEN 줄만 바꿉니다. 다른 줄은 그대로 둡니다."""
    env = config.BASE_DIR / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    out, done = [], False
    for line in lines:
        if re.match(r"\s*INSTAGRAM_ACCESS_TOKEN\s*=", line):
            out.append(f"INSTAGRAM_ACCESS_TOKEN={token}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"INSTAGRAM_ACCESS_TOKEN={token}")
    tmp = env.with_name(".env.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(env)          # 쓰다가 멈춰도 .env 가 반쯤 비는 일이 없게 임시 파일로 바꿔치기


def refresh_token(log=print) -> dict:
    """장기 토큰을 60일 더 늘리고 새 토큰을 .env 에 씁니다. {refreshed_at, expires_at} 를 돌려줍니다."""
    d = _api("GET", "refresh_access_token", base="https://graph.instagram.com",
             grant_type="ig_refresh_token")
    token, secs = d.get("access_token"), d.get("expires_in")
    if not token or not secs:
        raise InstaError(f"토큰 갱신 응답이 이상합니다 ({sorted(d)})")
    _write_env_token(token)
    config.INSTAGRAM_ACCESS_TOKEN = token
    os.environ["INSTAGRAM_ACCESS_TOKEN"] = token    # 앱이 설정을 다시 읽어도(config reload) 새 토큰을 쓰게
    now = dt.datetime.now().replace(microsecond=0)
    info = {"refreshed_at": now.isoformat(), "expires_at": (now + dt.timedelta(seconds=secs)).isoformat()}
    TOKEN_INFO.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_INFO.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"토큰을 갱신했습니다 — {info['expires_at'][:10]} 까지")
    return info


def ensure_token(log=print) -> None:
    """만료가 가깝거나 만료일을 모르면 갱신합니다. 갱신이 실패해도 지금 토큰이 살아 있으면 발행은 계속합니다."""
    exp = token_info().get("expires_at")
    if exp and (dt.datetime.fromisoformat(exp) - dt.datetime.now()).days > REFRESH_BEFORE_DAYS:
        return
    try:
        refresh_token(log)
    except InstaError as e:
        log(f"토큰 갱신 실패: {e} — 지금 토큰으로 계속합니다")


def _id(d: dict, what: str) -> str:
    if not d.get("id"):
        raise InstaError(f"{what}: 인스타가 id 를 돌려주지 않았습니다 ({d})")
    return d["id"]


def _wait_ready(container_id: str, what: str, timeout: int = 120) -> None:
    """컨테이너가 FINISHED 가 될 때까지 기다립니다. 인스타가 이미지를 가져가 처리하는 시간입니다."""
    end = time.time() + timeout
    while time.time() < end:
        d = _api("GET", container_id, fields="status_code,status")
        code = d.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstaError(f"{what} 처리 실패: {d.get('status') or code}")
        time.sleep(3)
    raise InstaError(f"{what} 처리가 {timeout}초 안에 끝나지 않았습니다.")


# ── 임시 공개 주소 ───────────────────────────────────
class _CardHandler(http.server.SimpleHTTPRequestHandler):
    """card01.jpg 같은 카드 파일만 내보냅니다. 폴더 목록·deck.html·caption.txt 는 404."""

    def _allowed(self) -> bool:
        return bool(_CARD_RE.fullmatch(urllib.parse.urlsplit(self.path).path.lstrip("/")))

    def do_GET(self):
        if self._allowed():
            super().do_GET()
        else:
            self.send_error(404)

    def do_HEAD(self):
        if self._allowed():
            super().do_HEAD()
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


def _drain(proc: subprocess.Popen, lines: queue.Queue) -> None:
    # 출력을 계속 비워야 합니다. 안 읽으면 파이프가 차서 cloudflared 가 멈춥니다.
    for line in proc.stdout:
        lines.put(line)


def _open_tunnel(port: int, timeout: int = 60) -> tuple[subprocess.Popen, str]:
    """cloudflared 임시 터널(계정 없이 쓰는 quick tunnel)을 열고 공개 주소를 돌려줍니다."""
    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_drain, args=(proc, lines), daemon=True).start()

    url, recent = "", []
    end = time.time() + timeout
    while time.time() < end and proc.poll() is None:
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            continue
        recent = (recent + [line.strip()])[-5:]
        m = _TUNNEL_RE.search(line)
        if m:
            url = m.group(0)
        # 주소가 먼저 찍히고, 실제 연결이 붙었다는 줄이 뒤에 나옵니다
        if url and "Registered tunnel connection" in line:
            return proc, url
    _close_tunnel(proc)
    raise InstaError("임시 공개 주소를 만들지 못했습니다. 인터넷 연결을 확인하세요.\n"
                     + "\n".join(recent))


def _close_tunnel(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_public(url: str, timeout: int = 60) -> None:
    """새 임시 주소로 카드가 바깥에서 열릴 때까지 기다립니다."""
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status == 200 and r.headers.get_content_type() == "image/jpeg":
                    return
                last = f"HTTP {r.status} {r.headers.get_content_type()}"
        except Exception as e:
            last = str(e)[:120]
        time.sleep(2)
    raise InstaError(f"임시 주소에서 카드가 열리지 않습니다: {last}")


@contextlib.contextmanager
def _public_folder(folder: Path, first: str, log):
    """with 블록 안에서만 folder 의 카드가 공개 주소로 열립니다. 블록을 나가면 바로 닫습니다."""
    handler = functools.partial(_CardHandler, directory=str(folder))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    proc = None
    try:
        log("임시 공개 주소를 여는 중…")
        proc, base = _open_tunnel(httpd.server_address[1])
        _wait_public(f"{base}/{first}")
        log(f"임시 주소 열림: {base}")
        yield base
    finally:
        _close_tunnel(proc)
        httpd.shutdown()
        httpd.server_close()
        log("임시 주소를 닫았습니다.")


# ── 공개 함수 ────────────────────────────────────────
def test_tunnel(company: str, log=print) -> str:
    """인스타에는 아무것도 보내지 않고, 이 컴퓨터의 첫 카드가 바깥 주소로 열리는지만 확인합니다."""
    if not CLOUDFLARED.exists():
        raise InstaError(f"임시 주소 프로그램이 없습니다: {CLOUDFLARED}")
    cards = insta_cards.made_cards(company)
    if not cards:
        raise InstaError(f"{company} 카드가 없습니다.")
    with _public_folder(cards[0].parent, cards[0].name, log) as base:
        url = f"{base}/{cards[0].name}"
        log(f"바깥에서 열림 확인: {url}")
    return url


def publish(company: str, caption: str, log=print) -> dict:
    """카드뉴스를 톰슨에듀AI 인스타에 캐러셀로 게시합니다. ⚠ 되돌릴 수 없습니다."""
    bad = problems(company, caption)
    if bad:
        raise InstaError("\n".join(bad))
    cards = insta_cards.made_cards(company)
    save_caption(company, caption)

    me = _api("GET", "me", fields="user_id,username")
    ig = me.get("user_id") or _id(me, "계정 확인")
    log(f"계정: @{me.get('username', '?')}")
    quota = (_api("GET", f"{ig}/content_publishing_limit",
                  fields="quota_usage,config").get("data") or [{}])[0]
    used, total = quota.get("quota_usage", 0), (quota.get("config") or {}).get("quota_total", 100)
    log(f"24시간 게시 한도: {used}/{total}")
    if used >= total:
        raise InstaError("24시간 게시 한도를 다 썼습니다. 내일 다시 시도하세요.")

    stamp = int(time.time())   # 같은 파일명을 다시 올릴 때 인스타가 옛 이미지를 쓰지 않게
    with _public_folder(cards[0].parent, cards[0].name, log) as base:
        children = []
        for i, p in enumerate(cards, 1):
            d = _api("POST", f"{ig}/media", image_url=f"{base}/{p.name}?v={stamp}",
                     is_carousel_item="true")
            children.append(_id(d, f"카드 {i} 등록"))
            log(f"  카드 {i}/{len(cards)} 등록")
        for i, cid in enumerate(children, 1):
            _wait_ready(cid, f"카드 {i}")
        log("카드를 캐러셀로 묶는 중…")
        parent = _id(_api("POST", f"{ig}/media", media_type="CAROUSEL",
                          children=",".join(children), caption=caption), "캐러셀 만들기")
        _wait_ready(parent, "캐러셀")
        # ── 여기서부터는 되돌릴 수 없습니다 ──
        mid = _id(_api("POST", f"{ig}/media_publish", creation_id=parent), "게시")

    rec = {"media_id": mid, "permalink": "", "cards": len(cards),
           "published_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    # 게시는 이미 끝났으니 주소를 못 받아도 기록부터 남깁니다 (다시 눌러 두 번 올라가는 것 방지)
    _mark(company, rec)
    try:
        rec["permalink"] = _api("GET", mid, fields="permalink").get("permalink", "")
        _mark(company, rec)
    except InstaError as e:
        log(f"게시는 됐지만 게시물 주소를 받지 못했습니다: {e}")
    log(f"게시 완료: {rec['permalink'] or mid}")
    return rec


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--test":
        try:
            test_tunnel(args[1])
        except InstaError as e:
            print(f"실패: {e}")
            sys.exit(1)
    else:
        print("사용법: python insta_publish.py --test <기업명>   (인스타에는 아무것도 보내지 않음)")
