# -*- coding: utf-8 -*-
r"""계정별 블로그 카테고리 목록을 읽어옵니다.

  venv\Scripts\python.exe collect_categories.py              (로그인된 계정 전부)
  venv\Scripts\python.exe collect_categories.py blog_id_5 blog_id_8

발행 패널을 열어 카테고리 드롭다운을 펼치고 이름만 읽은 뒤 닫습니다.
**글은 발행하지 않습니다.**

결과: drafts/_categories.json  → {"blog_id_5": ["◈톰슨에듀◈", "공기업", ...], ...}
"""
from __future__ import annotations
import json
import sys

from playwright.sync_api import sync_playwright

import account_check
import config
import se_selectors as SEL

OUT = config.DRAFTS_DIR / "_categories.json"

# 드롭다운을 연 뒤 카테고리 이름을 긁는 스크립트.
# 항목이 라디오 input 이라 값 속성에 이름이 없습니다(실측). 그래서 화면 글자를 읽습니다.
_READ_JS = """
() => {
  // 드롭다운이 열리면 목록이 나타납니다. 라벨 텍스트만 추립니다.
  const out = [];
  const seen = new Set();
  document.querySelectorAll(
    "[class*='option_list'] label, [class*='selectbox'] label, "
    + "[class*='category'] label, [class*='option'] li"
  ).forEach(el => {
    let t = (el.textContent || '').trim();
    // 하위 카테고리는 화면에 '하위 카테고리' 라는 안내 글자가 앞에 숨어 있습니다
    t = t.replace(/^하위\\s*카테고리\\s*/, '').trim();
    if (!t || t.length > 40 || seen.has(t)) return;
    seen.add(t);
    out.push(t);
  });
  return out;
}
"""


def collect(blog_id: str) -> list[str]:
    config.set_account(blog_id)
    names: list[str] = []
    with sync_playwright() as p:
        import browser_util
        import publisher
        ctx = browser_util.open_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(config.WRITE_URL)
            page.wait_for_timeout(5000)
            frame = page.frame_locator("#mainFrame")
            publisher._dismiss_popups(frame, page)
            page.wait_for_timeout(700)

            # 빈 글이면 발행 패널이 안 열릴 수 있어 최소한의 본문을 넣습니다
            frame.locator(", ".join(SEL.BODY_AREA)).first.click(timeout=8000)
            page.keyboard.type("카테고리 확인용")
            page.wait_for_timeout(400)

            if not publisher._click_first(frame, page, SEL.PUBLISH_OPEN,
                                          "발행 패널", timeout=6000):
                return []
            page.wait_for_timeout(1500)

            # 카테고리 드롭다운 열기
            publisher._click_first(frame, page, SEL.CATEGORY_BUTTON,
                                   "카테고리", timeout=4000)
            page.wait_for_timeout(1200)

            fr = next((f for f in page.frames if "PostWriteForm" in f.url), None)
            if fr:
                names = [n for n in fr.evaluate(_READ_JS)
                         if n not in ("전체공개", "이웃공개", "서로이웃공개", "비공개",
                                      "댓글허용", "공감허용", "검색허용", "현재", "예약",
                                      "블로그/카페 공유", "외부 공유 허용",
                                      "이 설정을 기본값으로 유지", "공지사항으로 등록")]
        finally:
            page.keyboard.press("Escape")
            ctx.close()
    return names


def main() -> None:
    targets = sys.argv[1:] or account_check.usable_accounts()
    data = {}
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass

    for i, acc in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {acc} …", flush=True)
        try:
            names = collect(acc)
        except Exception as e:
            print(f"   ❌ 실패: {str(e)[:100]}")
            continue
        data[acc] = names
        print(f"   카테고리 {len(names)}개: {', '.join(names[:8])}"
              + (" …" if len(names) > 8 else ""))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
