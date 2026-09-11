# -*- coding: utf-8 -*-
"""톰슨에듀 자동 포스팅 파이프라인 — 데스크톱 GUI.

탭 구성:
  1) 글 생성      — 기업 선택 → 생성 → 실시간 로그 → 이미지 미리보기 → 검증 결과
  2) 발행         — 최신 초안을 네이버 에디터에 자동 입력 (발행 버튼은 직접 클릭)
  3) 대기열       — 67개 기업 진행 현황, 완료 표시/취소, 최근 자동발행 로그
  4) 미리보기/수정 — 초안 원문을 GUI 안에서 직접 읽고 고쳐서 저장
  5) 설정         — 모델·예약 시간대·카테고리를 코드 수정 없이 변경

실행:
  venv\\Scripts\\python.exe run_app.py
"""
from __future__ import annotations
import html
import importlib
import json
import re
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTime, QUrl
from PySide6.QtGui import QPixmap, QFont, QColor
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QPlainTextEdit, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
    QScrollArea, QSplitter, QGroupBox, QProgressBar, QLineEdit, QTimeEdit,
    QFormLayout, QGridLayout, QInputDialog, QFileDialog, QDialog, QLayout,
)

import accounts
import config
import image_gen
import md_loader
import personas
import post_queue
import topics


def _login_account(blog_id: str) -> bool:
    """그 계정 전용 프로필로 네이버 로그인 창을 띄우고, 사람이 닫을 때까지 기다립니다.

    자동으로 아이디·비밀번호를 넣지 않습니다. 계정 정보를 프로그램이 다루지 않는 편이
    안전하고, 네이버도 자동 로그인 시도를 차단합니다.
    """
    from playwright.sync_api import sync_playwright
    import browser_util

    config.set_account(blog_id)
    print(f"'{blog_id}' 계정 로그인 창을 엽니다…")
    print("창에서 직접 로그인한 뒤, 로그인이 끝나면 창을 닫아주세요.\n")
    with sync_playwright() as p:
        ctx = browser_util.open_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(config.LOGIN_URL)
        # 사람이 창을 닫을 때까지 대기
        closed = {"v": False}
        ctx.on("close", lambda *_: closed.update(v=True))
        while not closed["v"]:
            try:
                page.wait_for_timeout(500)
            except Exception:
                break
    print("로그인 창이 닫혔습니다.")
    return True


def _company_from_draft_path(path: str) -> str:
    """drafts/{기업명}[_{주제}]_{YYYY-MM-DD}.md 에서 기업명만 뽑아냅니다.

    파일명에 주제를 넣기 시작하면서 날짜만 떼면 '금융결제원_NCS' 처럼
    주제가 기업명에 붙어버렸습니다. 알려진 주제 꼬리표도 함께 뗍니다.
    """
    stem = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", Path(path).stem)
    shorts = [re.sub(r"[^\w가-힣]+", "_", topics.get(k)["short"]).strip("_")
              for k in list(topics.TOPICS) + [topics.ALL_KEY]]
    for s in shorts:
        if s and stem.endswith("_" + s):
            return stem[: -(len(s) + 1)]
    return stem


# ───────────────────────── 공용: stdout 를 시그널로 전달 ─────────────────────────
class _StreamRedirect:
    """print() 출력을 Qt 시그널로 흘려보내는 파일 유사 객체."""

    def __init__(self, emit_fn):
        self._emit = emit_fn

    def write(self, text: str) -> int:
        if text:
            self._emit(text)
        return len(text)

    def flush(self) -> None:
        pass


class _Worker(QObject):
    """백그라운드 스레드에서 함수를 실행하고 로그·결과·에러를 시그널로 돌려줍니다."""
    log = Signal(str)
    finished = Signal(object)      # 성공 시 결과 객체
    failed = Signal(str)           # 실패 시 traceback 문자열

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = _StreamRedirect(self.log.emit)
        sys.stderr = _StreamRedirect(self.log.emit)
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            sys.stdout, sys.stderr = old_out, old_err


def run_in_thread(parent: QObject, fn, on_log, on_done, on_error, *args, **kwargs):
    """스레드+워커를 만들어 실행합니다. parent 가 참조를 들고 있어야 GC 되지 않습니다.

    ⚠ on_log/on_done/on_error 는 반드시 QObject(위젯)의 '바운드 메서드'여야 합니다.
    람다로 감싸면 PySide6 이 수신자의 스레드 소속을 알 수 없어 자동 큐잉(QueuedConnection)이
    아니라 발신 스레드에서 즉시 직접 호출(DirectConnection)해버리고, 그 안에서 GUI 위젯을
    건드리면 access violation 으로 즉시 크래시합니다. (실제로 이 버그로 크래시가 났었음)
    """
    thread = QThread(parent)
    worker = _Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.log.connect(on_log)
    worker.finished.connect(on_done)
    worker.failed.connect(on_error)

    # 표준 Qt 스레드 정리 패턴: thread.wait() 를 직접 부르지 않습니다.
    # (작업 스레드 안에서 잘못 호출되면 스스로를 기다리며 멈추는 교착상태가 됩니다)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    # 참조 유지 (안 하면 스레드가 중간에 GC 되어 죽음)
    parent._threads = getattr(parent, "_threads", [])
    parent._threads.append((thread, worker))
    return thread, worker


# ───────────────────────── 디자인 토큰 & 전역 스타일 ─────────────────────────
# 색은 여기서만 정의하고, 위젯에는 objectName / setProperty 로 역할만 붙입니다.
# (위젯마다 인라인 setStyleSheet 을 뿌리면 나중에 색 하나 바꾸기가 어려워집니다)
C = {
    "ground":  "#f4f6f9",   # 창 배경
    "surface": "#ffffff",   # 카드/입력 배경
    "sunk":    "#eceff4",   # 살짝 눌린 영역
    "line":    "#d8dee7",   # 테두리
    "ink":     "#1b1f27",   # 본문 글자
    "soft":    "#5c6675",   # 보조 글자
    "faint":   "#8b94a3",   # 라벨/캡션
    "accent":  "#3b7dd8",   # 주 동작 (생성)
    "accent_d": "#2f68b8",  # 주 동작 hover
    "accent_l": "#e8f0fb",  # 주 동작 배경 톤
    "go":      "#1f8a4d",   # 발행 (실행 계열)
    "go_d":    "#19733f",
    "stop":    "#c9453d",   # 브라우저 닫기 (종료 계열)
    "stop_d":  "#ad3a33",
    "ok_bg":   "#e4f2ea",   # 상태 배너 — 성공
    "ok_fg":   "#186b42",
    "warn_bg": "#fbf1dc",   # 상태 배너 — 경고
    "warn_fg": "#8a5a0f",
    "err_bg":  "#fbe6e5",   # 상태 배너 — 실패
    "err_fg":  "#a5342d",
    "log_bg":  "#161a21",   # 로그창 (어두운 콘솔 톤)
    "log_fg":  "#d4d9e1",
}

APP_QSS = f"""
QWidget {{
    background: {C['ground']};
    color: {C['ink']};
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 10pt;
}}
/* 라벨·체크박스는 배경을 갖지 않게 합니다. 위 QWidget 규칙을 그대로 상속하면
   흰 카드(QGroupBox) 안에서도 회색 바탕을 물고 나와 띠처럼 보입니다.
   배경이 필요한 라벨(role=info/status)은 아래에서 따로 지정합니다. */
QLabel, QCheckBox {{ background: transparent; }}

/* ── 탭 ── */
QTabWidget::pane {{
    border: none;
    background: {C['ground']};
    top: -1px;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {C['faint']};
    padding: 9px 18px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 10pt;
}}
QTabBar::tab:hover {{ color: {C['soft']}; }}
QTabBar::tab:selected {{
    color: {C['accent']};
    border-bottom: 2px solid {C['accent']};
    font-weight: bold;
}}

/* ── 버튼 ── */
QPushButton {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 6px;
    padding: 7px 14px;
    color: {C['ink']};
}}
QPushButton:hover  {{ background: {C['sunk']}; border-color: {C['faint']}; }}
QPushButton:pressed{{ background: {C['line']}; }}
QPushButton:disabled {{ color: {C['faint']}; background: {C['sunk']}; border-color: {C['line']}; }}

/* 역할별 강조 버튼: setProperty("role", "...") 로 지정 */
QPushButton[role="primary"] {{
    background: {C['accent']}; border-color: {C['accent']};
    color: #ffffff; font-weight: bold; padding: 8px 18px;
}}
QPushButton[role="primary"]:hover   {{ background: {C['accent_d']}; border-color: {C['accent_d']}; }}
QPushButton[role="primary"]:disabled{{ background: #a9bfdf; border-color: #a9bfdf; color: #eef3fa; }}

QPushButton[role="go"] {{
    background: {C['go']}; border-color: {C['go']};
    color: #ffffff; font-weight: bold; padding: 8px 18px;
}}
QPushButton[role="go"]:hover    {{ background: {C['go_d']}; border-color: {C['go_d']}; }}
QPushButton[role="go"]:disabled {{ background: #a8cfba; border-color: #a8cfba; color: #eef6f1; }}

QPushButton[role="stop"] {{
    background: {C['stop']}; border-color: {C['stop']};
    color: #ffffff; font-weight: bold; padding: 8px 18px;
}}
QPushButton[role="stop"]:hover    {{ background: {C['stop_d']}; border-color: {C['stop_d']}; }}
QPushButton[role="stop"]:disabled {{ background: #e2b6b3; border-color: #e2b6b3; color: #fbf0ef; }}

QPushButton[role="danger-text"] {{ color: {C['stop']}; }}
QPushButton[role="danger-text"]:hover {{ background: {C['err_bg']}; border-color: {C['stop']}; }}

/* ── 입력 ── */
QComboBox, QLineEdit, QTimeEdit {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {C['accent']};
}}
QComboBox:focus, QLineEdit:focus, QTimeEdit:focus {{ border-color: {C['accent']}; }}
/* QComboBox::drop-down 은 일부러 건드리지 않습니다. QSS 로 이 서브컨트롤을 조금이라도
   손대면 Qt 가 네이티브 그리기를 포기하고 ::down-arrow 이미지를 요구해서,
   따로 이미지를 주지 않으면 펼침 화살표가 통째로 사라집니다. */
QComboBox QAbstractItemView {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    selection-background-color: {C['accent_l']};
    selection-color: {C['ink']};
    outline: none;
}}

/* ── 표 ── */
QTableWidget {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 8px;
    gridline-color: {C['sunk']};
    selection-background-color: {C['accent_l']};
    selection-color: {C['ink']};
}}
QTableWidget::item {{ padding: 5px 8px; border: none; }}
QHeaderView::section {{
    background: {C['sunk']};
    color: {C['soft']};
    border: none;
    border-bottom: 1px solid {C['line']};
    padding: 7px 8px;
    font-weight: bold;
}}
QTableCornerButton::section {{ background: {C['sunk']}; border: none; }}

/* ── 로그창 / 편집기 ── */
QPlainTextEdit {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {C['accent']};
}}
QPlainTextEdit[role="log"] {{
    background: {C['log_bg']};
    color: {C['log_fg']};
    border: 1px solid #262c36;
}}

/* ── 진행 표시 ── */
QProgressBar {{
    background: {C['sunk']};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}

/* ── 그룹 박스 (이미지 미리보기) ── */
QGroupBox {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px 10px 10px;
    font-size: 9pt;
    color: {C['soft']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: {C['faint']};
}}

/* ── 스크롤 ── */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {C['line']}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {C['line']}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}

/* ── 라벨 역할 ── */
QLabel[role="section"] {{
    color: {C['faint']}; font-size: 9pt; font-weight: bold;
    letter-spacing: 1px; padding: 2px 2px 4px;
}}
QLabel[role="hint"] {{ color: {C['faint']}; font-size: 9pt; }}
QLabel[role="info"] {{
    background: {C['accent_l']}; color: {C['soft']};
    border: 1px solid #d5e3f6; border-radius: 8px; padding: 11px 14px;
}}
QLabel[role="path"] {{ color: {C['soft']}; }}
QLabel[role="status"] {{
    background: {C['sunk']}; color: {C['soft']};
    border: 1px solid {C['line']}; border-radius: 8px; padding: 10px 13px;
}}
QLabel[role="status"][tone="ok"] {{
    background: {C['ok_bg']}; color: {C['ok_fg']}; border-color: #c2e0d0;
}}
QLabel[role="status"][tone="warn"] {{
    background: {C['warn_bg']}; color: {C['warn_fg']}; border-color: #ecd9b0;
}}
QLabel[role="status"][tone="err"] {{
    background: {C['err_bg']}; color: {C['err_fg']}; border-color: #eec4c1;
}}

/* ── 주제 카드 ── */
QPushButton[role="topic"] {{
    background: {C['surface']};
    border: 1px solid {C['line']};
    border-radius: 8px;
    padding: 9px 11px;
    text-align: left;
}}
QPushButton[role="topic"]:hover {{ border-color: {C['accent']}; }}
QPushButton[role="topic"][sel="1"] {{
    border: 2px solid {C['accent']};
    background: {C['accent_l']};
}}
QPushButton[role="topic"]:disabled {{
    background: {C['sunk']}; border-color: {C['line']}; color: {C['faint']};
}}
QLabel[role="tname"] {{ font-weight: bold; }}
QLabel[role="twhy"]  {{ color: {C['soft']};  font-size: 8.5pt; }}
QLabel[role="tamt"]  {{ color: {C['faint']}; font-size: 8pt; }}
QLabel[role="chip"] {{
    font-size: 8pt; font-weight: bold; padding: 1px 7px; border-radius: 8px;
}}
QLabel[role="chip"][av="ok"]   {{ color: {C['ok_fg']};   background: {C['ok_bg']}; }}
QLabel[role="chip"][av="thin"] {{ color: {C['warn_fg']}; background: {C['warn_bg']}; }}
QLabel[role="chip"][av="none"] {{ color: {C['faint']};   background: {C['sunk']}; }}
"""

ALIGN_LABEL = {"left": "왼쪽", "center": "가운데", "justify": "양쪽"}

LOG_FONT = QFont("Consolas", 9)


def _restyle(w: QWidget) -> None:
    """setProperty 로 바꾼 역할(role/tone)을 화면에 즉시 반영시킵니다.
    Qt 는 프로퍼티가 바뀌어도 스타일을 자동으로 다시 계산하지 않습니다."""
    w.style().unpolish(w)
    w.style().polish(w)


def _set_status(label: QLabel, text: str, tone: str = "") -> None:
    """상태 배너 한 줄 갱신 (tone: "" | ok | warn | err)."""
    label.setText(text)
    label.setProperty("tone", tone)
    _restyle(label)


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section")
    return lbl


def _log_box() -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setFont(LOG_FONT)
    box.setProperty("role", "log")
    return box


class _SettingDialog(QDialog):
    """이번 글에만 적용할 스타일·주제·카테고리를 고르는 창.

    계정 기본값(accounts.py)은 건드리지 않습니다 — 여기서 바꾼 값은 이번 생성에만
    적용되고, 계정을 다시 고르면 기본값으로 돌아옵니다.
    """

    def __init__(self, parent, account: str, persona: str, topic: str,
                 category: str | None, company: str):
        super().__init__(parent)
        self.setWindowTitle("이번 글 설정")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        info = QLabel(f"계정 <b>{account}</b> · 기업 <b>{company or '(미선택)'}</b><br>"
                      "여기서 바꾼 값은 <b>이번 글에만</b> 적용됩니다.")
        info.setProperty("role", "info")
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._p = QComboBox()
        for k in personas.keys():
            self._p.addItem(personas.name(k), k)
        i = self._p.findData(persona)
        self._p.setCurrentIndex(max(i, 0))
        form.addRow("스타일", self._p)

        self._t = QComboBox()
        for k in topics.DISPLAY_ORDER + [topics.ALL_KEY]:
            self._t.addItem(topics.name(k), k)
        i = self._t.findData(topic)
        self._t.setCurrentIndex(max(i, 0))
        form.addRow("주제", self._t)

        self._c = QComboBox()
        self._c.addItem("(네이버 기본 카테고리)", None)
        for name in accounts.available_categories(account):
            self._c.addItem(name, name)
        i = self._c.findData(category)
        self._c.setCurrentIndex(max(i, 0))
        form.addRow("카테고리", self._c)
        root.addLayout(form)

        hint = QLabel("스타일을 바꾸면 어투·줄 길이·정렬이 함께 바뀝니다.")
        hint.setProperty("role", "hint")
        root.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        ok = QPushButton("적용")
        ok.setProperty("role", "primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        root.addLayout(btns)

    def persona(self) -> str:
        return self._p.currentData()

    def topic(self) -> str:
        return self._t.currentData()

    def category(self) -> str | None:
        return self._c.currentData()


# ───────────────────────── 탭 1: 글 생성 ─────────────────────────
class GenerateTab(QWidget):
    draft_ready = Signal(str)          # 생성된 초안 경로 → 발행 탭
    context_ready = Signal(str, str, object)   # 계정, 스타일, 카테고리

    def __init__(self):
        super().__init__()
        self._out_path: Path | None = None
        self._topic = topics.ALL_KEY
        self._persona = personas.DEFAULT
        self._category: str | None = None
        self._auto_category = True    # 계정 기본값을 따를지 (직접 고르면 False)
        self._topic_btns: dict[str, QPushButton] = {}
        self._persona_btns: dict[str, QPushButton] = {}
        self._build()
        self._apply_account_defaults()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        # ── 상단: 계정 ──
        acc_row = QHBoxLayout()
        acc_row.setSpacing(8)
        acc_row.addWidget(QLabel("계정"))
        self.acct_combo = QComboBox()
        self.acct_combo.setMinimumWidth(170)
        self.acct_combo.addItems(config.list_accounts())
        self.acct_combo.currentTextChanged.connect(self._apply_account_defaults)
        acc_row.addWidget(self.acct_combo)

        self.setting_label = QLabel()
        self.setting_label.setProperty("role", "hint")
        acc_row.addWidget(self.setting_label, 1)

        self.edit_setting_btn = QPushButton("설정 바꾸기")
        self.edit_setting_btn.setToolTip("이번 글에만 적용됩니다. 계정 기본값은 그대로입니다")
        self.edit_setting_btn.clicked.connect(self._edit_settings)
        acc_row.addWidget(self.edit_setting_btn)
        root.addLayout(acc_row)

        # ── 기업 선택 ──
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("기업"))
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setMinimumWidth(240)
        self.combo.addItems(md_loader.list_companies())
        self.combo.currentTextChanged.connect(self._on_company_changed)
        top.addWidget(self.combo, 1)

        self.next_btn = QPushButton("대기열 다음 차례")
        self.next_btn.clicked.connect(self._fill_next)
        top.addWidget(self.next_btn)

        self.gen_btn = QPushButton("글 생성 시작")
        self.gen_btn.setProperty("role", "primary")
        self.gen_btn.clicked.connect(self._start_generate)
        top.addWidget(self.gen_btn)
        root.addLayout(top)

        # ── 스타일 선택 ──
        root.addWidget(_section("스타일 — 어떤 어투로 쓸지 (마우스를 올리면 예시가 보입니다)"))
        self.persona_grid = QGridLayout()
        self.persona_grid.setSpacing(8)
        root.addLayout(self.persona_grid)
        self._build_persona_cards()

        # ── 주제 선택 ──
        root.addWidget(_section("주제 — 이 기업 자료로 쓸 수 있는 것"))
        self.topic_grid = QGridLayout()
        self.topic_grid.setSpacing(8)
        root.addLayout(self.topic_grid)
        self._build_topic_cards()

        # ── 진행 표시 ──
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)   # 무한 로딩
        self.progress.hide()
        root.addWidget(self.progress)

        # ── 좌: 로그 / 우: 이미지 미리보기 ──
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(12)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_layout.addWidget(_section("진행 로그"))
        self.log = _log_box()
        log_layout.addWidget(self.log)
        split.addWidget(log_panel)

        img_panel = QWidget()
        img_layout = QVBoxLayout(img_panel)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(4)
        img_layout.addWidget(_section("생성된 이미지"))
        self.img_scroll = QScrollArea()
        self.img_scroll.setWidgetResizable(True)
        self.img_holder = QWidget()
        self.img_holder_layout = QVBoxLayout(self.img_holder)
        self.img_holder_layout.setContentsMargins(0, 0, 6, 0)
        self.img_holder_layout.setSpacing(10)
        self.img_holder_layout.addStretch()
        self.img_scroll.setWidget(self.img_holder)
        img_layout.addWidget(self.img_scroll)
        split.addWidget(img_panel)

        split.setSizes([620, 400])
        root.addWidget(split, 1)

        # ── 하단: 검증 결과 요약 ──
        self.status_label = QLabel("기업을 고르고 [글 생성 시작]을 누르세요.")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "status")
        root.addWidget(self.status_label)

    # ── 스타일 카드 ────────────────────────────────
    def _persona_tip(self, key: str) -> str:
        """마우스를 올렸을 때 뜨는 미리보기.

        어투는 설명으로 읽어봐야 감이 안 옵니다. 실제 문장을 보여주는 게 빠릅니다.
        표 이미지 색까지 스타일을 따라가므로 그 색도 같이 찍어줍니다.
        """
        d = personas.get(key)
        theme = image_gen.CARD_THEMES.get(key, {})
        lines = "<br>".join(
            f"<span style='color:#111827'>{html.escape(s)}</span>"
            for s in d.get("sample", []))
        return (
            f"<table width='430' cellspacing='0' cellpadding='0'><tr><td>"
            f"<b style='font-size:10pt'>{html.escape(d['name'])}</b>"
            f"<span style='color:#6b7280'> — {html.escape(d.get('tag', ''))}</span>"
            f"<hr>{lines}<hr>"
            f"<span style='color:#6b7280; font-size:8pt'>"
            f"정렬 {ALIGN_LABEL.get(d['align'], d['align'])} · "
            f"한 줄 {d['line_min']}~{d['line_max']}자 · "
            f"소제목 {d['heads'][0]}~{d['heads'][1]}개 · "
            f"표 이미지 {theme.get('label', '없음') if d['use_tables'] else '없음'}"
            f"</span></td></tr></table>")

    def _build_persona_cards(self):
        """스타일 카드. 주제와 달리 기업에 따라 달라지지 않으니 한 번만 만듭니다."""
        for i, key in enumerate(personas.keys()):
            d = personas.get(key)
            btn = QPushButton()
            btn.setProperty("role", "topic")
            btn.setMinimumHeight(52)
            btn.setToolTip(self._persona_tip(key))
            btn.clicked.connect(lambda _=False, k=key: self._pick_persona(k))

            v = QVBoxLayout(btn)
            v.setContentsMargins(10, 7, 10, 7)
            v.setSpacing(2)
            # 글자가 두 줄로 넘칠 때 카드가 같이 늘어나도록.
            # 이걸 안 걸면 아래 줄이 위 줄에 겹쳐 그려집니다(실제로 겪음).
            v.setSizeConstraint(QLayout.SetMinimumSize)

            head = QHBoxLayout()
            head.setSpacing(6)
            nm = QLabel(d["name"])
            nm.setProperty("role", "tname")
            head.addWidget(nm)
            head.addStretch()
            sw = QLabel("■")               # 표 이미지 색 미리보기
            sw.setStyleSheet(
                f"color:{image_gen.CARD_THEMES.get(key, {}).get('accent', '#999')};")
            head.addWidget(sw)
            v.addLayout(head)

            tag = QLabel(d.get("tag", ""))
            tag.setProperty("role", "twhy")
            tag.setWordWrap(True)
            v.addWidget(tag)

            self._persona_btns[key] = btn
            self.persona_grid.addWidget(btn, 0, i)

    def _pick_persona(self, key: str):
        self._persona = key
        self._mark_selected()
        self._refresh_setting_label()

    # ── 주제 카드 ──────────────────────────────────
    def _build_topic_cards(self):
        """주제 카드를 한 번 만들어 두고, 기업이 바뀌면 내용만 갱신합니다."""
        keys = topics.DISPLAY_ORDER + [topics.ALL_KEY]
        for i, key in enumerate(keys):
            btn = QPushButton()
            btn.setProperty("role", "topic")
            btn.setCheckable(False)
            btn.setMinimumHeight(88)      # 제목 + 설명 두 줄 + 원문 글자수
            btn.clicked.connect(lambda _=False, k=key: self._pick_topic(k))

            v = QVBoxLayout(btn)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(3)
            # 설명이 두 줄로 넘치면 카드를 늘립니다. 이게 없으면 '원문 N자' 줄이
            # 설명 줄 위에 겹쳐 그려집니다 ('전 전형 종합 정리' 카드에서 실제로 발생).
            v.setSizeConstraint(QLayout.SetMinimumSize)

            head = QHBoxLayout()
            head.setSpacing(6)
            nm = QLabel(topics.get(key)["name"])
            nm.setProperty("role", "tname")
            head.addWidget(nm)
            head.addStretch()
            chip = QLabel()
            chip.setProperty("role", "chip")
            head.addWidget(chip)
            v.addLayout(head)

            why = QLabel()
            why.setProperty("role", "twhy")
            why.setWordWrap(True)
            # 줄바꿈되는 라벨은 레이아웃이 높이를 제대로 못 잡습니다(Qt 고질).
            # SetMinimumSize 만으로는 부족해서, 두 줄 자리를 아예 미리 잡아둡니다.
            why.setMinimumHeight(why.fontMetrics().lineSpacing() * 2 + 2)
            why.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            v.addWidget(why)

            amt = QLabel()
            amt.setProperty("role", "tamt")
            v.addWidget(amt)

            btn._chip, btn._why, btn._amt = chip, why, amt
            self._topic_btns[key] = btn
            self.topic_grid.addWidget(btn, i // 4, i % 4)

        self._refresh_topics()

    _AV_LABEL = {"ok": "가능", "thin": "제한적", "none": "자료 부족"}
    _AV_WHY = {
        "ok":   "이 기업 자료만으로 한 편을 채울 수 있습니다.",
        "thin": "자료가 얇아 일반적인 내용이 섞입니다.",
        "none": "원문에 거의 없어 지어내게 됩니다.",
    }

    def _refresh_topics(self, *_):
        company = self.combo.currentText().strip()
        profile = md_loader.get_profile(company) if company else None
        stats = md_loader.angle_stats(profile) if profile else {}

        for key, btn in self._topic_btns.items():
            if key == topics.ALL_KEY:
                av, n = "ok", None
                why = "주제를 정하기 애매할 때. 모든 기업에 가능합니다."
            else:
                n = stats.get(key, 0)
                av = topics.availability(n, key) if profile else "none"
                why = self._AV_WHY[av]

            btn._chip.setText(self._AV_LABEL[av])
            btn._chip.setProperty("av", av)
            _restyle(btn._chip)
            btn._why.setText(why)
            btn._amt.setText("주제 전체를 고루" if n is None else f"원문 {n:,}자")
            # '제한적'도 누를 수는 있게 둡니다 — 사정을 알고 쓰겠다면 막을 이유가 없습니다.
            btn.setEnabled(av != "none")

        # 고른 주제가 꺼졌으면 종합으로 되돌립니다
        if not self._topic_btns[self._topic].isEnabled():
            self._topic = topics.ALL_KEY
        self._mark_selected()

    def _pick_topic(self, key: str):
        self._topic = key
        self._mark_selected()
        self._refresh_setting_label()

    def _mark_selected(self):
        for key, btn in self._topic_btns.items():
            btn.setProperty("sel", "1" if key == self._topic else "0")
            _restyle(btn)
        for key, btn in self._persona_btns.items():
            btn.setProperty("sel", "1" if key == self._persona else "0")
            _restyle(btn)

    # ── 계정 기본값 ────────────────────────────────
    def _apply_account_defaults(self, *_):
        """계정을 고르면 그 계정의 스타일·주제·카테고리를 채웁니다."""
        d = accounts.defaults(self.acct_combo.currentText())
        self._persona = d["persona"]
        self._topic = d["topic"]
        self._auto_category = True
        self._refresh_topics()
        self._refresh_setting_label()

    def _on_company_changed(self, *_):
        self._refresh_topics()
        self._refresh_setting_label()      # 기업이 바뀌면 카테고리가 달라질 수 있음

    def _current_category(self) -> str | None:
        """이번 글에 쓸 카테고리. 직접 고른 게 있으면 그것, 아니면 계정 기본값."""
        if not self._auto_category:
            return self._category
        return accounts.category_for(self.acct_combo.currentText(),
                                     self.combo.currentText().strip())

    def _refresh_setting_label(self):
        cat = self._current_category() or "기본 카테고리"
        self.setting_label.setText(
            f"{personas.name(self._persona)}  ·  {topics.name(self._topic)}  ·  {cat}")

    def _edit_settings(self):
        """이번 글에만 적용할 설정을 바꿉니다."""
        dlg = _SettingDialog(self, account=self.acct_combo.currentText(),
                             persona=self._persona, topic=self._topic,
                             category=self._current_category(),
                             company=self.combo.currentText().strip())
        if dlg.exec() != QDialog.Accepted:
            return
        self._persona = dlg.persona()
        self._topic = dlg.topic()
        cat = dlg.category()
        auto = accounts.category_for(self.acct_combo.currentText(),
                                     self.combo.currentText().strip())
        self._auto_category = (cat == auto)
        self._category = cat
        self._refresh_topics()
        self._refresh_setting_label()

    def _fill_next(self):
        nxt = post_queue.next_company()
        if nxt:
            self.combo.setCurrentText(nxt)
        else:
            QMessageBox.information(self, "대기열", "모든 기업을 발행했습니다.")

    def _start_generate(self):
        company = self.combo.currentText().strip()
        if not company:
            QMessageBox.warning(self, "입력 필요", "기업명을 선택하거나 입력하세요.")
            return

        self.gen_btn.setEnabled(False)
        self.progress.show()
        self.log.clear()
        _set_status(self.status_label,
                    f"{company} · {topics.name(self._topic)} · "
                    f"{personas.name(self._persona)} 생성 중…  "
                    "본문 작성에 30초~1분쯤 걸립니다.")
        self._clear_images()

        import main as gen_main
        run_in_thread(
            self, gen_main.create_draft,
            on_log=self._append_log,
            on_done=self._on_done,
            on_error=self._on_error,
            company=company, quiet=False, topic=self._topic,
            persona=self._persona,
        )

    def _append_log(self, text: str) -> None:
        self.log.insertPlainText(text)

    def _on_done(self, result):
        self.gen_btn.setEnabled(True)
        self.progress.hide()
        out, post, profile, needed, missing, issues = result
        self._out_path = out

        if issues:
            _set_status(
                self.status_label,
                f"검증 미해결 {len(issues)}건 — 다시 쓰기를 2번 했는데도 남았습니다. "
                f"초안은 저장됐으니 [미리보기/수정] 탭에서 손보세요.\n"
                + "\n".join(f"· {i}" for i in issues),
                tone="warn")
        else:
            _set_status(
                self.status_label,
                f"검증 통과 — {post.title}\n{out}",
                tone="ok")

        self._load_images(profile["company_key"])
        post_queue.mark(profile["company_key"], draft=out.name,
                        status="draft_only", topic=self._topic,
                        account=self.acct_combo.currentText())
        self.context_ready.emit(self.acct_combo.currentText(),
                                self._persona, self._current_category())
        self.draft_ready.emit(str(out))

    def _on_error(self, tb: str):
        self.gen_btn.setEnabled(True)
        self.progress.hide()
        _set_status(self.status_label,
                    "생성에 실패했습니다. 아래 진행 로그의 마지막 부분을 확인하세요.",
                    tone="err")
        self.log.insertPlainText("\n" + tb)

    def _clear_images(self):
        while self.img_holder_layout.count() > 1:
            item = self.img_holder_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _load_images(self, company_key: str):
        self._clear_images()
        for suffix in ("대표", "전형절차", "준비체크리스트"):
            path = config.IMAGES_DIR / f"{company_key}_{suffix}.png"
            if not path.exists():
                continue
            box = QGroupBox(suffix)
            v = QVBoxLayout(box)
            v.setContentsMargins(10, 6, 10, 10)
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            pix = QPixmap(str(path))
            if not pix.isNull():
                lbl.setPixmap(pix.scaledToWidth(340, Qt.SmoothTransformation))
            v.addWidget(lbl)
            self.img_holder_layout.insertWidget(self.img_holder_layout.count() - 1, box)


# ───────────────────────── 탭 2: 발행 ─────────────────────────
class PublishTab(QWidget):
    def __init__(self):
        super().__init__()
        self._draft_path: str | None = None
        self._close_event: threading.Event | None = None
        self._is_dry: bool = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        info = QLabel(
            "제목·본문·서식·이미지·해시태그를 네이버 에디터에 자동으로 채웁니다.\n"
            "발행 버튼은 계정 안전을 위해 자동으로 누르지 않습니다. "
            "브라우저에서 내용을 확인한 뒤 직접 눌러주세요.")
        info.setWordWrap(True)
        info.setProperty("role", "info")
        root.addWidget(info)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("대상 초안"))
        self.draft_label = QLabel("글 생성 탭에서 만든 초안이 자동으로 선택됩니다")
        self.draft_label.setProperty("role", "hint")
        row.addWidget(self.draft_label, 1)

        self.pick_latest_btn = QPushButton("최근 초안 불러오기")
        self.pick_latest_btn.clicked.connect(self._pick_latest)
        row.addWidget(self.pick_latest_btn)
        root.addLayout(row)

        # ── 발행 계정 ──
        acc_row = QHBoxLayout()
        acc_row.setSpacing(8)
        acc_row.addWidget(QLabel("발행 계정"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(180)
        acc_row.addWidget(self.account_combo)

        self.account_hint = QLabel()
        self.account_hint.setProperty("role", "hint")
        acc_row.addWidget(self.account_hint, 1)

        self.add_account_btn = QPushButton("계정 추가·재로그인")
        self.add_account_btn.setToolTip(
            "새 계정을 등록하거나, 로그인이 풀린 계정을 다시 로그인합니다")
        self.add_account_btn.clicked.connect(self._add_account)
        acc_row.addWidget(self.add_account_btn)
        root.addLayout(acc_row)
        self._reload_accounts()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.dry_btn = QPushButton("미리보기")
        self.dry_btn.setToolTip("브라우저를 열지 않고, 에디터에 어떻게 입력될지만 확인합니다")
        self.dry_btn.clicked.connect(lambda: self._start_publish(dry=True))
        btn_row.addWidget(self.dry_btn)
        btn_row.addStretch()

        self.publish_btn = QPushButton("네이버 에디터에 채우기")
        self.publish_btn.setProperty("role", "go")
        self.publish_btn.clicked.connect(lambda: self._start_publish(dry=False))
        btn_row.addWidget(self.publish_btn)

        self.close_browser_btn = QPushButton("확인 완료 · 브라우저 닫기")
        self.close_browser_btn.setProperty("role", "stop")
        self.close_browser_btn.setEnabled(False)
        self.close_browser_btn.clicked.connect(self._close_browser)
        btn_row.addWidget(self.close_browser_btn)
        root.addLayout(btn_row)

        note = QLabel(
            "입력이 끝나도 브라우저는 열려 있습니다. 내용 확인과 발행까지 마친 뒤 "
            "[확인 완료 · 브라우저 닫기]를 눌러주세요.")
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        root.addWidget(note)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)

        root.addWidget(_section("진행 로그"))
        self.log = _log_box()
        root.addWidget(self.log, 1)

    def set_context(self, account: str, persona: str, category) -> None:
        """글 생성 탭에서 쓴 계정·스타일·카테고리를 그대로 이어받습니다."""
        i = self.account_combo.findText(account)
        if i >= 0:
            self.account_combo.setCurrentIndex(i)
        self._persona = persona
        self._category = category
        self.account_hint.setText(
            f"{personas.name(persona)} · {category or '기본 카테고리'}")

    def set_draft(self, path: str):
        self._draft_path = path
        self.draft_label.setText(Path(path).name)
        self.draft_label.setToolTip(path)
        self.draft_label.setProperty("role", "path")
        _restyle(self.draft_label)

    # ── 계정 ──────────────────────────────────────
    def _reload_accounts(self):
        """저장된 계정 목록을 다시 읽어 드롭다운을 채웁니다."""
        cur = self.account_combo.currentText() or config.BLOG_ID
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItems(config.list_accounts())
        i = self.account_combo.findText(cur)
        self.account_combo.setCurrentIndex(i if i >= 0 else 0)
        self.account_combo.blockSignals(False)
        n = self.account_combo.count()
        self.account_hint.setText(
            f"로그인된 계정 {n}개 — 글마다 골라서 올릴 수 있습니다"
            if n > 1 else "로그인된 계정이 하나입니다")

    def _add_account(self):
        """새 계정 로그인 창을 띄웁니다. 로그인은 사람이 직접 합니다."""
        blog_id, ok = QInputDialog.getText(
            self, "계정 추가·재로그인",
            "네이버 블로그 아이디를 입력하세요.\n"
            "(이미 있는 아이디를 넣으면 그 계정으로 다시 로그인합니다)")
        blog_id = (blog_id or "").strip()
        if not ok or not blog_id:
            return
        QMessageBox.information(
            self, "로그인 창이 열립니다",
            f"'{blog_id}' 계정으로 로그인할 브라우저 창이 열립니다.\n\n"
            "창에서 직접 로그인한 뒤, 로그인이 끝나면 그 창을 닫아주세요.\n"
            "로그인 정보는 이 계정 전용 폴더에 저장돼 다음부터 자동으로 쓰입니다.")

        self.log.clear()
        self.progress.show()
        self.publish_btn.setEnabled(False)
        self.dry_btn.setEnabled(False)
        self._pending_account = blog_id
        run_in_thread(
            self, _login_account,
            self._append_log, self._on_login_done, self._on_error, blog_id,
        )

    def _on_login_done(self, ok_flag):
        self.progress.hide()
        self.publish_btn.setEnabled(True)
        self.dry_btn.setEnabled(True)
        self._reload_accounts()
        acc = getattr(self, "_pending_account", "")
        if acc:
            i = self.account_combo.findText(acc)
            if i >= 0:
                self.account_combo.setCurrentIndex(i)
        self.log.insertPlainText(
            "\n\n✅ 로그인 창을 닫았습니다. 계정 목록을 새로 읽었습니다.\n"
            "   실제로 로그인됐는지는 이 계정으로 한 번 발행해보면 확인됩니다.")

    def _pick_latest(self):
        import publisher
        latest = publisher._latest_draft()
        if latest is None:
            QMessageBox.information(self, "초안 없음", "drafts 폴더에 초안이 없습니다.")
            return
        self.set_draft(str(latest))

    def _start_publish(self, dry: bool):
        if not self._draft_path:
            self._pick_latest()
        if not self._draft_path:
            return

        # 고른 계정으로 갈아끼웁니다. publisher 가 config 를 호출 시점에 읽으므로
        # 이 한 줄로 프로필 폴더·글쓰기 URL 이 전부 그 계정 것으로 바뀝니다.
        account = self.account_combo.currentText().strip()
        if account and account != config.BLOG_ID:
            config.set_account(account)
        self._account = account

        # 글에 쓴 스타일대로 정렬이 걸리고, 지정한 카테고리로 올라갑니다
        cat = getattr(self, "_category", None)
        config.CATEGORY = cat or ""

        self._is_dry = dry
        self.publish_btn.setEnabled(False)
        self.dry_btn.setEnabled(False)
        self.progress.show()
        self.log.clear()

        import publisher
        if dry:
            fn = publisher.dry_run
            kwargs = {}
        else:
            fn = publisher.fill_editor
            # GUI 에서는 터미널 input() 을 받을 수 없으므로 interactive=False 를 기본값으로 깔되,
            # wait_event 를 넘겨서 "확인 완료 · 브라우저 닫기" 버튼을 누르기 전까지는
            # 브라우저가 자동으로 닫히지 않게 합니다 (사람이 발행을 누를 시간을 확보).
            self._close_event = threading.Event()
            kwargs = {"interactive": False, "wait_event": self._close_event,
                      "persona": getattr(self, "_persona", None)}
            self.close_browser_btn.setEnabled(True)

        run_in_thread(
            self, fn,
            self._append_log,
            self._on_done,
            self._on_error,
            self._draft_path, **kwargs,
        )

    def _append_log(self, text: str) -> None:
        self.log.insertPlainText(text)

    def _close_browser(self) -> None:
        """사람이 브라우저에서 확인(+발행)까지 마쳤다는 신호. 작업 스레드의 대기를 풀어줍니다."""
        if self._close_event is not None:
            self._close_event.set()
        self.close_browser_btn.setEnabled(False)

    def _on_done(self, _result):
        self.publish_btn.setEnabled(True)
        self.dry_btn.setEnabled(True)
        self.close_browser_btn.setEnabled(False)
        self._close_event = None
        self.progress.hide()
        acc = getattr(self, "_account", "") or config.BLOG_ID
        self.log.insertPlainText(
            f"\n\n✅ 작업 완료 — '{acc}' 계정 창에서 내용 확인 후 [발행]을 직접 눌러주세요.")

        if not self._is_dry and self._draft_path:
            # ⚠ 실제 [발행] 버튼은 사람이 누르므로, 여기서는 "에디터까지 채움"만 확정된
            # 사실입니다. 진짜로 발행됐는지는 알 수 없어 "filled" 로 구분해서 기록합니다.
            company = _company_from_draft_path(self._draft_path)
            post_queue.mark(company, draft=Path(self._draft_path).name,
                            status="filled", account=acc)

    def _on_error(self, tb: str):
        self.publish_btn.setEnabled(True)
        self.dry_btn.setEnabled(True)
        self.close_browser_btn.setEnabled(False)
        self._close_event = None
        self.progress.hide()
        self.log.insertPlainText("\n" + tb)


# ───────────────────────── 탭 3: 대기열 ─────────────────────────
class QueueTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("role", "status")
        top.addWidget(self.summary, 1)

        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        root.addLayout(top)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)

        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)
        table_layout.addWidget(_section("기업 진행 현황"))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["순서", "기업명", "상태", "쓴 주제", "계정", "예약/발행 시각"])
        # 머리글 정렬을 아래 데이터와 맞춥니다 (글자는 왼쪽, 순서·상태는 가운데)
        for col, align in ((0, Qt.AlignCenter), (1, Qt.AlignLeft | Qt.AlignVCenter),
                           (2, Qt.AlignCenter), (3, Qt.AlignLeft | Qt.AlignVCenter),
                           (4, Qt.AlignLeft | Qt.AlignVCenter),
                           (5, Qt.AlignLeft | Qt.AlignVCenter)):
            self.table.horizontalHeaderItem(col).setTextAlignment(align)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 140)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        table_layout.addWidget(self.table)
        split.addWidget(table_panel)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_layout.addWidget(_section("자동 발행 기록"))
        self.daily_log = _log_box()
        log_layout.addWidget(self.daily_log)
        split.addWidget(log_panel)

        split.setSizes([440, 190])
        root.addWidget(split, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        skip_btn = QPushButton("건너뛰기로 표시")
        skip_btn.clicked.connect(self._skip_selected)
        btn_row.addWidget(skip_btn)

        undo_btn = QPushButton("기록 취소")
        undo_btn.clicked.connect(self._undo_selected)
        btn_row.addWidget(undo_btn)
        btn_row.addStretch()

        reset_btn = QPushButton("전체 초기화")
        reset_btn.setProperty("role", "danger-text")
        reset_btn.clicked.connect(self._reset_all)
        btn_row.addWidget(reset_btn)
        root.addLayout(btn_row)

    # 내부 상태값 → 화면 표기 + 글자색.
    # 배경색은 쓰지 않습니다: QSS 로 QTableWidget::item 을 스타일하면 Qt 가 아이템별
    # setBackground() 를 무시해서 조용히 안 먹습니다. 글자색만으로 구분합니다.
    STATUS_LABEL = {
        "":           ("대기",        C["faint"]),
        "draft_only": ("초안 작성",   C["warn_fg"]),
        "filled":     ("에디터 입력", C["accent"]),
        "scheduled":  ("발행 예약",   C["ok_fg"]),
        "published":  ("발행 완료",   C["ok_fg"]),
        "manual":     ("발행 완료",   C["ok_fg"]),
        "skipped":    ("건너뜀",      C["faint"]),
    }

    def refresh(self):
        done, total = post_queue.status()
        nxt = post_queue.next_task()
        nxt_txt = f"{nxt[0]} · {topics.name(nxt[1])}" if nxt else "모두 완료"
        self.summary.setText(
            f"계획 {total}편 중 {done}편 씀     다음 차례:  {nxt_txt}")

        names = post_queue.order()
        self.table.setRowCount(len(names))
        for i, name in enumerate(names):
            info = post_queue.company_info(name)
            raw = info.get("status", "") if info else ""
            when = info.get("scheduled_at", "") if info else ""
            label, fg = self.STATUS_LABEL.get(raw, (raw, C["soft"]))

            no_item = QTableWidgetItem(str(i + 1))
            no_item.setTextAlignment(Qt.AlignCenter)
            no_item.setForeground(QColor(C["faint"]))
            self.table.setItem(i, 0, no_item)

            self.table.setItem(i, 1, QTableWidgetItem(name))

            status_item = QTableWidgetItem(label)
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor(fg))
            self.table.setItem(i, 2, status_item)

            written = (info or {}).get("topics", [])
            planned = post_queue.plan().get(name, [])
            topic_item = QTableWidgetItem(
                f"{', '.join(topics.get(t)['short'] for t in written)}"
                f"  ({len(written)}/{len(planned)})" if written
                else f"0/{len(planned)}")
            topic_item.setForeground(QColor(C["soft"]))
            self.table.setItem(i, 3, topic_item)

            acc_item = QTableWidgetItem((info or {}).get("account", ""))
            acc_item.setForeground(QColor(C["soft"]))
            self.table.setItem(i, 4, acc_item)

            when_item = QTableWidgetItem(when)
            when_item.setForeground(QColor(C["soft"]))
            self.table.setItem(i, 5, when_item)

        self._refresh_daily_log()

    def _refresh_daily_log(self):
        log_path = config.DRAFTS_DIR / "_daily.log"
        self.daily_log.clear()
        if not log_path.exists():
            self.daily_log.setPlainText("아직 매일 자동 발행을 실행한 기록이 없습니다.")
            return
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            self.daily_log.setPlainText(f"(로그를 읽을 수 없습니다: {e})")
            return
        self.daily_log.setPlainText("\n".join(lines[-200:]))
        self.daily_log.verticalScrollBar().setValue(self.daily_log.verticalScrollBar().maximum())

    def _selected_company(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.text() if item else None

    def _skip_selected(self):
        name = self._selected_company()
        if not name:
            return
        post_queue.mark(name, status="skipped")
        self.refresh()

    def _undo_selected(self):
        name = self._selected_company()
        if not name:
            return
        post_queue.unmark(name)
        self.refresh()

    def _reset_all(self):
        if QMessageBox.question(
                self, "전체 초기화", "모든 발행 기록을 지웁니다. 계속할까요?"
        ) == QMessageBox.Yes:
            if post_queue.RECORD.exists():
                post_queue.RECORD.unlink()
            self.refresh()


# ───────────────────────── 탭 4: 초안 수정 ─────────────────────────
class PreviewTab(QWidget):
    """초안을 위지윅(CKEditor)으로 보면서 고칩니다.

    초안 파일은 발행기가 읽는 자체 문법([[H]], <blue> 등)이라, 열 때 HTML 로 바꾸고
    저장할 때 다시 그 문법으로 되돌립니다(dsl_html.py). 줄바꿈 위치가 곧 본문
    가독성이라 '한 줄 = 한 문단'으로 1:1 대응시켜 절대 합치지 않습니다.

    파일 형식(publisher.parse_draft() 가 그대로 읽습니다):
      1번째 줄 "# 제목"  →  본문  →  "---"  →  해시태그
    """

    def __init__(self):
        super().__init__()
        self._current_path: Path | None = None
        self._tags = ""
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("초안"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        top.addWidget(self.combo, 1)

        refresh_btn = QPushButton("목록 새로고침")
        refresh_btn.clicked.connect(self.refresh_list)
        top.addWidget(refresh_btn)

        self.add_img_btn = QPushButton("사진 넣기")
        self.add_img_btn.setToolTip(
            "사진을 골라 글 끝에 넣습니다. 여러 장 고르면 한 줄에 나란히 들어갑니다")
        self.add_img_btn.clicked.connect(self._insert_image)
        top.addWidget(self.add_img_btn)

        self.save_btn = QPushButton("저장")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.clicked.connect(self._save)
        top.addWidget(self.save_btn)
        root.addLayout(top)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(QLabel("제목"))
        self.title_edit = QLineEdit()
        title_row.addWidget(self.title_edit, 1)
        root.addLayout(title_row)

        self.web = QWebEngineView()
        self.web.setMinimumHeight(360)
        # 페이지는 file:// 기준으로 띄웁니다(초안 이미지를 file:// 로 불러오기 때문).
        # 그 상태에서는 QWebEngine 이 외부 주소 접근을 기본으로 막아 CKEditor CDN 도
        # 함께 차단되므로, 아래 두 가지를 명시적으로 열어줍니다.
        s = self.web.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        root.addWidget(self.web, 1)

        tag_row = QHBoxLayout()
        tag_row.setSpacing(8)
        tag_row.addWidget(QLabel("해시태그"))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("#한국전력공사 #NCS …")
        tag_row.addWidget(self.tag_edit, 1)
        root.addLayout(tag_row)

        self.status_label = QLabel("초안을 고르면 여기에 내용이 열립니다.")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "status")
        root.addWidget(self.status_label)

        self.refresh_list()

    def refresh_list(self):
        current = self._current_path
        self.combo.blockSignals(True)
        self.combo.clear()
        if config.DRAFTS_DIR.exists():
            drafts = sorted(
                (p for p in config.DRAFTS_DIR.glob("*.md") if not p.name.startswith("_")),
                key=lambda p: p.stat().st_mtime, reverse=True)
            for p in drafts:
                self.combo.addItem(p.name, str(p))
        self.combo.blockSignals(False)
        if current is not None:
            idx = self.combo.findData(str(current))
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
                return
        if self.combo.count():
            self.combo.setCurrentIndex(0)
            self._load(Path(self.combo.currentData()))

    def _on_combo_changed(self, idx: int):
        path = self.combo.currentData()
        if path:
            self._load(Path(path))

    def load_path(self, path: str):
        """외부(글 생성 탭)에서 새로 만든 초안을 열 때 호출합니다."""
        self.refresh_list()
        idx = self.combo.findData(path)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        else:
            self._load(Path(path))

    def _load(self, path: Path):
        import dsl_html
        import editor_page
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as e:
            _set_status(self.status_label, f"파일을 열 수 없습니다 — {e}", tone="err")
            return

        title, body, tags = dsl_html.split_draft(raw)
        self._current_path = path
        self.title_edit.setText(title)
        self.tag_edit.setText(tags)
        # 이미지를 file:// 로 불러오므로 초안 폴더를 기준 URL 로 잡아줍니다
        self.web.setHtml(editor_page.build(dsl_html.to_html(body)),
                         QUrl.fromLocalFile(str(config.BASE_DIR) + "/"))
        _set_status(self.status_label, str(path))

    def _insert_image(self):
        """사진을 골라 images/ 로 복사한 뒤, 글 끝에 이미지 덩어리로 넣습니다."""
        import shutil
        import dsl_html

        paths, _ = QFileDialog.getOpenFileNames(
            self, "넣을 사진 고르기", str(config.IMAGES_DIR),
            "사진 (*.png *.jpg *.jpeg *.webp)")
        if not paths:
            return
        if len(paths) > 2:
            QMessageBox.information(
                self, "두 장까지",
                "한 줄에는 두 장까지 넣을 수 있습니다. 앞의 두 장만 넣습니다.")
            paths = paths[:2]

        names = []
        for p in paths:
            src = Path(p)
            dst = config.IMAGES_DIR / src.name
            if src.resolve() != dst.resolve():          # 폴더 밖에서 고른 사진이면 복사
                if dst.exists() and QMessageBox.question(
                        self, "같은 이름이 있습니다",
                        f"images 폴더에 '{src.name}' 이 이미 있습니다. 덮어쓸까요?"
                ) != QMessageBox.Yes:
                    return
                try:
                    config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                except Exception as e:
                    QMessageBox.critical(self, "복사 실패", str(e))
                    return
            names.append(dst.stem)

        html = dsl_html._img_html(names).replace("\\", "\\\\").replace("'", "\\'")
        self.web.page().runJavaScript(f"insertImageBlock('{html}');")
        _set_status(self.status_label,
                    f"사진을 넣었습니다 — {', '.join(names)}  (저장을 눌러야 반영됩니다)",
                    tone="ok")

    def _save(self):
        if self._current_path is None:
            return
        # 페이지에서 HTML 을 받아온 뒤(비동기) 이어서 저장합니다
        self.web.page().runJavaScript("getContent();", self._save_with_html)

    def _save_with_html(self, html: str | None):
        import dsl_html
        if not html:
            _set_status(self.status_label,
                        "편집기 내용을 가져오지 못했습니다. 잠시 후 다시 눌러주세요.",
                        tone="err")
            return

        title = self.title_edit.text().strip()
        tags = self.tag_edit.text().strip()
        body = dsl_html.to_dsl(html)
        if not title:
            QMessageBox.warning(self, "제목 없음", "제목을 입력하세요.")
            return

        try:
            self._current_path.write_text(
                dsl_html.join_draft(title, body, tags), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return
        _set_status(self.status_label,
                    f"저장했습니다 — {self._current_path}", tone="ok")


# ───────────────────────── 탭 5: 설정 ─────────────────────────
class SettingsTab(QWidget):
    """config.py 소스는 건드리지 않고 settings_override.json 으로 값을 관리합니다."""

    MODEL_CHOICES = [
        ("claude-opus-5", "Opus 5 — 품질 우선 (기본, 글당 약 300~400원)"),
        ("claude-sonnet-5", "Sonnet 5 — 비용 절감 (글당 약 200원, 품질은 약간 낮아질 수 있음)"),
    ]
    OPEN_TYPE_CHOICES = [
        (2, "전체공개"), (1, "이웃공개"), (3, "서로이웃공개"), (0, "비공개"),
    ]

    def __init__(self):
        super().__init__()
        self._build()
        self._load_current()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(14)

        info = QLabel(
            f"블로그 계정  ·  {config.BLOG_ID}\n"
            "계정을 바꾸려면 2_로그인저장.bat 을 --switch 옵션으로 실행하세요.")
        info.setWordWrap(True)
        info.setProperty("role", "info")
        root.addWidget(info)

        # ── 글 생성 ──
        gen_box = QGroupBox("글 생성")
        gen_form = QFormLayout(gen_box)
        gen_form.setContentsMargins(16, 14, 16, 14)
        gen_form.setSpacing(10)
        gen_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.model_combo = QComboBox()
        for key, label in self.MODEL_CHOICES:
            self.model_combo.addItem(label, key)
        gen_form.addRow("모델", self.model_combo)
        root.addWidget(gen_box)

        # ── 발행 ──
        pub_box = QGroupBox("발행")
        pub_form = QFormLayout(pub_box)
        pub_form.setContentsMargins(16, 14, 16, 14)
        pub_form.setSpacing(10)
        pub_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("비워두면 네이버 기본 카테고리")
        pub_form.addRow("카테고리", self.category_edit)

        self.open_type_combo = QComboBox()
        for key, label in self.OPEN_TYPE_CHOICES:
            self.open_type_combo.addItem(label, key)
        pub_form.addRow("공개 범위", self.open_type_combo)
        root.addWidget(pub_box)

        # ── 매일 자동 발행 ──
        sch_box = QGroupBox("매일 자동 발행")
        sch_outer = QVBoxLayout(sch_box)
        sch_outer.setContentsMargins(16, 14, 16, 14)
        sch_outer.setSpacing(8)

        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        time_row.addWidget(QLabel("예약 시각"))
        self.schedule_from = QTimeEdit()
        self.schedule_from.setDisplayFormat("HH:mm")
        time_row.addWidget(self.schedule_from)
        time_row.addWidget(QLabel("~"))
        self.schedule_to = QTimeEdit()
        self.schedule_to.setDisplayFormat("HH:mm")
        time_row.addWidget(self.schedule_to)
        time_row.addWidget(QLabel("사이"))
        time_row.addStretch()
        sch_outer.addLayout(time_row)

        note = QLabel(
            "이 구간 안에서 매일 다른 시각을 골라 예약합니다. "
            "구간이 너무 좁으면 늘 비슷한 시각에 올라가 자동 발행 패턴이 드러날 수 있습니다.")
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        sch_outer.addWidget(note)
        root.addWidget(sch_box)

        # ── 동작 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        save_btn = QPushButton("설정 저장")
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        reset_btn = QPushButton("기본값으로 되돌리기")
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.status_label = QLabel("바꾼 설정은 저장하는 즉시 반영됩니다.")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "status")
        root.addWidget(self.status_label)
        root.addStretch()

    def _load_current(self):
        idx = self.model_combo.findData(config.GEN_MODEL)
        self.model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_edit.setText(config.CATEGORY)
        idx = self.open_type_combo.findData(config.OPEN_TYPE)
        self.open_type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.schedule_from.setTime(QTime.fromString(config.SCHEDULE_FROM, "HH:mm"))
        self.schedule_to.setTime(QTime.fromString(config.SCHEDULE_TO, "HH:mm"))

    def _save(self):
        override = {
            "GEN_MODEL": self.model_combo.currentData(),
            "CATEGORY": self.category_edit.text(),
            "OPEN_TYPE": self.open_type_combo.currentData(),
            "SCHEDULE_FROM": self.schedule_from.time().toString("HH:mm"),
            "SCHEDULE_TO": self.schedule_to.time().toString("HH:mm"),
        }
        try:
            config.SETTINGS_OVERRIDE_PATH.write_text(
                json.dumps(override, ensure_ascii=False, indent=2), encoding="utf-8")
            importlib.reload(config)   # 이번 실행 중인 GUI 에도 바로 반영
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return
        _set_status(self.status_label, "설정을 저장했습니다. 지금부터 바로 적용됩니다.", tone="ok")

    def _reset(self):
        if config.SETTINGS_OVERRIDE_PATH.exists():
            config.SETTINGS_OVERRIDE_PATH.unlink()
        importlib.reload(config)
        self._load_current()
        _set_status(self.status_label, "기본값으로 되돌렸습니다.")


# ───────────────────────── 메인 윈도우 ─────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("톰슨에듀 자동 포스팅")
        self.resize(1100, 750)

        tabs = QTabWidget()
        self.tabs = tabs
        self.gen_tab = GenerateTab()
        self.pub_tab = PublishTab()
        self.queue_tab = QueueTab()
        self.preview_tab = PreviewTab()
        self.settings_tab = SettingsTab()

        # 글이 생성되면: 발행 탭에 대상 지정 + 미리보기 탭에 열기 + 대기열 갱신
        self.gen_tab.context_ready.connect(self.pub_tab.set_context)
        self.gen_tab.draft_ready.connect(self.pub_tab.set_draft)
        self.gen_tab.draft_ready.connect(self.preview_tab.load_path)
        self.gen_tab.draft_ready.connect(self._on_draft_ready)

        tabs.addTab(self.gen_tab, "글 생성")
        tabs.addTab(self.pub_tab, "발행")
        tabs.addTab(self.queue_tab, "대기열")
        tabs.addTab(self.preview_tab, "초안 수정")
        tabs.addTab(self.settings_tab, "설정")
        tabs.currentChanged.connect(self._on_tab_changed)

        self.setCentralWidget(tabs)

    def _on_draft_ready(self, _path: str) -> None:
        self.queue_tab.refresh()

    def _on_tab_changed(self, index: int) -> None:
        """탭을 열 때마다 그 탭이 보는 파일/기록을 최신 상태로 다시 읽습니다."""
        widget = self.tabs.widget(index)
        if widget is self.queue_tab:
            self.queue_tab.refresh()
        elif widget is self.preview_tab:
            self.preview_tab.refresh_list()
        elif widget is self.settings_tab:
            self.settings_tab._load_current()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")          # OS 테마 차이를 없애고 QSS 가 그대로 먹게 합니다
    app.setStyleSheet(APP_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
