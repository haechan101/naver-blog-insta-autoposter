# -*- coding: utf-8 -*-
r"""여러 계정에 번갈아가며 글을 쓰고 **바로 발행**합니다.

  venv\Scripts\python.exe run_batch.py --count 3 --topic ncs
  venv\Scripts\python.exe run_batch.py --count 3 --dry      (발행 직전까지만)
  venv\Scripts\python.exe run_batch.py --count 8 --accounts blog_id_5,blog_id_8

⚠ --dry 없이 돌리면 글이 **실제로 블로그에 올라갑니다.** 되돌리려면 직접 지워야 합니다.
   처음에는 --dry 로 한 번, 그다음 --count 1 로 한 편만 해보시길 권합니다.

동작:
  1) 대기열에서 (기업 × 주제)를 하나 꺼냅니다
  2) 글 + 이미지를 만들고 검증합니다
  3) 계정을 하나 골라 에디터에 채우고 발행합니다
  4) 다음 글은 그다음 계정으로 (번갈아가며)
  5) 글 사이에 시간 간격을 둡니다
"""
from __future__ import annotations
import argparse
import datetime as dt
import random
import sys
import time
import traceback
from pathlib import Path

import account_check
import accounts
import config
import post_queue
import topics

LOG = config.DRAFTS_DIR / "_batch.log"


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1, help="쓸 글 수")
    ap.add_argument("--persona", default=None,
                    help="스타일 고정 (기본: 계정 기본값)")
    ap.add_argument("--topic", default=None,
                    choices=[topics.ALL_KEY] + topics.DISPLAY_ORDER,
                    help="주제 고정 (기본: 대기열이 기업마다 알아서 고름)")
    ap.add_argument("--accounts", default=None,
                    help="쓸 계정을 쉼표로. 기본: 로그인된 계정 전부")
    ap.add_argument("--company", default=None,
                    help="기업 고정. 대기열 대신 이 기업으로만 씁니다 "
                         "(공고가 떴을 때 여러 계정에 몰아 쓰는 용도)")
    ap.add_argument("--posting", default=None,
                    help="채용공고 텍스트 파일. 주면 글 맨 앞에 "
                         "'채용 일정 정리' 섹션이 실제 날짜와 함께 들어갑니다")
    ap.add_argument("--plan", default=None,
                    help="계정마다 주제를 따로 지정. "
                         "예) blog_id_1:resume,blog_id_5:ncs "
                         "(--accounts 를 대신하며 순서대로 씁니다)")
    ap.add_argument("--dry", action="store_true",
                    help="발행 버튼만 누르지 않음 (에디터 채우기까지는 진짜로 함)")
    ap.add_argument("--gap", type=int, default=180,
                    help="글 사이 최소 간격(초). 기본 180")
    args = ap.parse_args()

    # ── 계정 준비 ────────────────────────────────────
    # ⚠ 변수명을 accounts 로 쓰면 accounts 모듈을 가려서
    #   accounts.defaults() 가 깨집니다. 이름을 따로 씁니다.
    # --plan 은 계정과 주제를 한 번에 정합니다. 같은 기업으로 여러 계정에 쓸 때
    # 계정마다 다른 각도를 잡아줘야 서로 비슷한 글이 되지 않습니다.
    plan_topics: dict[str, str] = {}
    if args.plan:
        for pair in args.plan.split(","):
            acct, _, tk = pair.strip().partition(":")
            if not acct:
                continue
            if tk and tk not in topics.TOPICS and tk != topics.ALL_KEY:
                log(f"❌ 모르는 주제입니다: {tk}")
                return 1
            plan_topics[acct.strip()] = tk.strip() or None

    if plan_topics:
        account_list = list(plan_topics)
    elif args.accounts:
        account_list = [a.strip() for a in args.accounts.split(",") if a.strip()]
    else:
        account_list = account_check.usable_accounts()

    posting_text = None
    if args.posting:
        posting_text = Path(args.posting).read_text(encoding="utf-8")
        log(f"채용공고 {len(posting_text):,}자를 함께 넣습니다 — "
            "글 맨 앞에 '채용 일정 정리' 섹션이 들어갑니다")

    bad = [a for a in account_list if account_check.login_state(a)[0] != "ok"]
    if bad:
        log(f"❌ 로그인 안 된 계정이 있습니다: {', '.join(bad)}")
        log("   앱의 [계정 추가·재로그인] 으로 로그인한 뒤 다시 실행하세요.")
        return 1
    if not account_list:
        log("❌ 발행할 수 있는 계정이 없습니다.")
        return 1

    log(f"계정 {len(account_list)}개로 {args.count}편 "
        f"{'준비만(dry)' if args.dry else '작성·발행'}합니다: "
        f"{', '.join(account_list)}")

    import main as gen
    import publisher
    import validator

    done = 0
    for i in range(args.count):
        account = account_list[i % len(account_list)]

        # 주제를 고정했으면 '그 주제를 아직 안 쓴 기업'을 찾아야 합니다.
        # 안 그러면 같은 기업이 계속 나와서 같은 글이 여러 계정에 올라갑니다.
        # 계정 기본값 — 스타일·주제·카테고리
        d = accounts.defaults(account)
        persona = args.persona or d["persona"]
        want_topic = plan_topics.get(account) or args.topic or d["topic"]

        if args.company:                 # 기업을 고정한 경우 대기열을 쓰지 않습니다
            company, topic = args.company, want_topic
        else:
            task = post_queue.next_task(want_topic)
            if not task:
                log("계획된 글을 모두 썼습니다. 여기서 멈춥니다."
                    if not args.topic else
                    f"'{topics.name(args.topic)}' 로 더 쓸 기업이 없습니다.")
                break
            company, topic = task

        import personas
        log(f"── {i+1}/{args.count}  {company} · {topics.name(topic)} · "
            f"{personas.name(persona)}  → {account}")

        # 1) 생성
        try:
            out, post, profile, needed, missing, issues = gen.create_draft(
                company, posting_text, topic=topic,
                persona=persona, quiet=True)
        except Exception:
            log("  ❌ 글 생성 실패\n" + traceback.format_exc()[-500:])
            continue
        log(f"  초안: {out.name}  ({len(post.body)}자)")
        if issues:
            log(f"  ⚠ 검증 미해결 {len(issues)}건: {issues[0][:60]}")
        if missing:
            log(f"  ⚠ 없는 이미지: {', '.join(missing)}")

        # 2) 발행
        config.set_account(account)
        # ⚠ config.CATEGORY 는 모듈 전역입니다. 카테고리가 없는 계정에서
        #   그냥 두면 **앞 계정 값이 그대로 남습니다.** 실제로 blog_id_5 의
        #   '금융공기업기출' 이 뒤 4개 계정으로 새어 4번 연속 실패했습니다
        #   (2026-08-26 실측). 없으면 반드시 비워야 합니다.
        cat = accounts.category_for(account, company)
        config.CATEGORY = cat or ""
        log(f"  카테고리: {cat}" if cat else "  카테고리: 기본")
        try:
            publisher.fill_editor(out, interactive=False,
                                  publish_at_once=not args.dry,
                                  persona=persona)
        except Exception as e:
            log(f"  ❌ 발행 실패: {str(e)[:150]}")
            post_queue.mark(company, draft=out.name, status="draft_only",
                            topic=topic, account=account)
            continue

        post_queue.mark(company, draft=out.name,
                        status="draft_only" if args.dry else "published",
                        topic=topic, account=account)
        done += 1
        log(f"  ✅ {'준비 완료' if args.dry else '발행 완료'} — {account}")

        # 3) 간격 — 연달아 올리면 자동화로 보입니다
        if i < args.count - 1:
            wait = args.gap + random.randint(0, args.gap // 2)
            log(f"  ⏳ 다음 글까지 {wait // 60}분 {wait % 60}초 대기…")
            time.sleep(wait)

    written, total = post_queue.status()
    log(f"끝. 이번에 {done}편 처리 · 누적 {written}/{total}편")
    return 0


if __name__ == "__main__":
    sys.exit(main())
