# -*- coding: utf-8 -*-
"""발행 대기열 관리.

한 편의 단위는 **(기업 × 주제)** 입니다.
한전 하나로도 NCS·서류·면접 글을 따로 쓸 수 있기 때문에,
'기업을 한 번 썼으면 끝'으로 세면 나머지 주제를 영영 못 꺼냅니다.

기업마다 '자료가 충분한 주제'만 계획에 넣습니다(topics.availability == ok).
자료가 얇은 주제까지 계획에 넣으면 일반론으로 채운 글이 쌓여
블로그 전체가 유사문서로 묶일 위험이 커집니다.

기록 파일: drafts/_published.json
  { "한국전력공사": { "ncs": {draft, status, account, scheduled_at}, ... } }
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

import config
import md_loader
import topics as T

RECORD = config.DRAFTS_DIR / "_published.json"

# 검색 수요가 큰 기업부터. 여기 없는 기업은 JSON 순서대로 이어집니다.
PRIORITY = [
    "한국전력공사", "한국철도공사", "한국수자원공사", "한국수력원자력",
    "국민건강보험공단", "한국가스공사", "인천국제공항공사", "근로복지공단",
    "한국공항공사", "한국도로교통공단",
    "IBK기업은행", "KB국민은행", "NH농협은행", "신한은행", "하나은행", "우리은행",
    "카카오뱅크", "케이뱅크", "토스뱅크",
    "신용보증기금", "기술보증기금", "예금보험공사", "한국주택금융공사",
    "한국중부발전", "한국남동발전", "한국서부발전", "한국남부발전", "한국동서발전",
]


def _load() -> dict:
    if RECORD.exists():
        try:
            return _migrate(json.loads(RECORD.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {}


def _migrate(data: dict) -> dict:
    """예전 형식(기업 단위 한 칸)을 주제별 형식으로 옮깁니다.

    예전:  {"한전": {"draft":…, "status":"filled", "topics":["ncs"]}}
    지금:  {"한전": {"ncs": {"draft":…, "status":"filled"}}}
    주제를 모르던 시절 기록은 '종합(all)'으로 봅니다.
    """
    out = {}
    for company, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        if "status" not in v:            # 이미 새 형식
            out[company] = v
            continue
        rec = {"draft": v.get("draft", ""), "status": v.get("status", ""),
               "account": v.get("account", ""),
               "scheduled_at": v.get("scheduled_at", "")}
        keys = v.get("topics") or [T.ALL_KEY]
        out[company] = {k: dict(rec) for k in keys}
    return out


def _save(data: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def order() -> list[str]:
    """PRIORITY 를 앞에 두고 나머지를 뒤에 붙인 전체 순서."""
    names = md_loader.list_companies()
    head = [n for n in PRIORITY if n in names]
    tail = [n for n in names if n not in head]
    return head + tail


@lru_cache(maxsize=1)
def plan() -> dict[str, list[str]]:
    """기업마다 '쓸 만한 주제' 목록.

    자료가 충분한(ok) 주제를 앞에 두고, 얇지만 쓸 수는 있는(thin) 주제를 뒤에 붙입니다.
    thin 까지 넣는 이유: NCS·면접은 자료가 충분한 기업이 15개뿐이라, ok 만 세면
    그 주제를 맡은 계정이 금방 소재가 떨어집니다. 대신 thin 은 일반론이 섞이므로
    ok 를 먼저 다 쓴 뒤에 손대도록 순서를 뒤로 둡니다.

    67개 md 를 전부 읽어야 해서 결과를 캐시합니다.
    (md 파일을 바꿨다면 plan.cache_clear() 를 부르세요)
    """
    out: dict[str, list[str]] = {}
    for name in order():
        p = md_loader.get_profile(name)
        if not p:
            continue
        stats = md_loader.angle_stats(p)
        ok = [k for k in T.DISPLAY_ORDER
              if T.availability(stats.get(k, 0), k) == "ok"]
        thin = [k for k in T.DISPLAY_ORDER
                if T.availability(stats.get(k, 0), k) == "thin"]
        out[name] = ok + thin or [T.ALL_KEY]
    return out


def next_task(topic: str | None = None) -> tuple[str, str] | None:
    """다음에 쓸 (기업, 주제). 없으면 None.

    topic 을 주면 **그 주제를 아직 안 쓴 기업**을 찾습니다.
    이걸 안 하면 주제를 고정했을 때 같은 기업이 계속 나옵니다
    (대기열은 '아직 안 쓴 조합'을 찾는데, 주제를 덮어쓰면 그 조합이 아니게 되므로).
    실제로 --topic ncs 로 8편을 돌렸더니 8편 모두 같은 기업이 나왔습니다.
    """
    done = _load()
    for name, keys in plan().items():
        written = set((done.get(name) or {}).keys())
        if topic:
            # 그 주제를 쓸 만한 자료가 있고(계획에 있고) 아직 안 쓴 기업
            if topic in keys and topic not in written:
                return name, topic
            continue
        for k in keys:
            if k not in written:
                return name, k
    return None


def next_company() -> str | None:
    """(구) 다음 차례 기업만. 화면의 '대기열 다음 차례' 버튼이 씁니다."""
    t = next_task()
    return t[0] if t else None


def mark(company: str, draft: str = "", scheduled_at: str = "",
         status: str = "published", topic: str = "", account: str = "") -> None:
    """(기업, 주제) 한 편의 기록을 남깁니다.

    account 는 어느 블로그 계정에 올렸는지 — 계정을 여러 개 쓰면서 함께 남깁니다.
    """
    data = _load()
    rec = data.setdefault(company, {})
    rec[topic or T.ALL_KEY] = {
        "draft": draft, "scheduled_at": scheduled_at,
        "status": status, "account": account,
    }
    _save(data)


#: '다 쓴 것'으로 볼 상태. draft_only 는 초안만 있고 블로그에는 안 올라간 것입니다.
DONE_STATUS = {"published", "scheduled", "manual"}


def done_topics(company: str) -> list[str]:
    """이 기업으로 **실제로 발행한** 주제 목록.

    ⚠ 예전에는 기록이 있기만 하면 썼다고 쳤습니다. 그래서 발행에 실패해
      draft_only 로 남은 글이 완료로 잡혀 **다시 시도되지 않았습니다**
      (2026-09-11 실측: 세션이 끊겨 못 올린 2편이 영영 대기열에서 빠짐).
    """
    rec = _load().get(company) or {}
    return [k for k, v in rec.items()
            if (v or {}).get("status") in DONE_STATUS]


def records(company: str) -> dict:
    """이 기업의 주제별 기록 원본 {주제: {draft, status, account, scheduled_at}}."""
    return dict(_load().get(company) or {})


def company_info(company: str) -> dict:
    """화면 표시용 요약 — 상태·계정·시각은 가장 최근 것 하나를 씁니다."""
    rec = _load().get(company) or {}
    if not rec:
        return {}
    last = list(rec.values())[-1]
    return {
        "topics": list(rec.keys()),
        "status": last.get("status", ""),
        "account": last.get("account", ""),
        "scheduled_at": last.get("scheduled_at", ""),
    }


def unmark(company: str, topic: str = "") -> bool:
    """기록 취소. topic 을 주면 그 주제만, 안 주면 그 기업 전체."""
    data = _load()
    if company not in data:
        return False
    if topic:
        if topic not in data[company]:
            return False
        del data[company][topic]
        if not data[company]:
            del data[company]
    else:
        del data[company]
    _save(data)
    return True


def status() -> tuple[int, int]:
    """(쓴 편수, 계획된 총 편수). 단위는 기업이 아니라 (기업 × 주제) 한 편입니다."""
    done = _load()
    written = sum(len(v) for v in done.values())
    total = sum(len(v) for v in plan().values())
    return written, total


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if args and args[0] == "--reset":
        if RECORD.exists():
            RECORD.unlink()
        print("발행 기록을 초기화했습니다.")
    elif args and args[0] == "--skip" and len(args) > 1:
        mark(args[1], status="skipped")
        print(f"'{args[1]}' 를 건너뛴 것으로 표시했습니다.")
    elif args and args[0] == "--undo" and len(args) > 1:
        print("되돌렸습니다." if unmark(args[1]) else "기록에 없습니다.")
    else:
        done, total = status()
        rec = _load()
        print(f"쓴 글 {done} / 계획 {total}편  (단위: 기업 × 주제)\n")
        if rec:
            print("=== 이미 쓴 글 ===")
            for c, per in rec.items():
                for k, v in per.items():
                    tag = v.get("scheduled_at") or v.get("status", "")
                    acc = v.get("account", "")
                    print(f"  {c:<20} {T.get(k)['short']:<8} {tag:<12} {acc}")
        print("\n앞으로 10편:")
        n = 0
        for company, keys in plan().items():
            written = set((rec.get(company) or {}).keys())
            for k in keys:
                if k in written:
                    continue
                print(f"  - {company} · {T.get(k)['name']}")
                n += 1
                if n >= 10:
                    break
            if n >= 10:
                break
        if n == 0:
            print("  (계획된 글을 모두 썼습니다)")
