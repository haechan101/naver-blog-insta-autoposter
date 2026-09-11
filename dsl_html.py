# -*- coding: utf-8 -*-
"""초안 DSL ↔ HTML 변환.

초안(.md)은 발행기가 읽는 자체 문법으로 쓰여 있습니다.
    [[H]] 1) 소제목 📌      [[HR]]      [[IMG:이름]]      [[IMGS:이름1|이름2]]
    [[QUOTE]] 문구          **굵게**    <blue>…</blue>    <red>…</red>

이걸 그대로 보면서 고치기는 불편해서, 위지윅 에디터에 보여줄 HTML 로 바꾸고
저장할 때 다시 DSL 로 되돌립니다.

■ 가장 중요한 규칙 — 줄은 줄대로 보존한다
네이버 본문에서는 줄바꿈 위치 자체가 의미를 갖습니다(모바일 가독성 때문에
한 줄 18~26자로 끊어 쓰고 있음). 그래서 DSL 한 줄 = HTML <p> 하나로 1:1 대응시키고,
되돌릴 때도 <p> 하나 = 한 줄로 되돌립니다. 문장을 합치거나 재배치하지 않습니다.
"""
from __future__ import annotations
import html as _html
import re
from pathlib import Path

import config

BLUE = config.COLOR_KEY
RED = config.COLOR_WARN
MARK = config.COLOR_MARK


# ── DSL → HTML ────────────────────────────────────────
def _inline_to_html(s: str) -> str:
    """한 줄 안의 꾸밈 표기를 HTML 로."""
    out = _html.escape(s, quote=False)
    # escape 된 태그를 되살리면서 각각의 HTML 로 변환
    out = re.sub(r"&lt;blue&gt;(.*?)&lt;/blue&gt;",
                 rf'<span style="color:{BLUE}">\1</span>', out)
    out = re.sub(r"&lt;red&gt;(.*?)&lt;/red&gt;",
                 rf'<span style="color:{RED}">\1</span>', out)
    out = re.sub(r"&lt;hl&gt;(.*?)&lt;/hl&gt;",
                 rf'<span style="background-color:{MARK}">\1</span>', out)
    out = re.sub(r"&lt;u&gt;(.*?)&lt;/u&gt;", r"<u>\1</u>", out)
    out = re.sub(r"&lt;i&gt;(.*?)&lt;/i&gt;", r"<em>\1</em>", out)
    out = re.sub(r"&lt;s&gt;(.*?)&lt;/s&gt;", r"<s>\1</s>", out)
    # 링크 [글자](주소)
    out = re.sub(r"\[([^\]\[]+)\]\(([^)\s]+)\)",
                 lambda m: f'<a href="{_html.escape(m.group(2), quote=True)}">'
                           f'{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return out


def _img_src(name: str) -> str:
    """images/ 안의 실제 파일을 file:// URL 로. 없으면 빈 문자열."""
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = config.IMAGES_DIR / f"{name}{ext}"
        if p.exists():
            return Path(p).as_uri()
    return ""


def _img_html(names: list[str]) -> str:
    cells = []
    for n in names:
        src = _img_src(n)
        inner = (f'<img src="{src}" alt="{_html.escape(n, quote=True)}">'
                 if src else
                 f'<span class="missing">이미지 없음: {_html.escape(n)}</span>')
        cells.append(f'<span class="cell">{inner}'
                     f'<span class="cap">{_html.escape(n)}</span></span>')
    multi = " multi" if len(names) > 1 else ""
    joined = "".join(cells)
    return (f'<p class="imgblock{multi}" data-names="{_html.escape("|".join(names), quote=True)}">'
            f'{joined}</p>')


def to_html(body: str) -> str:
    """본문 DSL → 에디터에 넣을 HTML."""
    out: list[str] = []
    for raw in body.split("\n"):
        line = raw.rstrip()
        s = line.strip()

        if not s:
            out.append('<p class="blank"><br></p>')
            continue

        m = re.match(r"^\[\[H\]\]\s*(.*)$", s)
        if m:
            out.append(f'<h3 class="dsl-h">{_inline_to_html(m.group(1))}</h3>')
            continue

        if re.match(r"^\[\[HR\]\]\s*$", s):
            out.append('<hr class="dsl-hr">')
            continue

        m = re.match(r"^\[\[IMGS?:([^\]]+)\]\]\s*$", s)
        if m:
            out.append(_img_html([n.strip() for n in m.group(1).split("|")]))
            continue

        m = re.match(r"^\[\[QUOTE\]\]\s*(.*)$", s)
        if m:
            out.append(f'<blockquote class="dsl-quote">'
                       f'{_inline_to_html(m.group(1))}</blockquote>')
            continue

        out.append(f'<p>{_inline_to_html(s)}</p>')

    return "\n".join(out)


# ── HTML → DSL ────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")


# DSL 태그를 잠시 넣어둘 표식. 본문에 나올 수 없는 제어문자를 씁니다.
# (바로 <blue> 로 되돌리면, 다음 단계의 "남은 태그 제거"가 그것까지 지워버립니다)
_MARK = {k: (f"\x00{k}\x01", f"\x00/{k}\x01")
         for k in ("blue", "red", "hl", "u", "i", "s")}
_LINK_MARK = ("\x00L\x01", "\x00|\x01", "\x00/L\x01")   # 여는·구분·닫는


def _inline_to_dsl(frag: str) -> str:
    """HTML 꾸밈을 DSL 표기로 되돌리고 나머지 태그는 걷어냅니다."""
    s = frag
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</?(strong|b)\s*>", "**", s, flags=re.I)

    # 밑줄·기울임·취소선 (CKEditor 는 em/i, s/strike/del 을 섞어 씁니다)
    for key, pat in (("u", r"u"), ("i", r"em|i"), ("s", r"s|strike|del")):
        o, c = _MARK[key]
        s = re.sub(rf"<({pat})\s*>", o, s, flags=re.I)
        s = re.sub(rf"</({pat})\s*>", c, s, flags=re.I)

    # 링크 — 표식에는 {주소}{구분}{글자} 순서로 담습니다 (아래에서 그 순서로 되돌림)
    def _a(m: re.Match) -> str:
        o, sep, c = _LINK_MARK
        return f"{o}{m.group(1)}{sep}{m.group(2)}{c}"   # 1=주소, 2=글자
    s = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', _a, s, flags=re.I | re.S)

    def _span(m: re.Match) -> str:
        style = (m.group(1) or "").lower().replace(" ", "")
        inner = m.group(2)
        for key, color in (("blue", BLUE), ("red", RED), ("hl", MARK)):
            if color.lower() in style or _rgb(color) in style:
                o, c = _MARK[key]
                return f"{o}{inner}{c}"
        return inner

    # 색 span (중첩 없다는 전제 — 생성 규칙상 중첩되지 않습니다)
    s = re.sub(r'<span[^>]*style="([^"]*)"[^>]*>(.*?)</span>', _span, s,
               flags=re.I | re.S)
    s = _TAG_RE.sub("", s)                     # 나머지 HTML 태그 제거
    s = _html.unescape(s)
    for key, (o, c) in _MARK.items():          # 표식을 진짜 DSL 태그로
        s = s.replace(o, f"<{key}>").replace(c, f"</{key}>")
    # 표식은 {주소}{구분}{글자} 순서로 넣었으므로 되돌릴 때 자리를 바꿔줍니다
    o, sep, c = _LINK_MARK                     # → [글자](주소)
    s = re.sub(re.escape(o) + r"(?P<url>.*?)" + re.escape(sep)
               + r"(?P<text>.*?)" + re.escape(c),
               lambda m: f"[{m.group('text')}]({m.group('url')})", s, flags=re.S)
    s = re.sub(r"\*\*\s*\*\*", "", s)          # 빈 굵게 제거
    return re.sub(r"[ \t]+", " ", s).strip()


def _rgb(hex_color: str) -> str:
    """#4a90e2 → rgb(74,144,226) — 브라우저가 style 을 rgb 로 바꿔 돌려주기 때문."""
    h = hex_color.lstrip("#")
    return f"rgb({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)})"


_BLOCK_RE = re.compile(
    r"<(h3|p|blockquote|hr)\b([^>]*)>(.*?)</\1>|<hr\b[^>]*/?>",
    re.I | re.S)


def to_dsl(html: str) -> str:
    """에디터 HTML → 본문 DSL. 블록 하나 = 줄 하나."""
    lines: list[str] = []
    for m in _BLOCK_RE.finditer(html):
        tag = (m.group(1) or "hr").lower()
        attrs = m.group(2) or ""
        inner = m.group(3) or ""

        if tag == "hr":
            lines.append("[[HR]]")
            continue

        if tag == "h3":
            lines.append(f"[[H]] {_inline_to_dsl(inner)}")
            continue

        if tag == "blockquote":
            lines.append(f"[[QUOTE]] {_inline_to_dsl(inner)}")
            continue

        # p — 이미지 블록인지 먼저 확인
        dm = re.search(r'data-names="([^"]*)"', attrs)
        if dm:
            names = [n.strip() for n in _html.unescape(dm.group(1)).split("|")
                     if n.strip()]
            if names:
                token = "IMGS" if len(names) > 1 else "IMG"
                lines.append(f"[[{token}:{'|'.join(names)}]]")
            continue

        text = _inline_to_dsl(inner)
        lines.append(text)     # 빈 문단이면 빈 줄 그대로 유지

    # 문서 끝의 빈 줄만 정리
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


# ── 초안 파일 단위 ────────────────────────────────────
def split_draft(text: str) -> tuple[str, str, str]:
    """초안 파일 전체 → (제목, 본문, 해시태그줄). publisher.parse_draft 와 같은 규칙."""
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    rest = "\n".join(lines[1:])
    if "\n---" in rest:
        body, _, tags = rest.partition("\n---")
    else:
        body, tags = rest, ""
    return title.strip(), body.strip(), tags.strip()


def join_draft(title: str, body: str, tags: str) -> str:
    """(제목, 본문, 해시태그) → 초안 파일 전체 텍스트."""
    return f"# {title}\n\n{body}\n\n---\n{tags}\n"


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    title, body, tags = split_draft(p.read_text(encoding="utf-8"))
    html = to_html(body)
    back = to_dsl(html)
    same = back.strip() == body.strip()
    print(f"제목: {title}")
    print(f"왕복 변환 일치: {'예' if same else '아니오'}")
    if not same:
        a, b = body.strip().split("\n"), back.strip().split("\n")
        for i in range(max(len(a), len(b))):
            x = a[i] if i < len(a) else "(없음)"
            y = b[i] if i < len(b) else "(없음)"
            if x != y:
                print(f"  {i+1}행 원본: {x!r}")
                print(f"  {i+1}행 변환: {y!r}")
