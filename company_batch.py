# -*- coding: utf-8 -*-
r"""기업 하나를 골라 모든 계정에 한 편씩 쓰고 발행합니다.

■ 흐름
  1) 계획   계정마다 스타일·주제·카테고리·발행 시각을 정합니다 (build_plan)
  2) 확인   사람이 표를 보고 승인합니다 (앱 탭 또는 --run 없이 실행)
  3) 실행   계정마다 글 생성 → 에디터 입력 → 지금 발행 또는 예약 발행 (run_plan)

■ 주제 배정
계정 기본 주제를 그대로 쓰면 8개 중 4개가 '전 전형 종합'이라 같은 기업 종합 글이
4편 나갑니다. 그래서 두 번에 나눠 배정합니다.
  1차  계정 기본 주제를 줍니다. 단, 이미 발행했거나 자료가 없거나
       이번 실행에서 다른 계정이 먼저 가져간 주제는 주지 않습니다.
  2차  못 받은 계정에 남은 주제를 줍니다. 자료가 충분한 주제 → 종합 → 얇은 주제 순.
  주제가 모자라면 겹칠 수밖에 없는데, 그때는 **스타일이 다른 계정이 쓴 주제**를
  골라 같은 주제라도 글이 최대한 달라지게 합니다.

■ 발행 시각
  지금 발행  계정 사이에 간격을 둡니다. 간격 0 으로 5개 계정을 20분에 몰아 올렸더니
            세션 2개가 끊겼습니다(2026-09-11).
  예약 발행  시작 시각부터 계정마다 30~60분씩 벌려 네이버에 예약을 겁니다.
            발행은 네이버 서버가 하므로 PC 를 꺼도 됩니다. 내일 이후 날짜도 됩니다.
            에디터 작업은 계정 사이 간격을 두고 차례로 하므로, 앞 계정 작업이
            길어져 예약 시각이 너무 가까워지면 뒤로 밀어줍니다.

    venv\Scripts\python.exe company_batch.py 신용보증기금                       (계획만)
    venv\Scripts\python.exe company_batch.py 신용보증기금 --schedule "2026-09-16 09:00"
    venv\Scripts\python.exe company_batch.py 신용보증기금 --posting drafts\공고.txt --run
"""
from __future__ import annotations
import datetime as dt
import random
import time
from dataclasses import dataclass

import account_check
import accounts
import config
import md_loader
import personas
import post_queue
import topics as T

MODE_NOW = "now"
MODE_SCHEDULE = "schedule"

#: 예약 시각은 그 계정의 에디터 작업 시점보다 최소 이만큼 뒤여야 합니다
MIN_LEAD_MIN = 20
#: 예약은 최대 한 달 뒤까지만 잡습니다. 그 이상은 쓸 일이 없습니다.
MAX_AHEAD_DAYS = 30
#: 로그인 확인 결과 중 '끊긴 것'으로 보고 건너뛸 상태.
#: unknown 은 크롬이 쿠키 파일을 잠가서 못 읽은 경우라 끊겼다고 단정하지 않습니다.
LOGGED_OUT = {"expired", "none"}


@dataclass
class Row:
    """계획표 한 줄 = 계정 하나."""
    account: str
    persona: str
    default_topic: str
    login: str = ""
    topic: str | None = None
    category: str | None = None
    when: dt.datetime | None = None
    note: str = ""               # 배정 사유
    skip: bool = False
    # ── 실행 결과 ──
    status: str = ""             # published / scheduled / failed / skipped / stopped
    draft: str = ""
    message: str = ""


# ── 계획 ─────────────────────────────────────────────
def _ceil10(t: dt.datetime) -> dt.datetime:
    """10분 단위로 올림. 네이버 예약은 분을 10분 단위로만 고릅니다."""
    t = t.replace(second=0, microsecond=0)
    extra = (-t.minute) % 10
    return t + dt.timedelta(minutes=extra)


def _interleave(names: list[str]) -> list[str]:
    """스타일이 번갈아 나오게 계정 순서를 섞습니다 (A B C D A B C D).

    같은 스타일 글이 연달아 올라가면 한 사람이 쓴 티가 더 납니다.
    """
    groups = {k: [] for k in personas.keys()}
    for n in names:
        groups.setdefault(accounts.defaults(n)["persona"], []).append(n)
    out, i = [], 0
    while any(groups.values()):
        for k in list(groups):
            if i < len(groups[k]):
                out.append(groups[k][i])
        i += 1
        if all(i >= len(v) for v in groups.values()):
            break
    return out


def topic_pool(company: str) -> tuple[list[str], dict[str, str], set[str]]:
    """(쓸 수 있는 주제 순서, 주제별 자료 충분도, 이미 발행한 주제)."""
    p = md_loader.get_profile(company)
    if p is None:
        raise ValueError(f"'{company}' 자료가 없습니다.")
    stats = md_loader.angle_stats(p)
    avail = {k: T.availability(stats.get(k, 0), k) for k in T.DISPLAY_ORDER}
    avail[T.ALL_KEY] = "ok"
    ok = [k for k in T.DISPLAY_ORDER if avail[k] == "ok"]
    thin = [k for k in T.DISPLAY_ORDER if avail[k] == "thin"]
    done = set(post_queue.done_topics(p["company_key"]))
    return ok + [T.ALL_KEY] + thin, avail, done


def assign_topics(rows: list[Row], order: list[str], avail: dict[str, str],
                  done: set[str]) -> None:
    """계정마다 주제를 정합니다. 규칙은 모듈 설명 참고."""
    active = [r for r in rows if not r.skip]
    taken: dict[str, Row] = {}

    # 1차 — 계정 기본 주제
    for r in active:
        k = r.default_topic
        if k in order and k not in done and k not in taken:
            r.topic, r.note = k, "기본 주제"
            taken[k] = r

    # 2차 — 남은 주제
    free = [k for k in order if k not in done and k not in taken]
    for r in active:
        if r.topic:
            continue
        if r.default_topic in done:
            why = "기본 주제 이미 발행"
        elif r.default_topic not in order:
            why = "기본 주제 자료 부족"
        else:
            why = f"기본 주제를 {taken[r.default_topic].account} 가 사용"
        if free:
            k = free.pop(0)
            r.topic, r.note = k, f"다른 주제 발행 · {why}"
            taken[k] = r
            continue
        # 주제가 모자라 겹칠 수밖에 없음 — 스타일이 다른 계정의 주제를 고릅니다
        pool = [k for k in order if k not in done] or order
        def cost(k: str):
            owner = taken.get(k)
            return (owner is not None and owner.persona == r.persona,
                    avail.get(k) != "ok", order.index(k))
        k = min(pool, key=cost)
        owner = taken.get(k)
        r.topic = k
        r.note = f"겹침 · {owner.account} 와 같은 주제" if owner else "겹침 · 이미 발행한 주제"


def schedule_times(n: int, start: dt.datetime,
                   spread: tuple[int, int] = (30, 60)) -> list[dt.datetime]:
    """시작 시각부터 spread 분 사이로 벌린 n 개의 예약 시각."""
    t, out = _ceil10(start), []
    for _ in range(n):
        out.append(t)
        t = _ceil10(t + dt.timedelta(minutes=random.randint(*spread)))
    return out


def build_plan(company: str, mode: str = MODE_NOW,
               start: dt.datetime | None = None,
               spread: tuple[int, int] = (30, 60),
               account_list: list[str] | None = None) -> tuple[str, list[Row]]:
    """계획표를 만듭니다. (기업 정식 이름, 행 목록)을 돌려줍니다. 아무것도 올리지 않습니다."""
    p = md_loader.get_profile(company)
    if p is None:
        raise ValueError(f"'{company}' 자료가 없습니다.")
    name = p["company_key"]

    # 로그인 파일이 없는 계정도 표에 올려야 '왜 빠졌는지'가 보입니다.
    # config.list_accounts() 만 쓰면 그런 계정이 표에서 통째로 사라졌습니다.
    names = account_list or sorted(set(config.list_accounts()) | set(accounts.DEFAULTS))

    # 이미 이 기업 글을 올린 계정은 건너뜁니다. 같은 블로그에 같은 기업 글이
    # 두 번 올라가면 '계정마다 한 편씩'이라는 취지와 어긋납니다.
    posted: dict[str, str] = {}
    for k, v in post_queue.records(name).items():
        if (v or {}).get("status") in post_queue.DONE_STATUS and v.get("account"):
            posted.setdefault(v["account"], k)

    rows = []
    for a in _interleave(names):
        d = accounts.defaults(a)
        state = account_check.login_state(a)[0]
        r = Row(account=a, persona=d["persona"], default_topic=d["topic"],
                login=state, category=accounts.category_for(a, name))
        if a in posted:
            r.skip, r.note = True, f"건너뜀 · 이미 이 기업 글 발행 ({T.name(posted[a])})"
        elif state in LOGGED_OUT:
            r.skip, r.note = True, f"건너뜀 · 로그인 {state}"
        rows.append(r)

    order, avail, done = topic_pool(name)
    assign_topics(rows, order, avail, done)

    if mode == MODE_SCHEDULE:
        active = [r for r in rows if not r.skip]
        start = start or dt.datetime.now() + dt.timedelta(minutes=MIN_LEAD_MIN + 10)
        times = schedule_times(len(active), start, spread)
        limit = dt.datetime.now() + dt.timedelta(days=MAX_AHEAD_DAYS)
        if times and times[-1] > limit:
            raise ValueError(f"예약은 지금부터 {MAX_AHEAD_DAYS}일 이내로만 잡을 수 있습니다. "
                             f"마지막 글이 {times[-1]:%m/%d %H:%M} 로 넘어갑니다.")
        for r, t in zip(active, times):
            r.when = t
    return name, rows


# ── 실행 ─────────────────────────────────────────────
def _sleep(seconds: int, stop_event) -> bool:
    """중지 신호를 보면서 잡니다. 중지되면 False."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            return False
        time.sleep(1)
    return True


def run_plan(company: str, rows: list[Row], mode: str = MODE_NOW,
             posting_text: str | None = None,
             gap: tuple[int, int] = (180, 300),
             spread: tuple[int, int] = (30, 60),
             stop_event=None, log=print) -> list[Row]:
    """계획대로 실행합니다. ⚠ 실제로 블로그에 올라갑니다.

    계정 하나가 실패해도 멈추지 않고 다음 계정으로 넘어갑니다.
    결과는 각 Row 의 status / message 에 남습니다.
    """
    import main as gen
    import publisher

    active = [r for r in rows if not r.skip]
    for r in rows:
        if r.skip:
            r.status = "skipped"
            r.message = r.note

    prev_when: dt.datetime | None = None
    for i, r in enumerate(active, 1):
        if stop_event is not None and stop_event.is_set():
            r.status, r.message = "stopped", "중지 요청"
            continue

        log(f"\n── {i}/{len(active)}  {r.account} · {personas.name(r.persona)} · "
            f"{T.name(r.topic)}")

        # 1) 생성
        try:
            out, post, _profile, _needed, missing, issues = gen.create_draft(
                company, posting_text, quiet=True, topic=r.topic, persona=r.persona)
            r.draft = out.name
        except Exception as e:
            r.status, r.message = "failed", f"글 생성 실패: {str(e)[:150]}"
            log(f"  ❌ {r.message}")
            continue
        log(f"  초안 {out.name} · {len(post.body)}자")
        if issues:
            log(f"  ⚠ 검증 미해결 {len(issues)}건: {issues[0][:70]}")
        if missing:
            log(f"  ⚠ 없는 이미지: {', '.join(missing)}")

        # 2) 발행 시각 — 앞 작업이 길어져 너무 가까워졌으면 뒤로 밉니다
        when = None
        if mode == MODE_SCHEDULE:
            floor = _ceil10(dt.datetime.now() + dt.timedelta(minutes=MIN_LEAD_MIN))
            if prev_when is not None:
                floor = max(floor, _ceil10(prev_when + dt.timedelta(minutes=spread[0])))
            when = r.when or floor
            if when < floor:
                log(f"  예약 시각을 {when:%m/%d %H:%M} → {floor:%m/%d %H:%M} 로 미룹니다")
                when = floor
            r.when = when

        # 3) 발행
        config.set_account(r.account)
        # 카테고리는 계정마다 반드시 새로 넣습니다. 비워두지 않으면 앞 계정 값이 남습니다.
        config.CATEGORY = r.category or ""
        try:
            publisher.fill_editor(out, interactive=False,
                                  publish_at_once=(mode == MODE_NOW),
                                  schedule_at=when, persona=r.persona)
        except Exception as e:
            r.status, r.message = "failed", str(e)[:200]
            log(f"  ❌ 발행 실패: {r.message}")
            post_queue.mark(company, draft=out.name, status="draft_only",
                            topic=r.topic, account=r.account)
            continue

        if mode == MODE_NOW:
            r.status, r.message = "published", "발행 완료"
            post_queue.mark(company, draft=out.name, status="published",
                            topic=r.topic, account=r.account)
        else:
            r.status, r.message = "scheduled", f"{when:%m/%d %H:%M} 예약"
            post_queue.mark(company, draft=out.name, status="scheduled",
                            scheduled_at=f"{when:%Y-%m-%d %H:%M}",
                            topic=r.topic, account=r.account)
            prev_when = when
        log(f"  ✅ {r.message}")

        if i < len(active):
            wait = random.randint(*gap)
            log(f"  ⏳ 다음 계정까지 {wait // 60}분 {wait % 60}초")
            if not _sleep(wait, stop_event):
                log("  중지 요청을 받았습니다")

    return rows


def summary(rows: list[Row]) -> str:
    label = {"published": "발행", "scheduled": "예약", "failed": "실패",
             "skipped": "건너뜀", "stopped": "중지", "": "대기"}
    lines = []
    for r in rows:
        when = f"{r.when:%m/%d %H:%M}" if r.when else ""
        lines.append(f"  {label.get(r.status, r.status):<4} {r.account:<16} "
                     f"{personas.name(r.persona):<8} {T.name(r.topic) if r.topic else '-':<14} "
                     f"{when:<12} {r.message or r.note}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    ap.add_argument("--schedule", help='예약 시작 시각 "YYYY-MM-DD HH:MM". 없으면 지금 발행')
    ap.add_argument("--posting", help="채용공고 텍스트 파일")
    ap.add_argument("--gap", type=int, default=180, help="계정 사이 최소 간격(초)")
    ap.add_argument("--run", action="store_true", help="⚠ 실제로 발행합니다")
    args = ap.parse_args()

    mode = MODE_SCHEDULE if args.schedule else MODE_NOW
    start = dt.datetime.strptime(args.schedule, "%Y-%m-%d %H:%M") if args.schedule else None
    name, rows = build_plan(args.company, mode, start)

    print(f"[{name}] {'예약 발행' if mode == MODE_SCHEDULE else '지금 발행'} 계획\n")
    for r in rows:
        when = f"{r.when:%m/%d %H:%M}" if r.when else ""
        print(f"  {r.account:<16} {personas.name(r.persona):<8} "
              f"{T.name(r.topic) if r.topic else '-':<14} "
              f"{r.category or '기본':<10} {when:<12} {r.note}")

    if not args.run:
        print("\n계획만 보여드렸습니다. 실제로 올리려면 --run 을 붙이세요.")
    else:
        text = Path(args.posting).read_text(encoding="utf-8") if args.posting else None
        run_plan(name, rows, mode, text, gap=(args.gap, args.gap + args.gap // 2))
        print("\n결과\n" + summary(rows))
