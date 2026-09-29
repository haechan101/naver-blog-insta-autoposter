# -*- coding: utf-8 -*-
"""인스타 카드뉴스 문구 생성 — 공기업 분석 자료 → 카드 8장 문구 + 캡션.

■ 흐름
  자료(md) → Claude 가 1~5번 카드·마무리 항목·캡션을 씀 → 글자 검사(개수·금지어)
  → 카드 그리기 → 그림 검사(글자 넘침·줄 넘어감) → 문제가 있으면 알려주고 한 번 다시 씀
  그래도 남은 문제는 목록으로 돌려주고, 사람이 앱의 글자 수정 창에서 고칩니다.

■ 고정 문구
  6·7번 톰슨에듀AI 기능 카드와 8번 제목·저장 문구·띠 문구는 정해진 문구를 씁니다.
  서비스 설명을 모델이 매번 새로 쓰면 없는 기능을 약속하는 문장이 섞일 수 있어서입니다.

■ 문구 원칙 (블로그 글 생성과 같음)
  자료에 있는 사실만 · 출처/화자 언급 금지 · 자기소개서 클리닉 언급 금지.
  카드뉴스는 오래 남으므로 채용 일정·인원(지난 채용 기준)은 쓰지 않고 시험 구성만 씁니다.

실행 (앱 없이):
  venv\\Scripts\\python.exe insta_gen.py 한국전력공사 [--frame navy] [--color brand]
"""
from __future__ import annotations
import json
import re
import shutil

from pydantic import BaseModel, Field

import config
import generator          # _client, _retry 를 블로그 생성과 같이 씁니다
import insta_cards
import insta_publish
import md_loader

MAX_TRIES = 2     # 처음 + 문제를 알려주고 다시 쓰기 한 번. 한 번 쓸 때마다 API 비용이 들어 더 돌리지 않습니다

FIXED_FEATURES = [
    {"type": "features", "kicker": "톰슨에듀AI로 준비하기 ①", "title": "기초부터\n약점까지 잡기",
     "features": [{"key": "theory", "title": "유형별 NCS 이론",
                   "desc": "의사소통·수리·문제해결을\n유형별로 나눠 이론부터"},
                  {"key": "aiquiz", "title": "AI 약점 유형 추천",
                   "desc": "틀린 문제를 분석해\n약한 유형만 다시 풀기"}]},
    {"type": "features", "kicker": "톰슨에듀AI로 준비하기 ②", "title": "실전 점검과\n기업 분석까지",
     "features": [{"key": "mock", "title": "기업별 모의고사",
                   "desc": "출제 유형 그대로\n시간 배분까지 실전처럼"},
                  {"key": "analysis", "title": "공기업 분석 가이드",
                   "desc": "119개 공기업 정리\n무료 회원이면 전부 열람"}]},
]
OUTRO = {"title": "혼자 준비하기\n막막하다면",
         "save": "저장해두고 시험 전에 다시 보세요",
         "band": "*프로필 링크*에서 톰슨에듀AI 확인하기"}

# 출처·화자를 드러내는 말, 소개하지 않는 서비스
BANNED = ["담당자", "인사담당", "인사팀", "설명회", "현직자", "직무백서", "합격자에 따르면",
          "합격자들", "클리닉"]


# ── 출력 스키마 ──────────────────────────────────────
class Pair(BaseModel):
    k: str = Field(description="항목/머리 (공백 포함 7자 이내)")
    v: str = Field(description="내용. 줄바꿈은 \\n")


class CoverText(BaseModel):
    title: str = Field(description="표지 제목. 2줄, 한 줄 9자 이내. 핵심 수치나 키워드 하나를 *강조*")
    sub: str = Field(description="표지 부제 한 줄, 20자 이내. 예: 'IBK기업은행 필기, 이렇게 준비하세요'")


class IntroText(BaseModel):
    title: str = Field(description="2줄. 첫 줄 기업명(+쉼표), 둘째 줄 '어떤 곳일까?'. 기업명이 10자를 넘으면 널리 쓰는 약칭")
    lead: str = Field(description="기관 소개 2줄, 한 줄 18자 이내. 핵심어 하나를 *강조*")
    facts: list[Pair] = Field(description="정확히 4칸. 항목 7자 이내, 내용 2줄 이내·한 줄 8자 이내")
    concl: str = Field(description="결론 2줄, 한 줄 12자 이내. 둘째 줄 전체를 ==밑줄==")


class ListText(BaseModel):
    title: str = Field(description="카드 제목 2줄, 한 줄 11자 이내")
    items: list[str] = Field(description="정확히 3개. 각 2줄, 한 줄 16자 이내. 핵심 수치·키워드를 *강조*")
    concl: str = Field(description="결론 2줄, 한 줄 12자 이내. 둘째 줄 전체를 ==밑줄==")


class TableText(BaseModel):
    title: str = Field(description="카드 제목 2줄, 한 줄 11자 이내")
    rows: list[Pair] = Field(description="2~3행. 머리 7자 이내, 내용 2줄 이내·한 줄 15자 이내")
    concl: str = Field(description="결론 2줄, 한 줄 12자 이내. 둘째 줄 전체를 ==밑줄==")


class CaptionText(BaseModel):
    """캡션에서 기업마다 달라지는 칸. 나머지 서비스 안내는 CAPTION_TEMPLATE 고정 문구입니다."""
    hook: str = Field(description="캡션 첫 줄 한 문장, 30자 안팎, 마침표로 끝. 예: '코트라 NCS, 기출이 없어 막막하셨다면.'")
    short_name: str = Field(description="기업 약칭. 널리 쓰는 약칭이 없으면 기업명. 예: 코트라, 한전")
    exam_areas: str = Field(description="NCS 출제 영역을 · 로 이은 한 줄. 자료에 없으면 빈 문자열")
    exam_format: str = Field(description="문항 수·시험 시간 한 줄. 예: '6개 영역 각 20문항, 총 120문항 / 90분'. 자료에 없으면 빈 문자열")
    hashtags: list[str] = Field(description="해시태그 9~12개, # 없이, 띄어쓰기 없이")


class InstaDeckText(BaseModel):
    cover: CoverText
    intro: IntroText
    exam: ListText = Field(description="3번 카드: 필기 전반 (구성·문항 수·시간·출제 유형·과락 등)")
    detail: TableText = Field(description="4번 카드: NCS 영역별, 없으면 직렬·분야·부문별 시험 구성")
    prep: ListText = Field(description="5번 카드: 이 기업 필기 준비법 3단계")
    outro_items: list[str] = Field(description="8번 카드 정리 정확히 3개, 각 한 줄 16자 이내")
    caption: CaptionText


# ── 프롬프트 ─────────────────────────────────────────
SYSTEM = """너는 공기업·금융권 취업 준비생을 위한 인스타그램 카드뉴스 에디터다.
카드뉴스는 톰슨에듀AI(tompsonai.com — NCS·공기업 필기 학습 서비스) 인스타 계정에 올라간다.
목표: {기업} 필기를 준비하는 사람이 저장하고 싶어지는 핵심 정보를 짧고 강하게 전하고,
마지막에 톰슨에듀AI로 이어서 준비하고 싶어지게 만드는 것.

■ 카드 구성 (순서 고정)
1 표지(cover)      이 기업 필기에서 가장 눈에 띄는 사실 하나로 제목을 만든다.
                   좋은 예: "피듈형이라지만\\n실제는 *PSAT형*", "*100문항 100분*\\n1문항에 1분"
2 기업 소개(intro) 어떤 기관인지. facts 4칸은 설립·본사·유형·규모·대표 사업처럼 자료에 있는 사실
3 필기 전반(exam)  시험 구성·문항 수·시간·출제 유형·과락처럼 필기의 큰 그림 3가지
4 필기 상세(detail) 자료에 NCS 영역(의사소통·수리 등)이 나와 있으면 영역별로,
                   없으면 직렬·분야·부문별 시험 구성으로 2~3행
5 준비법(prep)     자료의 조언을 바탕으로 이 기업에 맞춘 준비 3단계
6·7 톰슨에듀AI 기능 카드와 8번 제목·띠 문구는 정해져 있다. 너는 8번 정리 항목(outro_items) 3개만 쓴다.
   outro_items 는 톰슨에듀AI로 할 일이다: 유형별 NCS 이론 / AI 약점 유형 추천 / 기업별 모의고사.
   예: "유형별 이론으로 기초 다지기", "AI 추천으로 약점 유형 보완", "모의고사로 100분 시간 배분 연습"

■ 사실 원칙
- 제공된 자료에 있는 사실·수치만 쓴다. 자료에 없는 수치·유형을 추측해 채우지 않는다.
- 필기 정보가 자료에 거의 없으면 3~5번은 전형 구조와 준비 포인트 중심으로 쓰되, 역시 자료에 있는 것만 쓴다.
- 채용 일정(접수 마감일·시험 날짜)과 채용 인원은 쓰지 않는다. 카드뉴스는 오래 남는데 자료는 지난 채용 기준이다.
  문항 수·시험 시간·배점·과락·배수 같은 시험 구성은 쓴다.
- [채용공고]가 함께 주어지면 이번 채용의 사실로 본다. 자료와 다르면(채용 단위, 전형 배수,
  시험 과목·배점·문항 수·시간, 평가 방식) **공고를 따른다.** 자료는 지난 채용 기준일 수 있다.
  공고에 없는 내용만 자료로 채우되, 공고의 채용 단위와 맞지 않는 자료 내용은 쓰지 않는다.
  배점처럼 채용 단위마다 다른 수치는 어느 단위 기준인지 밝힌다 (예: "상경계 기준").
  공고가 있어도 접수·시험 날짜와 채용 인원은 쓰지 않는다.
- 누가 말했는지, 어떤 자료인지 언급하지 않는다.
  "담당자", "인사팀", "설명회", "현직자", "합격자에 따르면", "직무백서" 같은 말은 쓰지 않는다.
- 자기소개서 클리닉은 언급하지 않는다.

■ 표기
- 카드에는 저절로 줄이 바뀌면 모양이 망가진다. 줄바꿈은 \\n 으로 직접 넣고 한 줄 글자 수(공백 포함)를 지켜라.
  표지 제목 2줄·한 줄 9자 / 표지 부제 20자 / 카드 제목 2줄·한 줄 11자 / intro lead 2줄·한 줄 18자
  facts 항목 7자, 내용 2줄·한 줄 8자 / 체크·단계 항목 2줄·한 줄 16자
  detail 머리 7자, 내용 2줄·한 줄 15자 / 결론(concl) 2줄·한 줄 12자 / outro 항목 1줄 16자
  영문·숫자·기호는 한글보다 좁으니 조금 더 써도 된다.
- *강조* 는 강조색 글자다. 카드마다 1~3곳, 핵심 수치나 키워드에만.
- ==밑줄== 은 형광 밑줄이다. 결론(concl)의 둘째 줄 전체에만 쓴다.
- 말투: 짧은 명사형 또는 합니다체. 과장·느낌표 남발 금지.

""" + """
■ 캡션(caption)
캡션의 서비스 안내(무료 체험, 모의고사 기능, 신청 방법)는 정해진 문구가 들어간다. 너는 아래 칸만 채운다.
- hook: 첫 줄 한 문장. 이 기업 필기를 준비하는 사람이 겪는 막막함을 자료에 근거해 짚는다.
  30자 안팎, 마침표로 끝낸다, 이모지 없음.
  예: "코트라 NCS, 기출이 없어 막막하셨다면." / "한전 필기, 한 영역만 무너져도 탈락입니다."
- short_name: 널리 쓰는 약칭 (코트라, 한전, 건보 등). 없으면 기업명 그대로.
- exam_areas: 자료에 나온 NCS 출제 영역을 · 로 잇는 짧은 한 줄. 예: "의사소통·수리·문제해결·자원관리·정보·조직이해"
  직군마다 다르면 대표 직군(보통 사무) 하나만 쓰고 끝에 괄호로 밝힌다. 예: "의사소통·수리·문제해결·자원관리·정보 (사무)"
  자료에 영역이 없으면 빈 문자열. 추측하지 않는다.
- exam_format: 자료에 나온 '문항 수'와 '시험 시간'만. 예: "6개 영역 각 20문항, 총 120문항 / 90분"
  둘 다 자료에 없으면 반드시 빈 문자열로 둔다. 과락·검사 종류 같은 다른 정보로 이 칸을 채우지 않는다.
  직군마다 다르면 대표 직군 하나만 쓰고 괄호로 밝힌다.
- hashtags: 9~12개. 기업명·약칭(영문 약칭 포함), 약칭+NCS, NCS·NCS모의고사·NCS무료,
  공기업취업·공기업준비·취업준비생, 무료체험 을 섞는다. '톰슨에듀AI' 는 자동으로 붙으니 넣지 않아도 된다.
"""

# 캡션 고정 틀. 체험 조건·서비스 안내가 바뀌면 여기만 고치세요.
# (모델이 서비스 조건을 새로 쓰면 없는 혜택을 약속할 수 있어 고정합니다)
TRIAL_DAYS = 5          # 무료 체험 기간 (2026-09-17 3일 → 5일)
CAPTION_TEMPLATE = """{hook}

{name} NCS 실전 모의고사를
{days}일 동안 무료로 풀어보실 수 있습니다.
결제 정보를 받지 않아 카드 등록 없이 회원가입만 하시면 됩니다.

[{short} NCS 실전모의고사]
{exam_lines}✔ 최근 기출 유형 반영, 실제 시험 형식 그대로
✔ 태블릿으로 실제 시험 환경 그대로 응시

[풀고 나면]
✔ 같은 모의고사를 푼 다른 응시자와 비교 분석
✔ 내 점수 위치와 시간을 뺏기는 영역 확인

[맞춤형 모의고사도 있습니다]
✔ 지원 기업 검색 → 기업 유형 맞춤 출제
✔ 원하는 영역만 선택, 영역당 문항수 조절

체험 이후에는 {short} 실전모의고사와
NCS 전체 사용권을 이용하실 수 있습니다.

신청은 tompsonai.com → 회원가입 → [{days}일 무료 체험하기]
{days}일 후 자동 종료되니 해지 신경 쓰실 일도 없습니다.

{hashtags}"""
FIXED_TAGS = ["톰슨에듀AI"]
TAGS_PER_LINE = 6

# 캡션만 새로 쓸 때의 지시문: 앞머리 몇 줄 + 위 SYSTEM 의 캡션 규칙을 그대로 씁니다
CAPTION_SYSTEM = """너는 공기업·금융권 취업 준비생을 위한 인스타그램 캡션 에디터다.
톰슨에듀AI(tompsonai.com — NCS·공기업 필기 학습 서비스) 계정에 {기업} 카드뉴스와 함께 올라간다.
제공된 자료에 있는 사실만 쓰고, 누가 말했는지·어떤 자료인지는 언급하지 않는다.
[채용공고]가 함께 주어지면 자료와 다른 부분(출제 영역·문항 수·시간 등)은 공고를 따른다.
채용 일정(날짜)과 채용 인원은 쓰지 않는다.

""" + "■ 캡션(caption)" + SYSTEM.split("■ 캡션(caption)", 1)[1]


# ── 채용공고 (선택) ──────────────────────────────────
# 붙여넣은 공고는 자료보다 우선합니다 (블로그 글 생성과 같은 원칙, 2026-09-15 결정).
# 인스타용으로 저장한 공고가 없으면 블로그 쪽에 저장해 둔 공고(drafts/_기업_공고.txt)를 씁니다.
def _posting_path(company: str) -> Path:
    return insta_cards.OUT_DIR / company / "posting.txt"


def load_posting(company: str) -> str:
    p = _posting_path(company)
    if p.exists():            # 비워서 저장했으면 '공고 없이'로 봅니다 (블로그 공고로 넘어가지 않음)
        return p.read_text(encoding="utf-8").strip()
    blog = config.DRAFTS_DIR / f"_{company}_공고.txt"
    return blog.read_text(encoding="utf-8").strip() if blog.exists() else ""


def save_posting(company: str, text: str) -> None:
    p = _posting_path(company)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip(), encoding="utf-8")


def _user_message(company: str, profile: dict, posting: str = "", extra: tuple = ()) -> str:
    parts = [f"기업명: {company}", md_loader.as_prompt_block(profile, "ncs")]
    if posting.strip():
        parts.append("[채용공고] — 이번 채용의 사실. 위 자료와 다르면 이 공고를 따른다\n" + posting.strip())
    return "\n\n".join([*parts, *extra])


def _fix_newlines(obj):
    """모델이 줄바꿈을 글자 그대로 '\\n' 으로 적는 경우가 있어 진짜 줄바꿈으로 바꿉니다."""
    if isinstance(obj, str):
        return obj.replace("\\n", "\n").strip()
    if isinstance(obj, list):
        return [_fix_newlines(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix_newlines(v) for k, v in obj.items()}
    return obj


def generate(company: str, profile: dict, feedback: str | None = None,
             previous: InstaDeckText | None = None, posting: str = "") -> InstaDeckText:
    """Claude 로 카드 문구·캡션을 씁니다. feedback 이 있으면 직전 생성본과 문제점을 함께 보냅니다."""
    extra = ()
    if feedback and previous:
        extra = ("[직전 생성본]\n" + previous.model_dump_json(indent=1),
                 "[직전 생성본의 문제점 — 반드시 고쳐라. 줄이 넘어간 문장은 더 짧게 쓰거나 "
                 "\\n 위치를 바꿔라. 문제없는 부분은 그대로 둬도 된다]\n" + feedback)
    client = generator._client()
    resp = generator._retry(lambda: client.messages.parse(
        model=config.GEN_MODEL,
        max_tokens=8000,
        system=SYSTEM.replace("{기업}", company),
        messages=[{"role": "user", "content": _user_message(company, profile, posting, extra)}],
        output_format=InstaDeckText,
    ))
    return InstaDeckText.model_validate(_fix_newlines(resp.parsed_output.model_dump()))


def to_deck(company: str, g: InstaDeckText) -> dict:
    return {"company": company, "cards": [
        {"type": "cover", "title": g.cover.title, "sub": g.cover.sub},
        {"type": "intro", "title": g.intro.title, "lead": g.intro.lead,
         "facts": [[p.k, p.v] for p in g.intro.facts], "concl": g.intro.concl},
        {"type": "checks", "title": g.exam.title, "items": g.exam.items, "concl": g.exam.concl},
        {"type": "rows", "title": g.detail.title,
         "rows": [[p.k, p.v] for p in g.detail.rows], "concl": g.detail.concl},
        {"type": "steps", "title": g.prep.title, "items": g.prep.items, "concl": g.prep.concl},
        *json.loads(json.dumps(FIXED_FEATURES, ensure_ascii=False)),
        dict(OUTRO, type="outro", items=g.outro_items),
    ]}


def compose_caption(c: CaptionText, company: str) -> str:
    """고정 틀에 기업별 칸을 채워 캡션을 완성합니다. 영역·문항 정보가 자료에 없으면 그 줄은 뺍니다."""
    exam_lines = "".join(f"✔ {x.strip()}\n" for x in (c.exam_areas, c.exam_format) if x.strip())
    tags = []
    for t in [*c.hashtags, *FIXED_TAGS]:
        t = re.sub(r"[\s#]+", "", t)
        if t and t not in tags:
            tags.append(t)
    lines = [" ".join(f"#{t}" for t in tags[i:i + TAGS_PER_LINE])
             for i in range(0, len(tags), TAGS_PER_LINE)]
    short = c.short_name.strip() or company
    return CAPTION_TEMPLATE.format(hook=c.hook.strip(), name=company, short=short, days=TRIAL_DAYS,
                                   exam_lines=exam_lines, hashtags="\n".join(lines))


def generate_caption(company: str, profile: dict, posting: str = "") -> CaptionText:
    """캡션 칸만 새로 씁니다 (카드 문구는 그대로). 카드보다 짧아 비용이 적게 듭니다."""
    client = generator._client()
    resp = generator._retry(lambda: client.messages.parse(
        model=config.GEN_MODEL,
        max_tokens=2000,
        system=CAPTION_SYSTEM.replace("{기업}", company),
        messages=[{"role": "user", "content": _user_message(company, profile, posting)}],
        output_format=CaptionText,
    ))
    return CaptionText.model_validate(_fix_newlines(resp.parsed_output.model_dump()))


def write_caption(company: str, log=print) -> str:
    """캡션만 새로 써서 저장합니다. 완성된 캡션을 돌려줍니다."""
    profile = md_loader.get_profile(company)
    if not profile:
        raise ValueError(f"'{company}' 공기업 분석 자료가 없습니다.")
    name = profile["company_key"]
    posting = load_posting(name)
    log(f"{name} 캡션 쓰는 중…" + (" (채용공고 함께)" if posting else ""))
    text = compose_caption(generate_caption(name, profile, posting), name)
    insta_publish.save_caption(name, text)
    log("캡션을 저장했습니다.")
    return text


def text_issues(g: InstaDeckText) -> list[str]:
    """그리기 전에 글자만 보고 잡을 수 있는 문제."""
    out = []
    counts = [("2번 카드 정보 칸", len(g.intro.facts), 4, 4), ("3번 카드 항목", len(g.exam.items), 3, 3),
              ("4번 카드 표", len(g.detail.rows), 2, 3), ("5번 카드 단계", len(g.prep.items), 3, 3),
              ("8번 카드 정리 항목", len(g.outro_items), 3, 3),
              ("해시태그", len(g.caption.hashtags), 5, 29)]
    for name, n, lo, hi in counts:
        if not lo <= n <= hi:
            want = f"{lo}개" if lo == hi else f"{lo}~{hi}개"
            out.append(f"{generator._josa(name, '이', '가')} {n}개입니다. {want}로 맞추세요")
    texts = json.dumps(g.model_dump(), ensure_ascii=False)
    for w in BANNED:
        if w in texts:
            out.append(f"'{w}' 는 쓰지 않습니다 (출처·화자 언급 또는 소개하지 않는 서비스)")
    if re.search(r"\d{1,2}월\s*\d{1,2}일|20\d\d\s*[./]\s*\d{1,2}\s*[./]", texts):
        out.append("채용 일정 날짜는 쓰지 않습니다 (지난 채용 기준이라 틀릴 수 있음)")
    if len(g.caption.hook) > 45:
        out.append(f"캡션 첫 줄이 {len(g.caption.hook)}자입니다. 30자 안팎으로 줄이세요")
    return out


def create(company: str, frame: str, color: str, new_caption: bool = True, log=print,
           posting_text: str | None = None) -> dict:
    """문구 쓰기 → 카드 그리기 → 검사 → (문제 있으면) 한 번 다시 쓰기. {"company", "issues"} 를 돌려줍니다.

    posting_text: 붙여넣은 채용공고. 주면 저장하고 씁니다 (빈 글자면 '공고 없이'로 저장).
                  None 이면 저장해 둔 공고를 씁니다.
    """
    profile = md_loader.get_profile(company)
    if not profile:
        raise ValueError(f"'{company}' 공기업 분석 자료가 없습니다.")
    name = profile["company_key"]
    if posting_text is not None:
        save_posting(name, posting_text)
    posting = load_posting(name)
    if posting:
        log(f"채용공고({len(posting):,}자)를 함께 씁니다 — 자료와 다르면 공고를 따릅니다.")
    if color == "brand" and not insta_cards.brand_color(name):
        log("기업 로고에서 색을 찾지 못해 기본색으로 만듭니다.")
        color = "base"

    old = insta_cards.OUT_DIR / name / "deck.json"
    if old.exists():
        shutil.copy2(old, old.with_name("deck_이전.json"))
        log("지금 문구는 deck_이전.json 으로 보관했습니다.")

    g, issues = None, []
    for attempt in range(1, MAX_TRIES + 1):
        log(f"① 자료로 카드 문구 쓰는 중… ({attempt}/{MAX_TRIES}번째, 1~2분)")
        g = generate(name, profile, "\n".join(f"- {i}" for i in issues) or None, g, posting)
        deck = to_deck(name, g)
        issues = text_issues(g)
        log("② 카드 그리고 검사하는 중…")
        _paths, layout = insta_cards.render_checked(deck, frame=frame, color=color)
        issues += layout
        if not issues:
            log("③ 검사 통과")
            break
        log("③ 확인할 점:\n" + "\n".join(f"   - {i}" for i in issues))

    if new_caption or not insta_publish.load_caption(name).strip():
        insta_publish.save_caption(name, compose_caption(g.caption, name))
        log("캡션과 해시태그를 저장했습니다.")
    else:
        log("캡션은 지금 것을 그대로 두었습니다.")
    if issues:
        log(f"\n남은 확인할 점 {len(issues)}건 — [카드 확인·발행] 탭에서 카드를 눌러 고치세요.")
    else:
        log("\n카드 8장을 만들었습니다.")
    return {"company": name, "issues": issues}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="인스타 카드뉴스 문구 생성 + 카드 만들기 (발행은 안 함)")
    ap.add_argument("company")
    ap.add_argument("--frame", default="white", choices=list(insta_cards.FRAMES))
    ap.add_argument("--color", default="base", choices=list(insta_cards.COLORS))
    args = ap.parse_args()
    create(args.company, args.frame, args.color)
