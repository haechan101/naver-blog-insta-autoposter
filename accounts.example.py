# -*- coding: utf-8 -*-
"""계정별 기본값 — 스타일 / 카테고리 / 주제. (예시 파일)

⚠ 실제 운영 파일 accounts.py 는 네이버 블로그 아이디가 들어 있어 공개하지 않습니다.
   이 파일을 accounts.py 로 복사한 뒤 blog_id_N 을 본인 아이디로 바꾸세요.
   구조와 로직은 운영본과 같습니다.

앱에서 계정을 고르면 이 값이 자동으로 채워지고, 생성 전에 바꿀 수 있습니다.
바꾼 값은 이번 생성에만 적용되고 여기 기본값은 그대로 남습니다.

카테고리가 None 이면 네이버 기본 카테고리를 그대로 씁니다.
"""
from __future__ import annotations
import json

import config

# 금융 계열 기업 — 카테고리를 둘로 나눠 쓰는 계정에서 씁니다.
FINANCE = {
    "IBK기업은행", "KB국민은행", "NH농협은행", "SGI서울보증", "iM뱅크",
    "신한은행", "우리은행", "하나은행", "카카오뱅크", "케이뱅크", "토스뱅크",
    "한국산업은행", "한국수출입은행", "한국투자공사", "한국증권금융",
    "한국예탁결제원", "한국거래소", "한국성장금융투자운용", "코스콤",
    "신용보증기금", "기술보증기금", "예금보험공사", "한국주택금융공사",
    "한국자산관리공사", "서민금융진흥원", "신용회복위원회", "금융감독원", "금융결제원",
    "금융보안원", "주택도시보증공사", "한국해양진흥공사",
}

# 계정마다 글 스타일과 주로 쓸 주제를 다르게 둡니다.
# 같은 사람이 운영하는 블로그처럼 보이지 않게 하려는 것이고,
# 스타일은 어투뿐 아니라 표 이미지의 색·글씨체·모양까지 바꿉니다.
DEFAULTS: dict[str, dict] = {
    "blog_id_1": {"persona": "brief",  "topic": "interview", "category": None},
    "blog_id_2": {"persona": "brief",  "topic": "all",       "category": None},
    "blog_id_3": {"persona": "talk",   "topic": "all",       "category": None},
    "blog_id_4": {"persona": "talk",   "topic": "company",   "category": None},
    # 기업 종류에 따라 카테고리가 갈립니다 (금융이면 '금융공기업기출')
    "blog_id_5": {"persona": "advice", "topic": "ncs",
                  "category": "공기업기출문제",
                  "category_finance": "금융공기업기출"},
    "blog_id_6": {"persona": "advice", "topic": "all",       "category": None},
    "blog_id_7": {"persona": "data",   "topic": "caution",   "category": None},
    "blog_id_8": {"persona": "data",   "topic": "all",       "category": "채용정보"},
}

FALLBACK = {"persona": "brief", "topic": "all", "category": None}

CATEGORY_CACHE = config.DRAFTS_DIR / "_categories.json"


def defaults(account: str) -> dict:
    """그 계정의 기본 설정 (사본을 돌려주므로 마음껏 고쳐도 됩니다)."""
    return dict(DEFAULTS.get(account) or FALLBACK)


def category_for(account: str, company: str) -> str | None:
    """그 계정·그 기업에 쓸 카테고리 이름. 없으면 None(기본 카테고리)."""
    d = DEFAULTS.get(account) or {}
    if company in FINANCE and d.get("category_finance"):
        return d["category_finance"]
    return d.get("category")


def available_categories(account: str) -> list[str]:
    """collect_categories.py 가 모아둔 그 계정의 카테고리 목록."""
    if not CATEGORY_CACHE.exists():
        return []
    try:
        return json.loads(CATEGORY_CACHE.read_text(encoding="utf-8")).get(account, [])
    except Exception:
        return []


if __name__ == "__main__":
    import topics
    import personas
    print(f"{'계정':<16}{'스타일':<12}{'주제':<16}카테고리")
    print("-" * 64)
    for acc in config.list_accounts():
        d = defaults(acc)
        cat = d.get("category") or "(기본)"
        if d.get("category_finance"):
            cat += f" / {d['category_finance']}"
        print(f"{acc:<16}{personas.name(d['persona']):<12}"
              f"{topics.name(d['topic']):<16}{cat}")
