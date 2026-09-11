# -*- coding: utf-8 -*-
r"""매일 1편 자동 작성 + 네이버 예약 발행.

동작:
  1) 대기열에서 아직 안 쓴 (기업 × 주제) 한 편을 꺼냅니다
     — 주제는 그 기업 자료가 충분한 것 중에서 자동으로 골라집니다
  2) 글 + 이미지를 만들고 검증합니다
  3) 네이버 에디터에 입력하고 '예약 발행'을 겁니다
     (실제 발행은 네이버 서버가 하므로 자동화 흔적이 남지 않습니다)
  4) 발행 기록을 남깁니다

실행:
  venv\Scripts\python.exe run_daily.py
  venv\Scripts\python.exe run_daily.py --dry                  (발행 없이 초안만)
  venv\Scripts\python.exe run_daily.py --company 한전KPS
  venv\Scripts\python.exe run_daily.py --topic resume         (주제 지정)
  venv\Scripts\python.exe run_daily.py --account blog_id_5       (계정 지정)
"""
from __future__ import annotations
import argparse
import datetime as dt
import random
import sys
import traceback

import config
import personas
import post_queue
import topics

LOG = config.DRAFTS_DIR / "_daily.log"


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def pick_time() -> dt.datetime | None:
    """예약 시각. 매일 조금씩 다르게 흩뿌려 패턴이 남지 않게 합니다.

    ⚠ **오늘 안의 시각만 돌려줍니다.** 네이버 예약 발행의 날짜 입력칸은 readonly 이고
      달력의 모든 날짜가 비활성으로 나와, 오늘이 아닌 날짜는 넣을 방법이 없습니다
      (2026-08-24 실측). 그래서 설정한 시간대가 이미 지났으면 None 을 돌려주고,
      호출한 쪽이 '오늘은 예약할 수 없다'고 판단하게 합니다.
      → 이 스크립트는 설정 시간대(기본 09:00~11:30)보다 이른 새벽에 돌려야 합니다.
    """
    h0, m0 = map(int, config.SCHEDULE_FROM.split(":"))
    h1, m1 = map(int, config.SCHEDULE_TO.split(":"))
    now = dt.datetime.now().replace(second=0, microsecond=0)

    start = now.replace(hour=h0, minute=m0)
    end = now.replace(hour=h1, minute=m1)
    if end <= start:                       # 자정을 넘기는 설정이면 오늘 끝까지로 자릅니다
        end = now.replace(hour=23, minute=50)

    # 이미 시간대가 지났으면 오늘은 예약할 수 없습니다
    if end <= now:
        return None
    if start <= now:                       # 시간대 중간이면 지금 이후로만
        start = now + dt.timedelta(minutes=20)
        if start >= end:
            return None

    span = int((end - start).total_seconds() // 600)      # 10분 단위 슬롯
    slot = random.randint(0, max(0, span))
    return start + dt.timedelta(minutes=10 * slot)


def _best_topic(company: str) -> str:
    """그 기업 자료로 아직 안 쓴 주제 중 가장 앞선 것. 없으면 종합."""
    planned = post_queue.plan().get(company, [])
    written = set(post_queue.done_topics(company))
    for k in planned:
        if k not in written:
            return k
    return topics.ALL_KEY


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", help="기업을 직접 지정")
    ap.add_argument("--topic", choices=[topics.ALL_KEY] + topics.DISPLAY_ORDER,
                    help="주제를 직접 지정 (기본: 대기열이 자동 선택)")
    ap.add_argument("--dry", action="store_true", help="초안만 만들고 발행하지 않음")
    ap.add_argument("--now", action="store_true", help="예약하지 않고 창만 띄움")
    ap.add_argument("--account", help="발행할 네이버 계정 (기본: 저장된 기본 계정)")
    args = ap.parse_args()

    # 계정마다 글 스타일과 즐겨 쓰는 주제가 다릅니다(accounts.py).
    # 스타일은 어투뿐 아니라 표 이미지 색·모양까지 바꿉니다.
    import accounts
    persona = None
    forced_topic = args.topic
    if args.account:
        config.set_account(args.account)
        d = accounts.defaults(args.account)
        persona = d["persona"]
        if not forced_topic and d["topic"] != topics.ALL_KEY:
            forced_topic = d["topic"]
        log(f"발행 계정: {args.account} · {personas.name(persona)}")

    # 한 편의 단위는 (기업 × 주제)입니다. 대기열이 그 기업 자료로 쓸 만한
    # 주제까지 함께 골라줍니다.
    if args.company:
        company = args.company
        topic = forced_topic or _best_topic(company)
    else:
        task = post_queue.next_task(forced_topic)
        if not task:
            log("계획된 글을 모두 썼습니다. post_queue.py --reset 으로 초기화할 수 있습니다.")
            return 0
        company, topic = task
        if forced_topic:
            topic = forced_topic

    done, total = post_queue.status()
    log(f"오늘의 글: {company} · {topics.name(topic)}  (진행 {done}/{total}편)")

    # ── 1. 글 생성 ───────────────────────────────────
    try:
        import main as gen
        out, post, profile, needed, missing, issues = gen.create_draft(
            company, topic=topic, persona=persona)
    except Exception:
        log("❌ 글 생성 실패\n" + traceback.format_exc())
        return 1

    log(f"초안 저장: {out.name}")
    if issues:
        log(f"⚠ 검증 미해결 {len(issues)}건: {issues[0]}")
    if missing:
        log(f"⚠ 없는 이미지 {len(missing)}개: {', '.join(missing)}")

    if args.dry:
        log("--dry 이므로 발행하지 않고 종료합니다.")
        return 0

    # ── 2. 예약 발행 ─────────────────────────────────
    when = None
    if not args.now:
        when = pick_time()
        if when is None:
            log(f"오늘은 예약할 수 없습니다 — 설정 시간대"
                f"({config.SCHEDULE_FROM}~{config.SCHEDULE_TO})가 이미 지났습니다.")
            log("   초안은 저장됐습니다. 발행 탭에서 직접 올리거나, "
                "내일 이른 시각에 다시 실행하세요.")
            post_queue.mark(company, draft=out.name, status="draft_only",
                            topic=topic, account=config.BLOG_ID)
            return 0
        log(f"예약 시각: {when:%Y-%m-%d %H:%M}")

    try:
        import publisher
        publisher.fill_editor(out, interactive=False, schedule_at=when,
                              persona=persona)
    except Exception:
        log("❌ 발행 단계 실패\n" + traceback.format_exc())
        post_queue.mark(company, draft=out.name, status="draft_only",
                        topic=topic, account=config.BLOG_ID)
        return 1

    post_queue.mark(company, draft=out.name,
                    scheduled_at=when.strftime("%Y-%m-%d %H:%M") if when else "",
                    status="scheduled" if when else "manual",
                    topic=topic, account=config.BLOG_ID)
    log(f"✅ 완료: {company} · {topics.name(topic)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
