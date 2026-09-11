# -*- coding: utf-8 -*-
"""표 이미지 자동 생성 (사양서 §6-2).

실제 블로그의 공고 캡처와 섞여도 이질감이 없도록
흰 배경 + 파란 헤더(#4a90e2) 톤으로 맞춥니다.
"""
from __future__ import annotations
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

W = 800
PAD = 28
ROW_H = 52
HEAD_H = 62
TITLE_H = 66

C_HEAD_BG = "#4a90e2"
C_HEAD_TX = "#ffffff"
C_TEXT = "#333333"
C_SUB = "#666666"
C_ZEBRA = "#f7f9fc"
C_LINE = "#dde3ea"
C_BG = "#ffffff"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["malgunbd.ttf", "malgun.ttf"] if bold else ["malgun.ttf", "malgunbd.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(str(Path("C:/Windows/Fonts") / n), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int,
          max_lines: int = 3) -> list[str]:
    """폭에 맞춰 줄바꿈. 한글은 어절 단위로 자르되 한 어절이 길면 글자 단위로."""
    words, lines, cur = str(text).split(" "), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while draw.textlength(w, font=font) > max_w:      # 어절 자체가 긴 경우
            cut = len(w)
            while cut > 1 and draw.textlength(w[:cut], font=font) > max_w:
                cut -= 1
            lines.append(w[:cut])
            w = w[cut:]
        cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsis(draw, lines[-1], font, max_w)
    return lines or [""]


def render_table(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    footer: str = "",
    tags: list[str] | None = None,
    out_path: Path | None = None,
) -> Path:
    """제목 + 헤더행 + 데이터행 + (푸터 / 태그) 표 이미지를 만듭니다."""
    tags = tags or []
    f_title = _font(30, bold=True)
    f_head = _font(21, bold=True)
    f_body = _font(20)
    f_small = _font(18)

    # 열 폭: 첫 열은 좁게, 마지막 열을 넓게
    inner_w = W - PAD * 2
    if len(headers) == 2:
        widths = [int(inner_w * 0.32), inner_w - int(inner_w * 0.32)]
    elif len(headers) == 3:
        widths = [int(inner_w * 0.16), int(inner_w * 0.18)]
        widths.append(inner_w - sum(widths))
    else:
        widths = [inner_w // len(headers)] * len(headers)
        widths[-1] = inner_w - sum(widths[:-1])

    # 1차 측정: 셀 줄바꿈 결과와 행 높이를 먼저 계산
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wrapped, row_hs = [], []
    for row in rows:
        cells = []
        for c_i, cell in enumerate(row[: len(headers)]):
            font = f_head if c_i == 0 else f_body
            cells.append(_wrap(probe, cell, font, widths[c_i] - 32))
        wrapped.append(cells)
        row_hs.append(max(ROW_H, max(len(c) for c in cells) * 30 + 22))

    tag_lines = _wrap(probe, "   ".join(f"#{t.replace(' ', '')}" for t in tags),
                      f_small, inner_w - 32, max_lines=2) if tags else []
    foot_h = ROW_H if footer else 0
    tag_h = (len(tag_lines) * 28 + 22) if tag_lines else 0

    h = TITLE_H + HEAD_H + sum(row_hs) + foot_h + tag_h + PAD
    img = Image.new("RGB", (W, h), C_BG)
    d = ImageDraw.Draw(img)

    # 제목
    d.text((PAD, PAD - 6), title, font=f_title, fill=C_TEXT)
    y = TITLE_H

    # 헤더행
    d.rectangle([PAD, y, W - PAD, y + HEAD_H], fill=C_HEAD_BG)
    x = PAD
    for i, hd in enumerate(headers):
        d.text((x + 16, y + (HEAD_H - 25) // 2), hd, font=f_head, fill=C_HEAD_TX)
        x += widths[i]
    y += HEAD_H

    # 데이터행
    for r_i, cells in enumerate(wrapped):
        rh = row_hs[r_i]
        if r_i % 2 == 1:
            d.rectangle([PAD, y, W - PAD, y + rh], fill=C_ZEBRA)
        d.line([PAD, y, W - PAD, y], fill=C_LINE)
        x = PAD
        for c_i, lines_ in enumerate(cells):
            font = f_head if c_i == 0 else f_body
            ty = y + (rh - len(lines_) * 30) // 2
            for ln in lines_:
                d.text((x + 16, ty), ln, font=font, fill=C_TEXT)
                ty += 30
            x += widths[c_i]
        y += rh

    d.line([PAD, y, W - PAD, y], fill=C_LINE)

    # 푸터
    if footer:
        d.rectangle([PAD, y, W - PAD, y + ROW_H], fill=C_ZEBRA)
        d.text((PAD + 16, y + (ROW_H - 24) // 2),
               _ellipsis(d, footer, f_body, inner_w - 32), font=f_body, fill=C_TEXT)
        y += ROW_H
        d.line([PAD, y, W - PAD, y], fill=C_LINE)

    # 태그
    if tag_lines:
        ty = y + 11
        for ln in tag_lines:
            d.text((PAD + 16, ty), ln, font=f_small, fill=C_HEAD_BG)
            ty += 28
        y += tag_h

    # 테두리 + 출처
    d.rectangle([PAD, TITLE_H, W - PAD, y], outline=C_LINE)
    d.text((PAD, y + 10), "출처: 톰슨에듀  ｜  tompsonai.com", font=_font(16), fill=C_SUB)

    out_path = out_path or (config.IMAGES_DIR / "table.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_cover(title: str, subtitle: str, tags: list[str],
                 out_path: Path) -> Path:
    """글 맨 위에 넣을 대표 이미지(타이틀 카드)."""
    W_, H_ = 800, 420
    NAVY = "#14315c"
    img = Image.new("RGB", (W_, H_), NAVY)
    d = ImageDraw.Draw(img)

    # 우측 하단 장식 원
    d.ellipse([W_ - 190, H_ - 190, W_ + 90, H_ + 90], fill="#1c4176")
    d.ellipse([W_ - 120, H_ - 120, W_ + 120, H_ + 120], fill="#24508c")

    f_kicker = _font(22, bold=True)
    f_title = _font(58, bold=True)
    f_sub = _font(26)
    f_tag = _font(19, bold=True)
    f_foot = _font(20)

    d.text((48, 62), "공기업 필기 분석", font=f_kicker, fill="#7fb2f0")

    # 기업명 (길면 줄여서)
    t = _ellipsis(d, title, f_title, W_ - 96)
    d.text((48, 104), t, font=f_title, fill="#ffffff")

    d.line([48, 190, 148, 190], fill="#4a90e2", width=5)
    for i, ln in enumerate(_wrap(d, subtitle, f_sub, W_ - 96, max_lines=2)):
        d.text((48, 212 + i * 36), ln, font=f_sub, fill="#d4e4f7")

    # 태그 칩
    x, y = 48, 300
    for tg in tags[:4]:
        label = f"#{tg.replace(' ', '')}"
        w = int(d.textlength(label, font=f_tag)) + 28
        if x + w > W_ - 48:
            break
        d.rounded_rectangle([x, y, x + w, y + 38], radius=19,
                            fill="#24508c", outline="#4a90e2")
        d.text((x + 14, y + 8), label, font=f_tag, fill="#cfe2fa")
        x += w + 10

    d.line([48, H_ - 62, W_ - 48, H_ - 62], fill="#2c5a94")
    d.text((48, H_ - 46), "톰슨에듀  ｜  tompsonai.com", font=f_foot, fill="#9dc2ea")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


# ── 프로필 기반 생성기 ───────────────────────────────
def make_exam_structure(profile: dict) -> Path | None:
    """시험 구조표. exam_blueprint 만으로 생성되므로 LLM 불필요."""
    bp = profile.get("exam_blueprint") or {}
    sessions = bp.get("sessions") or []
    if not sessions:
        return None

    rows = [[s.get("name") or "", s.get("format") or "", s.get("note") or ""]
            for s in sessions]

    bits = []
    if bp.get("time_min"):
        bits.append(f"총 시험시간 {bp['time_min']}분")
    if bp.get("deduction") is not None:
        bits.append("오답 감점 있음" if bp["deduction"] else "오답 감점 없음")
    if bp.get("has_essay"):
        bits.append("논술 있음")

    name = profile["company_key"]
    return render_table(
        title=f"{name} 필기시험 구조",
        headers=["구분", "형식", "구성"],
        rows=rows,
        footer="  ·  ".join(bits),
        out_path=config.IMAGES_DIR / f"{name}_시험구조.png",
    )


def make_cover(profile: dict) -> Path | None:
    """대표 이미지. 기업 로고를 구하지 않아도 101개 전부 자동 생성됩니다."""
    name = profile["company_key"]
    bp = profile.get("exam_blueprint") or {}
    bits = [s.get("name") for s in bp.get("sessions") or [] if s.get("name")]
    sub = " + ".join(bits) if bits else "필기시험"
    if bp.get("time_min"):
        sub += f"  ·  {bp['time_min']}분"
    return render_cover(
        title=name,
        subtitle=f"{sub} 출제경향과 준비 포인트",
        tags=profile.get("badges") or [],
        out_path=config.IMAGES_DIR / f"{name}_대표.png",
    )


def make_major_table(profile: dict, major_table: list[dict] | None) -> Path | None:
    """전공 과목표. 본문에서 길게 풀지 않고 표로 압축합니다."""
    if not major_table:
        return None
    name = profile["company_key"]
    return render_table(
        title=f"{name} 직렬별 전공 과목",
        headers=["직렬", "주요 과목"],
        rows=[[m.get("track", ""), m.get("subjects", "")] for m in major_table],
        footer="자세한 출제 범위는 tompsonai.com 에서 확인",
        out_path=config.IMAGES_DIR / f"{name}_전공.png",
    )


def make_ncs_areas(profile: dict, area_table: list[dict] | None = None) -> Path | None:
    """NCS 영역표. area_table 은 생성 모델이 만든 [{area, keywords}] 목록."""
    name = profile["company_key"]
    if area_table:
        rows = [[a.get("area", ""), a.get("keywords", "")] for a in area_table]
    else:
        areas = profile.get("ncs_areas") or []
        if not areas:
            return None
        rows = [[a, ""] for a in areas]

    return render_table(
        title=f"{name} NCS 출제 영역",
        headers=["영역", "자주 나온 유형"],
        rows=rows,
        tags=profile.get("badges") or [],
        out_path=config.IMAGES_DIR / f"{name}_NCS_영역.png",
    )


# ── md_loader(v2) 기반 생성기 — 카드형 미니멀 (HTML/CSS + Playwright) ──
# 표에 들어가는 문자열은 Python 그대로 HTML에 꽂히므로 텍스트 정확도는
# 아래 Pillow 버전과 동일하고, 디자인만 카드형으로 크게 올라갑니다.
import html_render as hr

# ── 스타일별 카드 테마 ────────────────────────────────
# 8개 계정이 똑같은 카드 이미지를 쓰면, 글을 아무리 다르게 써도 이미지가 같아
# 한 곳에서 만든 티가 납니다. 그래서 글 스타일(personas)마다 색·모양을 바꿉니다.
# 아래 값만 갈아끼우고 HTML 구조는 그대로 씁니다.
#
# ⚠ 색만 바꾸면 구분이 안 됩니다. 처음에 색상값만 갈아끼웠더니
#   A(파랑)와 C(남색)가 나란히 놓고 봐도 같은 카드로 보였습니다.
#   그래서 테마마다 `extra` 로 모양까지 갈아엎습니다.
#   (카드 테두리·그림자, 말머리표 모양, 행 구분선 vs 행 배경 등)
# 글씨체는 이 PC에 실제로 설치돼 있고 서로 눈에 띄게 다른 것만 씁니다.
# (설치 여부를 렌더링 폭으로 실측했습니다 — 바탕/Noto Sans KR/돋움/Consolas 는 확인됨,
#  나눔·Pretendard·한산뜻돋움 등은 없어서 맑은 고딕으로 대체되므로 쓰지 않습니다)
_F_MALGUN = "'Malgun Gothic','맑은 고딕',sans-serif"
_F_NOTO = "'Noto Sans KR','Malgun Gothic',sans-serif"
_F_BATANG = "'Batang','바탕','HANBatang',serif"          # 명조 — 문서·책 느낌
_F_MONO = "'Consolas','Dotum','돋움',monospace"          # 숫자는 고정폭, 한글은 돋움

CARD_THEMES: dict[str, dict] = {
    # A 브리핑형 — 맑은 고딕 · 흰 카드에 파란 왼쪽 띠 · 줄로 구분
    "brief": {
        "font": _F_MALGUN,
        "label": "흰 카드 · 파란 띠 · 맑은 고딕",
        "bg": "#dce7f6", "card": "#ffffff", "accent": "#3d7fd0",
        "accent_soft": "#e6f0fd", "ink": "#16233c", "sub": "#6b7688",
        "line": "#e9eef5", "radius": "20px", "shadow": "0 10px 30px rgba(15,23,42,.10)",
        "num_shape": "50%",           # 번호 배지 모양 (원)
        "extra": """
.card { border-left:7px solid #3d7fd0; }
""",
    },
    # B 대화형 — Noto Sans KR · 연녹색 카드 · 아주 둥글게 · 행이 말풍선 칩
    "talk": {
        "font": _F_NOTO,
        "label": "연녹색 카드 · 둥근 말풍선 · Noto Sans",
        "bg": "#cfe6d8", "card": "#f5fbf7", "accent": "#1f8a5c",
        "accent_soft": "#ddf0e6", "ink": "#123028", "sub": "#557a6c",
        "line": "#d9ebe1", "radius": "32px", "shadow": "0 12px 30px rgba(20,49,42,.12)",
        "num_shape": "50%",
        "extra": """
.card { padding:38px 34px; }
.title { font-size:30px; font-weight:700; }
.kicker { font-size:15px; padding:8px 17px; }
.rows { margin-top:22px; }
.row { border-bottom:none; background:#e9f5ee; border-radius:20px;
       padding:16px 20px; margin-bottom:9px; }
.row:last-child { margin-bottom:0; }
.row-num { background:#ffffff; }
.footer, .brand { border-top-color:#d9ebe1; }
""",
    },
    # C 조언형 — 바탕(명조) · 누런 종이 · 그림자 없이 테두리만 · 각진 모서리
    "advice": {
        "font": _F_BATANG,
        "label": "누런 종이 · 각진 테두리 · 바탕(명조)",
        "bg": "#ddd3ba", "card": "#faf5e8", "accent": "#2b4470",
        "accent_soft": "#e5dbbf", "ink": "#1d2438", "sub": "#6a614e",
        "line": "#e0d7c1", "radius": "3px", "shadow": "none",
        "num_shape": "2px",           # 사각 배지
        "extra": """
.card { border:1px solid #cdbf9f; padding:38px 42px; }
.title { font-size:29px; font-weight:700; letter-spacing:-.01em; }
.subtitle { font-size:18px; }
.kicker { background:none; border-radius:0; padding:0 0 0 11px;
          border-left:4px solid #2b4470; margin-bottom:14px; letter-spacing:.02em; }
.kicker::before { display:none; }
.rows { margin-top:24px; border-top:2px solid #cdbf9f; padding-top:6px; }
.row { padding:15px 0; }
.row-label { font-size:18px; }
.row-value { font-size:17px; }
.pill { background:none; border:1px solid #c7b795; border-radius:2px; }
""",
    },
    # D 분석형 — 돋움+Consolas · 어두운 화면 · 상단 강조 막대
    "data": {
        "font": _F_MONO,
        "label": "어두운 화면 · 주황 강조 · 돋움+고정폭",
        "bg": "#10151d", "card": "#1e2531", "accent": "#f5a623",
        "accent_soft": "#3a3222", "ink": "#eef2f8", "sub": "#9aa8bd",
        "line": "#2c3648", "radius": "5px", "shadow": "0 8px 24px rgba(0,0,0,.45)",
        "num_shape": "2px",
        "extra": """
.card { border:1px solid #2f3b52; border-top:4px solid #f5a623; padding:36px 40px; }
.title { font-size:27px; letter-spacing:-.01em; }
.subtitle { font-size:16px; }
.kicker { border-radius:3px; letter-spacing:.04em; font-size:13px; }
.row { padding:14px 0; }
.row-label { font-size:17px; }
.row-value { font-size:15px; }
.pill { border-radius:3px; font-size:13px; }
""",
    },
}


def card_css(persona: str | None = None) -> str:
    """그 스타일에 맞는 카드 CSS. 없는 스타일이면 브리핑형 테마를 씁니다."""
    t = CARD_THEMES.get(persona or "brief", CARD_THEMES["brief"])
    css = _CARD_CSS
    for key, val in t.items():
        if key in ("extra", "label"):     # CSS 자리표시자가 아닌 값
            continue
        css = css.replace(f"{{{key}}}", val)
    return css + t.get("extra", "")      # 모양 덮어쓰기는 맨 뒤에 붙여야 이깁니다


_CARD_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background:{bg};
  font-family:{font};
}
.page { display:inline-block; padding:26px; }
.card {
  width:700px;
  background:{card};
  border-radius:{radius};
  box-shadow:{shadow};
  padding:40px 42px;
}
.kicker {
  display:inline-flex; align-items:center; gap:8px;
  font-size:14px; font-weight:700; color:{accent};
  background:{accent_soft}; padding:7px 15px; border-radius:999px;
  margin-bottom:16px;
}
.kicker::before { content:''; width:7px; height:7px; border-radius:50%; background:{accent}; }
.title { font-size:28px; font-weight:800; color:{ink}; line-height:1.3; }
.subtitle { margin-top:8px; font-size:17px; color:{sub}; line-height:1.5; }
.rows { margin-top:26px; }
.row {
  display:flex; align-items:flex-start; gap:20px;
  padding:17px 0; border-bottom:1px solid {line};
}
.row:last-child { border-bottom:none; }
.row-num {
  flex:0 0 26px; height:26px; border-radius:{num_shape};
  background:{accent_soft}; color:{accent}; font-size:13px; font-weight:800;
  display:flex; align-items:center; justify-content:center;
}
.row-label { flex:0 0 140px; font-size:18px; font-weight:700; color:{ink}; }
.row-value { flex:1; font-size:16px; color:{sub}; line-height:1.5; }
.footer {
  margin-top:20px; padding-top:16px; border-top:1px dashed {line};
  font-size:14px; color:{sub};
}
.pills { margin-top:22px; display:flex; gap:8px; flex-wrap:wrap; }
.pill {
  font-size:14px; font-weight:700; color:{accent};
  background:{accent_soft}; padding:7px 14px; border-radius:999px;
}
.brand {
  margin-top:24px; padding-top:16px; border-top:1px solid {line};
  font-size:13px; color:{sub}; opacity:.75;
}
"""


def make_cover_v2(profile: dict, persona: str | None = None) -> Path | None:
    """대표 이미지. 카드형 미니멀 커버."""
    name = profile["company_key"]
    html = f"""
    <div class="page"><div class="card">
      <div class="kicker">공기업·금융권 채용 분석</div>
      <div class="title">{hr.esc(name)}</div>
      <div class="subtitle">서류·필기·면접, 전형 준비 포인트 한눈에 보기</div>
      <div class="pills"><span class="pill">서류</span><span class="pill">필기</span><span class="pill">면접</span></div>
      <div class="brand">톰슨에듀 · tompsonai.com</div>
    </div></div>"""
    return hr.render(html, card_css(persona), width=780,
                     out_path=config.IMAGES_DIR / f"{name}_대표.png")


def make_procedure_table(profile: dict, procedure_table: list[dict],
                         persona: str | None = None) -> Path | None:
    """전형 절차표. generator.py 의 procedure_table 필드로 채웁니다."""
    if not procedure_table:
        return None
    name = profile["company_key"]
    rows_html = "".join(
        f'<div class="row"><div class="row-num">{i}</div>'
        f'<div class="row-label">{hr.esc(s.get("stage",""))}</div>'
        f'<div class="row-value">{hr.esc(s.get("note",""))}</div></div>'
        for i, s in enumerate(procedure_table, 1)
    )
    html = f"""
    <div class="page"><div class="card">
      <div class="kicker">전형 절차</div>
      <div class="title">{hr.esc(name)}</div>
      <div class="rows">{rows_html}</div>
      <div class="brand">톰슨에듀 · tompsonai.com</div>
    </div></div>"""
    return hr.render(html, card_css(persona), width=780,
                     out_path=config.IMAGES_DIR / f"{name}_전형절차.png")


def make_prep_checklist(profile: dict, prep_table: list[dict],
                        persona: str | None = None) -> Path | None:
    """준비 체크리스트. generator.py 의 prep_table 필드로 채웁니다."""
    if not prep_table:
        return None
    name = profile["company_key"]
    rows_html = "".join(
        f'<div class="row"><div class="row-num">✓</div>'
        f'<div class="row-label">{hr.esc(t.get("item",""))}</div>'
        f'<div class="row-value">{hr.esc(t.get("tip",""))}</div></div>'
        for t in prep_table
    )
    html = f"""
    <div class="page"><div class="card">
      <div class="kicker">준비 체크리스트</div>
      <div class="title">{hr.esc(name)}</div>
      <div class="rows">{rows_html}</div>
      <div class="footer">자세한 전형별 준비 전략은 tompsonai.com 에서 확인</div>
      <div class="brand">톰슨에듀 · tompsonai.com</div>
    </div></div>"""
    return hr.render(html, card_css(persona), width=780,
                     out_path=config.IMAGES_DIR / f"{name}_준비체크리스트.png")


if __name__ == "__main__":
    import sys
    import md_loader

    # 사용법: python image_gen.py [기업명] [스타일(brief|talk|advice|data)]
    p = md_loader.get_profile(sys.argv[1] if len(sys.argv) > 1 else "한국전력공사")
    ps = sys.argv[2] if len(sys.argv) > 2 else None
    print("대표      :", make_cover_v2(p, ps))
    print("전형절차  :", make_procedure_table(p, [
        {"stage": "서류전형", "note": "정량 평가, 70배수/30배수"},
        {"stage": "필기전형", "note": "NCS + 인성검사, 2.5~4배수"},
        {"stage": "역량면접", "note": "PT면접 + 전공면접"},
        {"stage": "종합면접", "note": "경영진 면접, 100점 단독"},
    ], ps))
    print("준비체크  :", make_prep_checklist(p, [
        {"item": "서류 커트라인", "tip": "상한제 넘으면 자격증 그만"},
        {"item": "필기 과락", "tip": "영역별 하위 30% 방지"},
        {"item": "자기소개서", "tip": "필기 직후 미리 써두기"},
    ], ps))
    hr.close()
