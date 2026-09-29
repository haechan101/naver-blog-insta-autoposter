# -*- coding: utf-8 -*-
r"""인스타 반자동 발행 — 윈도우 작업 스케줄러가 발행 시각마다 실행합니다.

[확인 완료]된 카드 중 예약 시각이 지난 것 1건만 올립니다. 올릴 게 없으면 아무것도 하지 않습니다.
자동 발행은 앱의 [인스타 → 발행 대기열] 탭에서 켜고 끕니다.

실행:
  venv\Scripts\python.exe run_insta.py          때가 된 카드 1건 발행
  venv\Scripts\python.exe run_insta.py --dry    올리지 않고, 지금 돌면 무엇을 올릴지만 확인
  venv\Scripts\python.exe run_insta.py --list   대기열 보기
"""
from __future__ import annotations
import argparse
import traceback

import insta_publish
import insta_queue

log = insta_queue.file_log      # 기록: ../auto_insta/insta_out/_insta_daily.log


def main() -> None:
    ap = argparse.ArgumentParser(description="인스타 반자동 발행")
    ap.add_argument("--dry", action="store_true", help="올리지 않고 무엇을 올릴지만 확인")
    ap.add_argument("--list", action="store_true", help="대기열 보기")
    args = ap.parse_args()

    if args.list:
        for c, rec in insta_queue.entries():
            state = {"approved": "대기", "published": "발행됨", "failed": "멈춤"}.get(rec.get("status"), "?")
            when = rec.get("published_at") or rec.get("scheduled_at", "")
            note = "다시 확인 필요" if rec.get("changed") else rec.get("error", "")
            print(f"{when:<17} {state:<5} {c:<16} {note}")
        print(f"\n토큰: {insta_publish.token_status()}")
        print(f"자동 발행: {', '.join(insta_queue.auto_tasks()) or '꺼짐'}")
        return

    try:
        insta_queue.run_due(log=log, dry=args.dry)
    except Exception:
        log("오류로 멈췄습니다:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
