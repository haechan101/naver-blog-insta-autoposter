# -*- coding: utf-8 -*-
"""'공기업 분석/*.md' 로드 + 정규화.

이전 company_exam_profiles.json(NCS 필기 전용, 101개)을 대체합니다.
이 폴더는 실제 채용설명회·직무백서 원문(서류·자소서·필기·면접·인턴 전체)이라
- 웹 검색 없이도 기업 소개·인재상·최근 이슈를 충분히 채울 수 있고
- 면접 기출까지 실명 인용으로 확보됩니다.

67개 기업. 파일명 = "{기업명} 채용정보 및 구직자 준비전략.md"
"""
from __future__ import annotations
import re
from functools import lru_cache
from pathlib import Path

import config
import topics as T

_SUFFIX = " 채용정보 및 구직자 준비전략"

# (구) 예전에는 '체크리스트|주의해야 할 점' 섹션을 앞 내용의 반복으로 보고 버렸습니다.
# 주제를 나눠 쓰기 시작하면서 이 부분이 '이것만은 피하세요' 글의 주재료가 되어
# 더 이상 버리지 않습니다. 실측 12만 6천자가 이 분류에 해당합니다.

_H1_RE = re.compile(r"^# \d+\.\s*(.+?)\s*$", re.M)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


# 파일명 뒤에 붙은 괄호 설명. 예: "금융감독원(2027 종합직원 5급 채용공고).md"
# 이걸 안 벗기면 글 제목·해시태그·이미지 파일명에 공고 이름이 통째로 따라붙습니다.
_PAREN_RE = re.compile(r"\s*[(（][^)）]*[)）]\s*$")


def _company_name(stem: str) -> str:
    """파일 이름에서 기업명만 뽑습니다."""
    return _PAREN_RE.sub("", stem.replace(_SUFFIX, "")).strip()


@lru_cache(maxsize=1)
def _files() -> dict[str, Path]:
    return {_company_name(p.stem): p
            for p in config.MD_PROFILES_DIR.glob("*.md")}


def list_companies() -> list[str]:
    return sorted(_files().keys())


@lru_cache(maxsize=200)
def get_profile(company: str) -> dict | None:
    """기업명으로 프로필 조회 (정확 매칭 → 느슨한 부분매칭)."""
    files = _files()
    target = _norm(company)

    path = next((p for n, p in files.items() if _norm(n) == target), None)
    if path is None:
        path = next((p for n, p in files.items()
                    if target and (target in _norm(n) or _norm(n) in target)), None)
    if path is None:
        return None

    raw = path.read_text(encoding="utf-8")
    matches = list(_H1_RE.finditer(raw))

    # 맨 앞 안내 인용구(자료 출처: "OOO 차장이 직접 설명하였다" 등)
    preamble = raw[:matches[0].start()] if matches else raw
    bq = re.search(r"((?:^> .*\n?)+)", preamble, re.M)
    source_note = re.sub(r"^> ?", "", bq.group(1), flags=re.M).strip() if bq else ""

    final_strategy = ""
    kept = []
    sections: list[dict] = []          # 주제별로 뽑아 쓰기 위한 원본 섹션 목록
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[m.end():end].strip()

        if "최종 지원전략" in title:
            final_strategy = body          # 문서 전체의 압축 요약 — 별도 필드로
            continue                        # 본문 압축본과 중복되지 않게 뺌

        sections.append({
            "title": title,
            "body": body,
            "chars": len(re.sub(r"\s", "", body)),
            "topic": _classify(title),
        })
        kept.append(f"# {title}\n{body}")

    return {
        "company_key": _company_name(path.stem),
        "source_note": source_note,
        "digest": "\n\n".join(kept),
        "final_strategy": final_strategy,
        "sections": sections,
        "path": str(path),
    }


def _classify(title: str) -> str | None:
    """섹션 제목 → 주제 키. 먼저 맞는 하나에만 배정합니다.

    한 섹션을 여러 주제에 이중으로 세면 분량이 부풀려져
    '쓸 수 있다'고 잘못 판단하게 됩니다(실측 때 면접이 17개로 부풀려졌던 원인).
    """
    for key in T.MATCH_ORDER:
        if re.search(T.TOPICS[key]["pattern"], title):
            return key
    return None


def angle_stats(profile: dict) -> dict[str, int]:
    """주제별로 이 기업 원문이 몇 글자나 있는지."""
    out = {k: 0 for k in T.TOPICS}
    for s in profile.get("sections", []):
        if s["topic"]:
            out[s["topic"]] += s["chars"]
    return out


def as_prompt_block(p: dict, topic: str | None = None) -> str:
    """생성 프롬프트에 넣을 자료 텍스트.

    topic 을 주면 그 주제에 해당하는 섹션을 '주제 자료'로 앞에 따로 세우고,
    나머지는 배경으로 뒤에 붙입니다. 모델이 어디에 집중해야 하는지
    분량 배치만으로도 알 수 있게 하려는 것입니다.
    topic 이 없거나 'all' 이면 예전처럼 전체를 그대로 넣습니다.
    """
    parts = [f"기업명: {p['company_key']}"]
    if p.get("final_strategy"):
        parts.append(f"[핵심 요약 — 이 문서 전체를 압축한 최종 정리]\n{p['final_strategy']}")

    sections = p.get("sections")
    if not topic or topic == T.ALL_KEY or not sections:
        parts.append(f"[상세 원문]\n{p['digest']}")
        return "\n\n".join(parts)

    focus = [s for s in sections if s["topic"] == topic]
    rest = [s for s in sections if s["topic"] != topic]

    if focus:
        body = "\n\n".join(f"# {s['title']}\n{s['body']}" for s in focus)
        parts.append(
            f"[주제 자료 — 이 글은 '{T.get(topic)['focus']}'에 대한 글이다. "
            f"아래가 핵심 재료다]\n{body}")
    if rest:
        body = "\n\n".join(f"# {s['title']}\n{s['body']}" for s in rest)
        parts.append(f"[배경 자료 — 맥락 파악용. 여기에 분량을 쓰지 마라]\n{body}")
    return "\n\n".join(parts)


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "한국전력공사"
    p = get_profile(name)
    if not p:
        print(f"'{name}' 없음. 총 {len(list_companies())}개 기업 보유.")
        print(", ".join(list_companies()[:20]), "...")
    else:
        print("기업:", p["company_key"])
        print("자료 출처:", p["source_note"][:80])
        print("최종 지원전략 길이:", len(p["final_strategy"]), "자")
        print("digest 길이:", len(p["digest"]), "자")
        print("프롬프트 블록 길이:", len(as_prompt_block(p)), "자")
