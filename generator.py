# -*- coding: utf-8 -*-
"""블로그 글 생성 (v2 — 채용설명회·직무백서 원문 기반).

md_loader 가 주는 자료(서류·자소서·필기·면접·인턴 전체)만으로 생성합니다.
기업 소개·인재상·최근 이슈까지 원문에 이미 있어서 웹 검색이 필요 없습니다.
(구버전은 JSON에 시험 내용만 있어 기업 소개를 웹 검색으로 채웠습니다.)
"""
from __future__ import annotations
import time

import anthropic
from pydantic import BaseModel, Field

import config
import md_loader
import personas
import topics


def _retry(fn, tries: int = 5, base: float = 4.0):
    """API 과부하(529)·서버오류(5xx) 시 점점 늘려가며 재시도."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except (anthropic.OverloadedError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as e:
            last = e
            wait = min(base * (2 ** i), 60)
            print(f"  ⏳ API 혼잡/오류, {wait:.0f}초 후 재시도 ({i + 1}/{tries})…")
            time.sleep(wait)
    raise last


def _client() -> anthropic.Anthropic:
    key = config.ANTHROPIC_API_KEY or None
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


# ── 출력 스키마 ──────────────────────────────────────
class ProcedureStage(BaseModel):
    stage: str = Field(description="전형 단계명 (예: 서류전형, 필기전형, PT면접)")
    note: str = Field(description="배수·구성 등 핵심 정보. 공백 포함 22자 이내")


class PrepTip(BaseModel):
    item: str = Field(description="준비 포인트 (예: 서류 커트라인)")
    tip: str = Field(description="한 줄 팁. 공백 포함 25자 이내")


class BlogPost(BaseModel):
    title: str = Field(description="제목. '기업명 연도 키워드｜서브키워드' 형식, 전각 ｜ 사용, 35~55자")
    body: str = Field(description="본문 전체. 지정된 [[H]]/[[HR]]/[[IMG:]]/[[QUOTE]] 문법 사용")
    hashtags: list[str] = Field(description="해시태그 4~6개 (# 없이 키워드만)")
    procedure_table: list[ProcedureStage] = Field(
        description="전형 절차표 이미지에 넣을 3~6행. 서류→필기→면접 순서 그대로"
    )
    prep_table: list[PrepTip] = Field(
        description="준비 체크리스트 이미지에 넣을 3~5행. 본문 5) 섹션 내용과 일치"
    )


# ── 시스템 프롬프트 ──────────────────────────────────
GEN_SYSTEM = """너는 '톰슨에듀학원' 네이버 블로그를 운영하는 공기업·금융권 취업 전문 블로거다.
실제 채용설명회·직무백서 원문 자료를 받아, 수험생이 모바일에서 술술 읽는 블로그 글을 쓴다.

{PERSONA_BLOCK}

■ 사용할 수 있는 표기 (이 외에는 쓰지 마라)
줄 맨 앞에 단독으로:
  [[H]] 1) 소제목 📌      … 소제목. '숫자)' + 내용 + 끝에 이모지 1개
  [[HR]]                  … 구분선
  [[IMG:이름]]            … 이미지 한 장
  [[IMGS:이름1|이름2]]    … 이미지 여러 장을 한 줄에 나란히
  [[QUOTE]] 문구          … 인상적인 실제 인용구 한 문장
문장 안에서:
  **텍스트**              … 굵게. 글 전체 6~10회
  <blue>텍스트</blue>     … 파란 글씨. 글 전체 최대 5회 (핵심 숫자·조건에만)
  <red>텍스트</red>       … 빨간 글씨. 글 전체 최대 3회 (진짜 주의사항에만)

마크다운 헤더(#), 리스트(-, 1.), 표는 절대 쓰지 마라.

■ 이모지 규칙
소제목 끝 이모지는 아래 목록에서만 고른다. (다른 이모지는 에디터에서 깨진다)
  🏢 📌 🎯 🚀 🌱 📅 🔍 💡 📊 ⭐ 📋
변형 선택자가 붙는 이모지(✍️ ⚠️ ❗️ 등)는 절대 쓰지 마라.

{TOPIC_BLOCK}

■ 마무리 블록 (모든 글에서 아래 형태를 반드시 지킨다)
마지막 섹션(마무리 🌱)은 이 순서로 끝낸다.
글의 흐름은 "이 기업 준비는 이렇더라 → 그럼 어디서 어떻게 준비하지?
→ 톰슨AI에 그게 다 있다" 로 자연스럽게 이어져야 한다.
광고 문구를 나열하지 말고, **앞에서 설명한 이 글의 주제와 연결해서** 설득해라.
(예: 서류 글이면 "점수는 채웠는데 그다음은?"에서 이어가고,
     면접 글이면 "질문은 알겠는데 답을 어떻게 만들지?"에서 이어간다)

  ① 이 글 주제({TOPIC_NAME}) 준비의 핵심을 한 줄로 정리 (1~2줄)
     그리고 "혼자 준비하기 막막하다"는 공감 한 줄로 자연스럽게 넘어가라

  ※ 말투 — 만든 사람이 아니라 권해주는 사람으로 써라
     "그래서 톰슨AI를 만들었습니다", "저희가 준비했습니다", "제가 개발한" 처럼
     내가 만든 서비스를 소개하는 투는 절대 쓰지 마라. 광고로 읽힌다.
     대신 읽는 사람이 골라서 쓰도록 권하는 투로 써라.
       좋은 예: "이럴 때 톰슨AI를 한번 써보세요"
                "저는 톰슨AI로 이 부분을 해결했어요"
                "톰슨AI에서 이런 걸 지원하니 참고해 보세요"
                "여기서 {기업명} 유형만 골라 풀어볼 수 있어요"
     주어를 '나/우리'가 아니라 '여러분(독자)'과 '기능' 쪽에 두는 것이 핵심이다.

{CTA_BLOCK}

  ③ 들어와서 직접 해보라는 유도 문구 1~2줄
  ④ 본문의 마지막 줄은 정확히 "👉 https://tompsonai.com"
     (마무리 블록의 이미지 줄들은 위 ②에서 이미 들어갔으므로, 링크 뒤에는 아무것도 붙이지 않는다)

■ 분량 배분
- 본문 전체 1,700~2,700자.
- 핵심 섹션(위 구조에서 ★ 표시)이 본문의 40% 이상을 차지해야 한다.
- 곁가지 섹션은 짧게 끝내라. 자료가 얇은 곳을 억지로 늘리지 마라.

■ 내용 원칙
- 제공된 자료의 내용만 사용한다. 없는 정보는 지어내지 않는다.
- 원문은 구어체 설명 자료다. 그대로 옮기지 말고 존댓말 블로그 말투로 다시 써라.
  단, 실제 인용문·면접 질문 원문은 정확하게 살려라.
- **누가 설명했는지, 어떤 자료 기반인지는 절대 언급하지 마라.**
  "OOO 차장이 밝혔다", "담당자가 설명했다", "직무백서에 따르면",
  "채용설명회에서 공개된" 같은 출처·화자 언급을 전부 빼라.
  공개된 정보이니 그 내용 자체만 담백하게 사실처럼 전달해라.
- 수치(배수, 배점, 커트라인, 날짜 등)는 원문에 있는 것만 쓰고, 추측해서 채우지 마라.
- 원문 속 "자막 인식 오류로 추정된다" 류의 편집 메모는 절대 본문에 넣지 마라.
- 채용 일정·모집인원은 [채용공고]가 함께 제공됐을 때만 구체 수치를 쓴다.
  제공되지 않았으면 0) 섹션 자체를 만들지 말고, 본문에서도 날짜를 추측해 쓰지 마라.
- 마지막 섹션(마무리)은 위 ■마무리 블록 규칙을 그대로 따른다.

■ 제목
{기업명} {연도} {핵심키워드}｜{서브키워드 나열} 형식. 구분자는 전각 ｜ 를 쓴다.
35~55자. ｜ 뒤에는 검색 키워드를 · 로 나열한다.
이 글의 주제({TOPIC_NAME})가 제목에서 바로 드러나야 한다.
**연도는 반드시 {THIS_YEAR}년이다.** 자료 원문에 지난 연도가 적혀 있어도
제목에는 {THIS_YEAR}을 쓴다. 지난 연도가 제목에 박히면 낡은 글로 보여
검색에서 밀리고, 읽는 사람도 지난 채용 정보로 오해한다.

■ 표로 뺄 내용 (본문에 중복해서 쓰지 마라)
아래 두 필드는 표 이미지로 렌더링된다. 본문과 어긋나면 안 되고, 본문에 같은 내용을
다시 나열하지도 마라.
- procedure_table : 전형 단계 3~6개. 단계명 + 핵심 정보 22자 이내.
- prep_table      : 준비 포인트 3~5개. 항목 + 한 줄 팁 25자 이내.
                    이 글의 주제({TOPIC_NAME})에 맞는 포인트를 담아라."""


def _josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무에 맞는 조사를 붙입니다. ('자기소개서을(를)' 같은 표기를 피하려고)"""
    if not word:
        return word
    ch = word[-1]
    if "가" <= ch <= "힣":
        has_final = (ord(ch) - 0xAC00) % 28 != 0
    else:
        has_final = ch.isdigit() or ch.isalpha()   # 영문·숫자는 대충 받침 있음으로 처리
    return word + (with_final if has_final else without_final)


def _topic_block(topic_key: str, company: str,
                 persona_key: str | None = None) -> str:
    """주제에 맞는 '이 글의 목표 + 글 구조' 대목을 만듭니다."""
    t = topics.get(topic_key)
    pers = personas.get(persona_key)
    focus = t["focus"]
    lines = [
        f"■ 이 글의 목표 — {_josa(focus, '이', '가')} 주인공이다",
        f"이 글은 {company}의 {_josa(focus, '을', '를')} 다루는 글이다.",
        "독자가 다 읽고 나면 '이건 이렇게 준비하면 되겠구나'를 알게 되고,",
        "그래서 톰슨AI에서 이어서 준비해보고 싶어지게 만드는 것이 목적이다.",
        f"   {t['guide']}",
        "",
        "■ 글 구조 (이 순서 그대로, 6개 섹션)",
        (f'"{pers["hello"]}" 로 시작 → 도입 3~4줄' if pers["hello"]
         else "인사말 없이 곧바로 도입 2~3줄 (이 스타일은 인사말을 쓰지 않는다)"),
        f"   도입에서 이 글이 {company}의 {t['focus']}에 대한 글이라는 걸 분명히 밝혀라",
        f"[[IMG:{company}_대표]] → [[HR]]",
        f"0) {company} 채용 일정 정리 📅   ← [채용공고]가 제공됐을 때만. "
        "없으면 이 섹션을 아예 만들지 마라",
    ]

    core = set(t["core_idx"])
    for i, (title, hint) in enumerate(t["outline"]):
        star = " ★핵심" if i in core else ""
        head = f"{i + 1}) {title}{star}"
        lines.append(f"{head:<28}… {hint}" if hint else head)
        if i == 1:
            lines.append(f"   뒤에 [[IMG:{company}_전형절차]] → [[HR]]"
                         if pers["use_tables"] else "   뒤에 [[HR]]")
        elif i == len(t["outline"]) - 2:
            lines.append(f"   뒤에 [[IMG:{company}_준비체크리스트]] → [[HR]]"
                         if pers["use_tables"] else "   뒤에 [[HR]]")
        elif i < len(t["outline"]) - 1:
            lines.append("   뒤에 [[HR]]")

    lines += [
        "",
        "소제목 끝에는 허용된 이모지 중 내용에 맞는 것을 하나씩 붙여라.",
        "각 섹션은 [[H]] → 본문 → (해당되면 [[IMG:…]]) → [[HR]] 순서.",
        "마지막 섹션 뒤에는 [[HR]]을 넣지 않는다.",
        "위 목록에 있는 섹션만 쓴다. 임의로 추가하지 마라.",
        "원문에 인상적인 실제 인용문이 있으면 알맞은 섹션 끝에 [[QUOTE]] 로 한 번 인용해라.",
    ]
    return "\n".join(lines)


# 기능별 소개 문구 — 무엇을 강조할지. 이미지 줄은 config 에서 가져옵니다.
_FEATURE_PITCH = {
    "analysis": [
        "<blue>119개 공기업</blue>의 준비가이드가 기업별로 정리돼 있다",
        "각 기업 홈페이지 소개, 채용설명회에서 나온 이야기, 기출문제를 함께 분석해 만든 것이다",
        "'채용과정 소개'와 '필기분석 가이드' 두 편으로 나뉘고, 기업당 **32쪽이 넘는** 분량이다",
        "무료 회원이면 전부 열람할 수 있다",
        "인쇄해서 몇 번 읽어두면 필기뿐 아니라 나중에 면접 준비에도 도움이 된다",
        "→ 위 항목을 다 나열하지 말고, 이 글 주제와 맞는 두세 가지만 골라 자연스럽게 써라",
    ],
    "mock": [
        "**{기업명} 출제 유형 그대로** 실전처럼 풀어볼 수 있다",
        "실제 시험과 같은 구성이라 시간 감각까지 맞춰볼 수 있다는 점을 강조해라",
    ],
    "theory": [
        "의사소통·수리·문제해결 같은 영역을 유형별로 나눠 이론부터 잡아준다",
        "어느 영역이 약한지 모르겠다면 여기서부터 시작하면 된다고 연결해라",
    ],
    "aiquiz": [
        "틀린 문제를 분석해 **약한 유형만 골라** 다시 풀게 해준다",
        "무작정 많이 푸는 게 아니라 약점만 집중 공략한다는 점을 강조해라",
    ],
    "clinic": [
        "자소서 초안을 넣으면 **스토리텔링 방식으로 코칭과 수정**을 해준다",
        "고쳐준 글만 주는 게 아니라, 초안의 어디가 부족한지 항목별로 짚어준다",
        "**무료**로 받아볼 수 있다는 점을 꼭 밝혀라",
        "어떤 기업만 된다는 식의 제한은 언급하지 마라",
        "",
        "   ※ 왜 자소서가 중요한지 근거를 한 줄이라도 붙여라. 예:",
        "     · 서류를 계량 평가하는 곳에서는 자소서에도 점수가 매겨져 총점에 합산된다",
        "     · 그래서 학점·어학이 조금 부족해도 자소서로 상쇄되는 경우가 있고,",
        "       반대로 스펙이 좋은데 자소서에서 밀려 탈락하기도 한다",
        "   ※ 스토리텔링이 뭔지 궁금하게만 만들고, 원칙을 다 나열하지는 마라.",
        "     굳이 넣는다면 '1인칭으로 그때의 고민까지 드러내기' 정도 한 가지만.",
    ],
}


def _cta_block(topic_key: str) -> str:
    """그 글에 넣을 톰슨AI 기능 소개 대목을 만듭니다.

    ■ 왜 2개만 넣는가
    기능 5개를 매 글에 다 넣으면 마무리가 본문의 20%를 차지하고, 이미지 9장이
    모든 글에 똑같은 순서로 들어갑니다. 실측해보니 그 상태에서 글끼리 마무리
    유사도가 70%였습니다. 177편을 그렇게 쓰면 유사문서로 묶일 위험이 큽니다.
    그래서 주제마다 어울리는 2개만 골라 넣습니다(topics.py 의 cta).
    """
    t = topics.get(topic_key)
    keys = t.get("cta") or ["analysis", "mock"]
    lines = [
        f"  ② 톰슨AI의 기능 **두 가지만** 아래 순서대로, 각각 2~4줄씩 소개한다.",
        "     각 기능 소개 뒤에는 지정된 이미지 줄을 그대로 넣어라 (변형 금지).",
        "     여기 없는 다른 기능은 언급하지 마라.",
        "",
    ]
    for i, key in enumerate(keys, 1):
        label, imgs = config.TOMPSONAI_FEATURES[key]
        img_line = (f"[[IMGS:{'|'.join(imgs)}]]" if len(imgs) > 1
                    else f"[[IMG:{imgs[0]}]]")
        lines.append(f"     [{i}] {label}")
        for pitch in _FEATURE_PITCH[key]:
            lines.append(f"       - {pitch}")
        lines.append(f"       - 소개 뒤 이미지 줄:  {img_line}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_system(topic_key: str, company: str,
                 persona_key: str | None = None) -> str:
    """주제와 스타일에 맞춰 완성된 시스템 프롬프트."""
    import datetime as _dt

    t = topics.get(topic_key)
    bridge = t.get("bridge", "")
    body = GEN_SYSTEM.replace("{THIS_YEAR}", str(_dt.date.today().year))
    body = body.replace("{PERSONA_BLOCK}", personas.get(persona_key)["prompt"])
    body = body.replace("{TOPIC_BLOCK}",
                        _topic_block(topic_key, company, persona_key))
    body = body.replace("{CTA_BLOCK}", _cta_block(topic_key))
    if bridge:
        body = body.replace(
            '     그리고 "혼자 준비하기 막막하다"는 공감 한 줄로 자연스럽게 넘어가라',
            f'     그리고 아래 취지의 한 줄로 자연스럽게 다음 대목으로 넘어가라.\n'
            f'       "{bridge}"\n'
            f'     (똑같이 베끼지 말고 이 뜻을 살려 네 문장으로 써라)')
    return body.replace("{TOPIC_NAME}", t["name"])


def generate_post(
    company: str,
    profile: dict,
    posting_text: str | None = None,
    feedback: str | None = None,
    topic: str = topics.ALL_KEY,
    persona: str | None = None,
) -> BlogPost:
    client = _client()
    parts = [
        f"기업명: {company}",
        md_loader.as_prompt_block(profile, topic),
    ]
    if posting_text:
        parts.append(f"[채용공고]\n{posting_text}")
    else:
        parts.append("[채용공고]\n(제공되지 않음 — 0) 채용 일정 섹션을 만들지 마라)")
    if feedback:
        parts.append(f"[직전 생성본의 문제점 — 반드시 고쳐라]\n{feedback}")

    resp = _retry(lambda: client.messages.parse(
        model=config.GEN_MODEL,
        max_tokens=16000,   # md 원문이 길 때(예: IBK 924줄) 12000이면 JSON이 잘려 파싱 실패함
        system=build_system(topic, company, persona),
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        output_format=BlogPost,
    ))
    return resp.parsed_output


# ── 통합 파이프라인 ──────────────────────────────────
def build_post(company: str, posting_text: str | None = None,
               topic: str = topics.ALL_KEY, persona: str | None = None,
               **_ignored) -> tuple[BlogPost, dict]:
    """_ignored: 구버전 skip_research 등 호환용. 이제 검색 단계 자체가 없습니다."""
    profile = md_loader.get_profile(company)
    if profile is None:
        raise SystemExit(
            f"❌ '{company}' 자료가 없습니다.\n"
            f"   보유 기업 {len(md_loader.list_companies())}개. "
            f"main.py --list 로 확인하세요."
        )
    print(f"  ② 블로그 본문 생성 중… "
          f"(주제: {topics.name(topic)} · {personas.name(persona)})")
    post = generate_post(profile["company_key"], profile, posting_text,
                         topic=topic, persona=persona)
    return post, profile
