# -*- coding: utf-8 -*-
"""HTML/CSS 카드를 Playwright로 스크린샷 찍어 PNG로 만듭니다.

표에 들어가는 숫자·문구는 Python 문자열 그대로 HTML에 넣어 렌더링하므로
텍스트 정확도는 기존 Pillow 방식과 동일하고, 디자인 표현력만 크게 올라갑니다.

생성형 이미지 AI(미드저니 등)를 쓰지 않은 이유: 한글 텍스트를 깨뜨리는 경우가
많아, 배수·배점 같은 숫자가 틀리게 나오면 치명적인 데이터 표 이미지에는
적합하지 않습니다. 그래서 텍스트는 100% 정확한 템플릿 렌더링 방식을 씁니다.
"""
from __future__ import annotations
import html as _html
from pathlib import Path

from playwright.sync_api import sync_playwright

_pw = None
_browser = None


def _get_browser():
    """시스템 크롬을 씁니다 (publisher.py 와 동일). 번들 크로미움 별도 설치가 필요 없습니다."""
    global _pw, _browser
    if _browser is None:
        _pw = sync_playwright().start()
        try:
            _browser = _pw.chromium.launch(channel="chrome")
        except Exception:
            _browser = _pw.chromium.launch()   # 시스템 크롬이 없으면 번들 크로미움 시도
    return _browser


def close() -> None:
    """모든 이미지 생성이 끝난 뒤 한 번 호출해 브라우저를 정리합니다.
    호출하지 않아도 프로세스 종료 시 정리되지만, 명시적으로 부르는 게 안전합니다."""
    global _pw, _browser
    if _browser is not None:
        try:
            _browser.close()
            _pw.stop()
        except Exception:
            pass
        _browser = None
        _pw = None


def esc(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def render(html_body: str, css: str, width: int, out_path: Path) -> Path:
    """html_body(+css)를 카드 이미지로 렌더링해 out_path 에 저장합니다."""
    browser = _get_browser()
    # 2배로 찍습니다. 1배로 찍으면 글씨가 뭉개져서 명조/고딕 차이가 안 보이고,
    # 네이버가 이미지를 축소해 보여주므로 2배가 오히려 선명합니다.
    page = browser.new_page(viewport={"width": width, "height": 100},
                            device_scale_factor=2)
    try:
        page.set_content(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body>{html_body}</body></html>",
            wait_until="load",
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), full_page=True)
    finally:
        page.close()
    return out_path
