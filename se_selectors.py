# -*- coding: utf-8 -*-
"""네이버 스마트에디터 툴바 셀렉터 모음.

⚠ 네이버가 에디터 DOM을 바꾸면 여기만 고치면 됩니다.
   `python publisher.py --probe` 로 실제 툴바 버튼 목록을 덤프해
   아래 값과 대조하세요. (probe 결과는 drafts/_toolbar_probe.txt 에 저장)

각 항목은 '후보 리스트'이며 위에서부터 순서대로 시도합니다.
"""

# ── 본문/제목 영역 ───────────────────────────────────
TITLE_AREA = [
    ".se-section-documentTitle .se-text-paragraph",
    ".se-documentTitle .se-text-paragraph",
]
BODY_AREA = [
    ".se-component.se-text .se-text-paragraph",
]

# ── 글자 크기 (검증됨) ───────────────────────────────
FONT_SIZE_BUTTON = [
    ".se-font-size-code-toolbar-button",
    "button.se-toolbar-button[data-name='font-size-code']",
]
FONT_SIZE_OPTION = 'button[data-value="{size}"]'

# ── 글자 색 ──────────────────────────────────────────
FONT_COLOR_BUTTON = [".se-font-color-toolbar-button"]

# 글자색 팔레트만 노리도록 컨테이너로 감쌉니다.
# (감싸지 않으면 바로 옆 '배경색' 팔레트를 눌러버립니다)
_FC = '.se-property-color-picker-container[data-name="font-color"] '

# 스와치는 style="background-color: rgb(r, g, b);" 형태
FONT_COLOR_SWATCH = [
    _FC + 'button.se-color-palette[style*="{rgb}"]',
    'button.se-color-palette[style*="{rgb}"]',
]
# 기본 팔레트에 없는 색 → '더보기'로 사용자 지정 hex 입력
FONT_COLOR_MORE = [_FC + ".se-color-picker-more-button", ".se-color-picker-more-button"]
FONT_COLOR_INPUT = [_FC + "input.se-selected-color-hex", "input.se-selected-color-hex"]
FONT_COLOR_APPLY = [_FC + ".se-color-picker-apply-button", ".se-color-picker-apply-button"]

# 기본 팔레트 66색 (probe 덤프 그대로).
# ⚠ #4a90e2 는 여기 없습니다. 사용자 지정이 실패하면 이 중 가장 가까운 색으로 대체합니다.
# '더보기' 입력이 실패했을 때 쓸 지정 대체색.
# 단순 RGB 거리로는 #5bc7ff(하늘색)가 뽑히는데 글자색으로는 너무 흐려서,
# 가독성이 나은 #0095e9 를 명시적으로 지정합니다.
PALETTE_FALLBACK = {"#4a90e2": "#0095e9"}

PALETTE_COLORS = [
    "#999999", "#ffcdc0", "#ffe3c8", "#fff8b2", "#e3fdc8", "#c2f4db",
    "#bdfbfa", "#b0f1ff", "#9bdfff", "#fdd5f5", "#ffb7de", "#ffffff",
    "#777777", "#ffad98", "#ffd1a4", "#fff593", "#badf98", "#3fcc9c",
    "#15d0ca", "#28e1ff", "#5bc7ff", "#cd8bc0", "#ff97c1", "#f7f7f7",
    "#555555", "#ff5f45", "#ffa94f", "#ffef34", "#98d36c", "#00b976",
    "#00bfb5", "#00cdff", "#0095e9", "#bc61ab", "#ff65a8", "#e2e2e2",
    "#333333", "#ff0010", "#ff9300", "#ffd300", "#54b800", "#00a84b",
    "#009d91", "#00b3f2", "#0078cb", "#aa1f91", "#ff008c", "#c2c2c2",
    "#141414", "#ba0000", "#b85c00", "#ac9a00", "#36851e", "#007433",
    "#00756a", "#007aa6", "#004e82", "#740060", "#bb005c", "#9c9c9c",
    "#000000", "#700001", "#823f00", "#6a5f00", "#245b12", "#004e22",
    "#00554c", "#004e6a", "#003960", "#4f0041", "#830041",
]

# ── 글자 배경색(형광펜) ──────────────────────────────
# probe 확인: 글자색과 같은 구조이고 컨테이너의 data-name 만 다릅니다.
_BC = '.se-property-color-picker-container[data-name="background-color"] '
BG_COLOR_BUTTON = [".se-background-color-toolbar-button"]
BG_COLOR_SWATCH = [
    _BC + 'button.se-color-palette[style*="{rgb}"]',
]
BG_COLOR_MORE = [_BC + ".se-color-picker-more-button"]
BG_COLOR_INPUT = [_BC + "input.se-selected-color-hex"]
BG_COLOR_APPLY = [_BC + ".se-color-picker-apply-button"]

# ── 글자 꾸밈 (probe 확인 2026-08-20) ────────────────
# 굵게는 Ctrl+B 로 이미 쓰고 있습니다. 나머지는 툴바 버튼을 씁니다.
# (기울임·밑줄은 Ctrl+I / Ctrl+U 도 먹지만, 버튼이 더 확실합니다)
UNDERLINE_BUTTON = [".se-underline-toolbar-button"]
ITALIC_BUTTON = [".se-italic-toolbar-button"]
STRIKE_BUTTON = [".se-strikethrough-toolbar-button"]

# ── 링크 (probe 확인 2026-08-20) ─────────────────────
# '링크' 버튼 → 주소 입력 레이어. 입력칸과 확인 버튼 모두 실물 대조 완료.
LINK_BUTTON = [".se-link-toolbar-button"]
LINK_INPUT = [
    "input.se-custom-layer-link-input",
    "input[placeholder*='URL']",
]
LINK_APPLY = [
    "button.se-custom-layer-link-apply-button",
]

# ── 표 (probe 확인 2026-08-20) ───────────────────────
# ⚠ 크기를 고르는 격자는 없습니다. 버튼을 누르면 곧바로 3행 3열 표가 들어갑니다.
#    그보다 크게 하려면 표 위에 뜨는 '행/열 추가' 버튼을 눌러 늘려야 합니다.
#    Tab 으로는 행이 늘어나지 않습니다(실측 확인).
TABLE_BUTTON = [".se-table-toolbar-button"]
TABLE_DEFAULT_ROWS = 3
TABLE_DEFAULT_COLS = 3
TABLE_ROWS = "table.se-table-content tr"
# aria-label 이 "2행 다음에 행 추가" / "2열 다음에 열 추가" 형태입니다.
TABLE_ADD_ROW = ".se-cell-add-button[aria-label*='{n}행 다음']"
TABLE_ADD_COL = ".se-cell-add-button[aria-label*='{n}열 다음']"
TABLE_FIRST_CELL = "table.se-table-content tr:first-child td:first-child"

# ── 정렬 ─────────────────────────────────────────────
# 실측: 사장님 블로그 본문 문단은 가운데 530 / 왼쪽 76 / 양쪽 28 → 가운데가 기본
# probe 확인: 정렬은 드롭다운. 트리거 class 에 현재 정렬 상태가 들어갑니다
# (예: 왼쪽 정렬 상태면 se-align-left-toolbar-button).
ALIGN_BUTTON = [
    "button[data-name='align-drop-down-with-justify']",
    ".se-property-toolbar-drop-down-button[class*='se-align-']",
    ".se-align-left-toolbar-button",
    ".se-align-center-toolbar-button",
]
# probe 확정: data-value 가 left / center / right / justify
ALIGN_OPTION = [
    ".se-toolbar-option-align-{align}-button",
    "button[data-name='align-drop-down-with-justify'][data-value='{align}']",
]
# 툴바를 못 찾을 때 쓰는 단축키 후보
ALIGN_SHORTCUT = {"center": ["Control+Shift+E", "Control+e"],
                  "left": ["Control+Shift+L"]}

# ── 구분선 ───────────────────────────────────────────
# probe 확인(2026-08-04): '구분선 추가' 버튼이 곧바로 기본 구분선을 넣습니다.
# 실측: 블로그 구분선 32개가 se-l-default, 6개만 se-l-line1 → 기본값이 맞습니다.
HR_BUTTON = [
    ".se-insert-horizontal-line-default-toolbar-button",
    "button[data-name='horizontal-line'][data-value='default']",
    ".se-insert-menu-button-horizontalLine",
]
HR_OPTION = [                       # 스타일을 바꾸고 싶을 때만 (기본값이면 불필요)
    ".se-insert-menu-sub-panel-button-horizontalLine-default",
]

# ── 인용구 ───────────────────────────────────────────
# probe 확인: '인용구 추가' 버튼이 기본 인용구를 넣습니다. 실측도 se-l-default.
QUOTE_BUTTON = [
    ".se-insert-quotation-default-toolbar-button",
    "button[data-name='quotation'][data-value='default']",
    ".se-insert-menu-button-quotation",
]
QUOTE_OPTION = [                    # 다른 스타일을 쓰고 싶을 때만
    ".se-insert-menu-sub-panel-button-quotation-default",
]

# ── 이미지 (검증됨) ──────────────────────────────────
IMAGE_BUTTON = [
    ".se-image-toolbar-button",
    "button.se-toolbar-button[data-name='image']",
]

# 사진을 2장 이상 한 번에 올리면 '사진 첨부 방식' 팝업이 뜹니다.
#   개별사진 = 세로로 하나씩 / 콜라주 = 한 줄에 나란히 / 슬라이드 = 넘겨보기
# 실측: 사장님 블로그의 여러 장 묶음은 se-imageStrip → '콜라주'
IMAGE_LAYOUT_DIALOG = [
    ".se-popup-container",
    "[class*='se-popup']",
]
IMAGE_LAYOUT_OPTION = [
    "button:has-text('{name}')",
    "[class*='se-popup'] :text-is('{name}')",
    ":text-is('{name}')",
]

# ── 발행 / 예약 발행 (probe 2026-08-06) ──────────────
# ⚠ 네이버 클래스명은 publish_btn__m9KHH 처럼 해시가 붙어 배포마다 바뀝니다.
#   그래서 [class*=...] 부분매칭과 name/value 같은 의미 속성을 우선 씁니다.
PUBLISH_OPEN = [                       # 우측 상단 [발행] — 설정 패널을 엽니다
    "[class*='publish_btn']",
    "button.publish_btn__m9KHH",
]
PUBLISH_NOW_RADIO = ["input[name='radio_time'][value='now']"]
PUBLISH_SCHEDULE_RADIO = [             # '예약' 라디오 (확정됨)
    "input[name='radio_time'][value='pre']",
    "[class*='radio_item'][value='pre']",
]
PUBLISH_CONFIRM = [                    # 패널 안의 최종 [발행] (확정됨)
    "[class*='confirm_btn']",
    "button.confirm_btn__WEaBq",
]
# 공개 설정: 2=전체공개 1=이웃 3=서로이웃 0=비공개
PUBLISH_OPEN_TYPE = "input[name='open_type'][value='{v}']"

# 카테고리 선택. 드롭다운을 연 뒤 이름으로 고릅니다.
CATEGORY_BUTTON = [
    "[class*='selectbox_button']",
    "button.selectbox_button__jb1Dt",
]
# probe-publish 확인: 드롭다운 항목은 라디오 input 이고 이름이 속성에 안 담깁니다.
# 그래서 화면에 보이는 '글자'로 찾습니다. (현재 config.CATEGORY 가 비어 있어
#  기본 카테고리를 그대로 쓰는 중 — 이 경로는 카테고리를 지정할 때만 탑니다)
CATEGORY_OPTION = [
    "[class*='option_list'] :text-is('{name}')",
    "[class*='selectbox'] li:has-text('{name}')",
    "label:text-is('{name}')",
    ":text-is('{name}')",
]

# 날짜·시·분 (probe-publish 확인 2026-08-24. '예약'을 눌러야 나타납니다)
#   ⚠ 날짜 input 은 readonly 라 값을 써넣을 수 없습니다.
#      클릭하면 jQuery UI 달력이 뜨고, 거기서 날짜를 눌러야 합니다.
#   시는 00~23, 분은 10분 단위(00/10/20/30/40/50) select 입니다
PUBLISH_DATE_INPUT = [
    "input[class*='input_date']",
    "[class*='date__'] input",
]
PUBLISH_DATE_FORMAT = "%Y. %m. %d"          # 입력칸에 표시되는 형식 (검증용)

# jQuery UI 달력 (표준 구조)
DATEPICKER = "[class*='ui-datepicker']"
DATEPICKER_YEAR = ".ui-datepicker-year"
DATEPICKER_MONTH = ".ui-datepicker-month"
DATEPICKER_NEXT = "button.ui-datepicker-next"
DATEPICKER_PREV = "button.ui-datepicker-prev"
# 날짜 칸 — 비활성(ui-state-disabled)은 지난 날짜라 고를 수 없습니다
DATEPICKER_DAY = ("[class*='ui-datepicker'] td:not(.ui-state-disabled) "
                  "a:text-is('{day}')")
PUBLISH_HOUR_SELECT = [
    "select[class*='hour_option']",
    "[class*='hour__'] select",
]
PUBLISH_MIN_SELECT = [
    "select[class*='minute_option']",
    "[class*='minute__'] select",
]

# ── 팝업 ─────────────────────────────────────────────
POPUP_CANCEL = [".se-popup-button-cancel"]
POPUP_CLOSE_LABELS = ["닫기", "확인하지 않음", "나중에 할게요"]
