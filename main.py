# -*- coding: utf-8 -*-
"""
사용법:
  python main.py "한국전력공사"
  python main.py "한국전력공사" --posting 공고.txt
  python main.py --list                (보유 기업 목록)
"""
from __future__ import annotations
import argparse
import datetime as dt
import re

import config
import md_loader
import personas
import topics
import validator


def _safe(name: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", name).strip("_")


def create_draft(company: str, posting_text: str | None = None, quiet: bool = False,
                 topic: str = topics.ALL_KEY, persona: str | None = None):
    """생성 → 검증 → 이미지 → 저장. 초안 경로를 돌려줍니다.

    topic: topics.py 의 주제 키. 어떤 각도로 쓸지 정합니다.
    run_daily.py 에서도 이 함수를 씁니다.
    """
    import generator
    import image_gen

    def say(*a):
        if not quiet:
            print(*a)

    say(f"\n[{company}] 글 생성 시작 — {topics.name(topic)} · {personas.name(persona)}")
    post, profile = generator.build_post(company, posting_text, topic=topic,
                                        persona=persona)
    name = profile["company_key"]

    say("  ③ 검증 중…")
    issues = validator.validate(post, topic, persona)
    if not posting_text:
        issues += validator.validate_no_posting(post)
    if not quiet:
        validator.report(issues)

    for attempt in range(2):                     # 최대 2회 재생성 (총 3회 시도)
        if not issues:
            break
        say(f"  ④ 지적사항 반영해 재생성… ({attempt + 1}/2)")
        post = generator.generate_post(
            name, profile, posting_text,
            feedback="\n".join(f"- {i}" for i in issues), topic=topic,
            persona=persona)
        issues = validator.validate(post, topic, persona)
        if not posting_text:
            issues += validator.validate_no_posting(post)
        if not quiet:
            validator.report(issues)

    say("  ⑤ 이미지 생성…")
    # 카드 색·모서리는 글 스타일을 따라갑니다. 8개 계정이 같은 카드를 쓰면
    # 한 사람이 운영하는 블로그라는 게 그림만 봐도 드러납니다.
    for m in (image_gen.make_cover_v2(profile, persona),
              image_gen.make_procedure_table(
                  profile, [s.model_dump() for s in post.procedure_table], persona),
              image_gen.make_prep_checklist(
                  profile, [t.model_dump() for t in post.prep_table], persona)):
        if m:
            say(f"     ✅ {m.name}")
    import html_render
    html_render.close()   # 카드 렌더링용 브라우저 정리

    # 모델이 기업명 접두어를 빼먹는 일이 있습니다.
    # 예: [[IMG:전형절차]] ← 실제 파일은 금융감독원_전형절차.png
    # 그대로 두면 발행 때 그 자리가 비어버립니다(2026-08-26 실측, 2장 누락).
    # 접두어를 붙인 파일이 있으면 조용히 바로잡습니다.
    def _exists(n: str) -> bool:
        return any((config.IMAGES_DIR / f"{n}{e}").exists()
                   for e in (".png", ".jpg", ".jpeg", ".webp"))

    def _prefixed(n: str) -> str:
        return f"{name}_{n}" if not _exists(n) and _exists(f"{name}_{n}") else n

    post.body = re.sub(
        r"^\[\[(IMGS?):([^\]]+)\]\]",
        lambda m: f"[[{m.group(1)}:" + "|".join(
            _prefixed(n.strip()) for n in m.group(2).split("|")) + "]]",
        post.body, flags=re.M)

    needed = [n.strip()
              for v in re.findall(r"^\[\[IMGS?:([^\]]+)\]\]", post.body, re.M)
              for n in v.split("|")]
    missing = [n for n in needed
               if not any((config.IMAGES_DIR / f"{n}{e}").exists()
                          for e in (".png", ".jpg", ".jpeg", ".webp"))]

    config.DRAFTS_DIR.mkdir(exist_ok=True)
    # 파일명에 주제와 스타일을 넣습니다. 안 넣으면 같은 기업 글이
    # 같은 날 만들어질 때 서로 덮어씁니다(스타일 비교할 때 실제로 겪음).
    suffix = "" if topic == topics.ALL_KEY else f"_{_safe(topics.get(topic)['short'])}"
    if persona and persona != personas.DEFAULT:
        suffix += f"_{persona}"
    out = (config.DRAFTS_DIR /
           f"{_safe(name)}{suffix}_{dt.date.today().isoformat()}.md")
    tags = " ".join(f"#{t}" for t in post.hashtags)
    doc = [f"# {post.title}", "", post.body, "", "---", tags]
    if missing:
        doc += ["", "<!-- 필요한 이미지 (images/ 에 넣어주세요)",
                *[f"     - {m}.png" for m in missing], "-->"]
    out.write_text("\n".join(doc) + "\n", encoding="utf-8")

    return out, post, profile, needed, missing, issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("company", nargs="?", help="기업명")
    ap.add_argument("--posting", help="채용공고 텍스트 파일 경로(선택)")
    ap.add_argument("--topic", default=topics.ALL_KEY,
                    choices=[topics.ALL_KEY] + topics.DISPLAY_ORDER,
                    help="글 주제 (기본: 종합 정리)")
    ap.add_argument("--persona", default=None, choices=personas.keys(),
                    help="글 스타일 (기본: 브리핑형)")
    ap.add_argument("--account", default=None,
                    help="계정 기본값(스타일·주제)을 그대로 쓰기")
    ap.add_argument("--list", action="store_true", help="보유 기업 목록 출력")
    ap.add_argument("--topics", action="store_true",
                    help="그 기업으로 쓸 수 있는 주제 확인 (기업명과 함께)")
    args = ap.parse_args()

    if args.topics and args.company:
        p = md_loader.get_profile(args.company)
        if p is None:
            print(f"'{args.company}' 자료가 없습니다.")
            return
        stats = md_loader.angle_stats(p)
        label = {"ok": "가능", "thin": "제한적", "none": "자료 부족"}
        print(f"=== {p['company_key']} — 쓸 수 있는 주제 ===")
        for k in topics.DISPLAY_ORDER:
            st = topics.availability(stats[k], k)
            print(f"  {topics.TOPICS[k]['name']:<18}{label[st]:<7}원문 {stats[k]:,}자")
        print(f"  {topics.ALL_TOPIC['name']:<18}가능")
        return

    if args.list:
        names = md_loader.list_companies()
        print(f"=== 보유 기업 {len(names)}개 ===")
        for i in range(0, len(names), 4):
            print("  " + "  ".join(f"{n:<20}" for n in names[i:i + 4]))
        return

    company = args.company or input("기업명을 입력하세요 (예: 한국전력공사): ").strip()
    if not company:
        print("기업명이 없어 종료합니다.")
        return

    posting_text = None
    if args.posting:
        with open(args.posting, encoding="utf-8") as f:
            posting_text = f.read()

    topic, persona = args.topic, args.persona
    if args.account:                       # 계정 기본값을 쓰되, 직접 준 값이 우선
        import accounts
        d = accounts.defaults(args.account)
        persona = persona or d["persona"]
        if args.topic == topics.ALL_KEY:
            topic = d["topic"]

    out, post, profile, needed, missing, issues = create_draft(
        company, posting_text, topic=topic, persona=persona)
    tags = " ".join(f"#{t}" for t in post.hashtags)

    # ── 출력 ─────────────────────────────────────────
    plain = re.sub(r"^\[\[[^\]]*\]\].*$", "", post.body, flags=re.M)
    plain = re.sub(r"</?(blue|red)>|\*\*", "", plain)
    n_chars = len(re.sub(r"\s", "", plain))

    print("\n" + "=" * 60)
    print("제목:", post.title)
    print("=" * 60)
    print(post.body)
    print("-" * 60)
    print("해시태그:", tags)
    print(f"\n본문 {n_chars}자 · 소제목 {post.body.count('[[H]]')}개 "
          f"· 구분선 {post.body.count('[[HR]]')}개 · 이미지 {len(needed)}개")
    if missing:
        print("\n📌 아직 없는 이미지 (images/ 에 넣으면 발행 때 자동 삽입):")
        for m in missing:
            print(f"     - {m}.png")
    print(f"\n초안 저장: {out}")


if __name__ == "__main__":
    main()
