# -*- coding: utf-8 -*-
"""톰슨에듀 자동 포스팅 파이프라인 — 데스크톱 GUI.

화면 구성 — 위쪽 [블로그 | 인스타] 버튼으로 전환합니다.
  블로그
    기업 일괄 발행 — 기업 하나를 계정별 스타일·주제로 나눠 지금/예약 발행
    대기열         — 기업 진행 현황, 완료 표시/취소, 최근 자동발행 로그
    글 생성        — 기업 선택 → 생성 → 실시간 로그 → 이미지 미리보기 → 검증 결과
    발행           — 최신 초안을 네이버 에디터에 자동 입력
    초안 수정      — 초안 원문을 GUI 안에서 직접 읽고 고쳐서 저장
    설정           — 모델·예약 시간대·카테고리를 코드 수정 없이 변경
  인스타
    카드뉴스 만들기 — 기업·스타일을 고르면 자료로 카드 8장 문구·캡션을 쓰고 카드까지 그림
    카드 확인·발행  — 카드를 눌러 글자 수정, 스타일만 바꿔 다시 그리기, 캡션, [확인 완료]
    발행 대기열    — 확인 완료한 카드의 예약 시각, 자동 발행(작업 스케줄러) 켜기·끄기, 토큰 만료일
    자료 준비      — 기업별 로고·건물 사진, 톰슨에듀AI 로고·캡처가 들어갔는지 점검

실행:
  venv\\Scripts\\python.exe run_app.py
"""
from __future__ import annotations
import datetime as dt
import html
import importlib
import json
import os
import re
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTime, QUrl, QDateTime, QSize
from PySide6.QtGui import QPixmap, QFont, QColor, QIcon, QImageReader
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QPlainTextEdit, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
    QScrollArea, QSplitter, QGroupBox, QProgressBar, QLineEdit, QTimeEdit,
    QFormLayout, QGridLayout, QInputDialog, QFileDialog, QDialog, QLayout,
    QRadioButton, QButtonGroup, QSpinBox, QDateTimeEdit, QStackedWidget,
)

import accounts
import company_batch
import config
import image_gen
import insta_cards
import insta_gen
import insta_publish
import insta_queue
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

/* ── 블로그 / 인스타 전환 ── */
QPushButton[role="mode"] {{
    background: {C['surface']}; color: {C['soft']};
    border: 1px solid {C['line']}; border-radius: 0;
    padding: 7px 26px; font-weight: bold; min-width: 64px;
}}
QPushButton[role="mode"][pos="l"] {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QPushButton[role="mode"][pos="r"] {{
    border-top-right-radius: 7px; border-bottom-right-radius: 7px; border-left: none;
}}
QPushButton[role="mode"]:hover   {{ color: {C['ink']}; background: {C['sunk']}; }}
QPushButton[role="mode"]:checked {{ background: {C['ink']}; border-color: {C['ink']}; color: #ffffff; }}

/* ── 카드뉴스 썸네일 ── */
QPushButton[role="thumb"] {{
    background: {C['surface']}; border: 1px solid {C['line']};
    border-radius: 8px; padding: 6px;
}}
QPushButton[role="thumb"]:hover {{ border-color: {C['accent']}; }}
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


# ───────────────────────── 탭: 기업 일괄 발행 ─────────────────────────
class CompanyBatchTab(QWidget):
    """기업 하나를 골라 로그인된 모든 계정에 한 편씩 쓰고 발행합니다.

    계획과 실행 로직은 company_batch.py 에 있고, 이 탭은 입력·확인·진행 표시만 맡습니다.
    발행은 되돌릴 수 없어서 [계획 세우기] → 표 확인 → [발행 시작] → 확인 창 순서를
    반드시 거치게 했습니다. 설정을 바꾸면 계획을 지워 다시 세우게 합니다.
    """

    COLS = ["계정", "스타일", "주제", "카테고리", "발행 시각", "배정 사유", "결과"]
    _STATUS = {"published": "✅ 발행", "scheduled": "📅 예약", "failed": "❌ 실패",
               "skipped": "건너뜀", "stopped": "중지", "": ""}

    def __init__(self):
        super().__init__()
        self._rows: list = []
        self._company = ""
        self._plan_mode = company_batch.MODE_NOW
        self._plan_spread = (30, 60)
        self._stop_event: threading.Event | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        info = QLabel(
            "기업 하나를 고르면 로그인된 계정마다 스타일·주제에 맞춰 한 편씩 쓰고 발행합니다.\n"
            "[계획 세우기]로 표를 먼저 확인한 뒤 [발행 시작]을 누르세요. 발행은 되돌릴 수 없습니다.")
        info.setWordWrap(True)
        info.setProperty("role", "info")
        root.addWidget(info)

        # ── 기업 ──
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("기업"))
        self.company_combo = QComboBox()
        self.company_combo.setEditable(True)
        self.company_combo.setMinimumWidth(260)
        self.company_combo.addItems(md_loader.list_companies())
        top.addWidget(self.company_combo, 1)
        self.plan_btn = QPushButton("계획 세우기")
        self.plan_btn.setProperty("role", "primary")
        self.plan_btn.clicked.connect(self._make_plan)
        top.addWidget(self.plan_btn)
        root.addLayout(top)

        # ── 발행 방식 ──
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(QLabel("발행 방식"))
        self.now_radio = QRadioButton("지금 발행")
        self.sched_radio = QRadioButton("예약 발행")
        self.now_radio.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.now_radio)
        self._mode_group.addButton(self.sched_radio)
        mode_row.addWidget(self.now_radio)
        mode_row.addWidget(self.sched_radio)
        mode_row.addSpacing(18)
        mode_row.addWidget(QLabel("예약 시작"))
        self.start_edit = QDateTimeEdit()
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_edit.setCalendarPopup(True)
        now = QDateTime.currentDateTime()
        self.start_edit.setMinimumDateTime(now)
        # 예약은 최대 한 달 뒤까지만 씁니다
        self.start_edit.setMaximumDateTime(now.addDays(company_batch.MAX_AHEAD_DAYS))
        self.start_edit.setDateTime(self._default_start())
        mode_row.addWidget(self.start_edit)
        mode_row.addWidget(QLabel("글 사이"))
        self.spread_min = self._spin(10, 720, 30, "분")
        self.spread_max = self._spin(10, 720, 60, "분")
        mode_row.addWidget(self.spread_min)
        mode_row.addWidget(QLabel("~"))
        mode_row.addWidget(self.spread_max)
        mode_row.addStretch()
        root.addLayout(mode_row)

        gap_row = QHBoxLayout()
        gap_row.setSpacing(8)
        gap_row.addWidget(QLabel("계정 사이 작업 간격"))
        self.gap_min = self._spin(0, 60, 3, "분")
        self.gap_max = self._spin(0, 60, 5, "분")
        gap_row.addWidget(self.gap_min)
        gap_row.addWidget(QLabel("~"))
        gap_row.addWidget(self.gap_max)
        gap_hint = QLabel("에디터 작업 사이 쉬는 시간입니다. 너무 짧으면 네이버가 세션을 끊을 수 있습니다.")
        gap_hint.setProperty("role", "hint")
        gap_row.addWidget(gap_hint, 1)
        root.addLayout(gap_row)

        # ── 공고 ──
        root.addWidget(_section("채용공고 (선택) — 붙여넣으면 글 맨 앞에 채용 일정 섹션이 들어갑니다"))
        self.posting_edit = QPlainTextEdit()
        self.posting_edit.setPlaceholderText(
            "공고 원문이나 요약을 붙여넣으세요. 비워두면 일정 섹션 없이 씁니다.\n"
            "공기업 분석 자료와 다른 부분(직군·전형·시험 구성 등)은 붙여넣은 공고를 따릅니다.")
        self.posting_edit.setFixedHeight(76)
        root.addWidget(self.posting_edit)

        # ── 계획표 ──
        root.addWidget(_section("계획표"))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        head = self.table.horizontalHeader()
        for c in range(len(self.COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.status_label = QLabel("기업을 고르고 [계획 세우기]를 누르세요.")
        self.status_label.setProperty("role", "hint")
        btn_row.addWidget(self.status_label, 1)
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setProperty("role", "stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        self.start_btn = QPushButton("발행 시작")
        self.start_btn.setProperty("role", "go")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)

        root.addWidget(_section("진행 로그"))
        self.log = _log_box()
        root.addWidget(self.log, 1)

        # 위젯이 다 만들어진 뒤에 연결합니다 (만드는 도중 신호가 튀면 없는 위젯을 건드립니다)
        self.company_combo.currentTextChanged.connect(self._invalidate)
        self.now_radio.toggled.connect(self._on_mode_changed)
        self.start_edit.dateTimeChanged.connect(self._invalidate)
        for s in (self.spread_min, self.spread_max):
            s.valueChanged.connect(self._invalidate)
        self._apply_mode_enabled()

    # ── 입력값 ────────────────────────────────────
    @staticmethod
    def _spin(lo: int, hi: int, val: int, suffix: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSuffix(f" {suffix}")
        return s

    @staticmethod
    def _default_start() -> QDateTime:
        t = company_batch._ceil10(dt.datetime.now() + dt.timedelta(hours=1))
        return QDateTime.fromString(t.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm")

    def _start_dt(self) -> dt.datetime:
        s = self.start_edit.dateTime().toString("yyyy-MM-dd HH:mm")
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")

    def _mode(self) -> str:
        return (company_batch.MODE_SCHEDULE if self.sched_radio.isChecked()
                else company_batch.MODE_NOW)

    @staticmethod
    def _pair(a: QSpinBox, b: QSpinBox, scale: int = 1) -> tuple[int, int]:
        x, y = a.value() * scale, b.value() * scale
        return (min(x, y), max(x, y))

    # ── 상태 전환 ──────────────────────────────────
    def _apply_mode_enabled(self):
        sched = self.sched_radio.isChecked()
        for w in (self.start_edit, self.spread_min, self.spread_max):
            w.setEnabled(sched)

    def _on_mode_changed(self, *_):
        self._apply_mode_enabled()
        self._invalidate()

    def _invalidate(self, *_):
        """설정이 바뀌면 세워둔 계획을 버립니다. 옛 계획으로 발행되는 사고를 막습니다."""
        if self._stop_event is not None:          # 실행 중에는 건드리지 않습니다
            return
        if self._rows:
            self._rows = []
            self.table.setRowCount(0)
            self.status_label.setText("설정이 바뀌었습니다. [계획 세우기]를 다시 누르세요.")
        self.start_btn.setEnabled(False)

    def _set_running(self, on: bool):
        self.plan_btn.setEnabled(not on)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(on)
        for w in (self.company_combo, self.now_radio, self.sched_radio, self.start_edit,
                  self.spread_min, self.spread_max, self.gap_min, self.gap_max,
                  self.posting_edit):
            w.setEnabled(not on)
        self.progress.setVisible(on)
        if not on:
            self._apply_mode_enabled()

    # ── 계획 ──────────────────────────────────────
    def _make_plan(self):
        company = self.company_combo.currentText().strip()
        if not company:
            return
        mode = self._mode()
        start = None
        if mode == company_batch.MODE_SCHEDULE:
            start = self._start_dt()
            lead = dt.datetime.now() + dt.timedelta(minutes=company_batch.MIN_LEAD_MIN)
            if start < lead:
                QMessageBox.warning(
                    self, "예약 시각",
                    f"예약 시작은 지금부터 {company_batch.MIN_LEAD_MIN}분 이후로 잡아주세요.")
                return
        spread = self._pair(self.spread_min, self.spread_max)

        self.status_label.setText("계획을 세우는 중… (계정 로그인 상태를 확인합니다)")
        QApplication.processEvents()
        try:
            name, rows = company_batch.build_plan(company, mode, start, spread)
        except Exception as e:
            self.status_label.setText("계획을 세우지 못했습니다.")
            QMessageBox.warning(self, "계획 실패", str(e))
            return

        # 발행할 계정을 위로, 건너뛸 계정을 아래로 모읍니다. 묶음 안의 순서는 그대로입니다.
        rows = sorted(rows, key=lambda r: r.skip)
        self._company, self._rows = name, rows
        self._plan_mode, self._plan_spread = mode, spread
        self._fill_table()

        active = [r for r in rows if not r.skip]
        overlap = [r for r in active if r.note.startswith("겹침")]
        msg = f"{name} · 발행 {len(active)}편 · 건너뜀 {len(rows) - len(active)}개"
        if overlap:
            msg += f" · 주제 겹침 {len(overlap)}건"
        self.status_label.setText(msg)
        self.start_btn.setEnabled(bool(active))

    def _fill_table(self):
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            if r.when:
                when = f"{r.when:%m/%d %H:%M}"
            elif not r.skip and self._plan_mode == company_batch.MODE_NOW:
                when = "지금"
            else:
                when = ""
            result = self._STATUS.get(r.status, r.status)
            if r.status == "failed" and r.message:
                result = f"{result} · {r.message[:40]}"
            vals = [r.account, personas.name(r.persona),
                    topics.name(r.topic) if r.topic else "-",
                    r.category or "기본", when, r.note, result]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if r.skip:
                    item.setForeground(QColor(C["faint"]))
                self.table.setItem(i, c, item)

    # ── 실행 ──────────────────────────────────────
    def _start(self):
        active = [r for r in self._rows if not r.skip]
        if not active:
            return
        how = ("지금 바로 발행" if self._plan_mode == company_batch.MODE_NOW
               else "예약 발행")
        lines = [f"· {r.account}  {topics.name(r.topic)}"
                 + (f"  {r.when:%m/%d %H:%M}" if r.when else "") for r in active]
        ret = QMessageBox.question(
            self, "발행 확인",
            f"{self._company} 글 {len(active)}편을 {how}합니다.\n"
            "발행은 되돌릴 수 없습니다.\n\n" + "\n".join(lines) + "\n\n시작할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return

        posting = self.posting_edit.toPlainText().strip() or None
        self._stop_event = threading.Event()
        self._set_running(True)
        self.log.clear()
        self.status_label.setText(f"{self._company} · {how} 진행 중…")
        run_in_thread(
            self, company_batch.run_plan,
            self._append_log, self._on_done, self._on_error,
            self._company, self._rows, self._plan_mode, posting,
            gap=self._pair(self.gap_min, self.gap_max, 60),
            spread=self._plan_spread, stop_event=self._stop_event,
        )

    def _append_log(self, text: str) -> None:
        self.log.insertPlainText(text)
        self.log.ensureCursorVisible()
        if "✅" in text or "❌" in text:
            self._fill_table()

    def _stop(self):
        if self._stop_event is not None:
            self._stop_event.set()
        self.stop_btn.setEnabled(False)
        self.status_label.setText("중지 요청 — 지금 작업 중인 계정까지만 마치고 멈춥니다.")

    def _finish(self):
        self._stop_event = None
        self._set_running(False)
        self._fill_table()

    def _on_done(self, _rows):
        self._finish()
        ok = [r for r in self._rows if r.status in ("published", "scheduled")]
        bad = [r for r in self._rows if r.status in ("failed", "skipped", "stopped")]
        self.status_label.setText(
            f"끝 · 성공 {len(ok)}편 · 실패·건너뜀 {len(bad)}개. "
            "다시 하려면 [계획 세우기]부터 누르세요.")
        if bad:
            QMessageBox.information(
                self, "처리하지 못한 계정",
                "\n".join(f"· {r.account}: {r.message or r.note}" for r in bad)
                + "\n\n로그인이 끊긴 계정은 [발행] 탭의 [계정 추가·재로그인]으로 "
                  "다시 로그인한 뒤 계획을 새로 세우세요.")

    def _on_error(self, tb: str):
        self._finish()
        self.status_label.setText("오류로 멈췄습니다. 로그를 확인하세요.")
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


# ───────────────────────── 인스타 1: 자료 준비 ─────────────────────────
def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))


class InstaAssetsTab(QWidget):
    """카드뉴스에 들어갈 로고·사진이 준비됐는지 봅니다.

    사진은 사람이 폴더에 넣습니다. 이 탭은 빠진 것을 보여주고 폴더를 열어줄 뿐,
    인스타 계정에는 아무 요청도 보내지 않습니다.
    """

    def __init__(self):
        super().__init__()
        self._rows: list[tuple[str, Path | None, Path | None, int]] = []
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

        guide = QLabel(
            "기업 폴더에 <b>로고.png</b>와 <b>건물.jpg</b>를, <b>_톰슨에듀AI</b> 폴더에 "
            "<b>로고.png</b>를 넣고 새로고침하세요. 파일 규칙은 사진 폴더의 "
            "<b>_사진_넣는_법.txt</b>에 있습니다.")
        guide.setProperty("role", "info")
        guide.setWordWrap(True)
        root.addWidget(guide)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)

        common_panel = QWidget()
        common_layout = QVBoxLayout(common_panel)
        common_layout.setContentsMargins(0, 0, 0, 0)
        common_layout.setSpacing(4)
        common_layout.addWidget(_section("톰슨에듀AI 공통 자료"))
        self.common = self._make_table(["항목", "상태", "파일"])
        self.common.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.common.setColumnWidth(0, 200)
        self.common.setColumnWidth(1, 250)
        common_layout.addWidget(self.common)
        split.addWidget(common_panel)

        company_panel = QWidget()
        company_layout = QVBoxLayout(company_panel)
        company_layout.setContentsMargins(0, 0, 0, 0)
        company_layout.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_section("기업별 사진"))
        head.addStretch()
        self.only_missing = QCheckBox("빠진 기업만 보기")
        self.only_missing.toggled.connect(self._fill_table)
        head.addWidget(self.only_missing)
        company_layout.addLayout(head)
        self.table = self._make_table(["기업명", "로고", "건물 사진", "만든 카드"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(3, 90)
        self.table.cellDoubleClicked.connect(self._open_selected)
        company_layout.addWidget(self.table)
        split.addWidget(company_panel)

        split.setSizes([230, 420])
        root.addWidget(split, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        open_btn = QPushButton("선택한 기업 폴더 열기")
        open_btn.setProperty("role", "primary")
        open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(open_btn)
        brand_btn = QPushButton("_톰슨에듀AI 폴더 열기")
        brand_btn.clicked.connect(lambda: _open_folder(insta_cards.BRAND_DIR))
        btn_row.addWidget(brand_btn)
        all_btn = QPushButton("사진 폴더 전체 열기")
        all_btn.clicked.connect(lambda: _open_folder(insta_cards.ASSET_DIR))
        btn_row.addWidget(all_btn)
        btn_row.addStretch()
        hint = QLabel("기업 줄을 두 번 누르면 그 폴더가 열립니다")
        hint.setProperty("role", "hint")
        btn_row.addWidget(hint)
        root.addLayout(btn_row)

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        for col in range(len(headers)):
            t.horizontalHeaderItem(col).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setSelectionMode(QTableWidget.SingleSelection)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(30)
        t.setShowGrid(False)
        return t

    @staticmethod
    def _cell(text: str, fg: str = "") -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if fg:
            item.setForeground(QColor(fg))
        return item

    @staticmethod
    def _photo_state(path: Path | None, cover: bool) -> tuple[str, str]:
        """(표시 글자, 글자색). 표지는 1080×1350 칸을 꽉 채우므로 작거나 가로면 경고합니다."""
        if not path:
            return "없음", C["err_fg"]
        size = QImageReader(str(path)).size()
        w, h = size.width(), size.height()
        if w <= 0 or h <= 0:
            return f"{path.name} · 읽을 수 없는 파일", C["err_fg"]
        text = f"{path.name} · {w}×{h}"
        # 표지 위쪽 사진 칸(1080×780)을 채우는지 봅니다. 가로가 잘 맞고 세로는 위아래가 잘립니다
        if cover and max(insta_cards.COVER_PHOTO_W / w, insta_cards.COVER_PHOTO_H / h) > 1:
            return text + " · 작아서 흐려질 수 있음", C["warn_fg"]
        return text, C["ok_fg"]

    def refresh(self):
        companies = md_loader.list_companies()
        insta_cards.ensure_folders(companies)

        logo, white = insta_cards.brand_logos()
        common = [
            ("톰슨에듀AI 로고", *(("있음", C["ok_fg"]) if logo
                             else ("없음 · 지금은 '톰슨에듀AI' 글자로 들어감", C["err_fg"])),
             logo.name if logo else "_톰슨에듀AI\\로고.png"),
            ("톰슨에듀AI 흰색 로고 (선택)", *(("있음", C["ok_fg"]) if white
                                       else ("없음 · 표지에는 흰 글자로 들어감", C["faint"])),
             white.name if white else "_톰슨에듀AI\\로고_흰색.png"),
        ]
        own_shots = 0
        for key, label in insta_cards.FEATURE_LABEL.items():
            shot, own = insta_cards.feature_shot(key)
            own_name = insta_cards.FEATURE_SHOTS[key][0] + ".png"
            if shot and own:
                own_shots += 1
                common.append((f"캡처 · {label}", "인스타 전용 캡처", C["ok_fg"], shot.name))
            elif shot:
                common.append((f"캡처 · {label}", "블로그용 캡처로 대신하는 중", C["warn_fg"],
                               f"images\\{shot.name}  →  _톰슨에듀AI\\{own_name} 넣으면 교체"))
            else:
                common.append((f"캡처 · {label}", "없음", C["err_fg"], f"_톰슨에듀AI\\{own_name}"))
        common.append(("인스타 토큰", *(("있음 (.env)", C["ok_fg"]) if config.INSTAGRAM_ACCESS_TOKEN
                                       else ("없음", C["err_fg"])), ""))
        common.append(("임시 주소 프로그램", *(("있음", C["ok_fg"]) if insta_publish.CLOUDFLARED.exists()
                                             else ("없음 · 발행 전에 필요", C["err_fg"])),
                       "tools\\cloudflared.exe"))

        self.common.setRowCount(len(common))
        for i, (name, state, fg, file) in enumerate(common):
            self.common.setItem(i, 0, self._cell(name))
            self.common.setItem(i, 1, self._cell(state, fg))
            self.common.setItem(i, 2, self._cell(file, C["soft"]))

        self._rows = []
        for name in companies:
            c_logo, c_cover = insta_cards.company_assets(name)
            self._rows.append((name, c_logo, c_cover, len(insta_cards.made_cards(name))))
        ready = sum(1 for _, l, c, _ in self._rows if l and c)

        self.summary.setText(
            f"기업 {len(companies)}곳 중 로고·건물 사진 모두 있는 곳 {ready}곳     "
            f"톰슨에듀AI 로고 {'있음' if logo else '없음'}     "
            f"인스타 전용 캡처 {own_shots}/{len(insta_cards.FEATURE_LABEL)}")
        self.summary.setProperty("tone", "ok" if ready and logo else "warn")
        _restyle(self.summary)
        self._fill_table()

    def _fill_table(self, *_):
        rows = [r for r in self._rows
                if not (self.only_missing.isChecked() and r[1] and r[2])]
        self.table.setRowCount(len(rows))
        for i, (name, logo, cover, cards) in enumerate(rows):
            self.table.setItem(i, 0, self._cell(name))
            self.table.setItem(i, 1, self._cell(*self._photo_state(logo, cover=False)))
            self.table.setItem(i, 2, self._cell(*self._photo_state(cover, cover=True)))
            self.table.setItem(i, 3, self._cell(f"{cards}장" if cards else "-",
                                                C["ok_fg"] if cards else C["faint"]))

    def _open_selected(self, *_):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if not item:
            QMessageBox.information(self, "기업 선택", "표에서 기업을 먼저 고르세요.")
            return
        _open_folder(insta_cards.ASSET_DIR / item.text())


# ───────────────────────── 인스타: 카드 한 장 글자 수정 창 ─────────────────────────
class InstaCardEditDialog(QDialog):
    """카드 한 장의 글자를 고칩니다.

    [미리보기]는 저장하지 않고 그려만 보고, [저장]은 deck.json 을 고친 뒤 그 카드 한 장만 다시 그립니다.
    글자가 카드 밖으로 넘치면 알려줍니다 (카드는 넘친 글자를 조용히 잘라버리므로).
    """

    TYPE_LABEL = {"cover": "표지", "intro": "기업 소개", "checks": "체크 목록", "rows": "표",
                  "steps": "준비 단계", "features": "톰슨에듀AI 기능", "outro": "마무리"}
    # (필드, 화면 이름, 종류)  종류: text 여러 줄 · line 짧은 문구 · list 항목 목록 · pairs 두 칸 목록 · features
    FIELDS = {
        "cover":    [("title", "제목", "text"), ("sub", "부제", "line"), ("tag", "말풍선 (선택)", "line")],
        "intro":    [("title", "제목", "text"), ("lead", "설명 문장", "text"),
                     ("facts", "정보 칸 (항목 / 내용)", "pairs"), ("concl", "결론", "text")],
        "checks":   [("title", "제목", "text"), ("items", "체크 항목", "list"), ("concl", "결론", "text")],
        "rows":     [("title", "제목", "text"), ("rows", "표 (머리 / 내용)", "pairs"),
                     ("concl", "결론", "text")],
        "steps":    [("title", "제목", "text"), ("items", "준비 단계", "list"), ("concl", "결론", "text")],
        "features": [("kicker", "말머리", "line"), ("title", "제목", "text"),
                     ("features", "소개할 기능", "features")],
        "outro":    [("title", "제목", "text"), ("items", "정리 항목", "list"),
                     ("save", "저장 유도 문구", "line"), ("band", "맨 아래 띠 문구", "line")],
    }
    PREVIEW_W = 360

    def __init__(self, parent, company: str, index: int):
        super().__init__(parent)
        self.company, self.index = company, index
        self.card = dict(insta_cards.load_deck(company)["cards"][index])
        self._kind = self.card.get("type", "")
        self._texts: dict[str, QPlainTextEdit] = {}
        self._lists: dict[str, tuple[QVBoxLayout, list, bool]] = {}
        self._feats: list[tuple[QComboBox, QPlainTextEdit, QPlainTextEdit]] = []
        self._image_path = ""
        self._temp_preview = ""
        self._working = False
        self.setWindowTitle(f"{company} · {index + 1}번 카드 "
                            f"({self.TYPE_LABEL.get(self._kind, self._kind)}) 글자 수정")
        self.resize(1000, 760)
        self._build()
        cards = insta_cards.made_cards(company)
        if index < len(cards):
            self._set_image(str(cards[index]))

    # ── 화면 ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.image = QLabel()
        self.image.setProperty("role", "status")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedSize(self.PREVIEW_W + 4,
                                round(self.PREVIEW_W * insta_cards.H / insta_cards.W) + 4)
        left.addWidget(self.image)
        row = QHBoxLayout()
        self.preview_btn = QPushButton("미리보기")
        self.preview_btn.setToolTip("저장하지 않고 고친 글자로 그려만 봅니다")
        self.preview_btn.clicked.connect(self._preview)
        row.addWidget(self.preview_btn)
        big_btn = QPushButton("크게 보기")
        big_btn.clicked.connect(self._open_image)
        row.addWidget(big_btn)
        row.addStretch()
        left.addLayout(row)
        self.status = QLabel("글자를 고친 뒤 [미리보기]로 확인하고 [저장]을 누르세요.")
        self.status.setProperty("role", "status")
        self.status.setWordWrap(True)
        self.status.setFixedWidth(self.PREVIEW_W + 4)
        left.addWidget(self.status)
        left.addStretch()
        body.addLayout(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.form = QVBoxLayout(host)
        self.form.setContentsMargins(0, 0, 10, 0)
        self.form.setSpacing(6)
        hint = QLabel("줄바꿈은 카드에서도 줄바꿈  ·  <b>*강조*</b> 는 강조색 글자  ·  "
                      "<b>==밑줄==</b> 은 형광 밑줄")
        hint.setProperty("role", "info")
        hint.setWordWrap(True)
        self.form.addWidget(hint)
        for name, label, kind in self.FIELDS.get(self._kind, []):
            self.form.addWidget(_section(label))
            value = self.card.get(name)
            if kind in ("text", "line"):
                e = self._editor(value, 78 if kind == "text" else 50)
                self._texts[name] = e
                self.form.addWidget(e)
            elif kind in ("list", "pairs"):
                self._add_list(name, value or [], pair=(kind == "pairs"))
            elif kind == "features":
                for f in value or []:
                    self._add_feature(f)
        self.form.addStretch()
        scroll.setWidget(host)
        body.addWidget(scroll, 1)
        root.addLayout(body, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        self.save_btn = QPushButton("저장하고 카드 다시 만들기")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(self.save_btn)
        root.addLayout(btns)

    @staticmethod
    def _editor(text, height: int) -> QPlainTextEdit:
        e = QPlainTextEdit(str(text or ""))
        e.setFixedHeight(height)
        return e

    def _add_list(self, name: str, values: list, pair: bool):
        box = QVBoxLayout()
        box.setSpacing(6)
        self._lists[name] = (box, [], pair)
        for v in values:
            self._add_item(name, v)
        self.form.addLayout(box)
        add = QPushButton("+ 항목 추가")
        add.clicked.connect(lambda _=False, n=name: self._add_item(n, None))
        self.form.addWidget(add, 0, Qt.AlignLeft)

    def _add_item(self, name: str, value):
        box, entries, pair = self._lists[name]
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        if pair:
            k = self._editor((value or ["", ""])[0], 64)
            k.setFixedWidth(170)
            v = self._editor((value or ["", ""])[1], 64)
            h.addWidget(k)
            h.addWidget(v, 1)
            editors = (k, v)
        else:
            e = self._editor(value, 64)
            h.addWidget(e, 1)
            editors = (e,)
        rm = QPushButton("삭제")
        rm.setProperty("role", "danger-text")
        entry = (row, editors)
        rm.clicked.connect(lambda _=False, n=name, en=entry: self._remove_item(n, en))
        h.addWidget(rm, 0, Qt.AlignTop)
        box.addWidget(row)
        entries.append(entry)

    def _remove_item(self, name: str, entry):
        _box, entries, _pair = self._lists[name]
        for i, en in enumerate(entries):
            if en is entry:
                del entries[i]
                entry[0].setParent(None)
                entry[0].deleteLater()
                break

    def _add_feature(self, f: dict):
        row = QWidget()
        g = QGridLayout(row)
        g.setContentsMargins(0, 0, 0, 6)
        g.setSpacing(6)
        combo = QComboBox()
        for key, label in insta_cards.FEATURE_LABEL.items():
            combo.addItem(label, key)
        combo.setCurrentIndex(max(combo.findData(f.get("key")), 0))
        title = self._editor(f.get("title"), 50)
        desc = self._editor(f.get("desc"), 64)
        for r, (label, w) in enumerate((("화면", combo), ("이름", title), ("설명", desc))):
            g.addWidget(QLabel(label), r, 0, Qt.AlignTop)
            g.addWidget(w, r, 1)
        self.form.addWidget(row)
        self._feats.append((combo, title, desc))

    # ── 값 모으기 ──
    def _collect(self) -> dict:
        c = dict(self.card)
        for name, _label, kind in self.FIELDS.get(self._kind, []):
            if kind in ("text", "line"):
                val = self._texts[name].toPlainText().strip()
                if val:
                    c[name] = val
                else:
                    c.pop(name, None)
            elif kind in ("list", "pairs"):
                _box, entries, pair = self._lists[name]
                vals = []
                for _row, editors in entries:
                    texts = [e.toPlainText().strip() for e in editors]
                    if any(texts):          # 비워둔 항목은 뺍니다
                        vals.append(texts if pair else texts[0])
                c[name] = vals
            elif kind == "features":
                c[name] = [{"key": combo.currentData(), "title": t.toPlainText().strip(),
                            "desc": d.toPlainText().strip()} for combo, t, d in self._feats]
        return c

    def _checked_card(self) -> dict | None:
        card = self._collect()
        if not card.get("title"):
            QMessageBox.warning(self, "제목 없음", "제목은 비워둘 수 없습니다.")
            return None
        return card

    # ── 미리보기 · 저장 ──
    def _busy(self, on: bool, text: str = ""):
        self._working = on
        self.preview_btn.setEnabled(not on)
        self.save_btn.setEnabled(not on)
        if text:
            _set_status(self.status, text)

    def _preview(self):
        card = self._checked_card()
        if card:
            self._busy(True, "고친 글자로 그리는 중… (저장은 안 됩니다)")
            run_in_thread(self, insta_cards.preview_card, self._ignore_log, self._on_preview,
                          self._on_fail, self.company, self.index, card)

    def _save(self):
        card = self._checked_card()
        if card:
            self._busy(True, "저장하고 카드를 다시 그리는 중…")
            run_in_thread(self, insta_cards.save_card, self._ignore_log, self._on_saved,
                          self._on_fail, self.company, self.index, card)

    def _ignore_log(self, _text: str):
        pass

    def _on_preview(self, result):
        path, issues = result
        self._busy(False)
        self._drop_temp()
        self._temp_preview = path
        self._set_image(path)
        self._show_issues(issues, "미리보기입니다. 아직 저장하지 않았습니다.")

    def _on_saved(self, issues: list):
        self._busy(False)
        self.card = self._collect()
        cards = insta_cards.made_cards(self.company)
        if self.index < len(cards):
            self._set_image(str(cards[self.index]))
        if issues:
            # 문제가 있는 채로 창을 닫으면 모르고 발행하기 쉬워서, 창을 열어둔 채 알려줍니다
            self._show_issues(issues, "")
            QMessageBox.warning(self, "확인할 점",
                                "저장은 했지만 확인할 점이 있습니다.\n\n" + "\n".join(issues)
                                + "\n\n문구를 줄이거나 줄바꿈 위치를 바꿔 다시 저장하세요.")
            return
        self.accept()

    def _on_fail(self, tb: str):
        self._busy(False)
        _set_status(self.status, "실패했습니다: " + tb.strip().splitlines()[-1][:160], tone="err")

    def _show_issues(self, issues: list, ok_text: str):
        if issues:
            _set_status(self.status, "⚠ " + "\n⚠ ".join(issues), tone="warn")
        else:
            _set_status(self.status, ok_text, tone="ok")

    def _set_image(self, path: str):
        self._image_path = path
        pix = QPixmap(path)
        self.image.setPixmap(pix.scaled(self.PREVIEW_W, round(self.PREVIEW_W * insta_cards.H / insta_cards.W),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _open_image(self):
        if self._image_path and Path(self._image_path).exists():
            os.startfile(self._image_path)

    def _drop_temp(self):
        if self._temp_preview:
            try:
                Path(self._temp_preview).unlink()
            except OSError:
                pass
            self._temp_preview = ""

    def done(self, result: int):
        # 그리는 중에 창을 닫으면 작업이 끝난 뒤 없는 창을 건드리므로 막습니다
        if self._working:
            return
        self._drop_temp()
        super().done(result)


# ───────────────────────── 인스타: 스타일(틀 × 색) 고르기 ─────────────────────────
class InstaStylePicker(QWidget):
    """카드뉴스 스타일 고르기. [카드뉴스 만들기] 탭과 [카드 확인·발행] 탭이 같이 씁니다.

    틀 카드에 마우스를 올리면 표지+본문 미리보기 그림이 뜹니다. 그림은 처음 한 번만 브라우저로 만들고
    이후엔 저장된 파일을 씁니다. 고르는 곳이 여러 개여도 한 번만 만들어 함께 씁니다.
    """

    _previews: dict | None = None
    _preview_failed = False
    _loading = False
    _pickers: list = []

    def __init__(self):
        super().__init__()
        self._frame = insta_cards.DEFAULT_STYLE["frame"]
        self._frame_btns: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel("스타일"))
        for key, f in insta_cards.FRAMES.items():
            btn = QPushButton()
            btn.setProperty("role", "topic")
            btn.setMinimumSize(190, 52)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._pick_frame(k))
            v = QVBoxLayout(btn)
            v.setContentsMargins(10, 7, 10, 7)
            v.setSpacing(2)
            v.setSizeConstraint(QLayout.SetMinimumSize)   # 글자가 늘어나면 카드도 같이 늘어나게
            nm = QLabel(f["label"])
            nm.setProperty("role", "tname")
            v.addWidget(nm)
            tag = QLabel(f["desc"])
            tag.setProperty("role", "twhy")
            v.addWidget(tag)
            self._frame_btns[key] = btn
            row.addWidget(btn)
        row.addSpacing(12)

        colors = QVBoxLayout()
        colors.setSpacing(2)
        self.color_group = QButtonGroup(self)
        self.color_base = QRadioButton("기본색")
        self.color_brand = QRadioButton("기업색")
        self.color_group.addButton(self.color_base)
        self.color_group.addButton(self.color_brand)
        self.color_base.setChecked(True)
        colors.addWidget(self.color_base)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(6)
        brand_row.addWidget(self.color_brand)
        self.brand_swatch = QLabel()
        self.brand_swatch.setToolTip("기업 로고에서 뽑은 색입니다. 배경에 맞춰 밝기는 자동으로 조절됩니다.")
        brand_row.addWidget(self.brand_swatch)
        brand_row.addStretch()
        colors.addLayout(brand_row)
        row.addLayout(colors)
        self._mark_frame()

        cls = InstaStylePicker
        cls._pickers.append(self)
        if cls._previews is not None:
            self._apply_previews(cls._previews, cls._preview_failed)
        else:
            self._apply_previews({}, False)
            if not cls._loading:
                cls._loading = True
                run_in_thread(self, insta_cards.style_previews, self._ignore_log,
                              self._on_previews, self._on_preview_error)

    # ── 바깥에서 쓰는 것 ──
    def frame(self) -> str:
        return self._frame

    def color(self) -> str:
        return "brand" if self.color_brand.isChecked() else "base"

    def set_company(self, company: str):
        """기업색 칸을 그 기업 로고 색으로 바꿉니다. 로고에서 색을 못 뽑으면 기업색을 고를 수 없습니다."""
        rgb = insta_cards.brand_color(company) if company else None
        if rgb:
            hx = insta_cards.hex_color(rgb)
            self.brand_swatch.setText(f"<span style='color:{hx}; font-size:13pt'>■</span> {hx}")
        else:
            self.brand_swatch.setText("<span style='color:#8b94a3'>로고 없음</span>")
        self.color_brand.setEnabled(bool(rgb))
        if not rgb:
            self.color_base.setChecked(True)

    def set_style(self, style: dict | None):
        s = style or insta_cards.DEFAULT_STYLE
        self._frame = s.get("frame") if s.get("frame") in insta_cards.FRAMES \
            else insta_cards.DEFAULT_STYLE["frame"]
        use_brand = s.get("color") == "brand" and self.color_brand.isEnabled()
        (self.color_brand if use_brand else self.color_base).setChecked(True)
        self._mark_frame()

    # ── 안쪽 ──
    @staticmethod
    def _frame_tip(key: str, preview: Path | None, failed: bool = False) -> str:
        """마우스를 올리면 뜨는 미리보기. 틀은 설명보다 그림으로 봐야 감이 옵니다."""
        f = insta_cards.FRAMES[key]
        if preview:
            img = f"<br><img src='{preview.as_posix()}' width='440'>"
        else:
            msg = "미리보기 그림을 만들지 못했습니다" if failed else "미리보기 그림을 만드는 중…"
            img = f"<br><span style='color:#6b7280'>{msg}</span>"
        return f"<b>{html.escape(f['label'])}</b> — {html.escape(f['desc'])}{img}"

    def _apply_previews(self, paths: dict, failed: bool):
        for key, btn in self._frame_btns.items():
            btn.setToolTip(self._frame_tip(key, paths.get(key), failed))

    def _ignore_log(self, _text: str):
        pass

    def _on_previews(self, paths: dict):
        InstaStylePicker._previews = paths
        for p in InstaStylePicker._pickers:
            p._apply_previews(paths, False)

    def _on_preview_error(self, _tb: str):
        InstaStylePicker._previews, InstaStylePicker._preview_failed = {}, True
        for p in InstaStylePicker._pickers:
            p._apply_previews({}, True)

    def _pick_frame(self, key: str):
        self._frame = key
        self._mark_frame()

    def _mark_frame(self):
        for key, btn in self._frame_btns.items():
            btn.setProperty("sel", "1" if key == self._frame else "0")
            _restyle(btn)


# ───────────────────────── 인스타 1: 카드뉴스 만들기 ─────────────────────────
class InstaMakeTab(QWidget):
    """기업을 고르면 공기업 분석 자료로 카드 8장 문구와 캡션을 쓰고, 고른 스타일로 카드를 만듭니다.

    Claude API 로 문구를 쓰므로 한 번에 1~2분 걸리고, 검사에서 문제가 나와 다시 쓰면 그만큼 더 걸립니다.
    인스타 발행은 여기서 하지 않습니다. [카드 확인·발행] 탭에서 확인한 뒤 따로 합니다.
    """

    open_cards = Signal(str)      # [만든 카드 보기] → 카드 확인·발행 탭으로 넘어갑니다

    def __init__(self):
        super().__init__()
        self._running = False
        self._last = ""
        self._rows: list[tuple] = []
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        info = QLabel("표에서 기업을 고르고 스타일을 정한 뒤 <b>[카드뉴스 만들기]</b>를 누르세요. "
                      "공기업 분석 자료로 카드 8장 문구와 캡션을 쓰고 카드까지 그립니다 (1~2분). "
                      "인스타 발행은 <b>[카드 확인·발행]</b> 탭에서 확인한 뒤 따로 합니다.")
        info.setProperty("role", "info")
        info.setWordWrap(True)
        root.addWidget(info)

        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("role", "status")
        top.addWidget(self.summary, 1)
        self.only_new = QCheckBox("아직 안 만든 기업만")
        self.only_new.toggled.connect(self._fill)
        top.addWidget(self.only_new)
        self.refresh_btn = QPushButton("새로고침")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        self.table = InstaAssetsTab._make_table(["기업명", "사진", "카드", "인스타 발행"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 230)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(3, 150)
        self.table.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self.table)
        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_layout.addWidget(_section("진행 로그"))
        self.log = _log_box()
        log_layout.addWidget(self.log)
        split.addWidget(log_panel)
        split.setSizes([360, 170])
        root.addWidget(split, 1)

        post_head = QHBoxLayout()
        post_head.addWidget(_section("채용공고 (선택) — 붙여넣으면 자료와 다른 부분은 공고를 따릅니다"))
        post_head.addStretch()
        self.posting_state = QLabel()
        self.posting_state.setProperty("role", "hint")
        post_head.addWidget(self.posting_state)
        root.addLayout(post_head)
        self.posting_edit = QPlainTextEdit()
        self.posting_edit.setPlaceholderText(
            "공고 원문을 그대로 붙여넣으세요. 기업을 고르면 저장해 둔 공고가 있으면 불러옵니다.\n"
            "비워두면 공기업 분석 자료만으로 씁니다. 날짜·채용 인원은 카드에 넣지 않습니다.")
        self.posting_edit.setFixedHeight(64)
        self.posting_edit.textChanged.connect(self._update_posting_state)
        root.addWidget(self.posting_edit)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.picker = InstaStylePicker()
        row.addWidget(self.picker)
        row.addStretch()
        self.caption_chk = QCheckBox("캡션도 새로 쓰기")
        self.caption_chk.setChecked(True)
        self.caption_chk.setToolTip("끄면 지금 캡션을 그대로 둡니다 (캡션이 비어 있으면 끄더라도 새로 씁니다)")
        row.addWidget(self.caption_chk)
        self.view_btn = QPushButton("만든 카드 보기")
        self.view_btn.clicked.connect(self._view)
        row.addWidget(self.view_btn)
        self.make_btn = QPushButton("카드뉴스 만들기")
        self.make_btn.setProperty("role", "primary")
        self.make_btn.clicked.connect(self._make)
        row.addWidget(self.make_btn)
        root.addLayout(row)

        self.status = QLabel("표에서 기업을 고르세요.")
        self.status.setProperty("role", "status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    # ── 표 ──
    def refresh(self):
        current = self._selected()
        self._rows = []
        for name in md_loader.list_companies():
            logo, cover = insta_cards.company_assets(name)
            self._rows.append((name, bool(logo and cover), insta_cards.load_deck(name),
                               len(insta_cards.made_cards(name)), insta_publish.published(name)))
        made = sum(1 for r in self._rows if r[2])
        pub = sum(1 for r in self._rows if r[4])
        self.summary.setText(f"기업 {len(self._rows)}곳     카드 만든 곳 {made}곳     인스타 발행 {pub}곳")
        self._fill()
        self._select(current)
        self._sync()

    def _fill(self, *_):
        current = self._selected()
        rows = [r for r in self._rows if not (self.only_new.isChecked() and r[2])]
        self.table.setRowCount(len(rows))
        for i, (name, photos, deck, cards, rec) in enumerate(rows):
            self.table.setItem(i, 0, InstaAssetsTab._cell(name))
            self.table.setItem(i, 1, InstaAssetsTab._cell(
                "로고·건물 있음" if photos else "사진 빠짐", C["ok_fg"] if photos else C["warn_fg"]))
            made = (f"{cards}장 · {insta_cards.style_label(deck.get('style'))}" if deck and cards
                    else "문구만 있음" if deck else "-")
            self.table.setItem(i, 2, InstaAssetsTab._cell(made, C["ink"] if deck else C["faint"]))
            self.table.setItem(i, 3, InstaAssetsTab._cell(
                rec.get("published_at", "") if rec else "-", C["ok_fg"] if rec else C["faint"]))
        self._select(current)

    def _selected(self) -> str:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item else ""

    def _select(self, company: str):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == company:
                self.table.selectRow(r)
                return

    def _on_select(self):
        company = self._selected()
        if not company:
            return
        self.picker.set_company(company)
        self.posting_edit.setPlainText(insta_gen.load_posting(company))
        deck = insta_cards.load_deck(company)
        if deck:
            self.picker.set_style(deck.get("style"))
            _set_status(self.status, f"{company} · 이미 카드가 있습니다. 다시 만들면 새 문구로 바뀝니다.")
        else:
            _set_status(self.status, f"{company} · 아직 카드뉴스가 없습니다.")
        self._sync()

    def _update_posting_state(self):
        n = len(self.posting_edit.toPlainText().strip())
        self.posting_state.setText(f"공고 {n:,}자 · 자료보다 우선" if n else "공고 없음 · 자료만으로 씁니다")

    def _sync(self):
        idle = not self._running
        for w in (self.table, self.picker, self.caption_chk, self.only_new, self.refresh_btn,
                  self.posting_edit):
            w.setEnabled(idle)
        self.make_btn.setEnabled(idle and bool(self._selected()))
        target = self._selected() or self._last
        self.view_btn.setEnabled(idle and bool(target) and bool(insta_cards.made_cards(target)))

    # ── 만들기 ──
    def _make(self):
        company = self._selected()
        if not company:
            QMessageBox.information(self, "카드뉴스 만들기", "표에서 기업을 먼저 고르세요.")
            return
        if insta_cards.load_deck(company) and QMessageBox.question(
                self, "다시 만들기",
                f"{company}는 이미 카드 문구가 있습니다.\n"
                "새로 쓰면 직접 고친 문구도 새 문구로 바뀝니다 (지금 문구는 deck_이전.json 으로 보관).\n\n"
                "계속할까요?") != QMessageBox.Yes:
            return
        self._running = True
        self._last = company
        self._sync()
        self.log.clear()
        label = insta_cards.style_label({"frame": self.picker.frame(), "color": self.picker.color()})
        _set_status(self.status, f"{company} 카드뉴스를 만드는 중… ({label}) 문구를 쓰는 데 1~2분 걸립니다.")
        run_in_thread(self, insta_gen.create, self._on_log, self._on_done, self._on_error,
                      company, self.picker.frame(), self.picker.color(), self.caption_chk.isChecked(),
                      posting_text=self.posting_edit.toPlainText())

    def _on_log(self, text: str):
        self.log.insertPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_done(self, result: dict):
        self._running = False
        company = result.get("company", self._last)
        self._last = company
        self.refresh()
        self._select(company)
        issues = result.get("issues") or []
        if issues:
            _set_status(self.status, f"{company} 카드를 만들었습니다. 확인할 점 {len(issues)}건이 남았습니다 — "
                                     "[만든 카드 보기]에서 해당 카드를 눌러 고치세요.", tone="warn")
        else:
            _set_status(self.status, f"{company} 카드 8장과 캡션을 만들었습니다. [만든 카드 보기]로 확인하세요.",
                        tone="ok")
        self._sync()

    def _on_error(self, tb: str):
        self._running = False
        self.log.insertPlainText("\n" + tb)
        _set_status(self.status, "만들지 못했습니다: " + tb.strip().splitlines()[-1][:160], tone="err")
        self._sync()

    def _view(self):
        company = self._selected() or self._last
        if company:
            self.open_cards.emit(company)


# ───────────────────────── 인스타 2: 카드 확인·발행 ─────────────────────────
class InstaCardsTab(QWidget):
    """만든 카드뉴스를 한 장씩 확인·수정하고, 캡션을 붙여 인스타에 발행합니다.
    스타일만 바꿔 다시 그릴 수도 있습니다 (문구는 그대로).

    발행은 되돌릴 수 없으므로 확인 창을 거친 뒤에만 인스타에 요청을 보냅니다.
    [임시 주소 시험]은 인스타에는 아무것도 보내지 않습니다.
    """

    THUMB_W = 190               # 3장 × (190+14) + 간격이 왼쪽 칸 안에 들어가 가로 스크롤이 안 생기는 폭
    COLS = 3

    def __init__(self):
        super().__init__()
        self._running = False
        self._loading = False       # 캡션을 파일에서 불러오는 중에는 다시 저장하지 않습니다
        self._style_company: str | None = None   # 스타일 선택을 마지막으로 맞춘 기업
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("기업"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.currentTextChanged.connect(self._show)
        top.addWidget(self.combo)
        top.addStretch()
        open_btn = QPushButton("카드 폴더 열기")
        open_btn.clicked.connect(self._open_folder)
        top.addWidget(open_btn)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        root.addLayout(top)

        # ── 스타일: 틀 × 색 (문구는 그대로 두고 스타일만 바꿔 다시 그릴 때) ──
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        self.picker = InstaStylePicker()
        style_row.addWidget(self.picker)
        style_row.addStretch()

        self.make_btn = QPushButton("이 스타일로 다시 그리기")
        self.make_btn.setToolTip("문구는 그대로 두고 고른 스타일로 카드 그림만 다시 만듭니다")
        self.make_btn.setProperty("role", "primary")
        self.make_btn.clicked.connect(self._make_cards)
        style_row.addWidget(self.make_btn)
        root.addLayout(style_row)

        self.status = QLabel()
        self.status.setProperty("role", "status")
        root.addWidget(self.status)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(host)
        split.addWidget(scroll)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(6)
        cap_head = QHBoxLayout()
        cap_head.addWidget(_section("캡션"))
        cap_head.addStretch()
        self.caption_btn = QPushButton("캡션 새로 쓰기")
        self.caption_btn.setToolTip("카드 문구는 그대로 두고, 자료를 보고 캡션·해시태그만 새로 씁니다 (Claude API 사용)")
        self.caption_btn.clicked.connect(self._rewrite_caption)
        cap_head.addWidget(self.caption_btn)
        side_layout.addLayout(cap_head)
        self.caption = QPlainTextEdit()
        self.caption.setPlaceholderText(
            "게시글 본문과 해시태그를 적으세요.\n"
            "적는 대로 기업 카드 폴더의 caption.txt 에 저장됩니다.")
        self.caption.textChanged.connect(self._on_caption_changed)
        side_layout.addWidget(self.caption, 3)
        self.count = QLabel()
        self.count.setProperty("role", "hint")
        side_layout.addWidget(self.count)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.test_btn = QPushButton("임시 주소 시험")
        self.test_btn.setToolTip(
            "인스타에는 아무것도 보내지 않고, 이 컴퓨터의 카드가 바깥 주소로 열리는지만 확인합니다")
        self.test_btn.clicked.connect(self._test_tunnel)
        btn_row.addWidget(self.test_btn)
        btn_row.addStretch()
        self.approve_btn = QPushButton("확인 완료")
        self.approve_btn.setProperty("role", "primary")
        self.approve_btn.setToolTip("카드·캡션을 다 봤으면 누르세요. 발행 대기열에 들어가 정해진 시각에 자동으로 올라갑니다")
        self.approve_btn.clicked.connect(self._approve)
        btn_row.addWidget(self.approve_btn)
        self.pub_btn = QPushButton("지금 발행")
        self.pub_btn.setProperty("role", "go")
        self.pub_btn.setToolTip("대기열을 거치지 않고 지금 바로 인스타에 올립니다")
        self.pub_btn.clicked.connect(self._publish)
        btn_row.addWidget(self.pub_btn)
        side_layout.addLayout(btn_row)

        side_layout.addWidget(_section("진행 로그"))
        self.log = _log_box()
        side_layout.addWidget(self.log, 2)
        split.addWidget(side)
        split.setSizes([660, 390])
        root.addWidget(split, 1)

        hint = QLabel("카드를 누르면 글자를 고치는 창이 열립니다. "
                      "발행할 때만 이 컴퓨터에 임시 공개 주소를 열고, 끝나면 바로 닫습니다.")
        hint.setProperty("role", "hint")
        root.addWidget(hint)

    def refresh(self):
        current = self.combo.currentText()
        out = insta_cards.OUT_DIR
        # _스타일미리보기 같은 '_' 폴더는 기업이 아닙니다
        names = sorted(d.name for d in out.iterdir()
                       if d.is_dir() and not d.name.startswith("_")
                       and (any(d.glob("card*.jpg")) or (d / "deck.json").exists())
                       ) if out.exists() else []
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if current in names:
            self.combo.setCurrentText(current)
        self.combo.blockSignals(False)
        self._show(self.combo.currentText())

    def _show(self, company: str):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                # deleteLater 만 하면 지워지기 전까지 옛 썸네일이 새 썸네일 위에 겹쳐 보입니다
                w.setParent(None)
                w.deleteLater()
        self._loading = True
        self.caption.setPlainText(insta_publish.load_caption(company) if company else "")
        self._loading = False
        self._update_count()
        self._apply_style_of(company)
        self._sync_buttons()
        if not company:
            _set_status(self.status, "아직 만든 카드뉴스가 없습니다.")
            return
        cards = insta_cards.made_cards(company)
        if not cards:
            _set_status(self.status, f"{company} · 문구는 있고 카드는 아직 없습니다. 스타일을 고르고 [카드 만들기]를 누르세요.")
            return
        th = round(self.THUMB_W * insta_cards.H / insta_cards.W)
        for i, p in enumerate(cards):
            btn = QPushButton()
            btn.setProperty("role", "thumb")
            btn.setIcon(QIcon(QPixmap(str(p))))
            btn.setIconSize(QSize(self.THUMB_W, th))
            # 크기를 고정하지 않으면 격자가 창 높이에 맞춰 줄을 눌러서 카드끼리 겹칩니다
            btn.setFixedSize(self.THUMB_W + 14, th + 14)
            btn.setToolTip(f"{i + 1}번 카드 · 누르면 글자를 고칠 수 있습니다")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._edit_card(idx))
            self.grid.addWidget(btn, i // self.COLS, i % self.COLS)
        made = dt.datetime.fromtimestamp(cards[0].stat().st_mtime).strftime("%m/%d %H:%M")
        style = (insta_cards.load_deck(company) or {}).get("style")
        head = (f"{company} · 카드 {len(cards)}장 · {made} 만듦"
                + (f" · {insta_cards.style_label(style)}" if style else ""))
        rec = insta_publish.published(company)
        q = insta_queue.entry(company)
        waiting = q.get("status") == insta_queue.APPROVED
        self.approve_btn.setText("확인 취소" if waiting and not q.get("changed") else "확인 완료")
        if rec:
            _set_status(self.status, f"{head} · 인스타 발행됨 {rec['published_at']}", tone="ok")
        elif waiting and q.get("changed"):
            _set_status(self.status, f"{head} · ⚠ 확인한 뒤 카드나 캡션이 바뀌었습니다. "
                                     "다시 [확인 완료]를 눌러야 올라갑니다", tone="warn")
        elif waiting:
            _set_status(self.status, f"{head} · 확인 완료 · {q['scheduled_at']} 자동 발행 예정", tone="ok")
        elif q.get("status") == insta_queue.FAILED:
            _set_status(self.status, f"{head} · 자동 발행 3번 실패로 멈춤 — {q.get('error', '')}", tone="err")
        else:
            _set_status(self.status, f"{head} · 아직 확인 전")

    def _open_folder(self):
        company = self.combo.currentText()
        _open_folder(insta_cards.OUT_DIR / company if company else insta_cards.OUT_DIR)

    def _edit_card(self, index: int):
        company = self.combo.currentText()
        if not company:
            return
        if self._running:
            QMessageBox.information(self, "카드 수정", "지금 하는 작업이 끝난 뒤에 고칠 수 있습니다.")
            return
        deck = insta_cards.load_deck(company)
        if not deck or index >= len(deck.get("cards", [])):
            # 문구 파일이 없는 옛 카드는 고칠 수 없으니 그림만 엽니다
            os.startfile(str(insta_cards.made_cards(company)[index]))
            return
        InstaCardEditDialog(self, company, index).exec()
        self.refresh()      # 저장했든 안 했든 썸네일을 다시 읽습니다 (넘침 경고 뒤 닫은 경우 포함)

    # ── 스타일 ──
    def _apply_style_of(self, company: str):
        """기업을 바꾸면 그 기업 카드를 만들 때 썼던 스타일로 맞춥니다.

        같은 기업을 새로고침할 때는 사람이 방금 고른 스타일을 덮어쓰지 않습니다.
        """
        self.picker.set_company(company)
        if company == self._style_company:
            return
        self._style_company = company
        self.picker.set_style((insta_cards.load_deck(company) or {}).get("style") if company else None)

    def _make_cards(self):
        company = self.combo.currentText()
        if not company:
            return
        if not insta_cards.load_deck(company):
            QMessageBox.information(
                self, "다시 그리기",
                f"{company} 카드 문구가 아직 없습니다.\n[카드뉴스 만들기] 탭에서 먼저 만드세요.")
            return
        frame, color = self.picker.frame(), self.picker.color()
        label = insta_cards.style_label({"frame": frame, "color": color})
        _set_status(self.status, f"{company} · {label} 스타일로 카드를 다시 그리는 중…")
        self._start(insta_cards.rebuild, self._on_build_done, company, frame, color)

    def _on_build_done(self, _paths):
        self._finish()
        self._style_company = None      # 방금 만든 스타일(deck.json)을 다시 읽어 표시합니다
        self.refresh()

    # ── 캡션 ──
    def _on_caption_changed(self):
        self._update_count()
        company = self.combo.currentText()
        if company and not self._loading:
            insta_publish.save_caption(company, self.caption.toPlainText())

    def _rewrite_caption(self):
        company = self.combo.currentText()
        if not company:
            return
        if self.caption.toPlainText().strip() and QMessageBox.question(
                self, "캡션 새로 쓰기", "지금 캡션을 새로 쓴 캡션으로 바꿉니다. 계속할까요?") != QMessageBox.Yes:
            return
        _set_status(self.status, f"{company} 캡션을 새로 쓰는 중…")
        self._start(insta_gen.write_caption, self._on_caption_done, company)

    def _on_caption_done(self, text: str):
        self._finish()
        self._loading = True
        self.caption.setPlainText(text)
        self._loading = False
        self._update_count()
        _set_status(self.status, "캡션을 새로 썼습니다. 읽어보고 필요하면 고치세요.", tone="ok")

    def _update_count(self):
        text = self.caption.toPlainText()
        tags = len(insta_publish.hashtags(text))
        over = len(text) > insta_publish.CAPTION_MAX or tags > insta_publish.HASHTAG_MAX
        self.count.setText(
            f"{len(text):,} / {insta_publish.CAPTION_MAX:,}자 · "
            f"해시태그 {tags} / {insta_publish.HASHTAG_MAX}"
            + ("  — 인스타 제한을 넘었습니다" if over else ""))

    # ── 시험 · 발행 ──
    def _sync_buttons(self):
        ready = bool(self.combo.currentText()) and not self._running
        self.test_btn.setEnabled(ready)
        self.pub_btn.setEnabled(ready)
        self.make_btn.setEnabled(ready)
        self.caption_btn.setEnabled(ready)
        self.approve_btn.setEnabled(ready and bool(insta_cards.made_cards(self.combo.currentText())))
        self.combo.setEnabled(not self._running)
        self.picker.setEnabled(not self._running)

    def _start(self, fn, on_done, *args):
        self._running = True
        self._sync_buttons()
        self.log.clear()
        run_in_thread(self, fn, self._on_log, on_done, self._on_error, *args)

    def _test_tunnel(self):
        company = self.combo.currentText()
        if company:
            _set_status(self.status, "임시 주소 시험 중… 인스타에는 아무것도 보내지 않습니다.")
            self._start(insta_publish.test_tunnel, self._on_test_done, company)

    def _publish(self):
        company = self.combo.currentText()
        if not company:
            return
        caption = self.caption.toPlainText()
        bad = insta_publish.problems(company, caption)
        if bad:
            QMessageBox.warning(self, "발행 전 확인", "\n".join(bad))
            return
        n = len(insta_cards.made_cards(company))
        rec = insta_publish.published(company)
        again = (f"\n\n⚠ 이 기업은 {rec['published_at']}에 이미 올렸습니다. 한 번 더 올라갑니다."
                 if rec else "")
        msg = (f"@{config.INSTAGRAM_USERNAME or '톰슨에듀AI'} 계정에 {company} 카드 {n}장을 게시합니다.\n"
               f"게시는 되돌릴 수 없습니다. 지우려면 인스타에서 직접 삭제해야 합니다.{again}\n\n"
               "계속할까요?")
        if QMessageBox.question(self, "인스타에 발행", msg) != QMessageBox.Yes:
            return
        _set_status(self.status, f"{company} 발행 중…")
        self._start(insta_publish.publish, self._on_publish_done, company, caption)

    def _approve(self):
        """확인 완료 ↔ 확인 취소. 확인 완료하면 다음 빈 발행 시각에 자동 발행되도록 대기열에 넣습니다."""
        company = self.combo.currentText()
        if not company:
            return
        q = insta_queue.entry(company)
        if q.get("status") == insta_queue.APPROVED and not q.get("changed"):
            if QMessageBox.question(self, "확인 취소", f"{company}를 발행 대기열에서 뺍니다 "
                                                     f"({q['scheduled_at']} 예정이었음). 계속할까요?") == QMessageBox.Yes:
                insta_queue.unapprove(company)
                self.refresh()
            return
        try:
            rec = insta_queue.approve(company)
        except ValueError as e:
            QMessageBox.warning(self, "확인 완료할 수 없음", str(e))
            return
        self.refresh()
        auto = ("자동 발행이 켜져 있어 그 시각에 올라갑니다." if insta_queue.auto_tasks()
                else "자동 발행이 꺼져 있습니다. [발행 대기열] 탭에서 켜야 그 시각에 올라갑니다.")
        QMessageBox.information(self, "확인 완료", f"{company} 카드를 발행 대기열에 넣었습니다.\n"
                                                 f"예약 시각: {rec['scheduled_at']}\n\n{auto}\n\n"
                                                 "이제 카드나 캡션을 고치면 다시 확인 완료를 눌러야 올라갑니다.")

    def _on_log(self, text: str):
        self.log.insertPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _finish(self):
        self._running = False
        self._sync_buttons()

    def _on_test_done(self, _url: str):
        self._finish()
        _set_status(self.status, "임시 주소 시험 성공 · 카드가 바깥에서 열렸고, 주소는 닫았습니다.",
                    tone="ok")

    def _on_publish_done(self, rec: dict):
        self._finish()
        self.refresh()
        QMessageBox.information(self, "발행 완료",
                                f"인스타에 올렸습니다.\n{rec.get('permalink') or rec.get('media_id')}")

    def _on_error(self, tb: str):
        self._finish()
        # InstaError 는 사람에게 보여줄 문장이라 그 부분만 뽑고, 그 밖의 오류는 전체를 남깁니다
        m = re.search(r"InstaError: (.*)", tb, re.S)
        if m:
            text = m.group(1).strip()
            self.log.insertPlainText("\n" + text)
            _set_status(self.status, text.splitlines()[0], tone="err")
        else:
            self.log.insertPlainText("\n" + tb)
            _set_status(self.status, "실패했습니다. 진행 로그를 확인하세요.", tone="err")


# ───────────────────────── 인스타 3: 발행 대기열 ─────────────────────────
class InstaQueueTab(QWidget):
    """[확인 완료]한 카드의 발행 순서·시각을 보고 바꾸고, 자동 발행을 켜고 끕니다.

    자동 발행은 윈도우 작업 스케줄러에 '발행 시각마다 run_insta.py 실행' 작업을 등록하는 방식입니다.
    컴퓨터가 켜져 있고 로그인돼 있어야 돌고, 한 번에 1건만 올립니다.
    """

    STATE = {  # 상태 → (표시, 글자색)
        "waiting": ("발행 대기", C["accent"]),
        "changed": ("다시 확인 필요", C["warn_fg"]),
        "retry": ("대기 · 실패 {tries}회", C["warn_fg"]),
        "failed": ("멈춤 (3번 실패)", C["err_fg"]),
        "published": ("발행됨", C["ok_fg"]),
    }

    def __init__(self):
        super().__init__()
        self._running = False
        self._rows: list[tuple[str, dict]] = []
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        info = QLabel("[카드 확인·발행] 탭에서 <b>[확인 완료]</b>를 누른 카드가 여기 쌓입니다. "
                      "자동 발행을 켜두면 발행 시각마다 때가 된 카드를 <b>1건씩</b> 인스타에 올립니다. "
                      "그 시각에 컴퓨터가 켜져 있고 로그인돼 있어야 합니다.")
        info.setProperty("role", "info")
        info.setWordWrap(True)
        root.addWidget(info)

        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("role", "status")
        top.addWidget(self.summary, 1)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        root.addLayout(top)

        set_row = QHBoxLayout()
        set_row.setSpacing(8)
        set_row.addWidget(QLabel("발행 시각"))
        self.times_edit = QLineEdit()
        self.times_edit.setPlaceholderText("예: 08:30, 19:00")
        self.times_edit.setFixedWidth(200)
        set_row.addWidget(self.times_edit)
        save_btn = QPushButton("시각 저장")
        save_btn.clicked.connect(self._save_times)
        set_row.addWidget(save_btn)
        set_row.addStretch()
        self.auto_btn = QPushButton()
        self.auto_btn.clicked.connect(self._toggle_auto)
        set_row.addWidget(self.auto_btn)
        root.addLayout(set_row)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        self.table = InstaAssetsTab._make_table(["예약·발행 시각", "기업명", "상태", "스타일", "메모"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for col, w in ((0, 150), (1, 200), (2, 130), (3, 170)):
            self.table.setColumnWidth(col, w)
        self.table.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self.table)
        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_layout.addWidget(_section("발행 기록"))
        self.log = _log_box()
        log_layout.addWidget(self.log)
        split.addWidget(log_panel)
        split.setSizes([330, 170])
        root.addWidget(split, 1)

        act = QHBoxLayout()
        act.setSpacing(8)
        act.addWidget(QLabel("예약 시각"))
        self.when_edit = QDateTimeEdit()
        self.when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.when_edit.setCalendarPopup(True)
        act.addWidget(self.when_edit)
        self.move_btn = QPushButton("시각 바꾸기")
        self.move_btn.clicked.connect(self._reschedule)
        act.addWidget(self.move_btn)
        self.cancel_btn = QPushButton("확인 취소")
        self.cancel_btn.setProperty("role", "danger-text")
        self.cancel_btn.clicked.connect(self._cancel)
        act.addWidget(self.cancel_btn)
        act.addStretch()
        self.now_btn = QPushButton("지금 발행")
        self.now_btn.setProperty("role", "go")
        self.now_btn.clicked.connect(self._publish_now)
        act.addWidget(self.now_btn)
        root.addLayout(act)

        self.status = QLabel("표에서 카드를 고르면 예약 시각을 바꾸거나 확인을 취소할 수 있습니다.")
        self.status.setProperty("role", "status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    # ── 표시 ──
    def refresh(self):
        current = self._selected()
        self.times_edit.setText(", ".join(f"{t:%H:%M}" for t in insta_queue.post_times()))
        tasks = insta_queue.auto_tasks()
        self.auto_btn.setText("자동 발행 끄기" if tasks else "자동 발행 켜기")
        self.auto_btn.setProperty("role", "danger-text" if tasks else "primary")
        _restyle(self.auto_btn)

        self._rows = insta_queue.entries()
        waiting = sum(1 for _, r in self._rows if r.get("status") == insta_queue.APPROVED)
        auto = ("켜짐 (" + ", ".join(f"{n[-4:-2]}:{n[-2:]}" for n in tasks) + ")") if tasks else "꺼짐"
        self.summary.setText(f"자동 발행 {auto}     대기 {waiting}건     토큰 {insta_publish.token_status()}")
        self.summary.setProperty("tone", "ok" if tasks else "warn")
        _restyle(self.summary)

        self.table.setRowCount(len(self._rows))
        for i, (company, rec) in enumerate(self._rows):
            label, fg = self.STATE[self._state(rec)]
            deck = insta_cards.load_deck(company)
            when = rec.get("published_at") or rec.get("scheduled_at", "")
            memo = (rec.get("permalink") if rec.get("status") == insta_queue.PUBLISHED
                    else rec.get("error", ""))
            self.table.setItem(i, 0, InstaAssetsTab._cell(when))
            self.table.setItem(i, 1, InstaAssetsTab._cell(company))
            self.table.setItem(i, 2, InstaAssetsTab._cell(label.format(tries=rec.get("tries", 0)), fg))
            self.table.setItem(i, 3, InstaAssetsTab._cell(
                insta_cards.style_label(deck.get("style")) if deck else "-", C["soft"]))
            self.table.setItem(i, 4, InstaAssetsTab._cell(memo or "", C["soft"]))
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).text() == current:
                self.table.selectRow(r)
        self._load_log()
        self._sync()

    @staticmethod
    def _state(rec: dict) -> str:
        s = rec.get("status")
        if s == insta_queue.PUBLISHED:
            return "published"
        if s == insta_queue.FAILED:
            return "failed"
        if rec.get("changed"):
            return "changed"
        return "retry" if rec.get("tries") else "waiting"

    def _load_log(self):
        try:
            lines = insta_queue.LOG.read_text(encoding="utf-8").splitlines()[-200:]
        except OSError:
            lines = ["아직 발행 기록이 없습니다."]
        self.log.setPlainText("\n".join(lines))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _selected(self) -> str:
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        return item.text() if item else ""

    def _selected_rec(self) -> dict:
        company = self._selected()
        return next((r for c, r in self._rows if c == company), {})

    def _on_select(self):
        rec = self._selected_rec()
        if rec.get("scheduled_at") and rec.get("status") == insta_queue.APPROVED:
            self.when_edit.setDateTime(QDateTime.fromString(rec["scheduled_at"], "yyyy-MM-dd HH:mm"))
        self._sync()

    def _sync(self):
        rec = self._selected_rec()
        waiting = rec.get("status") == insta_queue.APPROVED and not self._running
        for w in (self.move_btn, self.cancel_btn, self.when_edit):
            w.setEnabled(waiting)
        self.now_btn.setEnabled(waiting and not rec.get("changed"))
        for w in (self.table, self.auto_btn, self.times_edit):
            w.setEnabled(not self._running)

    # ── 설정 ──
    def _save_times(self):
        valid = []
        for part in [p for p in re.split(r"[,\s]+", self.times_edit.text()) if p]:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", part)
            if not m or int(m[1]) > 23 or int(m[2]) > 59:
                QMessageBox.warning(self, "발행 시각", f"'{part}' 는 시각 형식이 아닙니다 (예: 08:30).")
                return
            valid.append(f"{int(m[1]):02d}:{m[2]}")
        if not valid:
            QMessageBox.warning(self, "발행 시각", "발행 시각을 하나 이상 적어주세요 (예: 08:30, 19:00).")
            return
        path = config.SETTINGS_OVERRIDE_PATH
        try:
            override = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except ValueError:
            override = {}
        override["INSTA_POST_TIMES"] = sorted(set(valid))
        path.write_text(json.dumps(override, ensure_ascii=False, indent=2), encoding="utf-8")
        importlib.reload(config)
        msg = "발행 시각을 저장했습니다. 이미 잡힌 예약 시각은 그대로입니다."
        if insta_queue.auto_tasks():
            try:
                insta_queue.enable_auto()          # 새 시각으로 작업을 다시 등록합니다
                msg += " 자동 발행 작업도 새 시각으로 다시 등록했습니다."
            except RuntimeError as e:
                QMessageBox.critical(self, "작업 등록 실패", str(e))
        self.refresh()
        _set_status(self.status, msg, tone="ok")

    def _toggle_auto(self):
        if insta_queue.auto_tasks():
            if QMessageBox.question(self, "자동 발행 끄기",
                                    "작업 스케줄러에서 자동 발행 작업을 지웁니다. 대기열은 그대로 남습니다.\n\n"
                                    "끌까요?") != QMessageBox.Yes:
                return
            insta_queue.disable_auto()
            self.refresh()
            _set_status(self.status, "자동 발행을 껐습니다.")
            return
        missing = []
        if not insta_publish.CLOUDFLARED.exists():
            missing.append("임시 주소 프로그램(tools\\cloudflared.exe)이 없습니다.")
        if not config.INSTAGRAM_ACCESS_TOKEN:
            missing.append(".env 에 인스타 토큰이 없습니다.")
        if missing:
            # 이대로 켜면 시각마다 실패만 쌓이고 3번 뒤 카드가 멈추므로 막습니다
            QMessageBox.warning(self, "자동 발행을 켤 수 없음",
                                "\n".join(missing) + "\n\n발행 확인(임시 주소 시험·첫 발행)을 마친 뒤 켜세요.")
            return
        times = ", ".join(f"{t:%H:%M}" for t in insta_queue.post_times())
        if QMessageBox.question(
                self, "자동 발행 켜기",
                f"윈도우 작업 스케줄러에 매일 {times} 에 run_insta.py 를 실행하는 작업을 등록합니다.\n"
                "그 시각에 [확인 완료]된 카드 중 때가 된 1건을 인스타에 올립니다 (게시는 되돌릴 수 없음).\n"
                "컴퓨터가 켜져 있고 로그인돼 있어야 돕니다.\n\n켤까요?") != QMessageBox.Yes:
            return
        try:
            insta_queue.enable_auto()
        except RuntimeError as e:
            QMessageBox.critical(self, "작업 등록 실패", str(e))
            return
        self.refresh()
        _set_status(self.status, f"자동 발행을 켰습니다 ({times}).", tone="ok")

    # ── 카드별 ──
    def _reschedule(self):
        company = self._selected()
        s = self.when_edit.dateTime().toString("yyyy-MM-dd HH:mm")
        try:
            insta_queue.reschedule(company, dt.datetime.strptime(s, "%Y-%m-%d %H:%M"))
        except ValueError as e:
            QMessageBox.warning(self, "시각 바꾸기", str(e))
            return
        self.refresh()
        _set_status(self.status, f"{company} 예약 시각을 {s} 로 바꿨습니다.", tone="ok")

    def _cancel(self):
        company = self._selected()
        if company and QMessageBox.question(self, "확인 취소", f"{company}를 발행 대기열에서 뺍니다. "
                                                            "카드와 캡션은 그대로 남습니다.") == QMessageBox.Yes:
            insta_queue.unapprove(company)
            self.refresh()

    def _publish_now(self):
        company = self._selected()
        if not company:
            return
        bad = insta_publish.problems(company, insta_publish.load_caption(company))
        if bad:
            QMessageBox.warning(self, "발행 전 확인", "\n".join(bad))
            return
        if QMessageBox.question(
                self, "지금 발행",
                f"@{config.INSTAGRAM_USERNAME or '톰슨에듀AI'} 계정에 {company} 카드뉴스를 지금 게시합니다.\n"
                "게시는 되돌릴 수 없습니다. 지우려면 인스타에서 직접 삭제해야 합니다.\n\n계속할까요?") != QMessageBox.Yes:
            return
        self._running = True
        self._sync()
        _set_status(self.status, f"{company} 발행 중…")
        run_in_thread(self, insta_queue.publish_now, self._on_log, self._on_done, self._on_error,
                      company, log=insta_queue.file_log)

    def _on_log(self, text: str):
        self.log.insertPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_done(self, _result):
        self._running = False
        self.refresh()
        _set_status(self.status, "발행했습니다. 인스타 앱에서 게시물을 확인하세요.", tone="ok")

    def _on_error(self, tb: str):
        self._running = False
        self.refresh()
        _set_status(self.status, "발행하지 못했습니다: " + tb.strip().splitlines()[-1][:160], tone="err")


# ───────────────────────── 메인 윈도우 ─────────────────────────
class MainWindow(QMainWindow):
    """위쪽 [블로그 | 인스타] 버튼으로 두 작업 공간을 오갑니다."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("톰슨에듀 자동 포스팅")
        self.resize(1100, 750)

        # ── 블로그 ──
        tabs = QTabWidget()
        self.tabs = tabs
        self.gen_tab = GenerateTab()
        self.pub_tab = PublishTab()
        self.batch_tab = CompanyBatchTab()
        self.queue_tab = QueueTab()
        self.preview_tab = PreviewTab()
        self.settings_tab = SettingsTab()

        # 글이 생성되면: 발행 탭에 대상 지정 + 미리보기 탭에 열기 + 대기열 갱신
        self.gen_tab.context_ready.connect(self.pub_tab.set_context)
        self.gen_tab.draft_ready.connect(self.pub_tab.set_draft)
        self.gen_tab.draft_ready.connect(self.preview_tab.load_path)
        self.gen_tab.draft_ready.connect(self._on_draft_ready)

        tabs.addTab(self.batch_tab, "기업 일괄 발행")
        tabs.addTab(self.queue_tab, "대기열")
        tabs.addTab(self.gen_tab, "글 생성")
        tabs.addTab(self.pub_tab, "발행")
        tabs.addTab(self.preview_tab, "초안 수정")
        tabs.addTab(self.settings_tab, "설정")
        tabs.currentChanged.connect(self._on_tab_changed)

        # ── 인스타 ──
        self.insta_tabs = QTabWidget()
        self.insta_make_tab = InstaMakeTab()
        self.insta_cards_tab = InstaCardsTab()
        self.insta_queue_tab = InstaQueueTab()
        self.insta_assets_tab = InstaAssetsTab()
        self.insta_tabs.addTab(self.insta_make_tab, "카드뉴스 만들기")
        self.insta_tabs.addTab(self.insta_cards_tab, "카드 확인·발행")
        self.insta_tabs.addTab(self.insta_queue_tab, "발행 대기열")
        self.insta_tabs.addTab(self.insta_assets_tab, "자료 준비")
        self.insta_tabs.currentChanged.connect(self._on_insta_tab_changed)
        self.insta_make_tab.open_cards.connect(self._open_insta_cards)

        self.stack = QStackedWidget()
        self.stack.addWidget(tabs)
        self.stack.addWidget(self.insta_tabs)

        # ── 블로그 / 인스타 전환 버튼 ──
        bar = QWidget()
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(18, 12, 18, 2)
        bar_row.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        for i, (text, pos) in enumerate((("블로그", "l"), ("인스타", "r"))):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setProperty("role", "mode")
            btn.setProperty("pos", pos)
            btn.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(btn, i)
            bar_row.addWidget(btn)
        bar_row.addStretch()
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idClicked.connect(self._on_mode_changed)

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(bar)
        col.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _on_mode_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 1:
            self._on_insta_tab_changed(self.insta_tabs.currentIndex())

    def _on_insta_tab_changed(self, index: int) -> None:
        """인스타 탭도 열 때마다 폴더를 다시 읽습니다 (사진을 방금 넣었을 수 있으므로)."""
        widget = self.insta_tabs.widget(index)
        if widget is self.insta_assets_tab:
            self.insta_assets_tab.refresh()
        elif widget is self.insta_cards_tab:
            self.insta_cards_tab.refresh()
        elif widget is self.insta_make_tab and not self.insta_make_tab._running:
            self.insta_make_tab.refresh()
        elif widget is self.insta_queue_tab and not self.insta_queue_tab._running:
            self.insta_queue_tab.refresh()

    def _open_insta_cards(self, company: str) -> None:
        """카드뉴스 만들기 → [만든 카드 보기]: 확인·발행 탭으로 넘어가 그 기업을 엽니다."""
        self.insta_tabs.setCurrentWidget(self.insta_cards_tab)     # 넘어가면서 목록을 새로 읽습니다
        self.insta_cards_tab.combo.setCurrentText(company)

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
