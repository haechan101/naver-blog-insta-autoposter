# -*- coding: utf-8 -*-
"""바탕화면에 '톰슨에듀 자동 포스팅' 바로가기를 만듭니다.

  venv\\Scripts\\python.exe make_shortcut.py

아이콘(app.ico)이 없으면 함께 만들고, 이미 있으면 그대로 씁니다.
바로가기는 콘솔 창 없이 앱만 뜨도록 pythonw.exe 로 실행합니다.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ICON = BASE / "app.ico"
PYW = BASE / "venv" / "Scripts" / "pythonw.exe"
TARGET_SCRIPT = BASE / "run_app.py"
SHORTCUT_NAME = "블로그 포스팅.lnk"

# 색은 앱(run_app.py)의 강조 파랑과 톰슨에듀AI 로고의 주황 포인트에서 가져왔습니다.
BLUE_TOP = (74, 144, 226)       # #4a90e2
BLUE_BOT = (37, 88, 158)        # 아래로 갈수록 깊어지게
PAPER = (255, 255, 255)
PAPER_EDGE = (222, 231, 242)    # 종이 아래 그림자 겸 테두리
LINE = (176, 192, 212)          # 종이 위 글줄
ACCENT = (245, 166, 35)         # #f5a623 — 연필 몸통
ACCENT_DARK = (214, 138, 20)    # 연필 몸통 그늘
WOOD = (232, 198, 156)          # 연필 깎인 부분
GRAPHITE = (63, 73, 88)         # 연필심


def _pencil(n: int, length: float, width: float):
    """연필 일러스트를 그린 투명 레이어를 돌려줍니다 (세로로 세운 상태).

    위에서부터  지우개 → 금속테 → 몸통 → 깎인 나무 → 심  순서입니다.
    회전은 바깥에서 하므로 여기서는 반듯하게만 그립니다.
    """
    from PIL import Image, ImageDraw

    w, h = int(width), int(length)
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)

    tip_h = h * 0.22           # 깎인 나무 부분 높이
    lead_h = h * 0.075         # 심
    er_h = h * 0.11            # 지우개
    band_h = h * 0.045         # 금속테

    # 지우개 (위쪽 둥글게)
    d.rounded_rectangle([0, 0, w, er_h + w * 0.4],
                        radius=w * 0.42, fill=(240, 130, 140))
    d.rectangle([0, er_h, w, er_h + band_h], fill=(196, 205, 216))

    # 몸통
    body_top = er_h + band_h
    body_bot = h - tip_h
    d.rectangle([0, body_top, w, body_bot], fill=ACCENT)
    # 오른쪽 절반에 그늘 — 둥근 연필처럼 보이게
    d.rectangle([w * 0.62, body_top, w, body_bot], fill=ACCENT_DARK)

    # 깎인 나무 (삼각형)
    d.polygon([(0, body_bot), (w, body_bot), (w / 2, h)], fill=WOOD)
    # 심
    d.polygon([(w / 2 - w * 0.30, h - lead_h * 1.9),
               (w / 2 + w * 0.30, h - lead_h * 1.9),
               (w / 2, h)], fill=GRAPHITE)
    return lay


def make_icon(path: Path) -> None:
    """블로그에 글 쓰는 모습 — 종이 위에 연필이 놓인 일러스트 아이콘.

    큰 크기에서는 종이·글줄·연필이 모두 보이고,
    작은 크기(16·24px)에서는 뭉개지지 않도록 연필만 크게 그립니다.
    가장자리 계단 현상을 없애려고 4배로 그린 뒤 줄입니다(수퍼샘플링).
    """
    from PIL import Image, ImageDraw, ImageFilter

    def draw(size: int) -> Image.Image:
        S = 4                                   # 수퍼샘플링 배수
        n = size * S
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # ── 배경: 둥근 사각형 + 세로 그라데이션 ──
        pad = n * 0.045
        radius = n * 0.235
        grad = Image.new("RGBA", (1, n))
        gd = ImageDraw.Draw(grad)
        for y in range(n):
            t = y / max(1, n - 1)
            gd.point((0, y), fill=(
                round(BLUE_TOP[0] + (BLUE_BOT[0] - BLUE_TOP[0]) * t),
                round(BLUE_TOP[1] + (BLUE_BOT[1] - BLUE_TOP[1]) * t),
                round(BLUE_TOP[2] + (BLUE_BOT[2] - BLUE_TOP[2]) * t), 255))
        grad = grad.resize((n, n))

        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [pad, pad, n - pad, n - pad], radius=radius, fill=255)
        img.paste(grad, (0, 0), mask)

        # 위쪽 하이라이트 — 아주 옅게. 타원을 그대로 쓰면 경계가 띠처럼 보여서
        # 흐림을 넣어 자연스럽게 풀어줍니다.
        gloss = Image.new("L", (n, n), 0)
        ImageDraw.Draw(gloss).ellipse(
            [-n * 0.25, -n * 0.70, n * 1.25, n * 0.34], fill=34)
        gloss = gloss.filter(ImageFilter.GaussianBlur(n * 0.06))
        white = Image.new("RGBA", (n, n), (255, 255, 255, 255))
        img.paste(white, (0, 0), Image.composite(
            gloss, Image.new("L", (n, n), 0), mask))

        # 16·24px 에서는 종이와 글줄이 다 뭉개져 회색 덩어리로만 보입니다.
        # 그래서 작은 크기는 연필 하나만 크게 그려 실루엣이 살아남게 합니다.
        small = size < 32

        if not small:
            # ── 종이 ──
            dx0, dy0 = n * 0.235, n * 0.20
            dx1, dy1 = n * 0.70, n * 0.80
            d.rounded_rectangle([dx0, dy0 + n * 0.012, dx1, dy1 + n * 0.012],
                                radius=n * 0.05, fill=PAPER_EDGE)
            d.rounded_rectangle([dx0, dy0, dx1, dy1],
                                radius=n * 0.05, fill=PAPER)

            # 글줄 — 오른쪽은 연필에 가리므로 짧게 둡니다
            left = dx0 + n * 0.055
            lh = n * 0.036
            for ry, wf in ((0.20, 0.62), (0.38, 0.86), (0.56, 0.86), (0.74, 0.50)):
                y = dy0 + (dy1 - dy0) * ry
                d.rounded_rectangle(
                    [left, y, left + (dx1 - left - n * 0.055) * wf, y + lh],
                    radius=lh / 2, fill=LINE)

            pen = _pencil(n, length=n * 0.72, width=n * 0.145)
            pen = pen.rotate(-38, resample=Image.BICUBIC, expand=True)
            px, py = int(n * 0.40), int(n * 0.14)
        else:
            pen = _pencil(n, length=n * 0.86, width=n * 0.235)
            pen = pen.rotate(-38, resample=Image.BICUBIC, expand=True)
            px = int((n - pen.width) / 2)
            py = int((n - pen.height) / 2)

        # 연필 그림자 — 종이 위에 떠 있는 느낌
        shadow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        shadow.paste(Image.new("RGBA", pen.size, (20, 40, 70, 90)),
                     (px, py + int(n * 0.02)), pen)
        shadow = shadow.filter(ImageFilter.GaussianBlur(n * 0.018))
        img.alpha_composite(Image.composite(
            shadow, Image.new("RGBA", (n, n), (0, 0, 0, 0)),
            mask.point(lambda v: 255 if v > 128 else 0)))

        img.alpha_composite(pen, (px, py))
        return img.resize((size, size), Image.LANCZOS)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [draw(s) for s in sizes]
    imgs[-1].save(path, format="ICO",
                  sizes=[(s, s) for s in sizes], append_images=imgs[:-1])


def _versioned_icon() -> Path:
    """아이콘을 '내용 해시가 붙은 이름'으로 복사해 그 경로를 돌려줍니다.

    윈도우는 아이콘을 경로 기준으로 캐시합니다. 같은 app.ico 를 덮어써도
    탐색기는 예전 그림을 계속 보여줍니다(실제로 그래서 '뭐가 달라졌냐'는 상황이 났음).
    파일명이 바뀌면 캐시가 안 걸리므로, 그림이 바뀔 때만 이름이 바뀌게 합니다.
    """
    import hashlib

    digest = hashlib.md5(ICON.read_bytes()).hexdigest()[:8]
    target = BASE / f"app_{digest}.ico"
    if not target.exists():
        target.write_bytes(ICON.read_bytes())
    # 예전 버전 아이콘 정리
    for old in BASE.glob("app_*.ico"):
        if old != target:
            try:
                old.unlink()
            except OSError:
                pass                     # 탐색기가 잡고 있으면 다음번에 지워집니다
    return target


def make_shortcut() -> Path:
    desktop = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, check=True).stdout.strip()
    link = Path(desktop) / SHORTCUT_NAME
    icon = _versioned_icon()

    # 바로가기 파일을 지웠다 다시 만듭니다. 덮어쓰기만 하면 탐색기가
    # 예전 아이콘을 계속 들고 있는 경우가 있습니다.
    if link.exists():
        link.unlink()

    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}')
$s.TargetPath = '{PYW}'
$s.Arguments = '"{TARGET_SCRIPT}"'
$s.WorkingDirectory = '{BASE}'
$s.IconLocation = '{icon},0'
$s.Description = '톰슨에듀 공기업 블로그 자동 포스팅'
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, text=True)
    return link


# 이름을 바꾸기 전에 쓰던 바로가기들 — 새로 만들 때 같이 지웁니다
_OLD_NAMES = ["톰슨에듀 자동 포스팅.lnk"]


def main() -> None:
    if not PYW.exists():
        print(f"❌ pythonw.exe 가 없습니다: {PYW}")
        sys.exit(1)

    make_icon(ICON)
    print(f"아이콘 생성: {ICON.name}")

    link = make_shortcut()
    print(f"✅ 바탕화면 바로가기: {link.name}")

    # 예전 이름의 바로가기가 남아 있으면 정리 (같은 앱이 두 개로 보이지 않게)
    for old in _OLD_NAMES:
        p = link.parent / old
        if p.exists() and p.name != link.name:
            p.unlink()
            print(f"   이전 바로가기 삭제: {old}")

    print("   더블클릭하면 콘솔 창 없이 앱이 바로 뜹니다.")


if __name__ == "__main__":
    main()
