# -*- coding: utf-8 -*-
"""인스타 반자동 발행 대기열.

■ 흐름
  카드뉴스 만들기 → 사람이 확인·수정 → [확인 완료] → 대기열 (다음 발행 시각 자동 배정)
  → 윈도우 작업 스케줄러가 발행 시각마다 run_insta.py 실행 → 때가 된 카드 1건 발행

■ 안전장치
  - 사람이 [확인 완료]한 카드만 올라갑니다.
  - 확인한 뒤 문구·캡션·스타일·카드 그림이 바뀌면 '다시 확인 필요'로 멈춥니다 (지문 비교).
  - 한 번 실행에 1건만 올립니다. 실패하면 다음 발행 시각으로 미루고, 3번 실패하면 멈춥니다.
  - 이미 올린 기업은 다시 올리지 않습니다.
  - 작업 스케줄러는 컴퓨터가 켜져 있고 로그인돼 있을 때만 돕니다. 꺼져 있던 시각의 카드는 다음 시각에 올라갑니다.

기록: ../auto_insta/insta_out/_queue.json
"""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import io
import json
import subprocess
import sys

import config
import insta_cards
import insta_publish

QUEUE = config.INSTA_OUT_DIR / "_queue.json"
LOG = config.INSTA_OUT_DIR / "_insta_daily.log"
MAX_TRIES = 3
MIN_LEAD_MIN = 10          # 지금부터 최소 10분 뒤 시각부터 배정합니다
FMT = "%Y-%m-%d %H:%M"     # 글자 그대로 비교해도 시간 순서가 맞는 형식

APPROVED, PUBLISHED, FAILED = "approved", "published", "failed"
CHANGED_MSG = "확인한 뒤 카드나 캡션이 바뀌었습니다. 다시 [확인 완료]를 눌러주세요."

TASK_PREFIX = "TompsonEduAI_Insta_"
RUNNER = config.BASE_DIR / "run_insta.py"


# ── 기록 ─────────────────────────────────────────────
def file_log(msg: str) -> None:
    """화면에 찍고 _insta_daily.log 에도 남깁니다 (자동 발행·앱의 지금 발행 모두)."""
    for text in str(msg).splitlines() or [""]:
        line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {text}"
        print(line)      # 작업 스케줄러(pythonw)에서는 화면이 없어 아무 일도 하지 않습니다
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def _load() -> dict:
    try:
        return json.loads(QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint(company: str) -> str:
    """카드 문구·스타일(deck.json), 캡션, 카드 그림이 확인 때와 같은지 비교하는 값."""
    h = hashlib.md5()
    d = insta_cards.OUT_DIR / company
    for name in ("deck.json", "caption.txt"):
        p = d / name
        h.update(p.read_bytes() if p.exists() else b"-")
    for p in insta_cards.made_cards(company):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


# ── 발행 시각 ────────────────────────────────────────
def post_times() -> list[dt.time]:
    out = []
    for s in config.INSTA_POST_TIMES:
        try:
            h, m = map(int, str(s).strip().split(":"))
            out.append(dt.time(h, m))
        except ValueError:
            continue
    return sorted(set(out)) or [dt.time(8, 30)]


def _taken(data: dict, except_company: str | None = None) -> set[str]:
    return {v["scheduled_at"] for c, v in data.items()
            if v.get("status") == APPROVED and c != except_company}


def next_slot(taken: set[str] = frozenset()) -> dt.datetime:
    """아직 아무 카드도 잡히지 않은 가장 가까운 발행 시각."""
    start = dt.datetime.now() + dt.timedelta(minutes=MIN_LEAD_MIN)
    day = start.date()
    for _ in range(400):
        for t in post_times():
            when = dt.datetime.combine(day, t)
            if when >= start and when.strftime(FMT) not in taken:
                return when
        day += dt.timedelta(days=1)
    raise RuntimeError("빈 발행 시각을 찾지 못했습니다")


# ── 확인 완료 · 취소 · 시각 변경 ─────────────────────
def approve(company: str) -> dict:
    """확인 완료: 대기열에 넣고 다음 빈 발행 시각을 배정합니다. 문제가 있으면 ValueError."""
    if insta_publish.published(company):
        raise ValueError(f"{company}는 이미 인스타에 올렸습니다.")
    bad = insta_publish.content_problems(company, insta_publish.load_caption(company))
    if bad:
        raise ValueError("\n".join(bad))
    data = _load()
    rec = {"status": APPROVED,
           "approved_at": dt.datetime.now().strftime(FMT),
           "scheduled_at": next_slot(_taken(data, company)).strftime(FMT),
           "fingerprint": fingerprint(company), "tries": 0, "error": ""}
    data[company] = rec
    _save(data)
    return rec


def unapprove(company: str) -> None:
    data = _load()
    if (data.get(company) or {}).get("status") != PUBLISHED:
        data.pop(company, None)
        _save(data)


def reschedule(company: str, when: dt.datetime) -> None:
    data = _load()
    rec = data.get(company)
    if not rec or rec.get("status") != APPROVED:
        raise ValueError(f"{company}는 발행 대기 중이 아닙니다.")
    s = when.strftime(FMT)
    if s in _taken(data, company):
        raise ValueError(f"{s}에는 이미 다른 카드가 잡혀 있습니다.")
    rec["scheduled_at"] = s
    _save(data)


def entry(company: str) -> dict:
    """화면 표시용 기록. 발행 대기 중이면 changed(확인 뒤 바뀜) 를 함께 넣습니다."""
    rec = dict(_load().get(company) or {})
    pub = insta_publish.published(company)
    if pub and rec and rec.get("status") != PUBLISHED:
        # 대기열을 거치지 않고 [지금 발행]으로 올린 경우. 화면에는 바로 발행됨으로 보여주고,
        # 기록(_queue.json)은 다음 자동 실행 때 run_due 가 발행됨으로 바꿉니다 (두 번 올리지 않음)
        rec.update(status=PUBLISHED, published_at=pub.get("published_at", ""),
                   permalink=pub.get("permalink", ""), error="")
        return rec
    if rec.get("status") == APPROVED:
        rec["changed"] = rec.get("fingerprint") != fingerprint(company)
        if not rec["changed"] and rec.get("error") == CHANGED_MSG:
            rec["error"] = ""        # 고쳤던 걸 되돌려 확인 때와 같아졌으면 옛 경고는 지웁니다
    return rec


def entries() -> list[tuple[str, dict]]:
    """대기 중(예약 시각 순) → 멈춤 → 발행됨(최근 순)."""
    items = [(c, entry(c)) for c in _load()]
    waiting = sorted((x for x in items if x[1].get("status") == APPROVED),
                     key=lambda x: x[1].get("scheduled_at", ""))
    failed = [x for x in items if x[1].get("status") == FAILED]
    done = sorted((x for x in items if x[1].get("status") == PUBLISHED),
                  key=lambda x: x[1].get("published_at", ""), reverse=True)
    return waiting + failed + done


# ── 발행 ─────────────────────────────────────────────
def _publish_one(data: dict, company: str, log) -> bool:
    rec = data[company]
    insta_publish.ensure_token(log)
    try:
        pub = insta_publish.publish(company, insta_publish.load_caption(company), log=log)
    except Exception as e:
        rec["tries"] = rec.get("tries", 0) + 1
        rec["error"] = (str(e).strip().splitlines() or ["알 수 없는 오류"])[0][:200]
        if rec["tries"] >= MAX_TRIES:
            rec["status"] = FAILED
            log(f"{company}: {MAX_TRIES}번 실패해 멈췄습니다 — {rec['error']}")
        else:
            rec["scheduled_at"] = next_slot(_taken(data, company)).strftime(FMT)
            log(f"{company}: 실패 {rec['tries']}회 — {rec['error']} → {rec['scheduled_at']} 에 다시 시도")
        _save(data)
        return False
    rec.update(status=PUBLISHED, published_at=pub.get("published_at", ""),
               permalink=pub.get("permalink", ""), error="")
    _save(data)
    log(f"{company}: 발행 완료 {pub.get('permalink', '')}")
    return True


def run_due(log=print, dry: bool = False) -> str | None:
    """예약 시각이 지난 카드 1건을 올립니다. 올린(dry 면 올릴) 기업명, 없으면 None."""
    data = _load()
    now = dt.datetime.now().strftime(FMT)
    due = sorted((v["scheduled_at"], c) for c, v in data.items()
                 if v.get("status") == APPROVED and v.get("scheduled_at", "~") <= now)
    if not due:
        log("때가 된 카드가 없습니다.")
        return None
    for _when, company in due:
        rec = data[company]
        if insta_publish.published(company):
            rec["status"] = PUBLISHED
            _save(data)
            log(f"{company}: 이미 올린 기업이라 대기열에서 발행됨으로 바꿨습니다.")
            continue
        if rec.get("fingerprint") != fingerprint(company):
            rec["error"] = CHANGED_MSG
            _save(data)
            log(f"{company}: {rec['error']}")
            continue
        if dry:
            log(f"[시험] 지금 실행하면 {company} 를 올립니다 (예약 {rec['scheduled_at']})")
            return company
        # 실패해도 다음 카드로 넘어가지 않습니다. 실패 원인(인터넷·토큰 등)은 보통 다음 카드도 똑같이 막습니다
        return company if _publish_one(data, company, log) else None
    return None


def publish_now(company: str, log=print) -> None:
    """대기열 순서와 상관없이 지금 올립니다 (사람이 누른 경우)."""
    data = _load()
    rec = data.get(company)
    if not rec or rec.get("status") != APPROVED:
        raise ValueError(f"{company}는 발행 대기 중이 아닙니다.")
    if rec.get("fingerprint") != fingerprint(company):
        raise ValueError(CHANGED_MSG)
    if not _publish_one(data, company, log):
        raise insta_publish.InstaError(data[company].get("error") or "발행하지 못했습니다.")


# ── 자동 발행 (윈도우 작업 스케줄러) ─────────────────
def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          encoding="cp949", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def auto_tasks() -> list[str]:
    """등록된 자동 발행 작업 이름들 (없으면 빈 목록 = 꺼짐)."""
    r = _schtasks("/Query", "/FO", "CSV", "/NH")
    names = []
    for row in csv.reader(io.StringIO(r.stdout)):
        if row and row[0].lstrip("\\").startswith(TASK_PREFIX):
            names.append(row[0].lstrip("\\"))
    return sorted(set(names))


def disable_auto() -> None:
    for name in auto_tasks():
        _schtasks("/Delete", "/TN", name, "/F")


def enable_auto() -> list[str]:
    """발행 시각마다 run_insta.py 를 실행하는 작업을 등록합니다 (기존 것은 지우고 새로)."""
    disable_auto()
    # 창 없이 돌도록 pythonw 를 씁니다. 로그는 _insta_daily.log 에 남습니다
    pyw = config.BASE_DIR / "venv" / "Scripts" / "pythonw.exe"
    exe = pyw if pyw.exists() else sys.executable
    made = []
    for t in post_times():
        name = f"{TASK_PREFIX}{t:%H%M}"
        r = _schtasks("/Create", "/TN", name, "/TR", f'"{exe}" "{RUNNER}"',
                      "/SC", "DAILY", "/ST", f"{t:%H:%M}", "/F")
        if r.returncode != 0:
            raise RuntimeError(f"작업 등록 실패 ({name}): {(r.stderr or r.stdout).strip()}")
        made.append(name)
    return made
