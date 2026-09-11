# -*- coding: utf-8 -*-
r"""
저장된 로그인 세션을 재사용해, drafts/의 초안을 네이버 스마트에디터에 자동 입력합니다.
※ 반자동: 제목·본문·이미지·태그까지 자동 입력하고 [발행] 버튼은 사람이 직접 누릅니다.

지원하는 초안 문법 (사양서 §2 / §9):
  [[H]] 1) 소제목 📌      → fs19 + 굵게
  [[HR]]                  → 구분선
  [[IMG:이름]]            → images/이름.(png|jpg|jpeg|webp) 삽입
  [[QUOTE]] 문구          → 인용구 박스
  **텍스트**              → 굵게
  <blue>텍스트</blue>     → #4a90e2
  <red>텍스트</red>       → #ff0010
  빈 줄                   → 빈 문단

사전 준비: save_login.py 로 naver_session.json 생성.

실행:
  venv\Scripts\python.exe publisher.py                       (가장 최근 초안)
  venv\Scripts\python.exe publisher.py drafts\한전KPS_2026-08-04.md
  venv\Scripts\python.exe publisher.py --probe               (툴바 셀렉터 덤프)
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, FrameLocator

import config
import browser_util
import personas
import se_selectors as SEL


# ── 초안 파싱 ────────────────────────────────────────
def parse_draft(path: str | Path) -> tuple[str, str, str]:
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"(?s)<!--.*?-->", "", text)          # 이미지 메모 주석 제거
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    rest = "\n".join(lines[1:])
    if "\n---" in rest:
        body, _, tags = rest.partition("\n---")
    else:
        body, tags = rest, ""
    return title.strip(), body.strip(), tags.strip()


def _find_image(name: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = config.IMAGES_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return None


# ── 셀렉터 유틸 ──────────────────────────────────────
def _click_first(frame: FrameLocator, page: Page, candidates: list[str],
                 what: str, timeout: int = 3500) -> bool:
    """후보 셀렉터를 위에서부터 시도해 처음 눌리는 것을 클릭."""
    for sel in candidates:
        try:
            loc = frame.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=timeout)
                page.wait_for_timeout(220)
                return True
        except Exception:
            continue
    print(f"  ⚠ '{what}' 버튼을 찾지 못했습니다. 이 부분은 건너뜁니다.")
    return False


# ── 서식 ─────────────────────────────────────────────
def _set_font_size(frame: FrameLocator, page: Page, size: str) -> None:
    if not _click_first(frame, page, SEL.FONT_SIZE_BUTTON, f"글자크기({size})"):
        return
    try:
        frame.locator(SEL.FONT_SIZE_OPTION.format(size=size)).first.click(timeout=3500)
        page.wait_for_timeout(180)
    except Exception:
        print(f"  ⚠ 글자크기 {size} 선택 실패")


def _set_align(frame: FrameLocator, page: Page, align: str) -> bool:
    """문단 정렬. 본문 입력 시작 전에 한 번 걸어두면 이후 문단이 이어받습니다."""
    if _click_first(frame, page, SEL.ALIGN_BUTTON, f"정렬({align})"):
        for tpl in SEL.ALIGN_OPTION:
            try:
                loc = frame.locator(tpl.format(align=align)).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2500)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                continue
        page.keyboard.press("Escape")
    for key in SEL.ALIGN_SHORTCUT.get(align, []):       # 단축키 폴백
        try:
            page.keyboard.press(key)
            page.wait_for_timeout(150)
            return True
        except Exception:
            continue
    print(f"  ⚠ 정렬({align}) 적용 실패. 왼쪽 정렬로 진행합니다.")
    return False


def _set_font_color(frame: FrameLocator, page: Page, hex_color: str | None) -> bool:
    """hex_color=None 이면 기본색(#000000)으로 되돌립니다."""
    target = (hex_color or "#000000").lower()

    if not _click_first(frame, page, SEL.FONT_COLOR_BUTTON, "글자색"):
        return False

    def click_swatch(hexv: str) -> bool:
        h = hexv.lstrip("#")
        rgb = f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"
        for tpl in SEL.FONT_COLOR_SWATCH:
            try:
                loc = frame.locator(tpl.format(rgb=rgb)).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2500)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                continue
        return False

    if click_swatch(target):                    # ① 기본 팔레트에 있으면 바로
        return True

    # ② '더보기' → hex 직접 입력 → 확인
    if _click_first(frame, page, SEL.FONT_COLOR_MORE, "색상 더보기", timeout=2500):
        page.wait_for_timeout(400)
        for sel in SEL.FONT_COLOR_INPUT:
            try:
                inp = frame.locator(sel).first
                if inp.count() and inp.is_visible():
                    inp.fill(target.lstrip("#"), timeout=2500)
                    page.wait_for_timeout(250)
                    if _click_first(frame, page, SEL.FONT_COLOR_APPLY,
                                    "색상 확인", timeout=2500):
                        return True
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(250)
                    return True
            except Exception:
                continue

    # ③ 그래도 안 되면 기본 팔레트 색으로 대체
    near = SEL.PALETTE_FALLBACK.get(target)
    if near is None:
        h = target.lstrip("#")
        tr, tg, tb = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        def dist(c: str) -> int:
            x = c.lstrip("#")
            return ((int(x[0:2], 16) - tr) ** 2 + (int(x[2:4], 16) - tg) ** 2
                    + (int(x[4:6], 16) - tb) ** 2)

        near = min(SEL.PALETTE_COLORS, key=dist)
    if near != target and click_swatch(near):
        print(f"  ℹ {target} 이 기본 팔레트에 없어 가장 가까운 {near} 로 대체했습니다.")
        return True

    print(f"  ⚠ 색상 {target} 적용 실패. 기본색으로 진행합니다.")
    page.keyboard.press("Escape")
    return False


def _set_bg_color(frame: FrameLocator, page: Page, hex_color: str | None) -> bool:
    """형광펜(글자 배경색). 구조는 글자색과 같고 팔레트 컨테이너만 다릅니다.
    hex_color=None 이면 배경을 없앱니다(흰색)."""
    target = (hex_color or "#ffffff").lower()

    if not _click_first(frame, page, SEL.BG_COLOR_BUTTON, "배경색"):
        return False

    h = target.lstrip("#")
    rgb = f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"
    for tpl in SEL.BG_COLOR_SWATCH:
        try:
            loc = frame.locator(tpl.format(rgb=rgb)).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                page.wait_for_timeout(200)
                return True
        except Exception:
            continue

    # 기본 팔레트에 없으면 '더보기'로 직접 입력
    if _click_first(frame, page, SEL.BG_COLOR_MORE, "배경색 더보기", timeout=2500):
        page.wait_for_timeout(400)
        for sel in SEL.BG_COLOR_INPUT:
            try:
                inp = frame.locator(sel).first
                if inp.count() and inp.is_visible():
                    inp.fill(h, timeout=2500)
                    page.wait_for_timeout(250)
                    if not _click_first(frame, page, SEL.BG_COLOR_APPLY,
                                        "배경색 확인", timeout=2500):
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(250)
                    return True
            except Exception:
                continue

    print(f"  ⚠ 형광펜 {target} 적용 실패. 그냥 진행합니다.")
    page.keyboard.press("Escape")
    return False


# ── 인라인 타이핑 ────────────────────────────────────
# 굵게(**), 색(<blue>/<red>), 밑줄(<u>), 기울임(<i>), 취소선(<s>),
# 형광펜(<hl>), 링크([글자](주소))
_INLINE_RE = re.compile(
    r"(\*\*|</?blue>|</?red>|</?u>|</?i>|</?s>|</?hl>|\[[^\]\[]+\]\([^)\s]+\))")
_LINK_RE = re.compile(r"^\[([^\]\[]+)\]\(([^)\s]+)\)$")

# 토글 태그 → 툴바 버튼. 여는 태그와 닫는 태그가 같은 버튼을 누릅니다.
_TOGGLE_BUTTON = {
    "u": (SEL.UNDERLINE_BUTTON, "밑줄"),
    "i": (SEL.ITALIC_BUTTON, "기울임"),
    "s": (SEL.STRIKE_BUTTON, "취소선"),
}

# 변형 선택자(U+FE0F)가 붙은 이모지는 Playwright 가 두 번 입력하는 문제가 있어
# (예: ✍️ → ✍✍️) 타이핑 직전에 제거합니다. 표시 모양은 거의 동일합니다.
_VS16 = "️"


def _safe_type(page: Page, text: str, delay: int = 5) -> None:
    page.keyboard.type(text.replace(_VS16, ""), delay=delay)


class _Fmt:
    """글자 꾸밈 상태. 태그가 여러 줄에 걸쳐 있어도 유지되도록 줄 밖에서 관리합니다."""

    def __init__(self) -> None:
        self.bold = False
        self.color: str | None = None
        self.bg: str | None = None
        self.toggles: set[str] = set()      # u / i / s

    def reset(self, page: Page, frame: FrameLocator) -> None:
        if self.bold:
            page.keyboard.press("Control+b")
            self.bold = False
        if self.color:
            _set_font_color(frame, page, None)
            self.color = None
        if self.bg:
            _set_bg_color(frame, page, None)
            self.bg = None
        for key in list(self.toggles):
            sel, what = _TOGGLE_BUTTON[key]
            _click_first(frame, page, sel, what)
            self.toggles.discard(key)


def _insert_link(frame: FrameLocator, page: Page, text: str, url: str) -> None:
    """글자에 링크를 겁니다. 글자를 먼저 치고, 그만큼 선택한 뒤 링크 버튼을 누릅니다."""
    _safe_type(page, text)
    for _ in range(len(text)):
        page.keyboard.press("Shift+ArrowLeft")
    if not _click_first(frame, page, SEL.LINK_BUTTON, "링크"):
        page.keyboard.press("ArrowRight")
        return
    page.wait_for_timeout(600)
    for sel in SEL.LINK_INPUT:
        try:
            box = frame.locator(sel).first
            if box.count() and box.is_visible():
                box.fill(url, timeout=2500)
                page.wait_for_timeout(250)
                # '링크 입력' 확인 버튼. 없으면 Enter 로 대신합니다.
                if not _click_first(frame, page, SEL.LINK_APPLY,
                                    "링크 확인", timeout=2500):
                    page.keyboard.press("Enter")
                page.wait_for_timeout(500)
                page.keyboard.press("End")
                return
        except Exception:
            continue
    print(f"  ⚠ 링크 입력칸을 못 찾았습니다: {url}")
    page.keyboard.press("Escape")
    page.keyboard.press("End")


def _type_inline(page: Page, frame: FrameLocator, line: str, fmt: _Fmt) -> None:
    """한 줄을 타이핑. 서식 상태(fmt)는 줄이 끝나도 유지됩니다."""
    for tok in _INLINE_RE.split(line):
        if tok == "":
            continue
        if tok == "**":
            page.keyboard.press("Control+b")
            fmt.bold = not fmt.bold
        elif tok == "<blue>":
            if _set_font_color(frame, page, config.COLOR_KEY):
                fmt.color = config.COLOR_KEY
        elif tok == "<red>":
            if _set_font_color(frame, page, config.COLOR_WARN):
                fmt.color = config.COLOR_WARN
        elif tok in ("</blue>", "</red>"):
            if fmt.color:
                _set_font_color(frame, page, None)
                fmt.color = None
        elif tok == "<hl>":
            if _set_bg_color(frame, page, config.COLOR_MARK):
                fmt.bg = config.COLOR_MARK
        elif tok == "</hl>":
            if fmt.bg:
                _set_bg_color(frame, page, None)
                fmt.bg = None
        elif tok in ("<u>", "</u>", "<i>", "</i>", "<s>", "</s>"):
            key = tok.strip("</>")
            sel, what = _TOGGLE_BUTTON[key]
            if _click_first(frame, page, sel, what):
                fmt.toggles.symmetric_difference_update({key})
        elif _LINK_RE.match(tok):
            m = _LINK_RE.match(tok)
            _insert_link(frame, page, m.group(1), m.group(2))
        else:
            _safe_type(page, tok)


# ── 블록 요소 ────────────────────────────────────────
def _insert_hr(frame: FrameLocator, page: Page) -> None:
    if not _click_first(frame, page, SEL.HR_BUTTON, "구분선"):
        return
    for sel in SEL.HR_OPTION:                   # 스타일 선택 팝업이 뜨는 경우만
        try:
            loc = frame.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                break
        except Exception:
            continue
    page.wait_for_timeout(400)


def _insert_quote(frame: FrameLocator, page: Page, text: str) -> None:
    if not _click_first(frame, page, SEL.QUOTE_BUTTON, "인용구"):
        page.keyboard.type(text, delay=6)       # 실패 시 평문으로라도 입력
        return
    for sel in SEL.QUOTE_OPTION:
        try:
            loc = frame.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                break
        except Exception:
            continue
    page.wait_for_timeout(400)
    page.keyboard.type(text, delay=6)
    page.keyboard.press("ArrowDown")            # 인용구 밖으로 빠져나오기
    page.keyboard.press("End")


def _choose_image_layout(frame: FrameLocator, page: Page, layout: str) -> bool:
    """'사진 첨부 방식'(개별사진/콜라주/슬라이드) 팝업이 뜨면 layout 을 고릅니다.

    2장 이상 한 번에 올릴 때만 나타납니다. 처리하지 않으면 여기서 멈춥니다.
    """
    for _ in range(20):                       # 최대 10초 대기
        for tpl in SEL.IMAGE_LAYOUT_OPTION:
            for target in (frame, page):
                try:
                    loc = target.locator(tpl.format(name=layout)).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=2500)
                        page.wait_for_timeout(600)
                        print(f"     사진 첨부 방식: {layout}")
                        return True
                except Exception:
                    continue
        page.wait_for_timeout(500)
    return False


def _insert_image(page: Page, frame: FrameLocator, paths: list[Path]) -> bool:
    """여러 장을 넘기면 '콜라주'로 골라 한 줄에 나란히 배치합니다."""
    try:
        with page.expect_file_chooser(timeout=15000) as fc:
            _click_first(frame, page, SEL.IMAGE_BUTTON, "이미지", timeout=8000)
        fc.value.set_files([str(p) for p in paths])

        if len(paths) > 1:
            page.wait_for_timeout(1200)
            if not _choose_image_layout(frame, page, config.IMAGE_LAYOUT):
                print(f"  ⚠ '사진 첨부 방식' 팝업에서 '{config.IMAGE_LAYOUT}' 를 "
                      "찾지 못했습니다. 창에서 직접 골라주세요.")

        page.wait_for_timeout(3000 + 1500 * len(paths))   # 업로드 대기
        return True
    except Exception as e:
        names = ", ".join(p.name for p in paths)
        print(f"  ⚠ 이미지 삽입 실패({names}): {str(e)[:60]}")
        return False


# ── 본문 렌더링 ──────────────────────────────────────
def plan(body: str) -> list[tuple[str, str]]:
    """본문을 (동작, 내용) 목록으로 변환. 브라우저 없이 검증 가능한 순수 함수."""
    actions: list[tuple[str, str]] = []
    for raw in body.split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if s == "[[HR]]":
            actions.append(("HR", ""))
        elif s.startswith("[[IMGS:"):        # 여러 장을 한 줄에 (이미지 스트립)
            actions.append(("IMGS", s[7:].rstrip("]").strip()))
        elif s.startswith("[[IMG:"):
            actions.append(("IMG", s[6:].rstrip("]").strip()))
        elif s.startswith("[[QUOTE]]"):
            actions.append(("QUOTE", s[len("[[QUOTE]]"):].strip()))
        elif s.startswith("[[H]]"):
            actions.append(("H", s[len("[[H]]"):].strip()))
        elif s.startswith("[[ALIGN:"):       # 이 줄부터 문단 정렬을 바꿉니다
            actions.append(("ALIGN", s[len("[[ALIGN:"):].rstrip("]").strip()))
        elif s.startswith("[[SIZE:"):        # 이 줄부터 글자 크기를 바꿉니다
            actions.append(("SIZE", s[len("[[SIZE:"):].rstrip("]").strip()))
        elif s.startswith("[[TABLE]]"):      # 표: 셀을 || 로, 행을 // 로 구분
            actions.append(("TABLE", s[len("[[TABLE]]"):].strip()))
        elif s == "":
            actions.append(("BLANK", ""))
        else:
            actions.append(("TEXT", line))
    return actions


def _insert_table(page: Page, frame: FrameLocator, spec: str) -> None:
    """표를 넣습니다.  spec 예)  이름||점수 // 홍길동||90 // 김철수||85

    네이버는 '표' 버튼을 누르면 곧바로 3행 3열을 넣습니다(크기 선택 없음).
    더 필요하면 표 위의 '행/열 추가' 버튼을 눌러 늘린 뒤, 칸마다 Tab 으로 이동하며
    채웁니다. (마지막 칸에서 Tab 을 눌러도 행이 늘어나지 않습니다 — 실측 확인)
    """
    rows = [[c.strip() for c in r.split("||")]
            for r in spec.split("//") if r.strip()]
    if not rows:
        return
    n_row, n_col = len(rows), max(len(r) for r in rows)
    print(f"  ▦ 표 삽입: {n_row}행 {n_col}열")

    if not _click_first(frame, page, SEL.TABLE_BUTTON, "표"):
        return
    page.wait_for_timeout(1200)

    def _grow(kind: str, have: int, want: int) -> int:
        """행 또는 열을 want 개가 되도록 늘립니다. 실제로 늘어난 수를 돌려줍니다."""
        tpl = SEL.TABLE_ADD_ROW if kind == "행" else SEL.TABLE_ADD_COL
        while have < want:
            try:
                # 마지막 줄 뒤에 붙입니다 (aria-label 의 번호는 0부터)
                btn = frame.locator(tpl.format(n=have - 1)).first
                if not btn.count():
                    break
                btn.click(timeout=2500)
                page.wait_for_timeout(300)
                have += 1
            except Exception:
                break
        return have

    got_row = _grow("행", SEL.TABLE_DEFAULT_ROWS, n_row)
    got_col = _grow("열", SEL.TABLE_DEFAULT_COLS, n_col)
    if got_row < n_row or got_col < n_col:
        print(f"  ⚠ 표를 {got_row}행 {got_col}열까지만 늘렸습니다. "
              f"넘치는 내용은 잘립니다.")
    n_row, n_col = min(n_row, got_row), min(n_col, got_col)

    # 첫 칸으로 이동한 뒤 Tab 으로 훑으며 채웁니다
    try:
        frame.locator(SEL.TABLE_FIRST_CELL).first.click(timeout=3000)
        page.wait_for_timeout(250)
    except Exception:
        print("  ⚠ 표 첫 칸을 찾지 못했습니다. 표를 건너뜁니다.")
        return

    for r in range(n_row):
        for c in range(n_col):
            val = rows[r][c] if c < len(rows[r]) else ""
            if val:
                _safe_type(page, val)
            if not (r == n_row - 1 and c == n_col - 1):
                page.keyboard.press("Tab")
                page.wait_for_timeout(90)
    page.keyboard.press("Control+End")
    page.wait_for_timeout(200)


def _render_body(page: Page, frame: FrameLocator, body: str) -> list[str]:
    """초안 본문을 에디터에 그립니다. 반환값은 없는 이미지 이름 목록."""
    missing: list[str] = []
    actions = plan(body)
    fmt = _Fmt()

    for i, (kind, val) in enumerate(actions):
        # 블록 요소 앞에서는 서식을 초기화해 굵게/색이 새어나가지 않게 함
        if kind in ("HR", "IMG", "IMGS", "QUOTE", "H", "TABLE"):
            fmt.reset(page, frame)

        if kind == "ALIGN":
            _set_align(frame, page, val)
            continue                     # 자기 줄을 차지하지 않는 지시자입니다
        if kind == "SIZE":
            _set_font_size(frame, page, val)
            continue

        if kind == "TABLE":
            _insert_table(page, frame, val)

        elif kind == "HR":
            _insert_hr(frame, page)

        elif kind in ("IMG", "IMGS"):
            names = [n.strip() for n in val.split("|")] if kind == "IMGS" else [val]
            paths, absent = [], []
            for n in names:
                p = _find_image(n)
                (paths.append(p) if p else absent.append(n))
            missing += absent
            for n in absent:
                print(f"  ⚠ 이미지 없음(건너뜀): {n}")
            if paths:
                joined = " + ".join(p.name for p in paths)
                print(f"  🖼 이미지 삽입{'(한 줄에 나란히)' if len(paths) > 1 else ''}: {joined}")
                _insert_image(page, frame, paths)
                page.keyboard.press("End")
            else:
                continue                        # 빈 줄도 만들지 않음

        elif kind == "QUOTE":
            _insert_quote(frame, page, val)

        elif kind == "H":
            _set_font_size(frame, page, config.HEADING_FONT_SIZE)
            page.keyboard.press("Control+b")
            page.keyboard.type(val, delay=6)
            page.keyboard.press("Control+b")
            _set_font_size(frame, page, config.BODY_FONT_SIZE)

        elif kind == "TEXT":
            _type_inline(page, frame, val, fmt)

        # BLANK 는 아래 Enter 로만 처리 (네이버가 빈 문단을 U+200B 로 저장)

        if i < len(actions) - 1:
            page.keyboard.press("Enter")
            # URL 줄 뒤에는 네이버가 링크 카드를 만드느라 잠시 포커스를 가져갑니다.
            # 곧바로 이미지를 넣으면 삽입이 씹히므로 카드가 자리잡을 때까지 기다립니다.
            if kind == "TEXT" and "http" in val:
                page.wait_for_timeout(2500)
                page.keyboard.press("Control+End")
                page.wait_for_timeout(300)

    fmt.reset(page, frame)          # 해시태그가 서식을 물려받지 않도록
    return missing


def dry_run(draft_path: str | Path) -> None:
    """브라우저 없이 초안을 해석해 실행 계획과 이미지 확보 현황을 출력."""
    title, body, tags = parse_draft(draft_path)
    actions = plan(body)

    print(f"제목: {title}")
    print(f"해시태그: {tags}\n")

    def img_names(kind: str, val: str) -> list[str]:
        return [n.strip() for n in val.split("|")] if kind == "IMGS" else [val]

    counts: dict[str, int] = {}
    missing, found = [], []
    for kind, val in actions:
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("IMG", "IMGS"):
            for n in img_names(kind, val):
                (found if _find_image(n) else missing).append(n)

    icon = {"H": "🔹 소제목", "HR": "─ 구분선", "IMG": "🖼 이미지",
            "IMGS": "🖼 이미지2", "QUOTE": "❝ 인용구",
            "TEXT": "  본문", "BLANK": "  (빈줄)"}
    for kind, val in actions:
        if kind == "BLANK":
            continue
        mark = ""
        if kind in ("IMG", "IMGS"):
            ns = img_names(kind, val)
            mark = "  " + " ".join("✅" if _find_image(n) else f"❌{n}" for n in ns)
            if kind == "IMGS":
                mark += "  (한 줄에 나란히)"
        print(f"{icon[kind]:<10} {val[:52]}{mark}")

    print("\n" + "=" * 56)
    for k in ("H", "HR", "IMG", "IMGS", "QUOTE", "TEXT", "BLANK"):
        print(f"  {icon[k].strip():<8} {counts.get(k, 0)}개")
    print(f"\n  이미지 확보 {len(found)} / {len(found) + len(missing)}")
    for m in missing:
        print(f"    ❌ images/{m}.png")

    # 인라인 서식 태그 짝 검사
    for tag in ("blue", "red"):
        o, c = body.count(f"<{tag}>"), body.count(f"</{tag}>")
        if o != c:
            print(f"  ⚠ <{tag}> 태그 짝이 안 맞습니다 ({o} vs {c})")
    if body.count("**") % 2:
        print("  ⚠ ** 굵게 표기 개수가 홀수입니다")


# ── 에디터 준비 ──────────────────────────────────────
def _dismiss_popups(frame: FrameLocator, page: Page) -> None:
    """'작성 중인 글' 팝업이 뜰 때까지 최대 6초 기다렸다가 취소."""
    for _ in range(12):
        try:
            btn = frame.locator(SEL.POPUP_CANCEL[0])
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
                break
        except Exception:
            pass
        page.wait_for_timeout(500)
    for label in SEL.POPUP_CLOSE_LABELS:
        try:
            btn = frame.get_by_role("button", name=label)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
        except Exception:
            pass


def _clear_editor(frame: FrameLocator, page: Page) -> None:
    """이전에 불러와진 내용을 모두 지워 빈 상태로."""
    for sels in (SEL.BODY_AREA, SEL.TITLE_AREA):
        try:
            frame.locator(", ".join(sels)).first.click(timeout=6000)
            page.keyboard.press("Control+a")
            page.keyboard.press("Control+a")    # 두 번 → 문서 전체 선택
            page.keyboard.press("Delete")
            page.wait_for_timeout(300)
        except Exception:
            pass


# ── 툴바 셀렉터 덤프 (--probe) ───────────────────────
_PROBE_JS = """(sel) => {
  const out = [];
  document.querySelectorAll(sel).forEach(b => {
    const cls = (b.className || '').toString();
    if (!cls.includes('se-')) return;
    const st = (b.getAttribute('style') || '');
    out.push({
      tag: b.tagName.toLowerCase(),
      cls: cls.trim().slice(0, 130),
      name: b.getAttribute('data-name') || '',
      value: b.getAttribute('data-value') || '',
      style: st.slice(0, 60),
      label: (b.getAttribute('aria-label') || b.title || b.innerText || '').trim().slice(0, 30),
    });
  });
  return out;
}"""

_BTN_SEL = "button, [role=button]"
# 색상 스와치·정렬 옵션은 button 이 아닐 수 있어 범위를 넓혀 잡습니다.
_WIDE_SEL = ("button, [role=button], li, a, span[class*=color], "
             "[class*=color], [class*=palette], [class*=align]")


def probe_publish(page: Page, frame: FrameLocator) -> None:
    """[발행] 패널을 열고 그 안의 요소를 덤프합니다 (예약 발행 셀렉터 확정용)."""
    fr = next((f for f in page.frames if "PostWriteForm" in f.url), None)
    if fr is None:
        print("probe 실패: 에디터 프레임을 찾지 못했습니다.")
        return

    js = """() => {
      const out = [];
      document.querySelectorAll(
        'button, input, select, option, label, [role=button], '
        + '[class*=radio], [class*=date], [class*=time], [class*=hour], [class*=minute]'
      ).forEach(el => {
        const t = (el.innerText || el.value || '').trim().slice(0, 30);
        out.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').toString().trim().slice(0, 90),
          type: el.getAttribute('type') || '',
          name: el.getAttribute('name') || '',
          value: (el.getAttribute('value') || '').slice(0, 20),
          text: t,
        });
      });
      return out;
    }"""

    def dump() -> list[dict]:
        try:
            return fr.evaluate(js)
        except Exception as e:
            print("  dump 실패:", str(e)[:80])
            return []

    sections: list[tuple[str, list[dict]]] = []

    opened = _click_first(frame, page, SEL.PUBLISH_OPEN, "발행 버튼", timeout=4000)
    page.wait_for_timeout(1500)
    sections.append((f"① 발행 패널 (열기 {'성공' if opened else '실패'})", dump()))

    # '예약'을 눌러야 날짜·시·분 UI 가 나타납니다. (발행 버튼은 누르지 않습니다)
    picked = False
    for sel in SEL.PUBLISH_SCHEDULE_RADIO:
        try:
            loc = frame.locator(sel).first
            if loc.count():
                loc.check(force=True, timeout=3000)
                picked = True
                break
        except Exception:
            continue
    if not picked:                       # 라디오가 숨겨져 있으면 라벨을 클릭
        try:
            frame.locator("label:has-text('예약')").first.click(timeout=3000)
            picked = True
        except Exception:
            pass
    page.wait_for_timeout(1200)
    sections.append((f"② 예약 선택 후 (선택 {'성공' if picked else '실패'})", dump()))

    # 날짜/시간 관련 요소만 따로 추려서 보기 쉽게
    keys = ("date", "time", "hour", "minute", "calendar", "day", "month")
    only = [r for r in sections[-1][1]
            if any(k in (r["cls"] + r["name"] + r["type"]).lower() for k in keys)]
    sections.append(("③ 날짜·시간 관련만 추림", only))

    # 카테고리 드롭다운도 열어서 항목 구조를 확인
    cat = _click_first(frame, page, SEL.CATEGORY_BUTTON, "카테고리", timeout=3000)
    page.wait_for_timeout(900)
    cat_rows = dump()
    ck = ("select", "option", "category", "list", "item")
    sections.append((f"④ 카테고리 드롭다운 (열기 {'성공' if cat else '실패'})",
                     [r for r in cat_rows
                      if any(k in (r["cls"] + r["tag"]).lower() for k in ck)]))

    out = config.DRAFTS_DIR / "_publish_probe.txt"
    out.parent.mkdir(exist_ok=True)
    buf = []
    for title, rows in sections:
        buf.append(f"\n===== {title} — {len(rows)}개 =====")
        buf.append("tag\tclass\ttype\tname\tvalue\ttext")
        for r in rows:
            buf.append("\t".join((r["tag"], r["cls"], r["type"],
                                  r["name"], r["value"], r["text"])))
    out.write_text("\n".join(buf), encoding="utf-8")
    print(f"\n✅ 발행 패널 덤프 완료: {out}")
    print("   ※ [발행] 버튼은 누르지 않았습니다. 글은 발행되지 않습니다.")
    print("   이 파일의 ③ ④ 부분을 보내주시면 예약시각·카테고리를 확정하겠습니다.")


def probe_toolbar(page: Page, frame: FrameLocator) -> None:
    fr = next((f for f in page.frames if "PostWriteForm" in f.url), None)
    if fr is None:
        print("probe 실패: 에디터 프레임을 찾지 못했습니다.")
        return

    def dump(sel: str) -> list[dict]:
        try:
            return fr.evaluate(_PROBE_JS, sel)
        except Exception as e:
            print("  dump 실패:", str(e)[:80])
            return []

    sections: list[tuple[str, list[dict]]] = [("① 툴바 전체", dump(_BTN_SEL))]

    # 드롭다운/팔레트를 하나씩 열고 그때 보이는 것들을 추가로 덤프
    for title, cands in (("② 글자색 팔레트", SEL.FONT_COLOR_BUTTON),
                         ("③ 정렬 옵션", SEL.ALIGN_BUTTON)):
        opened = _click_first(frame, page, cands, title, timeout=3000)
        page.wait_for_timeout(700)
        sections.append((f"{title} (열기 {'성공' if opened else '실패'})",
                         dump(_WIDE_SEL)))
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    out = config.DRAFTS_DIR / "_toolbar_probe.txt"
    out.parent.mkdir(exist_ok=True)
    buf = []
    for title, rows in sections:
        buf.append(f"\n===== {title} — {len(rows)}개 =====")
        buf.append("tag\tclass\tdata-name\tdata-value\tstyle\tlabel")
        for r in rows:
            buf.append("\t".join((r["tag"], r["cls"], r["name"],
                                  r["value"], r["style"], r["label"])))
    out.write_text("\n".join(buf), encoding="utf-8")
    print(f"\n✅ 덤프 완료: {out}")
    print("   이 파일을 보내주시면 색상·정렬 셀렉터를 정확히 맞추겠습니다.")


# ── 진입점 ───────────────────────────────────────────
def _set_category(frame: FrameLocator, page: Page, name: str) -> bool:
    """발행 패널의 카테고리를 name 으로 고릅니다."""
    if not _click_first(frame, page, SEL.CATEGORY_BUTTON, "카테고리", timeout=4000):
        return False
    page.wait_for_timeout(700)
    for tpl in SEL.CATEGORY_OPTION:
        try:
            loc = frame.locator(tpl.format(name=name)).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                page.wait_for_timeout(500)
                print(f"     카테고리: {name}")
                return True
        except Exception:
            continue
    print(f"  ⚠ 카테고리 '{name}' 를 찾지 못했습니다. 기본 카테고리로 진행합니다.")
    page.keyboard.press("Escape")
    return False


# 달력 조작을 브라우저 안에서 한 번에 끝내는 스크립트.
# Playwright 로 한 단계씩 만지면 중간에 달력이 닫혀버려서(실측 확인) 통째로 넘깁니다.
_PICK_DATE_JS = """
([year, month, day]) => {
  // 달력이 여러 개 있습니다(숨겨진 것 포함). 화면에 보이는 것만 골라야 합니다 —
  // 숨겨진 쪽은 모든 날짜가 비활성이라 '고를 수 없다'는 엉뚱한 결과가 나옵니다.
  const all = Array.from(document.querySelectorAll('.ui-datepicker'));
  const dp = all.find(el => el.offsetParent !== null
                            && getComputedStyle(el).display !== 'none')
             || all[0];
  if (!dp) return 'no-datepicker';
  for (let i = 0; i < 15; i++) {
    const y = parseInt((dp.querySelector('.ui-datepicker-year') || {}).textContent, 10);
    const m = parseInt(((dp.querySelector('.ui-datepicker-month') || {}).textContent || '')
                       .replace('월', ''), 10);
    if (!y || !m) return 'no-title';
    if (y === year && m === month) {
      const cells = dp.querySelectorAll('td:not(.ui-state-disabled) a');
      for (const a of cells) {
        if (a.textContent.trim() === String(day)) { a.click(); return 'ok'; }
      }
      return 'day-not-selectable';
    }
    if (y > year || (y === year && m > month)) return 'past';
    const next = dp.querySelector('.ui-datepicker-next');
    if (!next || next.classList.contains('ui-state-disabled')) return 'cannot-advance';
    next.click();
  }
  return 'too-far';
}
"""


def _pick_date(frame: FrameLocator, page: Page, when) -> bool:
    """예약 날짜를 고릅니다.

    ⚠ 오늘이 아닌 날짜는 현재 넣지 못합니다 (2026-08-24 실측).
      날짜 입력칸은 readonly 라 값을 쓸 수 없고, 클릭하면 뜨는 jQuery UI 달력은
      모든 날짜가 비활성(ui-state-disabled, 링크 없음) 상태로 나옵니다.
      네이티브 setter 로 값을 넣어도 곧바로 되돌아갑니다.
      → 그래서 '오늘'이면 달력을 아예 건드리지 않고 통과시키고,
        다른 날짜면 아래 시도를 해본 뒤 실패하면 정직하게 False 를 돌려줍니다.
        (예약이 어긋나 엉뚱한 시각에 발행되는 것보다 중단이 낫습니다)
    """
    import datetime as _dt

    # 오늘이면 입력칸이 이미 오늘 날짜라 손댈 필요가 없습니다
    if when.date() == _dt.date.today():
        return True

    fr = next((f for f in page.frames if "PostWriteForm" in f.url), None)
    if fr is None:
        return False

    opened = False
    for sel in SEL.PUBLISH_DATE_INPUT:
        try:
            loc = frame.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                opened = True
                break
        except Exception:
            continue
    if not opened:
        return False
    page.wait_for_timeout(800)

    try:
        res = fr.evaluate(_PICK_DATE_JS, [when.year, when.month, when.day])
    except Exception as e:
        print("  ⚠ 달력 조작 실패:", str(e)[:80])
        return False
    if res != "ok":
        print(f"  ⚠ 달력에서 날짜를 고르지 못했습니다 ({res}).")
        return False
    page.wait_for_timeout(600)

    # 입력칸에 실제로 반영됐는지 확인
    want = when.strftime(SEL.PUBLISH_DATE_FORMAT)
    for sel in SEL.PUBLISH_DATE_INPUT:
        try:
            loc = frame.locator(sel).first
            if loc.count():
                got = (loc.input_value() or "").strip()
                if got != want:
                    print(f"  ⚠ 날짜가 '{got}' 로 들어갔습니다 (원하는 값: {want})")
                return got == want
        except Exception:
            continue
    return False


def publish_now(frame: FrameLocator, page: Page, dry: bool = False) -> bool:
    """발행 패널을 열어 '현재'로 두고 곧바로 발행합니다.

    ⚠ 이 함수는 글을 실제로 올립니다. 되돌리려면 블로그에서 직접 삭제해야 합니다.
    dry=True 면 마지막 확정만 누르지 않습니다.
    """
    if not _click_first(frame, page, SEL.PUBLISH_OPEN, "발행 버튼", timeout=6000):
        return False
    page.wait_for_timeout(1500)

    if config.CATEGORY:
        _set_category(frame, page, config.CATEGORY)

    if config.OPEN_TYPE is not None:
        try:
            frame.locator(SEL.PUBLISH_OPEN_TYPE.format(v=config.OPEN_TYPE)) \
                 .first.check(force=True, timeout=2500)
        except Exception:
            print("  ⚠ 공개 설정을 바꾸지 못했습니다. 기존 설정으로 진행합니다.")

    # '현재' 라디오 — 예약이 아니라 즉시 발행
    for sel in SEL.PUBLISH_NOW_RADIO:
        try:
            loc = frame.locator(sel).first
            if loc.count():
                loc.check(force=True, timeout=3000)
                break
        except Exception:
            continue
    page.wait_for_timeout(600)

    if dry:
        print("  ✅ 발행 직전까지 준비했습니다. (dry 모드라 누르지 않았습니다)")
        return True

    if not _click_first(frame, page, SEL.PUBLISH_CONFIRM, "발행 확정", timeout=5000):
        return False
    page.wait_for_timeout(4000)
    return True


def schedule_publish(frame: FrameLocator, page: Page, when,
                     dry: bool = False) -> bool:
    """발행 패널을 열어 카테고리·공개설정·예약시각을 정하고 발행합니다.

    dry=True 면 마지막 [발행] 확정만 누르지 않습니다. 예약 시각이 제대로 들어가는지
    확인할 때 씁니다 — 글이 실제로 올라가지 않습니다.
    """
    if not _click_first(frame, page, SEL.PUBLISH_OPEN, "발행 버튼", timeout=6000):
        return False
    page.wait_for_timeout(1500)

    if config.CATEGORY:
        _set_category(frame, page, config.CATEGORY)

    if config.OPEN_TYPE is not None:
        try:
            frame.locator(SEL.PUBLISH_OPEN_TYPE.format(v=config.OPEN_TYPE)) \
                 .first.check(force=True, timeout=2500)
        except Exception:
            print("  ⚠ 공개 설정을 바꾸지 못했습니다. 기존 설정으로 진행합니다.")

    # '예약' 라디오. 숨겨진 input 일 수 있어 check(force=True) 를 먼저 씁니다.
    picked = False
    for sel in SEL.PUBLISH_SCHEDULE_RADIO:
        try:
            loc = frame.locator(sel).first
            if loc.count():
                loc.check(force=True, timeout=3000)
                picked = True
                break
        except Exception:
            continue
    if not picked:
        try:
            frame.locator("label:has-text('예약')").first.click(timeout=3000)
            picked = True
        except Exception:
            pass
    if not picked:
        print("  ⚠ '예약' 항목을 찾지 못했습니다. 즉시 발행되지 않도록 중단합니다.")
        return False
    page.wait_for_timeout(900)

    # 날짜 — 입력칸이 readonly 라 달력을 열어 날짜를 눌러야 합니다
    want_date = when.strftime(SEL.PUBLISH_DATE_FORMAT)
    if not _pick_date(frame, page, when):
        print(f"  ⚠ 예약 날짜({want_date})를 고르지 못했습니다. "
              "오늘 날짜로 잡힐 수 있어 중단합니다.")
        return False
    # 시 / 분 (네이버는 10분 단위)
    for sels, val, what in (
            (SEL.PUBLISH_HOUR_SELECT, f"{when.hour:02d}", "시"),
            (SEL.PUBLISH_MIN_SELECT, f"{when.minute // 10 * 10:02d}", "분")):
        picked_t = False
        for sel in sels:
            try:
                loc = frame.locator(sel).first
                if loc.count():
                    loc.select_option(val, timeout=2500)
                    picked_t = True
                    break
            except Exception:
                continue
        if not picked_t:
            print(f"  ⚠ 예약 {what}({val})을 고르지 못했습니다. 중단합니다.")
            return False
    page.wait_for_timeout(500)

    if dry:
        print(f"  ✅ 예약 시각 {want_date} {when.hour:02d}:"
              f"{when.minute // 10 * 10:02d} 까지 입력했습니다.")
        print("     (dry 모드라 [발행]은 누르지 않았습니다 — 글은 올라가지 않습니다)")
        return True

    if not _click_first(frame, page, SEL.PUBLISH_CONFIRM, "예약 발행 확정", timeout=4000):
        return False
    page.wait_for_timeout(3000)
    return True


def fill_editor(draft_path: str | Path | None, interactive: bool = True,
                probe: bool = False, probe_pub: bool = False,
                schedule_at=None, wait_event=None,
                publish_at_once: bool = False,
                persona: str | None = None) -> None:
    """wait_event 가 주어지면(threading.Event), 입력을 마친 뒤 터미널 input() 대신
    그 이벤트가 set() 될 때까지 기다립니다. GUI 등 콘솔이 없는 호출자용 —
    사람이 "닫기" 버튼을 눌러야 브라우저를 닫도록 하려는 목적입니다."""
    if not config.USER_DATA_DIR.exists():
        print("❌ 로그인 정보가 없습니다. 먼저 2_로그인저장.bat 을 1회 실행하세요.")
        sys.exit(1)

    title = body = tags = ""
    if not (probe or probe_pub):
        # draft_path 를 안 주면 가장 최근 초안을 씁니다 (CLI 무인자 실행과 같은 동작).
        # 이걸 여기서 처리하지 않으면 파이썬에서 직접 부를 때 알아보기 힘든
        # TypeError(NoneType) 로 죽습니다.
        if draft_path is None:
            draft_path = _latest_draft()
            if draft_path is None:
                print("❌ drafts 폴더에 초안이 없습니다. 먼저 글을 생성하세요.")
                return
            print(f"가장 최근 초안을 엽니다: {Path(draft_path).name}")
        title, body, tags = parse_draft(draft_path)
        print(f"제목: {title}")
        print(f"본문 {len(body)}자 입력 예정\n")

    with sync_playwright() as p:
        context = browser_util.open_context(p)
        page = context.pages[0] if context.pages else context.new_page()

        if not browser_util.is_logged_in(page):
            print("=" * 60)
            print("❌ 네이버에서 로그아웃된 상태입니다.")
            print("   2_로그인저장.bat 을 실행해 다시 로그인해 주세요.")
            print("   (로그인 화면의 [로그인 상태 유지] 체크를 꼭 켜주세요)")
            print("=" * 60)
            if interactive:
                input("Enter로 종료 ▶ ")
            context.close()
            return

        page.goto(config.WRITE_URL)
        page.wait_for_timeout(4000)

        if not any("PostWriteForm" in fr.url for fr in page.frames):
            print("=" * 60)
            print("❌ 글쓰기 에디터가 열리지 않았습니다.")
            print(f"   로그인 계정이 blog '{config.BLOG_ID}' 소유자가 맞는지 확인하세요.")
            print("=" * 60)
            if interactive:
                input("확인 후 Enter로 종료 ▶ ")
            context.close()
            return

        frame = page.frame_locator("#mainFrame")
        _dismiss_popups(frame, page)
        page.wait_for_timeout(800)

        if probe or probe_pub:
            (probe_publish if probe_pub else probe_toolbar)(page, frame)
            if interactive:
                input("Enter로 종료 ▶ ")
            context.close()
            return

        missing: list[str] = []
        try:
            _clear_editor(frame, page)

            # 제목
            frame.locator(", ".join(SEL.TITLE_AREA)).first.click(timeout=8000)
            page.keyboard.type(re.sub(r"\*\*|</?(blue|red)>", "", title), delay=12)

            # 본문
            frame.locator(", ".join(SEL.BODY_AREA)).first.click(timeout=8000)
            page.wait_for_timeout(300)
            _set_font_size(frame, page, config.BODY_FONT_SIZE)
            # 정렬은 글 스타일을 따릅니다. 줄글(조언형)은 양쪽 정렬이라야
            # 오른쪽 끝이 들쭉날쭉하지 않아 읽기 편합니다.
            align = (personas.get(persona)["align"] if persona
                     else config.BODY_ALIGN)
            if align:
                _set_align(frame, page, align)
            missing = _render_body(page, frame, body)

            # 해시태그
            if tags:
                # 본문 마지막 줄이 URL이면 주의가 필요합니다.
                # 네이버는 'URL 문단을 벗어나는 순간'(= Enter를 친 직후)에 비로소
                # 링크 카드를 만들기 시작하고, 그 삽입이 끝나면 DOM이 재배치되면서
                # 커서가 튑니다. 그래서 Enter 전에 기다려봐야 소용이 없고,
                # 타이핑 중에 카드가 들어오면 앞 몇 글자가 링크 줄에 남아버립니다.
                # (실제로 '#IB'만 링크 뒤에 붙어 깨진 적 있음)
                # → Enter 를 먼저 쳐서 카드 생성을 유발하고, 그게 끝날 때까지 기다린 뒤
                #    커서를 다시 맨 끝으로 보내고 나서 입력합니다.
                last_line = next((l.strip() for l in reversed(body.split("\n"))
                                  if l.strip()), "")
                page.keyboard.press("Enter")
                if "http" in last_line:
                    # 카드가 다 붙어 편집 영역이 잠잠해질 때까지 기다립니다
                    if not _wait_editor_settled(page, frame):
                        print("  ⚠ 링크 카드 처리가 오래 걸립니다. 해시태그 위치를 확인해 주세요.")
                    page.keyboard.press("Control+End")
                    page.wait_for_timeout(400)

                # 링크(카드)와 해시태그 사이 빈 줄 하나
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)
                page.keyboard.press("Control+End")
                page.wait_for_timeout(200)
                page.keyboard.type(re.sub(r"\*\*", "", tags), delay=12)
                page.keyboard.press("Enter")
        except Exception as e:
            print(f"⚠ 자동 입력 중 문제: {str(e)[:120]}")
            print("  브라우저 창에서 직접 이어서 작성하셔도 됩니다.")

        # ── 즉시 발행 ────────────────────────────────
        if publish_at_once:
            print(f"\n  🚀 '{config.BLOG_ID}' 계정으로 바로 발행합니다…")
            ok = publish_now(frame, page)
            browser_util.save_cookies(context)
            page.wait_for_timeout(1500)
            context.close()
            if ok:
                print("  ✅ 발행 완료")
                return
            raise RuntimeError("발행 버튼을 누르지 못했습니다")

        # ── 예약 발행 ────────────────────────────────
        if schedule_at is not None:
            print(f"\n  📅 {schedule_at:%Y-%m-%d %H:%M} 으로 예약 발행 설정 중…")
            if schedule_publish(frame, page, schedule_at):
                print("  ✅ 예약 발행 완료")
                browser_util.save_cookies(context)
                page.wait_for_timeout(1500)
                context.close()
                return
            print("  ❌ 예약 발행 실패. 글은 그대로 있으니 창에서 직접 발행해 주세요.")

        print("\n" + "=" * 60)
        print("✅ 입력 완료. 창에서 확인 후 [발행] 버튼을 직접 눌러주세요.")
        print("   (자동 발행하지 않습니다 — 계정 안전을 위한 반자동 모드)")
        if missing:
            print("\n   📌 아직 없어서 건너뛴 이미지:")
            for m in missing:
                print(f"      - images/{m}.png")
        print("=" * 60)
        if wait_event is not None:
            print("   (GUI 의 '확인 완료 · 브라우저 닫기' 버튼을 누르면 닫힙니다)")
            wait_event.wait()
        elif interactive:
            input("작업이 끝나면 이 창에서 Enter ▶ ")
        else:
            page.wait_for_timeout(1500)
        browser_util.save_cookies(context)   # 쿠키 백업 갱신
        context.close()


def _wait_editor_settled(page, frame, quiet_ms: int = 1200,
                         timeout_ms: int = 15000) -> bool:
    """편집 영역 내용이 quiet_ms 동안 더 이상 변하지 않을 때까지 기다립니다.

    URL 을 입력하면 네이버가 링크 카드를 비동기로 만들어 붙이는데, 이게 언제
    끝나는지는 네트워크 사정에 따라 다릅니다. 고정 시간(3초 등)으로 기다리면
    느릴 때 그대로 뚫려서, 타이핑 도중 카드가 삽입되며 커서가 튀고
    앞 몇 글자가 링크 줄에 남아버립니다(실제로 '#IB', '#한국' 이 그렇게 남았음).
    그래서 '언제 끝나는지' 대신 '더 이상 안 변한다'를 기준으로 기다립니다.

    카드 클래스명에 의존하지 않으므로 네이버가 마크업을 바꿔도 계속 동작합니다.
    """
    body = frame.locator(".se-component.se-text, .se-component").first
    last, stable_since = None, 0
    waited = 0
    step = 250
    while waited < timeout_ms:
        try:
            now = body.evaluate("el => el.parentElement.innerHTML.length")
        except Exception:
            now = None
        if now is not None and now == last:
            stable_since += step
            if stable_since >= quiet_ms:
                return True
        else:
            stable_since = 0
            last = now
        page.wait_for_timeout(step)
        waited += step
    return False


def _latest_draft() -> Path | None:
    if not config.DRAFTS_DIR.exists():
        return None
    drafts = [p for p in config.DRAFTS_DIR.glob("*.md") if not p.name.startswith("_")]
    return max(drafts, key=lambda p: p.stat().st_mtime) if drafts else None


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--probe" in args:
        print("네이버 글쓰기 화면을 열고 툴바 버튼 목록을 파일로 저장합니다.")
        print("구분선/인용구/글자색이 안 들어갈 때 실행해 주세요.\n")
        fill_editor(None, probe=True)
        sys.exit(0)

    if "--probe-publish" in args:
        print("[발행] 패널을 열어 예약 발행 관련 요소를 파일로 저장합니다.\n")
        fill_editor(None, probe_pub=True)
        sys.exit(0)

    dry = "--dry" in args
    if dry:
        print("[브라우저를 열지 않고] 최근 초안이 어떻게 입력될지 미리 봅니다.\n")
    args = [a for a in args if not a.startswith("--")]

    target = args[0] if args else None
    if target is None:
        latest = _latest_draft()
        if latest is None:
            print("❌ drafts 폴더에 초안이 없습니다. 먼저 1_글생성.bat 을 실행하세요.")
            input("Enter로 종료 ▶ ")
            sys.exit(1)
        print(f"가장 최근 초안을 엽니다: {latest.name}")
        target = str(latest)

    if dry:
        dry_run(target)
    else:
        fill_editor(target)
