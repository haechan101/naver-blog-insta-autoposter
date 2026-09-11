# -*- coding: utf-8 -*-
"""생성된 초안 자동 검증 (사양서 §10, V1~V15).

위반 항목을 문자열 리스트로 돌려줍니다.
main.py 가 이 결과로 1회 재생성을 시도합니다.
"""
from __future__ import annotations
import datetime as dt
import re

import config
import personas
import topics

BLOCK_RE = re.compile(r"^\[\[(H|HR|IMG:[^\]]*|QUOTE)\]\]")


def _content_lines(body: str) -> list[str]:
    """블록 토큰과 빈 줄을 뺀 '사람이 읽는' 줄만."""
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if not s or BLOCK_RE.match(s):
            continue
        out.append(s)
    return out


def _plain(body: str) -> str:
    """토큰을 걷어낸 순수 텍스트 (분량 계산용)."""
    t = re.sub(r"^\[\[[^\]]*\]\].*$", "", body, flags=re.M)
    t = re.sub(r"</?(blue|red)>", "", t)
    return t.replace("**", "")


def _section_texts(body: str) -> list[tuple[str, str]]:
    """[[H]] 기준으로 (소제목, 본문) 쌍으로 자릅니다."""
    parts = re.split(r"^\[\[H\]\]\s*(.+)$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), _plain(parts[i + 1])))
    return out


def validate(post, topic: str = topics.ALL_KEY,
             persona: str | None = None) -> list[str]:
    body = post.body
    issues: list[str] = []
    pers = personas.get(persona)

    lines = _content_lines(body)
    plain_len = len(re.sub(r"\s", "", _plain(body)))

    # V1/V2 줄 리듬 — 기준은 스타일마다 다릅니다.
    # (조언형은 40~70자 줄글이라, 브리핑형 기준을 들이대면 매번 실패합니다)
    lo, hi = pers["line_min"], pers["line_max"]
    if lines:
        avg = sum(len(l) for l in lines) / len(lines)
        if avg > hi * 1.2:
            issues.append(
                f"V1 줄이 너무 깁니다(평균 {avg:.1f}자, {pers['name']} 목표 {lo}~{hi}자). "
                "이 스타일의 줄 리듬에 맞춰 나누세요.")
        elif avg < lo * 0.75:
            issues.append(
                f"V1 줄이 너무 짧습니다(평균 {avg:.1f}자, {pers['name']} 목표 {lo}~{hi}자). "
                "억지로 쪼개지 말고 이 스타일의 리듬대로 쓰세요.")
        over = sum(1 for l in lines if len(l) > pers["over_len"]) / len(lines)
        if over > pers["over_ratio"]:
            issues.append(
                f"V2 {pers['over_len']}자 넘는 줄이 {over:.0%}입니다"
                f"(목표 {pers['over_ratio']:.0%} 이하).")

    # V24 문단 나누기 — 빈 줄 없이 줄이 계속 붙으면 화면이 꽉 차 보입니다.
    # 실제로 B·D 스타일에서 빈 줄이 0개인 글이 나온 적이 있어 따로 잡습니다.
    body_lines = body.split("\n")
    n_blank = sum(1 for l in body_lines if not l.strip())
    # 분모는 '빈 줄이 아닌 모든 줄'입니다. lines(=본문 문장만)로 재면
    # [[H]]·[[HR]]·[[IMG]] 줄이 빠져 분모가 작아지고, 문단마다 빈 줄을 제대로
    # 넣은 글까지 '빈 줄이 너무 많다'고 반려됩니다(2026-08-26 실측: 39/32).
    n_text = sum(1 for l in body_lines if l.strip())
    if n_blank < 6:
        issues.append(
            f"V24 빈 줄이 {n_blank}개뿐입니다. 문단이 안 나뉘어 답답해 보입니다. "
            "3~5줄마다 빈 줄을 하나 넣으세요.")
    elif n_text and n_blank > n_text * pers["blank_max"]:
        # 줄마다 빈 줄을 넣으면 관련된 내용까지 떨어져 읽기 나빠집니다
        # (빈 줄 규칙을 넣었더니 실제로 이렇게 과교정된 적이 있음)
        #
        # ⚠ 상한은 스타일을 따릅니다. 조언형은 '한 줄 = 한 문단'이고 지침이
        #   "문단 사이마다 빈 줄"이라, 75% 고정으로 잡았더니 규칙과 지침이
        #   서로 부딪혀 재생성만 3번 돌았습니다(2026-08-26 실측).
        issues.append(
            f"V24 빈 줄이 너무 많습니다(본문 {n_text}줄에 빈 줄 {n_blank}개). "
            "줄마다 띄우지 말고, 내용이 이어지는 3~5줄은 붙여 쓰고 묶음 사이만 띄우세요.")
    else:
        # 빈 줄 없이 몇 줄이나 연달아 붙는지
        run = best = 0
        for l in body_lines:
            if l.strip() and not BLOCK_RE.match(l.strip()):
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > 9:
            issues.append(
                f"V24 빈 줄 없이 {best}줄이 이어집니다. 중간에 빈 줄을 넣어 끊으세요.")

    # V23 반말체(평서형) 금지 — 블로그 글은 전부 존댓말입니다.
    # 분석형이 건조하게 쓰다 보면 "~이다 / ~한다" 로 흘러가기 쉬워 따로 잡습니다.
    # (명사형 종결 "과락 — 하위 30%" 은 허용)
    plain_end = [l for l in lines
                 if re.search(r"(?:이다|한다|된다|았다|었다|린다|든다|난다)\.$", l)]
    if plain_end:
        issues.append(
            f"V23 반말체로 끝난 문장이 {len(plain_end)}개 있습니다: "
            f"\"{plain_end[0][:28]}\" — 모두 '~습니다' 로 바꾸세요.")

    # V3 본문 길이
    if not (config.BODY_MIN_CHARS <= plain_len <= config.BODY_MAX_CHARS):
        issues.append(
            f"V3 본문 분량 {plain_len}자 "
            f"(목표 {config.BODY_MIN_CHARS}~{config.BODY_MAX_CHARS}자)")

    # V4 소제목 개수
    n_h = len(re.findall(r"^\[\[H\]\]", body, re.M))
    h_lo, h_hi = pers["heads"]
    if not (h_lo <= n_h <= h_hi):
        issues.append(f"V4 소제목 {n_h}개 ({pers['name']} 목표 {h_lo}~{h_hi}개)")

    # V18 변형 선택자(U+FE0F) 이모지 — 에디터에서 두 번 입력되어 깨짐
    if "️" in body or "️" in post.title:
        bad = {m for m in re.findall(r".️", body + post.title)}
        issues.append(
            f"V18 에디터에서 깨지는 이모지가 있습니다: {' '.join(sorted(bad))} "
            "→ 🏢 📌 ✏ 🎯 🚀 🌱 📅 🔍 💡 📊 ⭐ 중에서 고르세요.")

    # V5 구분선
    n_hr = len(re.findall(r"^\[\[HR\]\]", body, re.M))
    if n_hr < 3:
        issues.append(f"V5 구분선 {n_hr}개 (최소 3개). 섹션마다 [[HR]]을 넣으세요.")

    # V6 이미지
    imgs = re.findall(r"^\[\[IMGS?:([^\]]+)\]\]", body, re.M)
    n_img = sum(len(v.split("|")) for v in imgs)
    # 기업 이미지 3장(대표·전형절차·준비체크리스트) + 마무리 기능 이미지.
    # 마무리 이미지 수는 주제마다 다릅니다(기능 2개를 고르는데 기능별로 1~2장).
    cta_imgs = sum(len(config.TOMPSONAI_FEATURES[k][1])
                   for k in (topics.get(topic).get("cta") or []))
    # 표를 안 쓰는 스타일(대화형)은 대표 이미지 1장만 들어갑니다
    need = (3 if pers["use_tables"] else 1) + cta_imgs
    if n_img < need:
        issues.append(
            f"V6 이미지 {n_img}장 (이 주제는 최소 {need}장). "
            "마무리 기능 소개 이미지가 빠졌는지 확인하세요.")

    # V7 색상 태그
    n_blue = len(re.findall(r"<blue>", body))
    n_red = len(re.findall(r"<red>", body))
    if n_blue > 6:
        issues.append(
            f"V7 <blue>가 {n_blue}회입니다(최대 6회). "
            "NCS 영역명·직렬명의 <blue>를 **굵게**로 바꾸고, "
            "가장 중요한 숫자·조건 6개만 파랑으로 남기세요.")
    if n_red > 3:
        issues.append(f"V7 <red>가 {n_red}회입니다(최대 3회)")
    if n_blue != len(re.findall(r"</blue>", body)):
        issues.append("V7 <blue> 여는/닫는 태그 개수가 다릅니다")
    if n_red != len(re.findall(r"</red>", body)):
        issues.append("V7 <red> 여는/닫는 태그 개수가 다릅니다")

    # V21 사람이 직접 넣는 꾸밈(밑줄·기울임·취소선·형광펜)의 짝이 맞는지.
    # 생성 모델은 이 표기를 쓰지 않습니다. 초안 수정 탭에서 손댄 결과를 검사하는 것입니다.
    for tag, label in (("u", "밑줄"), ("i", "기울임"),
                       ("s", "취소선"), ("hl", "형광펜")):
        o = len(re.findall(rf"<{tag}>", body))
        c = len(re.findall(rf"</{tag}>", body))
        if o != c:
            issues.append(f"V21 {label} 태그의 여는/닫는 개수가 다릅니다 ({o}/{c})")

    # V8 금지 문법
    if re.search(r"^#{1,6}\s", body, re.M):
        issues.append("V8 마크다운 헤더(#)가 있습니다")
    if re.search(r"^\s*[-*]\s", body, re.M):
        issues.append("V8 마크다운 리스트(-)가 있습니다")
    if re.search(r"^\s*\d+\.\s", body, re.M):
        issues.append("V8 번호 리스트(1.)가 있습니다")
    if re.search(r"^\s*\|.*\|", body, re.M):
        issues.append("V8 마크다운 표가 있습니다")

    # V9 제목
    if "｜" not in post.title:
        issues.append("V9 제목에 전각 구분자 ｜ 가 없습니다")
    if not (30 <= len(post.title) <= 60):
        issues.append(f"V9 제목 길이 {len(post.title)}자 (목표 35~55자)")

    # V22 제목의 연도가 지난 해면 안 됩니다.
    # 자료 원문에 작년 채용이 적혀 있으면 모델이 그대로 제목에 쓰는 일이 있는데,
    # 지난 연도가 박히면 낡은 글로 보여 검색에서 밀립니다.
    # (내년 연도는 허용합니다 — 상반기 공고는 전년도에 나오기 때문)
    this_year = dt.date.today().year
    for y in re.findall(r"20\d{2}", post.title):
        if int(y) < this_year:
            issues.append(
                f"V22 제목에 지난 연도 {y}가 있습니다. {this_year}으로 바꾸세요.")
            break

    # V10 마무리 마지막 줄은 링크
    tail = [l.strip() for l in body.strip().split("\n") if l.strip()]
    if not tail or tail[-1] != "👉 https://tompsonai.com":
        issues.append("V10 본문 마지막 줄이 정확히 '👉 https://tompsonai.com' 이어야 합니다")

    # V16 그 주제에 배정된 기능 이미지가 순서대로 들어갔는지 (주제마다 다릅니다)
    def _img_line(names: list[str]) -> str:
        return (f"[[IMGS:{'|'.join(names)}]]" if len(names) > 1
                else f"[[IMG:{names[0]}]]")

    cta_keys = topics.get(topic).get("cta") or []
    pos = -1
    for key in cta_keys:
        label, names = config.TOMPSONAI_FEATURES[key]
        want = _img_line(names)
        at = body.find(want)
        if at < 0:
            issues.append(f"V16 마무리에 '{label}' 이미지 줄 {want} 이 없습니다")
        elif at < pos:
            issues.append(f"V16 마무리 이미지 순서가 어긋났습니다. '{label}' 이 앞으로 왔습니다")
        else:
            pos = at

    # 배정 안 된 기능의 이미지가 섞여 들어오면 안 됩니다 (마무리가 다시 길어집니다)
    for key, (label, names) in config.TOMPSONAI_FEATURES.items():
        if key not in cta_keys and _img_line(names) in body:
            issues.append(
                f"V16 이 주제에 배정되지 않은 '{label}' 이미지가 들어갔습니다. 빼세요.")

    # V17 배정된 기능이 말로도 소개됐는지 (기능마다 확인할 낱말이 다릅니다)
    _WORDS = {
        "analysis": (("119",), "'119개 공기업' 언급"),
        "mock":     (("모의고사",), "'NCS 실전 모의고사' 소개"),
        "theory":   (("이론",), "'유형별 NCS 이론 학습' 소개"),
        "aiquiz":   (("AI",), "'AI 추천 문제 풀이' 소개"),
        "clinic":   (("자소서", "자기소개서"), "'자기소개서 클리닉' 소개"),
    }
    for key in cta_keys:
        words, what = _WORDS[key]
        if not any(w in body for w in words):
            issues.append(f"V17 마무리에 {what}이 없습니다")
    if "clinic" in cta_keys and "무료" not in body:
        issues.append("V17 자기소개서 클리닉이 '무료'라는 점을 밝히지 않았습니다")

    # V13 일정·인원 환각 (공고 미첨부 시 main.py 가 검사하도록 플래그만 노출)
    # → validate_no_posting() 에서 별도 처리

    # V19 원문 편집 메모가 새어들었는지 (자막 인식 오류 각주 등)
    if "자막" in body or "인식 오류" in body:
        issues.append("V19 원문의 편집 메모(자막 오류 각주 등)가 본문에 섞였습니다. 삭제하세요.")

    # V20 '내가 만든 서비스' 투 금지 — 권해주는 투여야 합니다
    maker = re.findall(
        r"[^\n]*(?:만들었|개발했|출시했|저희가 준비|제가 준비|우리가 준비)[^\n]*", body)
    maker = [l for l in maker if "톰슨" in l or "AI" in l or "서비스" in l]
    if maker:
        issues.append(
            "V20 서비스를 '내가 만들었다'는 투로 소개했습니다: "
            f"\"{maker[0].strip()[:40]}\" — 광고로 읽힙니다. "
            "'한번 써보세요', '여기서 골라 풀어볼 수 있어요'처럼 "
            "읽는 사람에게 권하는 투로 바꾸세요.")

    # V15 분량 배분 — 이 글의 '핵심 섹션'이 본문의 40% 이상인가
    # 어느 섹션이 핵심인지는 주제마다 다릅니다(topics.py 의 core_idx).
    # 소제목 문구는 모델이 조금씩 바꿔 쓰므로, 순서(몇 번째 섹션인가)로 판별합니다.
    secs = _section_texts(body)
    if secs and plain_len:
        t = topics.get(topic)
        core_idx = set(t["core_idx"])
        # 채용 일정(0번) 섹션이 있으면 뒤 섹션들이 한 칸씩 밀립니다
        offset = 1 if secs and re.search(r"채용 일정|일정 정리", secs[0][0]) else 0
        core = sum(len(re.sub(r"\s", "", txt))
                   for i, (_, txt) in enumerate(secs)
                   if (i - offset) in core_idx)
        if core / plain_len < 0.38:
            names = ", ".join(t["outline"][i][0] for i in sorted(core_idx))
            issues.append(
                f"V15 핵심 섹션({names})이 본문의 {core / plain_len:.0%}입니다(최소 40%). "
                f"이 글의 주제는 '{t['name']}'입니다. 곁가지를 줄이고 핵심을 더 채우세요.")

    return issues


def validate_no_posting(post) -> list[str]:
    """채용공고가 첨부되지 않았을 때만 적용 (V13)."""
    issues = []
    body = post.body
    if re.search(r"20\d{2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}", body):
        issues.append("V13 공고가 없는데 구체적 날짜가 있습니다. 삭제하세요.")
    for kw in ("모집인원", "접수기간", "배수 선발", "명 선발"):
        if kw in body:
            issues.append(f"V13 공고가 없는데 '{kw}'가 있습니다. 삭제하세요.")
    return issues


def report(issues: list[str]) -> None:
    if not issues:
        print("  ✅ 검증 통과")
        return
    print(f"  ⚠ 검증 위반 {len(issues)}건")
    for i in issues:
        print(f"     - {i}")
