"""PySide6 desktop interface for literature search, settings, and reports."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTime, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from core import report
from core.config import ROOT, load_config
from core.custom_topics import (
    CUSTOM_DIRECTION,
    CUSTOM_TOPIC_MARKER,
    apply_custom_topic,
    custom_topic_name,
    normalize_custom_selection,
    parse_terms,
)
from core.portal import (
    save_credentials,
    save_email_settings,
    save_portal_settings,
    save_translation_settings,
)
from core.scheduler import create_daily_task, daily_task_exists, delete_daily_task

GUI_SETTINGS_PATH = ROOT / "state" / "gui_settings.json"
SEARCH_DAYS = {"3天": 3, "7天": 7, "15天": 15}
APP_VERSION = "1.0.0"
APP_ICON_NAME = "文献.ico"


class LiteratureApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("文献日报 · 设置与运行")
        self.setWindowIcon(_application_icon())
        self.resize(1180, 900)
        self.setMinimumSize(900, 680)
        self.gui_settings = self._load_gui_settings()
        base_topics = load_config().get("topics", [])
        self.gui_settings = normalize_custom_selection(
            self.gui_settings,
            {str(topic.get("name", "")) for topic in base_topics},
        )
        self.cfg = apply_custom_topic(load_config(), self.gui_settings)
        self.site_rows: list[dict] = []
        self.translation_credentials: dict[str, dict[str, QLineEdit]] = {}
        self.translation_credential_saved: dict[tuple[str, str], bool] = {}
        self.email_password_saved = bool((self.cfg.get("email") or {}).get("password"))
        self.preview_papers: list[dict] = []
        self.preview_payload: dict = {}
        self.process: subprocess.Popen | None = None
        self.output_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._load_sites()
        self._refresh_task_status()
        self._load_latest_preview()
        self._load_latest_html()
        self.output_timer = QTimer(self)
        self.output_timer.timeout.connect(self._drain_output)
        self.output_timer.start(100)

    @staticmethod
    def _load_gui_settings() -> dict:
        if not GUI_SETTINGS_PATH.exists():
            return {}
        data = json.loads(GUI_SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("本机 GUI 设置格式无效")
        return data

    def _build_ui(self) -> None:
        installed_fonts = set(QFontDatabase.families())
        self.chinese_font = next(
            (name for name in ("SimSun", "Noto Serif SC", "Microsoft YaHei UI") if name in installed_fonts),
            "Arial",
        )
        self.app_font = QFont()
        self.app_font.setFamilies(["Arial", self.chinese_font])
        self.app_font.setPointSize(11)
        self.app_font.setWeight(QFont.Weight.Bold)
        QApplication.setFont(self.app_font)
        stylesheet = """
            QWidget {
                background: #f3f6fb;
                color: #243247;
                font-size: 11pt;
                font-weight: 700;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d9e2ef;
                border-radius: 8px;
                margin-top: 12px;
                padding: 14px 10px 10px 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #1f4e79;
                font-size: 12pt;
            }
            QLineEdit, QComboBox, QSpinBox, QTimeEdit, QTableWidget, QPlainTextEdit, QTextBrowser {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 6px;
                selection-background-color: #b7c9dc;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
                border: 1px solid #486581;
            }
            QPushButton {
                background: #e8edf3;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 14px;
            }
            QPushButton:hover { background: #dce5ee; }
            QPushButton#runButton {
                background: #174a75;
                color: #ffffff;
                border: 1px solid #123b5e;
                padding: 10px 18px;
            }
            QPushButton#runButton:hover { background: #123b5e; }
            QTabWidget::pane {
                background: #ffffff;
                border: 1px solid #d9e2ef;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #e8edf3;
                border: 1px solid #d9e2ef;
                padding: 9px 16px;
                margin-right: 3px;
            }
            QTabBar::tab:selected { background: #ffffff; color: #174a75; }
            QHeaderView::section {
                background: #eaf0f6;
                border: none;
                padding: 8px;
            }
            QTableWidget { gridline-color: #e2e8f0; }
            """
        self.setStyleSheet(stylesheet)

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(20, 16, 20, 16)
        shell_layout.setSpacing(12)
        hero = QVBoxLayout()
        title = QLabel("文献日报")
        title.setFont(QFont(self.chinese_font, 22, QFont.Weight.Bold))
        subtitle = QLabel("配置检索范围，定时收集文献，并在结果页和 HTML 日报中查看。")
        subtitle.setStyleSheet("color:#64748b")
        hero.addWidget(title)
        hero.addWidget(subtitle)
        shell_layout.addLayout(hero)

        self.main_tabs = QTabWidget()
        shell_layout.addWidget(self.main_tabs, 1)
        self.settings_page = self._build_settings_page()
        self.preview_page = self._build_preview_page()
        self.html_page = self._build_html_page()
        self.log_page = self._build_log_page()
        self.main_tabs.addTab(self.settings_page, "检索与设置")
        self.main_tabs.addTab(self.preview_page, "检索结果")
        self.main_tabs.addTab(self.html_page, "HTML 日报")
        self.main_tabs.addTab(self.log_page, "运行日志")
        self.search_topic.currentTextChanged.connect(self._load_latest_html)

        actions = QHBoxLayout()
        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self._save_settings)
        self.run_button = QPushButton("立即检索")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._run_now)
        actions.addWidget(save_button)
        actions.addWidget(self.run_button)
        about_button = QPushButton("关于软件")
        about_button.clicked.connect(self._show_about)
        actions.addWidget(about_button)
        actions.addStretch(1)
        self.run_status = QLabel("就绪")
        actions.addWidget(self.run_status)
        shell_layout.addLayout(actions)
        self.setCentralWidget(shell)

    def _group(self, title: str, parent: QWidget) -> tuple[QGroupBox, QGridLayout]:
        group = QGroupBox(title, parent)
        layout = QGridLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        return group, layout

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(10, 10, 10, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 14, 8)

        portal, self.sites_layout = self._group("校园网 / 期刊数据库门户", content)
        self.auto_login = QCheckBox("所有出版社站点均不可达时尝试自动登录门户")
        self.auto_login.setChecked(bool(self.cfg.get("portal", {}).get("auto_login")))
        self.sites_layout.addWidget(self.auto_login, 0, 0, 1, 4)
        for column, heading in enumerate(("门户名称", "登录网址（自行填写）", "账号", "密码（留空保留）")):
            label = QLabel(heading)
            label.setStyleSheet("color:#64748b")
            self.sites_layout.addWidget(label, 1, column)
        self.sites_layout.setColumnStretch(1, 2)
        layout.addWidget(portal)

        translation, translation_layout = self._group("翻译服务", content)
        self.translation_enabled = QCheckBox("启用翻译")
        self.translation_enabled.setChecked(bool((self.cfg.get("translation") or {}).get("enabled", True)))
        self.translation_backend = QComboBox()
        self.translation_backend.addItems(("auto", "youdao", "mymemory", "deepseek", "zhipu", "baidu"))
        self.translation_backend.setCurrentText((self.cfg.get("translation") or {}).get("backend", "auto"))
        self.translation_mode = QComboBox()
        self.translation_mode.addItem("仅标题", "title")
        self.translation_mode.addItem("仅摘要", "abstract")
        self.translation_mode.addItem("标题和摘要", "both")
        saved_mode = (self.cfg.get("translation") or {}).get("mode", "both")
        mode_index = self.translation_mode.findData(saved_mode)
        self.translation_mode.setCurrentIndex(mode_index if mode_index >= 0 else 2)
        self.abstract_max_chars = QSpinBox()
        self.abstract_max_chars.setRange(0, 5000)
        self.abstract_max_chars.setSingleStep(100)
        self.abstract_max_chars.setValue(int((self.cfg.get("translation") or {}).get("abstract_max_chars", 700)))
        translation_layout.addWidget(self.translation_enabled, 0, 0)
        translation_layout.addWidget(QLabel("翻译后端"), 0, 1)
        translation_layout.addWidget(self.translation_backend, 0, 2)
        translation_layout.addWidget(QLabel("翻译内容"), 0, 3)
        translation_layout.addWidget(self.translation_mode, 0, 4)
        translation_layout.addWidget(QLabel("摘要字符数"), 0, 5)
        translation_layout.addWidget(self.abstract_max_chars, 0, 6)
        self.translation_frame = translation
        self._build_translation_credentials(translation_layout)
        translation_note = QLabel("密钥留空表示保留已保存的值；联网翻译会将文本发送至所选服务商。")
        translation_note.setStyleSheet("color:#64748b")
        translation_layout.addWidget(translation_note, 4, 0, 1, 7)
        self.translation_mode.currentIndexChanged.connect(self._update_translation_controls)
        self._update_translation_controls()
        layout.addWidget(translation)

        email, email_layout = self._group("邮件日报", content)
        email_cfg = self.cfg.get("email") or {}
        self.email_enabled = QCheckBox("筛选后自动发送邮件")
        self.email_enabled.setChecked(bool(email_cfg.get("enabled")))
        email_layout.addWidget(self.email_enabled, 0, 0, 1, 2)
        self.email_host = QLineEdit(email_cfg.get("smtp_host", ""))
        self.email_user = QLineEdit(email_cfg.get("user", ""))
        self.email_to = QLineEdit("; ".join(email_cfg.get("to") or []))
        self.email_port = QLineEdit(str(email_cfg.get("smtp_port", 465)))
        self.email_ssl = QCheckBox("SSL")
        self.email_ssl.setChecked(bool(email_cfg.get("use_ssl", True)))
        self.email_password = QLineEdit()
        self.email_password.setEchoMode(QLineEdit.EchoMode.Password)
        for row, label, widget in (
            (1, "SMTP 服务器", self.email_host),
            (2, "发件邮箱", self.email_user),
            (3, "收件邮箱（多个用分号隔开）", self.email_to),
        ):
            email_layout.addWidget(QLabel(label), row, 0)
            email_layout.addWidget(widget, row, 1, 1, 3)
        email_layout.addWidget(QLabel("端口"), 1, 4)
        email_layout.addWidget(self.email_port, 1, 5)
        email_layout.addWidget(self.email_ssl, 1, 6)
        email_layout.addWidget(QLabel("SMTP 授权码"), 2, 4)
        email_layout.addWidget(self.email_password, 2, 5, 1, 2)
        self.email_password_saved = bool(email_cfg.get("password"))
        email_note = QLabel(
            "邮件由“发件邮箱”对应的 SMTP 账户发送；需填写 SMTP 服务器、端口和收件邮箱。"
            "若发给自己，收件邮箱填同一地址。授权码留空保留已保存值；凭据由当前 Windows 用户加密保存。"
            + ("（已有授权码）" if self.email_password_saved else "")
        )
        email_note.setWordWrap(True)
        email_note.setStyleSheet("color:#64748b")
        email_layout.addWidget(email_note, 4, 0, 1, 7)
        layout.addWidget(email)

        custom_topic, custom_layout = self._group("自定义关键词组", content)
        self.custom_keyword_terms = QPlainTextEdit()
        self.custom_keyword_terms.setMaximumHeight(100)
        self.custom_keyword_terms.setPlaceholderText(
            "每行一个关键词，也可用逗号或分号分隔；建议同时填写英文同义词"
        )
        saved_terms = self.gui_settings.get("custom_keyword_terms") or ""
        if isinstance(saved_terms, list):
            saved_terms = "\n".join(str(term) for term in saved_terms)
        self.custom_keyword_terms.setPlainText(str(saved_terms))
        custom_topic.setVisible(False)
        custom_layout.addWidget(QLabel("关键词"), 0, 0, Qt.AlignmentFlag.AlignTop)
        custom_layout.addWidget(self.custom_keyword_terms, 0, 1, 1, 3)
        custom_note = QLabel(
            "方向名称由关键词自动组合（例如 Perovskite, COF 显示为“Perovskite COF”）；"
            "多个词按“或”检索，填写关键词后会增加一个可单独选择的方向。"
            "没有翻译 API 时不会自动把中文翻译成英文，会尝试原词检索；"
            "OpenAlex/Crossref 元数据多为英文，建议同时填写英文同义词。"
        )
        custom_note.setWordWrap(True)
        custom_note.setStyleSheet("color:#64748b")
        custom_layout.addWidget(custom_note, 1, 0, 1, 4)

        schedule, schedule_layout = self._group("检索范围与每日计划", content)
        self.search_topic = QComboBox()
        self.search_topic.addItem("全部主题")
        self.search_topic.addItems(
            str(topic.get("name", ""))
            for topic in self.cfg.get("topics", [])
            if not topic.get(CUSTOM_TOPIC_MARKER)
        )
        self.search_topic.addItem(CUSTOM_DIRECTION)
        self.search_topic.setCurrentText(self.gui_settings.get("search_topic", "全部主题"))
        self.search_topic.currentTextChanged.connect(self._update_custom_topic_visibility)
        self.search_window = QComboBox()
        self.search_window.addItems(SEARCH_DAYS)
        saved_window = self.gui_settings.get("search_window")
        self.search_window.setCurrentText(saved_window if saved_window in SEARCH_DAYS else "3天")
        self.schedule_time = QTimeEdit()
        self.schedule_time.setDisplayFormat("HH:mm")
        selected_time = QTime.fromString(self.gui_settings.get("schedule_time", "08:00"), "HH:mm")
        self.schedule_time.setTime(selected_time if selected_time.isValid() else QTime(8, 0))
        schedule_layout.addWidget(QLabel("检索方向"), 0, 0)
        schedule_layout.addWidget(self.search_topic, 0, 1)
        schedule_layout.addWidget(QLabel("时间范围"), 0, 2)
        schedule_layout.addWidget(self.search_window, 0, 3)
        schedule_layout.addWidget(QLabel("每天运行时间"), 0, 4)
        schedule_layout.addWidget(self.schedule_time, 0, 5)
        create_task = QPushButton("设置每日任务")
        create_task.clicked.connect(self._create_task)
        delete_task = QPushButton("取消任务")
        delete_task.clicked.connect(self._delete_task)
        schedule_layout.addWidget(create_task, 0, 6)
        schedule_layout.addWidget(delete_task, 0, 7)
        self.task_status = QLabel("检查中…")
        schedule_layout.addWidget(self.task_status, 1, 0, 1, 8)
        schedule_note = QLabel(
            "立即检索和每日计划均使用所选方向、时间范围；会尽量获取匹配项，但仍受 OpenAlex / "
            "Crossref 返回上限影响。较长时间 + 全部主题会产生更多 API 请求。"
        )
        schedule_note.setWordWrap(True)
        schedule_note.setStyleSheet("color:#64748b")
        schedule_layout.addWidget(schedule_note, 2, 0, 1, 8)
        self.include_reported = QCheckBox("立即检索时包含此前已报告的文献（每日计划仍只发新增）")
        self.include_reported.setChecked(bool(self.gui_settings.get("include_reported", True)))
        schedule_layout.addWidget(self.include_reported, 3, 0, 1, 8)
        layout.addWidget(schedule)
        layout.addWidget(custom_topic)
        self.custom_topic_group = custom_topic
        self._update_custom_topic_visibility()
        layout.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_translation_credentials(self, layout: QGridLayout) -> None:
        configured = self.cfg.get("translation", {}) or {}
        fields = {
            "deepseek": [("api_key", "DeepSeek API Key")],
            "zhipu": [("api_key", "智谱 API Key")],
            "baidu": [("appid", "百度 AppID"), ("secret", "百度 Secret")],
        }
        for row, (provider, provider_fields) in enumerate(fields.items(), start=1):
            provider_vars: dict[str, QLineEdit] = {}
            configured_provider = configured.get(provider) or {}
            layout.addWidget(QLabel(provider), row, 0)
            for index, (field, label) in enumerate(provider_fields):
                label_column = 1 + index * 2
                entry_column = label_column + 1
                saved = bool(configured_provider.get(field))
                label_widget = QLabel(f"{label}（已保存）" if saved else label)
                if saved:
                    label_widget.setStyleSheet("color:#16803c")
                layout.addWidget(label_widget, row, label_column)
                entry = QLineEdit()
                if field in ("api_key", "secret"):
                    entry.setEchoMode(QLineEdit.EchoMode.Password)
                layout.addWidget(entry, row, entry_column)
                provider_vars[field] = entry
                self.translation_credential_saved[(provider, field)] = saved
            self.translation_credentials[provider] = provider_vars

    def _load_sites(self) -> None:
        sites = self.cfg.get("portal", {}).get("sites") or []
        credentials = self.cfg.get("portal_credentials") or {}
        for row, site in enumerate(sites, start=2):
            name = site.get("name", "")
            credential = credentials.get(name) or {}
            if not isinstance(credential, dict):
                raise ValueError(f"门户「{name}」的凭据配置格式无效")
            url = QLineEdit(site.get("url", ""))
            username = QLineEdit(credential.get("username", ""))
            password = QLineEdit()
            password.setEchoMode(QLineEdit.EchoMode.Password)
            self.sites_layout.addWidget(QLabel(name), row, 0)
            self.sites_layout.addWidget(url, row, 1)
            self.sites_layout.addWidget(username, row, 2)
            self.sites_layout.addWidget(password, row, 3)
            self.site_rows.append(
                {
                    "name": name,
                    "url": url,
                    "username": username,
                    "password": password,
                    "has_password": bool(credential.get("password")),
                }
            )
        if not sites:
            self.sites_layout.addWidget(
                QLabel("尚未在 config.yaml 的 portal.sites 中配置门户地址。"), 2, 0, 1, 4
            )

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("主题"))
        self.preview_topic = QComboBox()
        self.preview_topic.addItem("全部主题")
        self.preview_topic.addItems([str(topic.get("name", "")) for topic in self.cfg.get("topics", [])])
        self.preview_topic.currentTextChanged.connect(self._render_preview)
        controls.addWidget(self.preview_topic)
        controls.addWidget(QLabel("关键词"))
        self.preview_query = QLineEdit()
        self.preview_query.setPlaceholderText("搜索标题、摘要、期刊或 DOI")
        self.preview_query.textChanged.connect(self._render_preview)
        controls.addWidget(self.preview_query, 1)
        self.preview_status = QLabel("尚无日报；运行一次筛选后会显示结果。")
        controls.addWidget(self.preview_status)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_table = QTableWidget(0, 5)
        self.preview_table.setHorizontalHeaderLabels(("分数", "主题", "日期", "期刊", "标题"))
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setColumnWidth(0, 72)
        self.preview_table.setColumnWidth(1, 150)
        self.preview_table.setColumnWidth(2, 110)
        self.preview_table.setColumnWidth(3, 260)
        self.preview_table.itemSelectionChanged.connect(self._show_preview_detail)
        self.preview_table.cellDoubleClicked.connect(self._open_selected_paper)
        splitter.addWidget(self.preview_table)
        self.preview_detail = QPlainTextEdit()
        self.preview_detail.setReadOnly(True)
        splitter.addWidget(self.preview_detail)
        splitter.setSizes((500, 300))
        layout.addWidget(splitter, 1)
        return page

    def _build_html_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.html_status = QLabel("在此页面直接浏览完整交互式 HTML 日报。")
        reload_button = QPushButton("刷新日报")
        reload_button.clicked.connect(self._load_latest_html)
        bar.addWidget(self.html_status, 1)
        bar.addWidget(reload_button)
        layout.addLayout(bar)
        self.html_view = QWebEngineView()
        self.html_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.html_view.page().newWindowRequested.connect(self._open_external_window)
        layout.addWidget(self.html_view, 1)
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            "background:#101827;color:#e2e8f0;border:0;border-radius:6px;padding:12px;"
            "font-size:11pt;font-weight:700;"
        )
        layout.addWidget(self.output)
        return page

    def _days_selected(self) -> int:
        selected = self.search_window.currentText()
        if selected not in SEARCH_DAYS:
            raise ValueError("请选择有效的检索时间范围")
        return SEARCH_DAYS[selected]

    def _update_translation_controls(self, *_args) -> None:
        self.abstract_max_chars.setEnabled(
            self.translation_mode.currentData() in ("abstract", "both")
        )

    def _update_custom_topic_visibility(self, *_args) -> None:
        if hasattr(self, "custom_topic_group"):
            self.custom_topic_group.setVisible(
                self.search_topic.currentText() == CUSTOM_DIRECTION
            )

    def _save_settings(self, show_message: bool = True) -> bool:
        try:
            settings = self._gui_settings_from_ui()
            apply_custom_topic(self.cfg, settings)
            for site in self.site_rows:
                username = site["username"].text().strip()
                password = site["password"].text()
                if not username and not password:
                    continue
                if not username:
                    raise ValueError(f"请填写「{site['name']}」的账号")
                if not password and not site["has_password"]:
                    raise ValueError(f"请填写「{site['name']}」的密码")
                save_credentials(site["name"], username, password)
                site["has_password"] = True
                site["password"].clear()

            save_portal_settings(
                self.auto_login.isChecked(),
                [{"name": site["name"], "url": site["url"].text()} for site in self.site_rows],
            )
            credentials = {
                provider: {field: entry.text().strip() for field, entry in fields.items()}
                for provider, fields in self.translation_credentials.items()
            }
            save_translation_settings(
                enabled=self.translation_enabled.isChecked(),
                backend=self.translation_backend.currentText(),
                abstract_max_chars=self.abstract_max_chars.value(),
                credentials=credentials,
                mode=self.translation_mode.currentData(),
            )
            for provider, fields in self.translation_credentials.items():
                for field, entry in fields.items():
                    if entry.text():
                        self.translation_credential_saved[(provider, field)] = True
                        entry.clear()

            try:
                email_port = int(self.email_port.text())
            except ValueError as exc:
                raise ValueError("SMTP 端口必须是整数") from exc
            recipients = [
                recipient.strip()
                for recipient in self.email_to.text().replace(",", ";").split(";")
                if recipient.strip()
            ]
            save_email_settings(
                enabled=self.email_enabled.isChecked(),
                smtp_host=self.email_host.text(),
                smtp_port=email_port,
                use_ssl=self.email_ssl.isChecked(),
                user=self.email_user.text(),
                password=self.email_password.text(),
                recipients=recipients,
            )
            if self.email_password.text():
                self.email_password_saved = True
                self.email_password.clear()
            self._write_gui_settings(settings)
            self.gui_settings = settings
            self.cfg = apply_custom_topic(load_config(), settings)
            self._refresh_topic_options()
            self._append_log("设置已保存；门户、翻译 API 和 SMTP 密钥由当前 Windows 用户加密存储。")
            if show_message:
                QMessageBox.information(self, "已保存", "设置已保存到本机。")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False

    def _gui_settings_from_ui(self) -> dict:
        terms = parse_terms(self.custom_keyword_terms.toPlainText())
        selected_topic = self.search_topic.currentText()
        if selected_topic == CUSTOM_DIRECTION and not terms:
            raise ValueError("请选择自定义方向时，请至少输入一个关键词")
        return {
            "schedule_time": self.schedule_time.time().toString("HH:mm"),
            "search_topic": selected_topic,
            "search_window": self.search_window.currentText(),
            "include_reported": self.include_reported.isChecked(),
            "custom_keyword_terms": terms,
        }

    def _write_gui_settings(self, settings: dict) -> None:
        GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = GUI_SETTINGS_PATH.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(GUI_SETTINGS_PATH)

    def _refresh_topic_options(self) -> None:
        for combo in (self.search_topic, self.preview_topic):
            selected = (
                self.gui_settings.get("search_topic", combo.currentText())
                if combo is self.search_topic
                else combo.currentText()
            )
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("全部主题")
            combo.addItems(
                str(topic.get("name", ""))
                for topic in self.cfg.get("topics", [])
                if topic.get("name")
                and (combo is self.preview_topic or not topic.get(CUSTOM_TOPIC_MARKER))
            )
            if combo is self.search_topic:
                combo.addItem(CUSTOM_DIRECTION)
            if selected not in {
                combo.itemText(index) for index in range(combo.count())
            }:
                selected = "全部主题"
            combo.setCurrentText(selected)
            combo.blockSignals(False)
        self._update_custom_topic_visibility()

    def _show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("关于文献日报")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setMinimumWidth(620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("文献日报")
        title.setStyleSheet("font-size:20pt;color:#2870c8;font-weight:700")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"文献日报 GUI v{APP_VERSION}"))
        layout.addWidget(QLabel("研究文献检索、筛选与日报工具。"))
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)

        details = QGridLayout()
        details.setHorizontalSpacing(18)
        details.setVerticalSpacing(10)
        rows = (("作者：", "Shanyue Wei"),)
        for row, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setStyleSheet("color:#64748b")
            text = QLabel(value)
            text.setWordWrap(True)
            details.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
            details.addWidget(text, row, 1)

        email = "xmweishanyue@fjirsm.ac.cn"
        email_label = QLabel("邮箱：")
        email_label.setStyleSheet("color:#64748b")
        copy_email = QPushButton("复制")
        copy_email.clicked.connect(lambda: QApplication.clipboard().setText(email))
        details.addWidget(email_label, len(rows), 0)
        details.addWidget(QLabel(email), len(rows), 1)
        details.addWidget(copy_email, len(rows), 2)
        layout.addLayout(details)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)
        layout.addWidget(QLabel("检索数据源：OpenAlex、Crossref"))

        close_button = QPushButton("关闭")
        close_button.setObjectName("runButton")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _create_task(self) -> None:
        if not self._save_settings(show_message=False):
            return
        try:
            message = create_daily_task(self.schedule_time.time().toString("HH:mm"))
            self._refresh_task_status()
            QMessageBox.information(self, "定时任务已设置", message)
        except Exception as exc:
            QMessageBox.critical(self, "设置定时任务失败", str(exc))

    def _delete_task(self) -> None:
        try:
            message = delete_daily_task()
            self._refresh_task_status()
            QMessageBox.information(self, "定时任务已取消", message)
        except Exception as exc:
            QMessageBox.critical(self, "取消定时任务失败", str(exc))

    def _refresh_task_status(self) -> None:
        try:
            self.task_status.setText("已启用" if daily_task_exists() else "未启用")
        except Exception as exc:
            self.task_status.setText(f"无法检查：{exc}")

    def _search_command(self) -> list[str]:
        days = self._days_selected()
        fetch_limit = min(2000, max(400, days * 12))
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-daily"]
        else:
            command = [
                sys.executable,
                "-X",
                "utf8",
                "-u",
                str(ROOT / "run_daily.py"),
            ]
        command.extend([
            "--no-open",
            "--days",
            str(days),
            "--top",
            "2000",
            "--max-per-topic",
            "2000",
            "--fetch-limit",
            str(fetch_limit),
        ])
        topic = self.search_topic.currentText()
        if topic == CUSTOM_DIRECTION:
            topic = custom_topic_name(
                {"custom_keyword_terms": self.custom_keyword_terms.toPlainText()}
            )
            if not topic:
                raise ValueError("自定义方向至少需要填写一个关键词")
        if topic and topic != "全部主题":
            command.extend(["--topic", topic])
        if self.include_reported.isChecked():
            command.append("--include-reported")
        if not self.translation_enabled.isChecked():
            command.append("--no-translate")
        return command

    def _run_now(self) -> None:
        if self.process and self.process.poll() is None:
            QMessageBox.information(self, "正在运行", "当前已有一次筛选任务运行中。")
            return
        if not self._save_settings(show_message=False):
            return
        try:
            command = self._search_command()
        except ValueError as exc:
            QMessageBox.critical(self, "检索设置无效", str(exc))
            return
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            QMessageBox.critical(self, "无法启动", str(exc))
            return
        self.run_status.setText("运行中…")
        self.run_button.setEnabled(False)
        self.main_tabs.setCurrentWidget(self.log_page)
        self._append_log("开始运行筛选任务…")
        threading.Thread(
            target=self._read_process_output, args=(self.process,), daemon=True
        ).start()

    def _read_process_output(self, process: subprocess.Popen) -> None:
        if process.stdout:
            for line in process.stdout:
                self.output_queue.put(("line", line.rstrip()))
        self.output_queue.put(("exit", process.wait()))

    def _drain_output(self) -> None:
        try:
            while True:
                kind, value = self.output_queue.get_nowait()
                if kind == "line":
                    self._append_log(value)
                else:
                    self.run_status.setText(f"结束（退出码 {value}）")
                    self._append_log(f"任务结束，退出码 {value}。")
                    self.run_button.setEnabled(True)
                    self.process = None
                    self._load_latest_preview()
                    self._load_latest_html()
        except queue.Empty:
            pass

    def _append_log(self, text: str) -> None:
        self.output.appendPlainText(text)

    def _load_latest_preview(self) -> None:
        data_dir = ROOT / "out" / "data"
        files = sorted(data_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not files:
            return
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            if not isinstance(payload.get("papers"), list):
                raise ValueError("日报 JSON 中缺少 papers 列表")
            self._populate_preview(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.preview_status.setText(f"读取日报失败：{exc}")

    def _populate_preview(self, payload: dict) -> None:
        self.preview_payload = payload
        topics = ["全部主题"] + [str(topic.get("name", "")) for topic in payload.get("topics") or []]
        self.preview_topic.blockSignals(True)
        self.preview_topic.clear()
        self.preview_topic.addItems(dict.fromkeys(topics))
        self.preview_topic.setCurrentText("全部主题")
        self.preview_topic.blockSignals(False)
        self.preview_query.clear()
        self._render_preview()
        self.main_tabs.setCurrentWidget(self.preview_page)

    def _render_preview(self, *_args) -> None:
        papers = self.preview_payload.get("papers") or []
        selected_topic = self.preview_topic.currentText()
        query = self.preview_query.text().strip().casefold()
        visible = [
            paper
            for paper in papers
            if (selected_topic == "全部主题" or selected_topic in (paper.get("topics") or []))
            and (
                not query
                or query
                in " ".join(
                    str(paper.get(field) or "")
                    for field in (
                        "title_en",
                        "title_zh",
                        "abstract_en",
                        "abstract_zh",
                        "journal",
                        "doi",
                    )
                ).casefold()
            )
        ]
        self.preview_papers = visible
        self.preview_table.setRowCount(len(visible))
        for row, paper in enumerate(visible):
            values = (
                str(paper.get("score", "")),
                " / ".join(paper.get("topics") or []),
                str(paper.get("published", "")),
                str(paper.get("journal", "")),
                str(paper.get("title_zh") or paper.get("title_en", "")),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.preview_table.setItem(row, column, item)
        stats = self.preview_payload.get("stats") or {}
        self.preview_status.setText(
            f"{self.preview_payload.get('date', '')} · 显示 {len(visible)} / {len(papers)} 篇"
            f" · 已翻译标题 {stats.get('translated', 0)} 篇"
        )
        if visible:
            self.preview_table.selectRow(0)
            self._show_preview_detail()
        else:
            self.preview_detail.setPlainText("没有符合条件的文献。")

    def _show_preview_detail(self) -> None:
        row = self.preview_table.currentRow()
        if row < 0 or row >= len(self.preview_papers):
            return
        paper = self.preview_papers[row]
        lines = [
            paper.get("title_zh") or paper.get("title_en", ""),
            paper.get("title_en", "") if paper.get("title_zh") else "",
            f"{paper.get('journal', '')} · {paper.get('published', '')} · 相关度 {paper.get('score', '')}",
            "",
            "中文摘要",
            paper.get("abstract_zh") or "（暂无中文摘要）",
            "",
            "Abstract",
            paper.get("abstract_en") or "（暂无英文摘要）",
            "",
            "命中关键词",
            "、".join(paper.get("matched_terms") or []) or "—",
            "",
            f"DOI: {paper.get('doi', '')}",
            f"链接: {paper.get('url_publisher') or paper.get('url_doi') or ''}",
        ]
        self.preview_detail.setPlainText("\n".join(str(line) for line in lines if line is not None))

    def _open_selected_paper(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.preview_papers):
            return
        url = self.preview_papers[row].get("url_publisher") or self.preview_papers[row].get("url_doi")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _load_latest_html(self) -> None:
        latest = ROOT / "out" / "daily" / "latest.html"
        selected_topic = self.search_topic.currentText()
        if selected_topic == CUSTOM_DIRECTION:
            selected_topic = custom_topic_name(self.gui_settings)
        data_dir = ROOT / "out" / "data"
        files = sorted(data_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if files:
            try:
                source = json.loads(files[0].read_text(encoding="utf-8"))
                if selected_topic and selected_topic != "全部主题":
                    topics = [
                        topic
                        for topic in source.get("topics") or []
                        if topic.get("name") == selected_topic
                    ]
                    papers = report.filter_papers_to_topics(source.get("papers") or [], topics)
                    payload = report.build_payload(
                        papers,
                        topics,
                        source.get("date", ""),
                        {"mode": source.get("mode", ""), "warning": source.get("warning", "")},
                        (source.get("stats") or {}).get("translated", 0),
                    )
                    payload["generated"] = source.get("generated", "")
                    self.html_status.setText(
                        f"当前日报：{source.get('date', '')} · 仅显示 {selected_topic}"
                    )
                else:
                    payload = source
                    self.html_status.setText(
                        f"当前日报：{source.get('date', '')} · 可在此页面直接交互浏览"
                    )
                self.html_view.setHtml(report.render_html(payload), QUrl.fromLocalFile(str(ROOT)))
                return
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                self.html_status.setText(f"读取 HTML 日报数据失败：{exc}")
        if latest.exists():
            self.html_view.setUrl(QUrl.fromLocalFile(str(latest.resolve())))
            self.html_status.setText(f"当前日报：{latest.name} · 可在此页面直接交互浏览")
        else:
            self.html_view.setHtml(
                "<html><meta charset='utf-8'><body style='font: bold 16px Arial,SimSun,sans-serif;"
                "padding:32px;color:#243247;background:#f3f6fb'>尚无 HTML 日报，请先运行一次筛选任务。</body></html>",
                QUrl.fromLocalFile(str(ROOT)),
            )
            self.html_status.setText("尚无日报")

    @staticmethod
    def _open_external_window(request) -> None:
        url = request.requestedUrl()
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def closeEvent(self, event) -> None:
        if self.process and self.process.poll() is None:
            answer = QMessageBox.question(
                self,
                "任务仍在运行",
                "关闭窗口不会停止筛选任务。仍要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def main() -> None:
    if getattr(sys, "frozen", False):
        arguments = sys.argv[1:]
        if "--run-daily" in arguments:
            _restore_frozen_output_streams()
            import run_daily

            index = arguments.index("--run-daily")
            sys.argv = ["run_daily.py", *arguments[index + 1 :]]
            raise SystemExit(run_daily.main())
        if "--run-scheduled" in arguments:
            import run_scheduled

            raise SystemExit(run_scheduled.main())

    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(_application_icon())
    try:
        window = LiteratureApp()
        window.show()
        sys.exit(app.exec())
    except Exception as exc:
        QMessageBox.critical(None, "文献日报 GUI 启动失败", str(exc))
        raise


def _application_icon() -> QIcon:
    bundle_root = Path(getattr(sys, "_MEIPASS", ROOT))
    for path in (bundle_root / APP_ICON_NAME, ROOT / APP_ICON_NAME):
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
            raise ValueError(f"程序图标文件无效：{path}")
    raise FileNotFoundError(f"找不到程序图标：{APP_ICON_NAME}")


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    import ctypes

    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    result = set_app_id("FJIRSM.LiteratureDaily")
    if result != 0:
        raise OSError(f"设置 Windows 任务栏应用 ID 失败：HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _restore_frozen_output_streams() -> None:
    if os.name != "nt":
        return
    import ctypes
    import msvcrt

    for name, std_handle in (("stdout", -11), ("stderr", -12)):
        stream = getattr(sys, name, None)
        if stream is not None:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            continue
        handle = ctypes.windll.kernel32.GetStdHandle(std_handle)
        if handle in (0, -1):
            continue
        file_descriptor = msvcrt.open_osfhandle(handle, os.O_TEXT)
        setattr(
            sys,
            name,
            os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            ),
        )


if __name__ == "__main__":
    main()
