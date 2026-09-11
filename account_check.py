# -*- coding: utf-8 -*-
"""계정별 네이버 로그인 상태 확인.

브라우저를 띄우지 않고 프로필 폴더의 쿠키 파일만 읽습니다.
발행을 시작하기 전에 '이 계정 지금 되나?'를 빠르게 확인하려는 용도입니다.

  venv\\Scripts\\python.exe account_check.py
"""
from __future__ import annotations
import datetime as dt
import shutil
import sqlite3
import tempfile
from pathlib import Path

import config

# 크롬 쿠키의 시간 기준점 (1601-01-01 UTC, 마이크로초 단위)
_EPOCH = dt.datetime(1601, 1, 1)


def login_state(blog_id: str) -> tuple[str, dt.datetime | None]:
    """('ok' | 'expired' | 'none' | 'unknown', 만료시각)

    NID_AUT 쿠키가 로그인 여부를 가장 정확하게 알려줍니다.
    """
    db = config.PROFILES_ROOT / blog_id / "Default" / "Network" / "Cookies"
    if not db.exists():
        return "none", None

    # 크롬이 파일을 잠그고 있을 수 있어 복사본을 읽습니다
    tmp = Path(tempfile.gettempdir()) / f"_ck_{blog_id}.db"
    try:
        shutil.copy2(db, tmp)
        con = sqlite3.connect(str(tmp))
        row = con.execute(
            "SELECT expires_utc FROM cookies "
            "WHERE host_key LIKE '%naver.com' AND name='NID_AUT' "
            "ORDER BY expires_utc DESC LIMIT 1").fetchone()
        con.close()
    except Exception:
        return "unknown", None
    finally:
        tmp.unlink(missing_ok=True)

    if not row:
        return "none", None
    exp = row[0]
    if not exp:                      # 세션 쿠키 — 브라우저를 닫으면 사라집니다
        return "expired", None
    when = _EPOCH + dt.timedelta(microseconds=exp)
    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return ("ok" if when > now_utc else "expired"), when


LABEL = {
    "ok": "로그인됨",
    "expired": "만료됨 — 다시 로그인 필요",
    "none": "로그인 안 됨",
    "unknown": "확인 불가",
}


def usable_accounts() -> list[str]:
    """지금 바로 발행할 수 있는 계정만."""
    return [a for a in config.list_accounts() if login_state(a)[0] == "ok"]


def main() -> None:
    accs = config.list_accounts()
    print(f"=== 계정 {len(accs)}개 로그인 상태 ===\n")
    ok = 0
    for a in accs:
        state, when = login_state(a)
        tail = f"  (만료 {when:%Y-%m-%d})" if when else ""
        mark = "O" if state == "ok" else "X"
        print(f"  [{mark}] {a:<18}{LABEL[state]}{tail}")
        ok += state == "ok"
    print(f"\n발행 가능: {ok} / {len(accs)}개")
    if ok < len(accs):
        print("   로그인 안 된 계정은 앱의 [계정 추가·재로그인] 으로 로그인하세요.")


if __name__ == "__main__":
    main()
