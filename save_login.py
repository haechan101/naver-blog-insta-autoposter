# -*- coding: utf-8 -*-
r"""
[로그아웃됐을 때, 또는 계정을 바꿀 때 실행] 네이버 로그인 상태를 저장합니다.
사장님이 직접 브라우저에서 로그인하면, 그 브라우저 프로필을 통째로 보관합니다.
비밀번호는 이 프로그램이 다루지 않습니다.

실행:
  2_로그인저장.bat
  venv\Scripts\python.exe save_login.py
  venv\Scripts\python.exe save_login.py --check              (로그인 상태만 확인)
  venv\Scripts\python.exe save_login.py --switch 다른아이디     (계정 전환)
  venv\Scripts\python.exe save_login.py --reset               (현재 계정 프로필 초기화)
"""
import json
import shutil
import sys

from playwright.sync_api import sync_playwright

import config
import browser_util


def _report_cookies(ctx) -> None:
    """네이버 로그인 쿠키의 만료 시점을 표로 보여줍니다.

    '세션 쿠키'로 표시되면 브라우저를 닫는 순간 사라진다는 뜻이므로,
    로그인할 때 [로그인 상태 유지] 를 켜지 않은 것입니다.
    """
    import datetime as dt

    watch = ("NID_AUT", "NID_SES", "NID_JKL", "NID_SUP", "nid_inf")
    rows = [c for c in ctx.cookies() if c["name"] in watch]
    if not rows:
        print("   (네이버 로그인 쿠키가 없습니다)")
        return

    now = dt.datetime.now()
    print("\n   쿠키           만료                       남은 기간")
    print("   " + "-" * 54)
    session_only = False
    for c in sorted(rows, key=lambda x: x["name"]):
        exp = c.get("expires", -1)
        if not exp or exp <= 0:
            session_only = True
            print(f"   {c['name']:<14} 세션 쿠키(브라우저 닫으면 삭제)   ⚠")
        else:
            d = dt.datetime.fromtimestamp(exp)
            left = d - now
            days = left.days
            mark = "⚠" if days < 7 else ""
            print(f"   {c['name']:<14} {d:%Y-%m-%d %H:%M}          "
                  f"{days}일 {left.seconds // 3600}시간 {mark}")
    if session_only:
        print("\n   ⚠ '세션 쿠키'가 있습니다 = [로그인 상태 유지] 를 안 켜고 로그인하셨습니다.")
        print("     save_login.py --reset 으로 초기화 후, 체크박스를 켜고 다시 로그인해 주세요.")


def check() -> bool:
    print(f"'{config.BLOG_ID}' 계정의 네이버 로그인이 살아있는지 확인합니다…\n")
    with sync_playwright() as p:
        ctx = browser_util.open_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ok = browser_util.is_logged_in(page)
        print("✅ 로그인 상태입니다." if ok
              else "❌ 로그아웃 상태입니다. 2_로그인저장.bat 을 실행하세요.")
        _report_cookies(ctx)
        ctx.close()
        return ok


def switch_account(new_blog_id: str) -> None:
    """설정에 새 블로그 아이디를 저장합니다. 로그인은 뒤이어 main() 이 진행합니다."""
    old = config.BLOG_ID
    config.ACCOUNT_PATH.write_text(
        json.dumps({"blog_id": new_blog_id}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("=" * 62)
    print(f"계정을 전환합니다: '{old}' → '{new_blog_id}'")
    print(f"이 계정 전용 로그인 정보를 새로 만듭니다: browser_profile/{new_blog_id}/")
    print("(기존 계정의 로그인 정보는 그대로 남아있어, 다시 --switch 로 돌아갈 수 있습니다)")
    print("=" * 62)


def main() -> None:
    args = sys.argv[1:]

    if "--check" in args:
        check()
        return

    if "--switch" in args:
        i = args.index("--switch")
        if i + 1 >= len(args):
            print("사용법: save_login.py --switch <새_블로그_아이디>")
            return
        switch_account(args[i + 1])
        # config 를 새로 읽어야 하므로 재실행 안내
        print("\n계속해서 로그인을 진행합니다…\n")
        import importlib
        importlib.reload(config)

    if "--reset" in args and config.USER_DATA_DIR.exists():
        shutil.rmtree(config.USER_DATA_DIR, ignore_errors=True)
        print(f"'{config.BLOG_ID}' 계정 프로필을 지웠습니다.")

    with sync_playwright() as p:
        ctx = browser_util.open_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if browser_util.is_logged_in(page):
            print("=" * 62)
            print(f"✅ 이미 '{config.BLOG_ID}' 계정으로 로그인되어 있습니다.")
            print("   (다른 계정으로 바꾸려면: save_login.py --switch 새아이디)")
            print("=" * 62)
            browser_util.save_cookies(ctx)
            input("Enter로 종료 ▶ ")
            ctx.close()
            return

        page.goto(config.LOGIN_URL)
        print("=" * 62)
        print(f"① 뜬 브라우저 창에서 '{config.BLOG_ID}' 계정으로 직접 로그인하세요.")
        print()
        print("   ⚠ 로그인 화면의 [로그인 상태 유지] 를 꼭 체크해 주세요.")
        print("     이걸 켜야 컴퓨터를 꺼도 로그인이 풀리지 않습니다.")
        print()
        print("② 2단계 인증이나 '새로운 기기 등록' 화면이 뜨면")
        print("   [등록] 을 눌러 이 기기를 등록해 주세요.")
        print()
        print("③ 로그인이 끝나면 이 창으로 돌아와 Enter 를 누르세요.")
        print("=" * 62)
        input("로그인 완료 후 Enter ▶ ")

        page.wait_for_timeout(500)
        ok = browser_util.is_logged_in(page)
        browser_util.save_cookies(ctx)

        print()
        if ok:
            print(f"✅ 로그인 저장 완료: {config.USER_DATA_DIR}")
            print("   이제 컴퓨터를 꺼도 로그인이 유지됩니다.")
            _report_cookies(ctx)
        else:
            print("⚠ 아직 로그아웃 상태로 보입니다. 로그인이 끝난 뒤 다시 실행해 주세요.")
        input("Enter로 종료 ▶ ")
        ctx.close()


if __name__ == "__main__":
    main()
