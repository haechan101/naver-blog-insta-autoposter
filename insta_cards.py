# -*- coding: utf-8 -*-
"""인스타그램 카드뉴스 — 디자인과 이미지 렌더.

■ 스타일 = 틀 × 색
모든 카드뉴스가 같은 디자인이면 피드가 전부 똑같아 보여서, 만들기 전에 고릅니다.
  틀  white 화이트 볼드 · navy 네이비 금융 · note 노트 필기   (배경·글꼴·장식)
  색  base  틀의 기본 강조색 · brand 기업색 (기업 로고에서 뽑은 색)
기업색은 배경 위에서 읽히도록 밝기를 자동으로 맞춥니다
(예: 노란 KB 로고색 → 흰 바탕에서는 진한 금색, 강조 밑줄은 원래 노란색).
표지는 어느 틀이든 기업 사진 위에 어두운 막을 씌운 같은 구성이고 강조색만 따라갑니다.
글꼴은 이 컴퓨터에 설치된 것만 씁니다 (Noto Sans KR · 한컴 고딕 · 함초롬돋움).

■ 크기
1080×1350 (4:5 세로). 인스타 피드에서 정사각형보다 화면을 더 차지합니다.
캐러셀은 모든 장이 같은 비율이어야 해서 전부 같은 크기로 만듭니다.

■ 입력 deck
    {"company": "국민건강보험공단",
     "style": {"frame": "white", "color": "base"},      ← 없으면 기본
     "cards": [{"type": "cover", ...}, {"type": "intro", ...}, ...]}
카드 종류: cover, intro, checks, rows, steps, features, outro
문구 안에서  *강조* → 강조색 글자,  ==밑줄== → 형광 밑줄,  줄바꿈 → 줄바꿈.
만들 때 deck.json 으로 함께 저장해 두므로, 문구는 그대로 두고 스타일만 바꿔 다시 만들 수 있습니다.

■ 사진 (사람이 넣습니다. 있으면 자동으로 씁니다)
  ../auto_insta/insta_images/<기업명>/로고.png    표지 좌측 상단 기업 로고 (기업색도 여기서 뽑음)
  ../auto_insta/insta_images/<기업명>/건물.jpg    표지 배경. 없으면 남색 배경
  ../auto_insta/insta_images/_톰슨에듀AI/로고.png     모든 카드 우측 상단. 없으면 '톰슨에듀AI' 글자
  ../auto_insta/insta_images/_톰슨에듀AI/캡처_*.png   6·7번 카드 화면. 없으면 블로그용 images/ 캡처
만든 카드는 ../auto_insta/insta_out/<기업명>/card01.jpg … 에 저장합니다.
"""
from __future__ import annotations
import base64
import colorsys
import hashlib
import html as _html
import json
import mimetypes
import re
from pathlib import Path

import config

W, H = 1080, 1350
COVER_PHOTO_W, COVER_PHOTO_H = 1080, 780      # 표지 위쪽 사진 칸
ASSET_DIR = config.INSTA_ASSET_DIR
BRAND_DIR = config.INSTA_BRAND_DIR
OUT_DIR = config.INSTA_OUT_DIR
PREVIEW_DIR = OUT_DIR / "_스타일미리보기"
BRAND_TEXT = "톰슨에듀<b>AI</b>"
SITE = "tompsonai.com"
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 기업 폴더 안 파일 이름(앞부분). 소문자로 비교합니다.
LOGO_NAMES = ("로고", "logo")
COVER_NAMES = ("건물", "표지", "cover")

# 톰슨에듀AI 기능 카드에 넣는 화면 캡처: (인스타 전용 캡처, 블로그 마무리에서 쓰는 images/ 파일).
# 블로그용 캡처는 가로로 길어서 카드 칸(약 4:3)에 넣으면 잘리므로, 전용 캡처가 있으면 그걸 씁니다.
FEATURE_SHOTS = {
    "theory":   ("캡처_유형별이론", "유형별NCS이론"),
    "aiquiz":   ("캡처_AI추천", "유형별NCS문제풀이1"),
    "mock":     ("캡처_모의고사", "NCS_봉투모의고사"),
    "analysis": ("캡처_공기업분석", "공기업 분석_톰슨ai"),
}
FEATURE_LABEL = {
    "theory": "유형별 NCS 이론",
    "aiquiz": "AI 약점 유형 추천",
    "mock": "기업별 모의고사",
    "analysis": "공기업 분석",
}

GUIDE = """인스타 카드뉴스 사진 넣는 법
============================

■ 기업 폴더 (예: 국민건강보험공단)
  로고.png   표지 왼쪽 위 흰 네모 안에 들어갑니다. 둘레 여백은 자동으로 잘라냅니다.
             '기업색' 스타일은 이 로고에서 색을 뽑습니다.
  건물.jpg   표지 위쪽 사진 칸(1080×780)에 들어갑니다. 가로 사진이 잘 맞고,
             세로 사진은 가운데 위쪽을 기준으로 위아래가 잘립니다. 작으면 흐려집니다.
  폴더 이름은 공기업 분석 자료의 기업명과 같아야 합니다. 이름을 바꾸지 마세요.

■ _톰슨에듀AI 폴더
  로고.png          모든 카드 오른쪽 위, '톰슨에듀AI' 글자 옆에 들어갑니다. 없으면 글자만 들어갑니다.
  로고_흰색.png     어두운 표지 위에 쓸 흰색 로고 (선택).
  캡처_유형별이론.png   캡처_AI추천.png   캡처_모의고사.png   캡처_공기업분석.png
                    6·7번 카드의 톰슨에듀AI 화면. 칸 비율이 약 4:3 이고 위쪽을 기준으로 잘립니다.
                    없으면 블로그용 images 폴더의 캡처를 씁니다.

※ 건물 사진과 로고는 기업 공식 홍보 자료처럼 써도 되는 것만 넣으세요.
"""


# ── 스타일: 틀 × 색 ─────────────────────────────────
DEFAULT_STYLE = {"frame": "white", "color": "base"}
COLORS = {"base": "기본색", "brand": "기업색"}

_NOTO = "'Noto Sans KR','Malgun Gothic',sans-serif"

# vars 는 CSS 변수(--이름)로 들어갑니다. 색을 바꾸고 싶으면 여기만 고치면 됩니다.
#   main   구조 색 (체크 원, 번호 원, 표 머리, 말머리, 사이트 주소)
#   accent *강조* 글자색 / mark ==밑줄== 색 / cover-em 표지 제목 강조색
FRAMES: dict[str, dict] = {
    "white": {
        "label": "화이트 볼드",
        "desc": "흰 바탕 · 굵은 고딕 · 파란 강조",
        "vars": {
            "bg": "#ffffff", "ink": "#111111", "sub": "#333333", "muted": "#6b7280",
            "main": "#1d3b8b", "accent": "#2563eb", "mark": "rgba(37,99,235,.14)",
            "cover-em": "#ffd54a", "cover-panel": "#0f1f4a",
            "kick-bg": "#e8effc", "tile-bg": "#f3f6fb", "tile-k": "#5b6678", "tile-v": "#16233d",
            "line": "#edf0f5", "check-mark": "#ffffff",
            "step-bg": "#cfe8fb", "step-num-fg": "#ffffff",
            "shot-bg": "#f3f6fb", "shot-border": "#e3e9f2",
            "band-bg": "#1d3b8b", "band-fg": "#ffffff", "band-em": "#ffd54a",
            "brand-fg": "#1f4fbf",
            "font-title": _NOTO, "font-body": _NOTO, "w-title": "900",
        },
        "css": "",
    },
    "navy": {
        "label": "네이비 금융",
        "desc": "짙은 남색 바탕 · 한컴 고딕 · 금색 강조",
        "vars": {
            "bg": "#0f1d3a", "ink": "#ffffff", "sub": "#d3dbea", "muted": "#9fb0d0",
            "main": "#f5c451", "accent": "#f5c451", "mark": "rgba(245,196,81,.32)",
            "cover-em": "#f5c451", "cover-panel": "#0f1d3a",
            "kick-bg": "rgba(245,196,81,.16)", "tile-bg": "rgba(255,255,255,.07)",
            "tile-k": "#9fb0d0", "tile-v": "#ffffff",
            "line": "rgba(255,255,255,.14)", "check-mark": "#0f1d3a",
            "step-bg": "rgba(255,255,255,.08)", "step-num-fg": "#0f1d3a",
            "shot-bg": "#1a2a4d", "shot-border": "rgba(255,255,255,.18)",
            "band-bg": "#f5c451", "band-fg": "#0f1d3a", "band-em": "#b3261e",
            "brand-fg": "#ffffff",
            "font-title": "'한컴 고딕','Hancom Gothic'," + _NOTO, "font-body": _NOTO,
            "w-title": "700",
        },
        "css": """
.card:not(.cover) { background:radial-gradient(circle at 88% 0%, #22396b 0%, #0f1d3a 52%); }
""",
    },
    "note": {
        "label": "노트 필기",
        "desc": "크림색 줄노트 · 함초롬돋움 · 형광펜 강조",
        "vars": {
            "bg": "#fbf7ea", "ink": "#2a2a2a", "sub": "#46413a", "muted": "#8a8272",
            "main": "#2f5fd0", "accent": "#2f5fd0", "mark": "rgba(255,226,70,.85)",
            "cover-em": "#ffe246", "cover-panel": "#2a2a2a",
            "kick-bg": "#ffffff", "tile-bg": "#ffffff", "tile-k": "#8a8272", "tile-v": "#2a2a2a",
            "line": "#d9cfb3", "check-mark": "#ffffff",
            "step-bg": "#ffffff", "step-num-fg": "#ffffff",
            "shot-bg": "#ffffff", "shot-border": "#e3d9bf",
            "band-bg": "#2f5fd0", "band-fg": "#ffffff", "band-em": "#ffe246",
            "brand-fg": "#2f5fd0",
            "font-title": "'함초롬돋움','HCR Dotum'," + _NOTO,
            "font-body": "'함초롬돋움','HCR Dotum'," + _NOTO, "w-title": "700",
        },
        "css": """
.card:not(.cover) {
  background-image:
    linear-gradient(90deg, transparent 50px, #f0b7ad 50px, #f0b7ad 53px, transparent 53px),
    repeating-linear-gradient(180deg, transparent 0 66px, #ebe2c6 66px 68px); }
.mark { background:linear-gradient(transparent 38%, var(--mark) 38%, var(--mark) 92%, transparent 92%); }
.tile { border:2px solid #e6dcc3; border-top:8px solid var(--main); box-shadow:0 6px 0 #efe7cf; }
.kick { border:2px solid var(--main); }
.r { border-bottom-style:dashed; }
.r:first-child { border-top-style:dashed; }
""",
    },
}


def _resolve(style: dict | None, frame: str | None = None, color: str | None = None) -> dict:
    s = dict(DEFAULT_STYLE, **(style or {}))
    if frame:
        s["frame"] = frame
    if color:
        s["color"] = color
    if s["frame"] not in FRAMES:
        s["frame"] = DEFAULT_STYLE["frame"]
    if s["color"] not in COLORS:
        s["color"] = DEFAULT_STYLE["color"]
    return s


def style_label(style: dict | None) -> str:
    s = _resolve(style)
    return f"{FRAMES[s['frame']]['label']} · {COLORS[s['color']]}"


# ── 색 계산 ──────────────────────────────────────────
def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hex_color(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _lum(rgb) -> float:
    """WCAG 상대 휘도 (0 검정 ~ 1 흰색)."""
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _fit(rgb, bg, ratio: float) -> str:
    """색상은 두고 밝기만 조절해 bg 위에서 대비가 ratio 이상이 되게 합니다."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    step = -0.02 if _lum(bg) > 0.4 else 0.02
    cur = tuple(rgb)
    for _ in range(60):
        cur = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))
        if _contrast(cur, bg) >= ratio:
            break
        l = min(1.0, max(0.0, l + step))
    return hex_color(cur)


def _mix(rgb, bg, t: float) -> str:
    """rgb 를 t 비율만 bg 에 섞은 색 (t=0.2 → 아주 옅은 색)."""
    return hex_color(round(b + (c - b) * t) for c, b in zip(rgb, bg))


def _rgba(rgb, a: float) -> str:
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"


def _is_dark(frame: str) -> bool:
    return _lum(_rgb(FRAMES[frame]["vars"]["bg"])) < 0.3


# ── 도우미 ───────────────────────────────────────────
def _img_uri(path: Path) -> str:
    """이미지를 data URI 로. 로컬 파일 경로는 브라우저 보안 정책에 막힐 수 있어 통째로 넣습니다."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _trim_logo(path: Path, pad: int = 2):
    """로고 둘레의 빈 여백을 잘라낸 PIL 이미지. 원본 파일은 건드리지 않습니다. 못 열면 None.

    기업 홈페이지에서 받은 로고는 둘레에 여백이 넉넉해서, 표지의 흰 네모에 넣으면
    실제 로고가 절반 크기로 보였습니다 (IBK기업은행 로고 375×148 에서 확인).
    """
    from PIL import Image, ImageChops

    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None
    # 1) 투명한 여백: 거의 투명한 픽셀은 빈 곳으로 봅니다
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box:
        im = im.crop(box)
    # 2) 흰 여백: 투명한 곳이 하나도 없는(흰 바탕) 로고일 때만 자릅니다.
    #    투명 로고에 이것까지 하면 흰 글자 부분이 잘려나갈 수 있습니다.
    if im.getchannel("A").getextrema()[0] >= 250:
        white = Image.new("RGB", im.size, (255, 255, 255))
        diff = ImageChops.difference(im.convert("RGB"), white).convert("L")
        box = diff.point(lambda v: 255 if v > 20 else 0).getbbox()
        if box:
            im = im.crop(box)
    if pad:
        canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
        canvas.paste(im, (pad, pad))
        im = canvas
    return im


def _png_uri(im) -> str:
    import io

    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _logo_uri(path: Path) -> str:
    im = _trim_logo(path)
    return _png_uri(im) if im else _img_uri(path)


def _images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _IMG_EXT)


def _find(folder: Path, *stems: str) -> Path | None:
    """folder 안에서 이름(확장자 뺀)이 stems 중 하나와 똑같은 이미지."""
    want = {s.lower() for s in stems}
    return next((p for p in _images(folder) if p.stem.lower() in want), None)


def company_assets(company: str) -> tuple[Path | None, Path | None]:
    """(로고, 건물 사진). 없으면 None.

    이름이 로고/logo 로 시작하면 로고, 건물/표지/cover 로 시작하면 표지 사진입니다.
    이름을 안 맞췄으면 로고가 아닌 첫 사진을 표지로 씁니다.
    """
    files = _images(ASSET_DIR / company)
    logo = next((p for p in files if p.stem.lower().startswith(LOGO_NAMES)), None)
    cover = (next((p for p in files if p.stem.lower().startswith(COVER_NAMES)), None)
             or next((p for p in files if p != logo), None))
    return logo, cover


def brand_color(company: str) -> tuple[int, int, int] | None:
    """기업 로고에서 가장 넓게 쓰인 '색다운 색'. 흰색·회색·검정은 뺍니다. 로고가 없으면 None.

    KB국민은행 로고는 노란 별 + 회색 글자라 노란색이, IBK기업은행은 파란색이 나옵니다.
    """
    logo, _ = company_assets(company)
    im = _trim_logo(logo) if logo else None
    if im is None:
        return None
    im.thumbnail((240, 240))
    bins: dict[int, list] = {}
    for r, g, b, a in im.getdata():
        if a < 200:
            continue
        hue, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.35 or v < 0.25:
            continue
        bins.setdefault(int(hue * 24) % 24, []).append((r, g, b))
    if not bins:
        return None
    px = max(bins.values(), key=len)
    if len(px) < 30:            # 점 몇 개뿐인 색은 대표색으로 보지 않습니다
        return None
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))


def style_vars(frame: str, color: str, company: str) -> dict[str, str]:
    """틀의 기본 색에서, 기업색을 고른 경우 강조 계열만 기업 로고 색으로 바꿔 끼웁니다."""
    v = dict(FRAMES[frame]["vars"])
    rgb = brand_color(company) if color == "brand" else None
    if not rgb:
        return v
    bg = _rgb(v["bg"])
    dark = _is_dark(frame)
    v["main"] = _fit(rgb, bg, 4.5)
    v["accent"] = _fit(rgb, bg, 4.5 if dark else 3.0)
    v["cover-em"] = _fit(rgb, (11, 18, 38), 4.5)
    # 노트는 형광펜이라 진하게, 나머지는 글자 뒤 둥근 칩이라 옅게
    v["mark"] = _rgba(rgb, 0.35 if frame == "note" else 0.18)
    if dark:
        v["kick-bg"] = _rgba(rgb, 0.18)
        v["band-bg"] = v["main"]
    elif frame == "white":
        v["kick-bg"] = _mix(rgb, bg, 0.12)
        v["band-bg"] = v["main"]
    return v


def _style_css(s: dict, company: str) -> str:
    root = ";".join(f"--{k}:{val}" for k, val in style_vars(s["frame"], s["color"], company).items())
    return f":root{{{root}}}\n{FRAMES[s['frame']]['css']}"


def brand_logos() -> tuple[Path | None, Path | None]:
    """톰슨에듀AI (기본 로고, 흰색 로고). 흰색은 어두운 표지 위에 씁니다."""
    return _find(BRAND_DIR, "로고", "logo"), _find(BRAND_DIR, "로고_흰색", "logo_white")


def feature_shot(key: str) -> tuple[Path | None, bool]:
    """(캡처 파일, 인스타 전용 캡처인지)."""
    own, blog = FEATURE_SHOTS.get(key, ("", ""))
    p = _find(BRAND_DIR, own) if own else None
    if p:
        return p, True
    return (_find(config.IMAGES_DIR, blog) if blog else None), False


def made_cards(company: str) -> list[Path]:
    """이미 만들어 둔 카드 이미지."""
    d = OUT_DIR / company
    return sorted(d.glob("card*.jpg")) if d.exists() else []


def load_deck(company: str) -> dict | None:
    """저장해 둔 카드 문구(deck.json). 없으면 None."""
    try:
        return json.loads((OUT_DIR / company / "deck.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def ensure_folders(companies: list[str]) -> None:
    """기업별 사진 폴더와 _톰슨에듀AI 폴더를 만듭니다. 이미 있으면 그대로 둡니다.

    폴더를 사람이 직접 만들면 '한전'처럼 이름이 달라져 사진을 못 찾기 쉬워서 미리 만들어 둡니다.
    """
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for name in companies:
        (ASSET_DIR / name).mkdir(exist_ok=True)
    guide = ASSET_DIR / "_사진_넣는_법.txt"
    if not guide.exists():
        guide.write_text(GUIDE, encoding="utf-8")


def _t(s) -> str:
    """문구 → HTML. 이스케이프한 뒤 *강조*, ==밑줄==, 줄바꿈을 바꿉니다."""
    s = _html.escape(str(s or ""))
    # re.S: 강조가 줄바꿈을 건너가도 잡습니다 (예: "*나만의\n풀이 순서*")
    s = re.sub(r"==(.+?)==", r'<span class="mark">\1</span>', s, flags=re.S)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s, flags=re.S)
    return s.replace("\n", "<br>")


def _brand(dark: bool = False) -> str:
    """우측 상단 톰슨에듀AI 표시. 로고 파일이 있으면 그림, 없으면 글자.

    가로로 긴 로고(글자가 들어간 워드마크)는 그림만 넣고, 정사각형에 가까운 아이콘은
    그림만으로는 이름이 안 보이므로 옆에 '톰슨에듀AI' 글자를 붙입니다.
    """
    # 글자는 span 으로 감쌉니다. .brand 가 flex 라서 '톰슨'과 <b>AI</b> 가 따로 떨어지면 사이가 벌어집니다
    text = f"<span>{BRAND_TEXT}</span>"
    logo, white = brand_logos()
    img = white if dark and white else logo
    if not img:
        return f'<div class="brand only-text">{text}</div>'
    im = _trim_logo(img)
    if im is None:
        return f'<div class="brand"><img src="{_img_uri(img)}"></div>'
    if im.width >= im.height * 2:
        if dark and img is not white:
            # 진한 색 워드마크는 어두운 배경에서 안 보이므로 흰 글자로 대신합니다
            return f'<div class="brand only-text">{text}</div>'
        return f'<div class="brand"><img class="wide" src="{_png_uri(im)}"></div>'
    return f'<div class="brand"><img src="{_png_uri(im)}">{text}</div>'


# ── 디자인 (색·글꼴은 CSS 변수, 값은 위 FRAMES) ─────────
_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#e9edf3; }
/* 2026-09-22 디자인 개편: 벤치마킹한 카드뉴스(가운데 정렬 굵은 제목·빨간 강조·형광 밑줄·체크 원·
   하늘색 단계 상자·검은 띠)와 겹치지 않게, 왼쪽 정렬 + 쪽 번호 머리 + 칩 강조 + 번호 목록 + 타임라인으로 바꿨습니다. */
.card { width:1080px; height:1350px; position:relative; overflow:hidden; background:var(--bg);
        color:var(--ink); font-family:var(--font-body); display:flex; flex-direction:column;
        align-items:flex-start; padding:170px 84px 150px; margin:0 0 40px; }
/* 좌측 상단 쪽 번호·섹션 이름, 맨 아래 사이트 주소: 넘겨볼 때 한 시리즈라는 게 보이도록 */
.meta { position:absolute; top:62px; left:84px; display:flex; align-items:baseline; gap:12px;
        font-family:'Noto Sans KR','Malgun Gothic',sans-serif; }
.meta .num { font-size:40px; font-weight:900; color:var(--main); letter-spacing:-.02em; }
.meta .of { font-size:26px; font-weight:700; color:var(--muted); }
.meta .lbl { margin-left:10px; padding-left:20px; border-left:3px solid var(--line); font-size:28px;
             font-weight:700; color:var(--muted); }
.foot { position:absolute; left:84px; right:84px; bottom:52px; padding-top:22px; border-top:2px solid var(--line);
        display:flex; justify-content:space-between; font-family:'Noto Sans KR','Malgun Gothic',sans-serif;
        font-size:26px; font-weight:700; color:var(--muted); letter-spacing:.02em; }
/* 우측 상단 '톰슨에듀AI' 는 한 가지 색: 밝은 틀은 파란 글자, 어두운 표지·네이비 틀은 흰 글자 */
.brand { position:absolute; top:50px; right:66px; font-size:36px; font-weight:900;
         font-family:'Noto Sans KR','Malgun Gothic',sans-serif; color:var(--brand-fg);
         letter-spacing:-.02em; display:flex; align-items:center; gap:12px; }
.brand b { color:inherit; font-weight:900; }
.brand img { display:block; height:58px; border-radius:14px; }
.brand img.wide { height:50px; border-radius:0; }
h1.t { font-family:var(--font-title); font-size:78px; font-weight:var(--w-title); line-height:1.22;
       letter-spacing:-.035em; text-align:left; }
em { font-style:normal; color:var(--accent); }
/* 강조 칩: 형광 밑줄 대신 글자 뒤 둥근 색 바탕 (노트 필기 틀은 형광펜으로 따로 덮어씀) */
.mark { background:var(--mark); border-radius:12px; padding:0 12px;
        -webkit-box-decoration-break:clone; box-decoration-break:clone; }
.kick { font-size:32px; font-weight:800; color:var(--main); background:var(--kick-bg);
        padding:10px 26px; border-radius:14px; margin-bottom:28px; }
.lead { margin-top:36px; font-size:40px; font-weight:500; line-height:1.55; color:var(--sub); }
/* 결론: 왼쪽 색 막대 상자 */
.concl { margin-top:auto; width:100%; font-family:var(--font-title); font-size:50px; font-weight:800;
         line-height:1.4; letter-spacing:-.025em; padding:24px 0 24px 34px; border-left:12px solid var(--main); }

/* 1. 표지: 위쪽은 사진, 아래쪽은 단색 판 위에 기업명·제목 (왼쪽 정렬) */
.cover { padding:0; display:block; background:var(--cover-panel); color:#fff; }
.cover .photo { position:absolute; left:0; right:0; top:0; height:780px;
                background-size:cover; background-position:center 35%; }
.cover .photo.plain { background:radial-gradient(circle at 82% 18%, #3a5fb4 0%, #17285a 55%, var(--cover-panel) 100%); }
/* 위는 로고·'톰슨에듀AI' 가 읽히게 살짝 어둡게, 아래는 판 색으로 자연스럽게 이어지게 */
.cover .photo-shade { position:absolute; left:0; right:0; top:0; height:782px;
  background:linear-gradient(180deg, rgba(8,14,30,.55) 0%, rgba(8,14,30,.08) 26%,
                                     rgba(8,14,30,0) 55%, var(--cover-panel) 100%); }
.cover .brand { color:#fff; }
.cover .logo { position:absolute; top:44px; left:60px; height:96px; background:#fff;
               padding:14px 24px; border-radius:18px; }
.cover .logo.tall { height:156px; padding:16px 22px; }
.cover .panel { position:absolute; left:0; right:0; bottom:0; padding:0 72px 96px; }
.cover .co { display:flex; align-items:center; gap:18px; font-size:38px; font-weight:800; color:var(--cover-em); }
.cover .co::before { content:''; flex:0 0 56px; height:6px; border-radius:3px; background:var(--cover-em); }
.bubble { background:rgba(255,255,255,.14); color:#fff; font-size:30px; font-weight:800;
          padding:8px 20px; border-radius:12px; }
.cover h1 { margin-top:24px; font-family:var(--font-title); font-size:100px; font-weight:var(--w-title);
            line-height:1.16; letter-spacing:-.04em; color:#fff; }
.cover h1 em { color:var(--cover-em); }
.cover .sub { margin-top:28px; font-size:40px; font-weight:500; color:rgba(255,255,255,.78); }

/* 2. 기업 소개 */
.tiles { margin-top:52px; width:100%; display:grid; grid-template-columns:1fr 1fr; gap:20px; }
.tile { background:var(--tile-bg); border-radius:20px; padding:30px 34px; border-top:8px solid var(--main); }
.tile .k { font-size:28px; color:var(--tile-k); font-weight:700; }
.tile .v { margin-top:10px; font-family:var(--font-title); font-size:44px; font-weight:900;
           color:var(--tile-v); line-height:1.28; letter-spacing:-.025em; }
/* 기관 소개는 설명 + 정보 칸 4개 + 결론까지 들어가 가장 빽빽해서, 간격과 글자를 조금 줄입니다 */
.intro .lead { margin-top:26px; font-size:38px; }
.intro .tiles { margin-top:36px; gap:16px; }
.intro .tile { padding:22px 30px; }
.intro .tile .v { font-size:40px; }
.intro .concl { font-size:46px; padding:18px 0 18px 30px; }

/* 3. 필기 구성: 체크 원 대신 01·02·03 번호 칸 */
.checks { margin-top:60px; width:100%; display:flex; flex-direction:column; gap:40px; counter-reset:chk; }
.check { display:flex; align-items:flex-start; gap:30px; font-size:44px; font-weight:600; line-height:1.42;
         counter-increment:chk; }
.check i { flex:0 0 76px; height:76px; border-radius:20px; background:var(--kick-bg); color:var(--main);
           font-style:normal; font-size:34px; font-weight:900; display:flex; align-items:center;
           justify-content:center; font-family:'Noto Sans KR','Malgun Gothic',sans-serif; }
.check i::after { content:counter(chk, decimal-leading-zero); }

/* 4. 표 형태 */
.rows { margin-top:56px; width:100%; }
.r { display:flex; gap:30px; padding:32px 0; border-bottom:2px solid var(--line); align-items:baseline; }
.r:first-child { border-top:4px solid var(--main); }
.r .k { flex:0 0 290px; font-family:var(--font-title); font-size:44px; font-weight:900; color:var(--main);
        line-height:1.3; letter-spacing:-.02em; }
.r .v { flex:1; font-size:39px; font-weight:500; line-height:1.48; color:var(--sub); }

/* 5. 준비 전략: 상자 대신 세로 타임라인 */
.steps { margin-top:60px; width:100%; display:flex; flex-direction:column; gap:34px; position:relative; }
.steps::before { content:''; position:absolute; left:35px; top:36px; bottom:36px; width:4px;
                 border-radius:2px; background:var(--line); }
.step { position:relative; display:flex; align-items:flex-start; gap:34px; font-size:44px; font-weight:600;
        line-height:1.4; }
.step b { position:relative; z-index:1; flex:0 0 74px; height:74px; border-radius:50%; background:var(--main);
          color:var(--step-num-fg); font-size:36px; font-weight:900; display:flex; align-items:center;
          justify-content:center; box-shadow:0 0 0 10px var(--bg); }
.step span { padding-top:6px; }

/* 6·7. 톰슨에듀AI 기능 */
.feats { margin-top:48px; width:100%; display:flex; flex-direction:column; gap:44px; }
.feat { display:flex; gap:36px; align-items:center; }
.feat .shot { flex:0 0 420px; height:320px; border-radius:26px; overflow:hidden; background:var(--shot-bg);
              border:2px solid var(--shot-border); box-shadow:0 16px 40px rgba(20,35,70,.16); }
.feat .shot img { width:100%; height:100%; object-fit:cover; object-position:top center; }
.feat h3 { font-family:var(--font-title); font-size:48px; font-weight:900; letter-spacing:-.03em;
           color:var(--ink); line-height:1.25; }
.feat p { margin-top:16px; font-size:37px; line-height:1.46; color:var(--sub); font-weight:500; }

/* 8. 마무리: 검은 띠 대신 둥근 버튼 모양 안내 */
.outro { padding-bottom:110px; }
.stars { margin-top:56px; width:100%; display:flex; flex-direction:column; gap:30px; }
.star { display:flex; gap:24px; font-size:44px; font-weight:600; align-items:center; }
.star::before { content:''; flex:0 0 18px; height:18px; border-radius:5px; background:var(--accent);
                transform:rotate(45deg); }
.site { margin-top:auto; font-size:46px; font-weight:900; color:var(--main); letter-spacing:-.01em;
        font-family:'Noto Sans KR','Malgun Gothic',sans-serif; }
.save { margin-top:10px; font-size:32px; color:var(--muted); font-weight:600; }
.band { margin-top:34px; width:100%; background:var(--band-bg); color:var(--band-fg); border-radius:28px;
        padding:36px 44px; display:flex; align-items:center; justify-content:space-between; gap:20px;
        font-family:var(--font-title); font-size:46px; font-weight:900; line-height:1.35; letter-spacing:-.02em; }
.band::after { content:'→'; font-size:54px; }
.band em { color:var(--band-em); }
"""


# ── 카드 종류별 HTML ─────────────────────────────────
# 좌측 상단에 쪽 번호와 함께 붙는 섹션 이름
SECTION_LABEL = {"intro": "기관 소개", "checks": "필기 구성", "rows": "세부 구성",
                 "steps": "준비 전략", "features": "톰슨에듀AI", "outro": "마무리"}


def _meta(c: dict, num: int, total: int) -> str:
    if not num:
        return ""
    return (f'<div class="meta"><span class="num">{num:02d}</span><span class="of">/ {total:02d}</span>'
            f'<span class="lbl">{SECTION_LABEL.get(c.get("type"), "")}</span></div>')


def _foot() -> str:
    return f'<div class="foot"><span>{SITE}</span><span>NCS · 공기업 필기</span></div>'


def _page(c: dict, body: str, brand: str, num: int = 0, total: int = 0, cls: str = "") -> str:
    kick = f'<div class="kick">{_t(c["kicker"])}</div>' if c.get("kicker") else ""
    lead = f'<p class="lead">{_t(c["lead"])}</p>' if c.get("lead") else ""
    concl = f'<div class="concl">{_t(c["concl"])}</div>' if c.get("concl") else ""
    return (f'<div class="card {cls}">{_meta(c, num, total)}{brand}{kick}'
            f'<h1 class="t">{_t(c["title"])}</h1>{lead}{body}{concl}{_foot()}</div>')


def _cover(c, company, logo, cover_img, brand_dark, **_):
    photo = (f'<div class="photo" style="background-image:url({_img_uri(cover_img)})"></div>'
             if cover_img else '<div class="photo plain"></div>')
    logo_html = ""
    if logo:
        im = _trim_logo(logo)
        # 심볼 아래 글자가 있는 세로형 로고는 같은 높이에 넣으면 글자가 안 읽혀서 칸을 키웁니다 (한국가스기술공사)
        tall = " tall" if im and im.width < im.height * 2 else ""
        logo_html = f'<img class="logo{tall}" src="{_png_uri(im) if im else _img_uri(logo)}">'
    bubble = f'<span class="bubble">{_t(c["tag"])}</span>' if c.get("tag") else ""
    sub = f'<div class="sub">{_t(c["sub"])}</div>' if c.get("sub") else ""
    return (f'<div class="card cover">{photo}<div class="photo-shade"></div>{logo_html}{brand_dark}'
            f'<div class="panel"><div class="co"><span>{_t(company)}</span>{bubble}</div>'
            f'<h1>{_t(c["title"])}</h1>{sub}</div></div>')


def _intro(c, brand, num=0, total=0, **_):
    tiles = "".join(f'<div class="tile"><div class="k">{_t(k)}</div><div class="v">{_t(v)}</div></div>'
                    for k, v in c.get("facts", []))
    return _page(c, f'<div class="tiles">{tiles}</div>', brand, num, total, cls="intro")


def _checks(c, brand, num=0, total=0, **_):
    items = "".join(f'<div class="check"><i></i><span>{_t(x)}</span></div>' for x in c.get("items", []))
    return _page(c, f'<div class="checks">{items}</div>', brand, num, total)


def _rows(c, brand, num=0, total=0, **_):
    rows = "".join(f'<div class="r"><div class="k">{_t(k)}</div><div class="v">{_t(v)}</div></div>'
                   for k, v in c.get("rows", []))
    return _page(c, f'<div class="rows">{rows}</div>', brand, num, total)


def _steps(c, brand, num=0, total=0, **_):
    items = "".join(f'<div class="step"><b>{i}</b><span>{_t(x)}</span></div>'
                    for i, x in enumerate(c.get("items", []), 1))
    return _page(c, f'<div class="steps">{items}</div>', brand, num, total)


def _features(c, brand, num=0, total=0, **_):
    blocks = []
    for f in c.get("features", []):
        shot, _own = feature_shot(f.get("key", ""))
        img = f'<div class="shot"><img src="{_img_uri(shot)}"></div>' if shot else ""
        blocks.append(f'<div class="feat">{img}<div class="txt">'
                      f'<h3>{_t(f["title"])}</h3><p>{_t(f["desc"])}</p></div></div>')
    return _page(c, f'<div class="feats">{"".join(blocks)}</div>', brand, num, total)


def _outro(c, brand, num=0, total=0, **_):
    items = "".join(f'<div class="star">{_t(x)}</div>' for x in c.get("items", []))
    save = f'<div class="save">{_t(c["save"])}</div>' if c.get("save") else ""
    # 예전 문구의 ▼ 는 버튼 모양에 어울리지 않아 뺍니다 (화살표는 CSS 로 붙음)
    band = re.sub(r"\s*▼\s*", " ", c.get("band", "")).strip()
    return (f'<div class="card outro">{_meta(c, num, total)}{brand}'
            f'<h1 class="t">{_t(c["title"])}</h1><div class="stars">{items}</div>'
            f'<div class="site">{SITE}</div>{save}'
            f'<div class="band"><span>{_t(band)}</span></div></div>')


_BUILDERS = {"cover": _cover, "intro": _intro, "checks": _checks, "rows": _rows,
             "steps": _steps, "features": _features, "outro": _outro}


def build_html(deck: dict, frame: str | None = None, color: str | None = None) -> str:
    company = deck["company"]
    s = _resolve(deck.get("style"), frame, color)
    logo, cover_img = company_assets(company)
    # 네이비처럼 어두운 틀은 본문 카드도 어두우므로 표지와 같은 로고 규칙을 씁니다
    brand, brand_dark = _brand(dark=_is_dark(s["frame"])), _brand(dark=True)
    parts = []
    total = len(deck["cards"])
    for i, c in enumerate(deck["cards"]):
        card = _BUILDERS[c["type"]](c, company=company, logo=logo, cover_img=cover_img,
                                    brand=brand, brand_dark=brand_dark,
                                    num=c.get("num") or i + 1, total=c.get("total") or total)
        parts.append(card.replace('<div class="card', f'<div id="card{i}" class="card', 1))
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{_CSS}\n{_style_css(s, company)}</style></head>"
            f"<body>{''.join(parts)}</body></html>")


def _launch(p):
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        return p.chromium.launch()


def _render(deck: dict, out_dir: Path | None, frame: str | None, color: str | None,
            check: bool) -> tuple[list[Path], list[str]]:
    from playwright.sync_api import sync_playwright

    deck = dict(deck, style=_resolve(deck.get("style"), frame, color))
    out_dir = Path(out_dir or OUT_DIR / deck["company"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("card*.jpg"):
        old.unlink()
    (out_dir / "deck.json").write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = out_dir / "deck.html"
    html_path.write_text(build_html(deck), encoding="utf-8")

    paths, issues = [], []
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": W + 40, "height": H + 40}, device_scale_factor=1)
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_timeout(500)
        for i in range(len(deck["cards"])):
            if check:
                issues += _card_issues(page, f"card{i}", f"{i + 1}번 카드")
            el = page.query_selector(f"#card{i}")
            fp = out_dir / f"card{i + 1:02d}.jpg"
            el.screenshot(path=str(fp), type="jpeg", quality=92)
            paths.append(fp)
        browser.close()
    return paths, issues


def render(deck: dict, out_dir: Path | None = None,
           frame: str | None = None, color: str | None = None) -> list[Path]:
    """카드마다 1080×1350 JPEG 를 만듭니다. 만든 파일 경로 목록을 돌려줍니다.

    문구와 고른 스타일을 deck.json 으로 함께 저장합니다 (스타일만 바꿔 다시 만들 때 씁니다).
    """
    return _render(deck, out_dir, frame, color, check=False)[0]


def render_checked(deck: dict, out_dir: Path | None = None, frame: str | None = None,
                   color: str | None = None) -> tuple[list[Path], list[str]]:
    """render 와 같고, 글자 넘침·의도치 않은 줄바꿈 목록('3번 카드: …')을 함께 돌려줍니다."""
    return _render(deck, out_dir, frame, color, check=True)


def rebuild(company: str, frame: str, color: str, log=print) -> list[Path]:
    """저장해 둔 문구(deck.json)로, 고른 스타일의 카드를 다시 만듭니다."""
    deck = load_deck(company)
    if not deck:
        raise ValueError(f"{company} 카드 문구(deck.json)가 없습니다.")
    s = _resolve(None, frame, color)
    if s["color"] == "brand" and not brand_color(company):
        log("기업 로고에서 색을 찾지 못해 기본색으로 만듭니다.")
        s["color"] = "base"
    log(f"{company} · {style_label(s)} 스타일로 만드는 중…")
    paths = render(deck, frame=s["frame"], color=s["color"])
    log(f"카드 {len(paths)}장을 만들었습니다.")
    return paths


# ── 카드 한 장 고치기 (앱의 글자 수정 창) ─────────────────
# 글자가 카드 밖으로 넘치거나 로고·맨 아래 띠와 겹치면 true.
# 카드는 overflow:hidden 이라 넘친 글자는 조용히 잘려서, 그림만 봐서는 놓치기 쉽습니다.
_OVERFLOW_JS = """
(id) => {
  const card = document.getElementById(id);
  const r = card.getBoundingClientRect();
  const foot = card.querySelector('.foot');                            // 본문은 맨 아래 주소 줄 위까지
  const bottom = foot ? foot.getBoundingClientRect().top - 8 : r.bottom - 30;
  const logo = card.querySelector('.logo');                            // 표지는 로고 칸 아래부터
  const top = card.classList.contains('cover')
    ? (logo ? logo.getBoundingClientRect().bottom + 10 : r.top + 150) : r.top + 130;
  // .panel(표지 글자 묶음)은 원래 카드 폭을 꽉 채우므로 자신은 빼고 안의 글자만 봅니다
  const skip = '.photo, .photo-shade, .logo, .brand, .brand *, .panel, .foot, .foot *, .meta, .meta *';
  for (const el of card.querySelectorAll('*')) {
    if (el.matches(skip)) continue;
    const b = el.getBoundingClientRect();
    if (!b.width || !b.height) continue;
    if (b.top < top || b.bottom > bottom || b.left < r.left + 10 || b.right > r.right - 10) return true;
  }
  return false;
}
"""


# 문구에 넣은 줄(\n)보다 실제로 그려진 줄이 많으면 = 한 줄이 길어 저절로 줄이 넘어간 것.
# 넘치지는 않아도 제목이 3줄이 되는 식으로 모양이 망가져서 따로 잡습니다. 넘어간 문장 앞부분을 돌려줍니다.
_WRAP_JS = """
(id) => {
  const card = document.getElementById(id);
  const out = [];
  const sel = 'h1, .sub, .co > span, .lead, .concl, .kick, .tile .k, .tile .v, .check > span, '
            + '.r .k, .r .v, .step > span, .feat h3, .feat p, .star, .save, .band > span';
  for (const el of card.querySelectorAll(sel)) {
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3;
    const range = document.createRange();
    range.selectNodeContents(el);
    const ys = [...range.getClientRects()].filter(r => r.width > 1).map(r => r.top).sort((a, b) => a - b);
    let lines = 0, last = -1e9;
    for (const y of ys) { if (y - last > lh * 0.5) { lines++; last = y; } }
    const explicit = (el.innerHTML.match(/<br\\s*\\/?>/gi) || []).length + 1;
    if (lines > explicit) out.push(el.innerText.replace(/\\s*\\n\\s*/g, ' / ').trim().slice(0, 40));
  }
  return out;
}
"""


def _card_issues(page, card_id: str, label: str) -> list[str]:
    out = []
    if page.evaluate(_OVERFLOW_JS, card_id):
        out.append(f"{label}: 글자가 카드 밖으로 넘치거나 로고·띠와 겹칩니다")
    for text in page.evaluate(_WRAP_JS, card_id):
        out.append(f"{label}: 한 줄이 길어 줄이 저절로 넘어갔습니다 — \"{text}\"")
    return out


def render_card(deck: dict, index: int, out_path: Path) -> list[str]:
    """deck 의 index 번째 카드 한 장만 그립니다. 글자 넘침·줄 넘어감 목록을 돌려줍니다 (없으면 빈 목록)."""
    import tempfile
    from playwright.sync_api import sync_playwright

    # 한 장만 그려도 쪽 번호는 원래 위치(예: 03 / 08)로 나오게 합니다 (저장되는 문구에는 안 들어감)
    one = dict(deck, cards=[dict(deck["cards"][index], num=index + 1, total=len(deck["cards"]))])
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "card.html"
        html_path.write_text(build_html(one), encoding="utf-8")
        with sync_playwright() as p:
            browser = _launch(p)
            page = browser.new_page(viewport={"width": W + 40, "height": H + 40}, device_scale_factor=1)
            page.goto(html_path.as_uri())
            page.evaluate("document.fonts.ready.then(() => true)")
            page.wait_for_timeout(300)
            issues = _card_issues(page, "card0", "이 카드")
            page.query_selector("#card0").screenshot(path=str(out_path), type="jpeg", quality=92)
            browser.close()
    return issues


def preview_card(company: str, index: int, card: dict) -> tuple[str, list[str]]:
    """저장하지 않고, 고친 카드 한 장을 임시 파일로 그려봅니다. (임시 파일 경로, 확인할 점 목록)"""
    import os
    import tempfile

    deck = load_deck(company)
    if not deck:
        raise ValueError(f"{company} 카드 문구(deck.json)가 없습니다.")
    deck["cards"][index] = card
    fd, path = tempfile.mkstemp(prefix="tompson_card_", suffix=".jpg")
    os.close(fd)
    return path, render_card(deck, index, Path(path))


def save_card(company: str, index: int, card: dict) -> list[str]:
    """고친 카드 한 장을 deck.json 에 저장하고 그 카드 그림만 다시 만듭니다. 확인할 점 목록을 돌려줍니다."""
    deck = load_deck(company)
    if not deck:
        raise ValueError(f"{company} 카드 문구(deck.json)가 없습니다.")
    deck["cards"][index] = card
    out_dir = OUT_DIR / company
    (out_dir / "deck.json").write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "deck.html").write_text(build_html(deck), encoding="utf-8")
    return render_card(deck, index, out_dir / f"card{index + 1:02d}.jpg")


# ── 스타일 미리보기 (앱에서 마우스를 올리면 보이는 그림) ──────
_SAMPLE = {
    "company": "예시 기업",
    "cards": [
        {"type": "cover", "title": "필기, *이렇게*\n준비하세요", "sub": "스타일 미리보기"},
        {"type": "checks", "title": "필기,\n이렇게 나옵니다",
         "items": ["직업기초능력 *60문항*", "과목마다 *40%* 넘기기", "총점 ==60%== 이상"],
         "concl": "한 과목도\n==버리면 안 됩니다=="},
    ],
}


def _preview_path(frame: str) -> Path:
    # 디자인이 바뀌면 이름이 바뀌어 새로 만들어집니다
    key = hashlib.md5((_CSS + json.dumps(FRAMES[frame], ensure_ascii=False)
                       + json.dumps(_SAMPLE, ensure_ascii=False)).encode("utf-8")).hexdigest()[:8]
    return PREVIEW_DIR / f"{frame}_{key}.jpg"


def style_previews() -> dict[str, Path]:
    """틀마다 표지+본문 한 장씩 나란히 붙인 미리보기 그림. 이미 있으면 브라우저를 띄우지 않습니다."""
    out = {f: _preview_path(f) for f in FRAMES}
    missing = [f for f, p in out.items() if not p.exists()]
    if not missing:
        return out
    import tempfile
    from PIL import Image

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW_DIR.glob("*.jpg"):
        if old not in out.values():
            old.unlink()
    for f in missing:
        with tempfile.TemporaryDirectory() as tmp:
            shots = []
            for p in render(_SAMPLE, Path(tmp), frame=f, color="base"):
                with Image.open(p) as im:          # with: 윈도우에서 파일을 붙잡고 있으면 임시 폴더가 안 지워짐
                    shots.append(im.convert("RGB").resize((540, 675)))
        sheet = Image.new("RGB", (540 * 2 + 20, 675), "#ffffff")
        for i, im in enumerate(shots):
            sheet.paste(im, (i * 560, 0))
        sheet.save(out[f], quality=88)
    return out
