#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import time
import asyncio
import logging
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import tg_ws_proxy


APP_NAME = "TG WS Proxy"
APP_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "proxy.log"
LOCK_FILE = APP_DIR / "app.lock"

DEFAULT_CONFIG = {
    "port": 1080,
    "host": "127.0.0.1",
    "dc_ip": [
        "2:149.154.167.220",
        "4:149.154.167.220",
    ],
    "verbose": False,
}

log = logging.getLogger("tg-ws-qt")
_logging_initialized = False
_lock_fp = None
_proxy_thread: Optional[threading.Thread] = None
_async_stop: Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Event]] = None
_config: dict = {}
_last_proxy_error: Optional[str] = None
_user_requested_stop = False


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def setup_macos_accessory_mode() -> None:
    if sys.platform != "darwin":
        return

    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        info = bundle.infoDictionary()
        if info is not None:
            info["LSUIElement"] = "1"
        localized = bundle.localizedInfoDictionary()
        if localized is not None:
            localized["LSUIElement"] = "1"
    except Exception:
        pass


def activate_macos_app() -> None:
    if sys.platform != "darwin":
        return

    try:
        from AppKit import NSApplication, NSApplicationActivateIgnoringOtherApps
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
    except Exception:
        pass


def setup_logging(verbose: bool = False) -> None:
    global _logging_initialized

    ensure_dirs()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    if _logging_initialized:
        for handler in root.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(logging.DEBUG)
            else:
                handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        return

    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=3 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    _logging_initialized = True


def load_config() -> dict:
    ensure_dirs()

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            merged = dict(DEFAULT_CONFIG)
            merged.update(data)

            if not isinstance(merged.get("dc_ip"), list):
                merged["dc_ip"] = list(DEFAULT_CONFIG["dc_ip"])

            if not merged.get("host"):
                merged["host"] = DEFAULT_CONFIG["host"]

            try:
                merged["port"] = int(merged.get("port", DEFAULT_CONFIG["port"]))
            except Exception:
                merged["port"] = DEFAULT_CONFIG["port"]

            merged["verbose"] = bool(merged.get("verbose", DEFAULT_CONFIG["verbose"]))
            return merged
        except Exception as exc:
            log.warning(f"Failed to load config: {exc}")

    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def acquire_lock() -> bool:
    global _lock_fp

    ensure_dirs()

    try:
        import fcntl
        _lock_fp = open(LOCK_FILE, "w")
        fcntl.flock(_lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fp.write(str(os.getpid()))
        _lock_fp.flush()
        return True
    except OSError:
        return False
    except Exception as exc:
        log.error(f"Failed to acquire lock: {exc}")
        return False


def release_lock() -> None:
    global _lock_fp

    if _lock_fp is None:
        return

    try:
        import fcntl
        fcntl.flock(_lock_fp, fcntl.LOCK_UN)
    except Exception:
        pass

    try:
        _lock_fp.close()
    except Exception:
        pass

    _lock_fp = None


def parse_and_validate_config(cfg: dict) -> dict:
    host = str(cfg.get("host", DEFAULT_CONFIG["host"])).strip()
    if not host:
        raise ValueError("Хост не должен быть пустым")

    port = int(cfg.get("port", DEFAULT_CONFIG["port"]))
    if not (1 <= port <= 65535):
        raise ValueError("Порт должен быть в диапазоне 1..65535")

    dc_ip = cfg.get("dc_ip", DEFAULT_CONFIG["dc_ip"])
    if not isinstance(dc_ip, list) or not dc_ip:
        raise ValueError("Список DC не должен быть пустым")

    dc_ip = [str(item).strip() for item in dc_ip if str(item).strip()]
    if not dc_ip:
        raise ValueError("Список DC не должен быть пустым")

    tg_ws_proxy.parse_dc_ip_list(dc_ip)

    return {
        "host": host,
        "port": port,
        "dc_ip": dc_ip,
        "verbose": bool(cfg.get("verbose", False)),
    }


def start_proxy() -> None:
    global _proxy_thread, _config, _last_proxy_error, _user_requested_stop

    if _proxy_thread and _proxy_thread.is_alive():
        return

    _user_requested_stop = False
    _last_proxy_error = None

    cfg = parse_and_validate_config(_config)
    port = cfg["port"]
    host = cfg["host"]
    dc_ip_list = cfg["dc_ip"]
    verbose = cfg["verbose"]

    dc_opt = tg_ws_proxy.parse_dc_ip_list(dc_ip_list)

    log.info(f"Starting proxy on {host}:{port}")

    _proxy_thread = threading.Thread(
        target=_run_proxy_thread,
        args=(port, dc_opt, verbose, host),
        daemon=True,
        name="proxy",
    )
    _proxy_thread.start()


def _run_proxy_thread(port: int, dc_opt: Dict[int, List[str]], verbose: bool, host: str) -> None:
    global _async_stop, _last_proxy_error

    setup_logging(verbose)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_ev = asyncio.Event()
    _async_stop = (loop, stop_ev)

    try:
        loop.run_until_complete(
            tg_ws_proxy._run(
                port,
                dc_opt,
                stop_event=stop_ev,
                host=host,
            )
        )
    except Exception as exc:
        _last_proxy_error = str(exc)
        log.exception(f"Proxy crashed: {exc}")
    finally:
        try:
            loop.close()
        except Exception:
            pass
        _async_stop = None


def stop_proxy() -> None:
    global _proxy_thread, _async_stop, _user_requested_stop

    _user_requested_stop = True

    if _async_stop:
        loop, stop_ev = _async_stop
        try:
            loop.call_soon_threadsafe(stop_ev.set)
        except Exception:
            pass

        if _proxy_thread:
            _proxy_thread.join(timeout=5)

    _proxy_thread = None
    log.info("Proxy stopped")


def restart_proxy() -> None:
    stop_proxy()
    time.sleep(0.25)
    start_proxy()


def is_proxy_running() -> bool:
    return _proxy_thread is not None and _proxy_thread.is_alive()


def read_log_tail(max_lines: int = 300) -> str:
    ensure_dirs()

    if not LOG_FILE.exists():
        return "Лог-файл еще не создан.\n"

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as exc:
        return f"Не удалось прочитать лог: {exc}\n"


class CardFrame(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        layout.addWidget(self.title)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(10)
        layout.addLayout(self.body_layout)


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)

        self.config = dict(config)
        self.setWindowTitle("Настройки")
        self.setMinimumSize(560, 420)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        form_card = CardFrame("Основные параметры")
        root.addWidget(form_card)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.host_edit = QLineEdit(self.config.get("host", DEFAULT_CONFIG["host"]))
        self.host_edit.setPlaceholderText("127.0.0.1")
        form.addRow("Хост", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(self.config.get("port", DEFAULT_CONFIG["port"])))
        form.addRow("Порт", self.port_spin)

        self.verbose_check = QCheckBox("Подробное логирование")
        self.verbose_check.setChecked(bool(self.config.get("verbose", False)))
        form.addRow("", self.verbose_check)

        form_card.body_layout.addLayout(form)

        dc_card = CardFrame("DC → IP")
        root.addWidget(dc_card, 1)

        self.dc_text = QPlainTextEdit()
        self.dc_text.setPlainText("\n".join(self.config.get("dc_ip", DEFAULT_CONFIG["dc_ip"])))
        self.dc_text.setMinimumHeight(170)
        self.dc_text.setPlaceholderText("2:149.154.167.220\n4:149.154.167.220")
        dc_card.body_layout.addWidget(self.dc_text)

        hint = QLabel("Каждая строка в формате DC:IP")
        hint.setObjectName("mutedLabel")
        dc_card.body_layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        root.addWidget(buttons)

    def restore_defaults(self) -> None:
        self.host_edit.setText(DEFAULT_CONFIG["host"])
        self.port_spin.setValue(DEFAULT_CONFIG["port"])
        self.verbose_check.setChecked(DEFAULT_CONFIG["verbose"])
        self.dc_text.setPlainText("\n".join(DEFAULT_CONFIG["dc_ip"]))

    def get_config(self) -> dict:
        lines = [line.strip() for line in self.dc_text.toPlainText().splitlines() if line.strip()]
        return {
            "host": self.host_edit.text().strip(),
            "port": self.port_spin.value(),
            "dc_ip": lines,
            "verbose": self.verbose_check.isChecked(),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        global _config
        _config = load_config()
        setup_logging(_config.get("verbose", False))

        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._tray_message_shown = False
        self._force_quit = False
        self.log_tail_lines = 300

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(860, 620)
        self.resize(1020, 720)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        top_grid = QGridLayout()
        top_grid.setHorizontalSpacing(14)
        top_grid.setVerticalSpacing(14)
        root.addLayout(top_grid)

        self.status_card = CardFrame("Состояние")
        top_grid.addWidget(self.status_card, 0, 0)

        self.status_label = QLabel("Запуск...")
        self.status_label.setObjectName("statusLabel")
        self.status_card.body_layout.addWidget(self.status_label)

        self.info_label = QLabel("")
        self.info_label.setObjectName("mutedLabel")
        self.status_card.body_layout.addWidget(self.info_label)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("errorLabel")
        self.error_label.hide()
        self.status_card.body_layout.addWidget(self.error_label)

        self.quick_card = CardFrame("Быстрые действия")
        top_grid.addWidget(self.quick_card, 0, 1)

        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(10)

        self.open_tg_btn = QPushButton("Открыть в Telegram")
        self.open_tg_btn.clicked.connect(self.open_in_telegram)
        self.open_tg_btn.setMinimumHeight(42)

        self.restart_btn = QPushButton("Перезапустить")
        self.restart_btn.clicked.connect(self.restart_proxy_action)
        self.restart_btn.setMinimumHeight(42)

        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.clicked.connect(self.show_settings)
        self.settings_btn.setMinimumHeight(42)

        quick_actions.addWidget(self.open_tg_btn)
        quick_actions.addWidget(self.restart_btn)
        quick_actions.addWidget(self.settings_btn)
        self.quick_card.body_layout.addLayout(quick_actions)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        stats_container = QWidget()
        stats_layout = QVBoxLayout(stats_container)
        stats_layout.setContentsMargins(0, 0, 0, 0)

        stats_card = CardFrame("Статистика")
        stats_layout.addWidget(stats_card)

        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMinimumHeight(170)
        stats_card.body_layout.addWidget(self.stats_text)

        splitter.addWidget(stats_container)

        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)

        log_card = CardFrame("Логи")
        log_layout.addWidget(log_card)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.refresh_log_btn = QPushButton("Обновить")
        self.refresh_log_btn.clicked.connect(self.refresh_log)

        self.clear_view_btn = QPushButton("Очистить окно")
        self.clear_view_btn.clicked.connect(self.clear_log_display)

        self.open_log_btn = QPushButton("Открыть файл")
        self.open_log_btn.clicked.connect(self.open_log_file)

        toolbar.addWidget(self.refresh_log_btn)
        toolbar.addWidget(self.clear_view_btn)
        toolbar.addWidget(self.open_log_btn)
        toolbar.addStretch()

        log_card.body_layout.addLayout(toolbar)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log_card.body_layout.addWidget(self.log_text)

        splitter.addWidget(log_container)
        splitter.setSizes([220, 420])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готово")

        self.create_tray()
        self.apply_styles()
        self.apply_runtime_info()

        try:
            start_proxy()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Не удалось запустить прокси:\n{exc}")

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(2000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.refresh_log)
        self.log_timer.start(3000)

        self.update_status()
        self.update_stats()
        self.refresh_log()

    def create_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setToolTip(APP_NAME)

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray_icon.setIcon(icon)

        menu = QMenu(self)

        open_action = QAction("Показать окно", self)
        open_action.triggered.connect(self.show_normal_from_tray)
        menu.addAction(open_action)

        tg_action = QAction("Открыть в Telegram", self)
        tg_action.triggered.connect(self.open_in_telegram)
        menu.addAction(tg_action)

        restart_action = QAction("Перезапустить прокси", self)
        restart_action.triggered.connect(self.restart_proxy_action)
        menu.addAction(restart_action)

        settings_action = QAction("Настройки", self)
        settings_action.triggered.connect(self.show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_normal_from_tray()

    def show_normal_from_tray(self) -> None:
        self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
        )
        activate_macos_app()
        self.raise_()
        self.activateWindow()

    def apply_runtime_info(self) -> None:
        self.info_label.setText(f"{_config['host']}:{_config['port']}")

    def apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #0f1115;
                color: #e8ecf1;
                font-size: 13px;
            }

            QFrame#card {
                background: #171a21;
                border: 1px solid #242938;
                border-radius: 14px;
            }

            QLabel#cardTitle {
                font-size: 15px;
                font-weight: 700;
                color: #ffffff;
            }

            QLabel#statusLabel {
                font-size: 20px;
                font-weight: 800;
                color: #ffffff;
            }

            QLabel#mutedLabel {
                color: #9aa4b2;
            }

            QLabel#errorLabel {
                color: #ff8d8d;
                background: rgba(255, 82, 82, 0.08);
                border: 1px solid rgba(255, 82, 82, 0.2);
                border-radius: 8px;
                padding: 8px 10px;
            }

            QPushButton {
                background: #232838;
                border: 1px solid #31384d;
                border-radius: 10px;
                padding: 10px 14px;
                color: #f4f7fb;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #2b3246;
                border: 1px solid #415072;
            }

            QPushButton:pressed {
                background: #1c2230;
            }

            QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {
                background: #10141c;
                border: 1px solid #2a3142;
                border-radius: 10px;
                padding: 8px 10px;
                color: #e8ecf1;
                selection-background-color: #2f6fed;
            }

            QPlainTextEdit, QTextEdit {
                font-family: Menlo, Monaco, Consolas, monospace;
                font-size: 12px;
            }

            QDialog {
                background: #0f1115;
            }

            QStatusBar {
                background: #11141b;
                color: #9aa4b2;
                border-top: 1px solid #1d2330;
            }

            QMenu {
                background: #171a21;
                color: #e8ecf1;
                border: 1px solid #2a3142;
                padding: 6px;
            }

            QMenu::item {
                padding: 8px 18px;
                border-radius: 8px;
            }

            QMenu::item:selected {
                background: #2a3142;
            }

            QCheckBox {
                spacing: 8px;
            }
        """)

    def update_status(self) -> None:
        self.apply_runtime_info()

        if is_proxy_running():
            self.status_label.setText("Прокси работает")
            self.status_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #55d68c;")
            self.status_bar.showMessage(f"Прокси активен на {_config['host']}:{_config['port']}")
            self.error_label.hide()

            if self.tray_icon:
                self.tray_icon.setToolTip(f"{APP_NAME} — работает")
        else:
            if _user_requested_stop:
                self.status_label.setText("Прокси остановлен")
                self.status_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #ffb454;")
                self.error_label.hide()
                self.status_bar.showMessage("Прокси остановлен")
            else:
                self.status_label.setText("Прокси не работает")
                self.status_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #ff7676;")
                self.status_bar.showMessage("Прокси не работает")

                if _last_proxy_error:
                    self.error_label.setText(_last_proxy_error)
                    self.error_label.show()
                else:
                    self.error_label.hide()

            if self.tray_icon:
                self.tray_icon.setToolTip(f"{APP_NAME} — не работает")

    def update_stats(self) -> None:
        try:
            stats_parts = []

            if hasattr(tg_ws_proxy, "_stats"):
                try:
                    stats_parts.append(str(tg_ws_proxy._stats.summary()))
                except Exception as exc:
                    stats_parts.append(f"Ошибка чтения статистики: {exc}")

            if hasattr(tg_ws_proxy, "_best_ip_snapshot"):
                try:
                    best_ip = tg_ws_proxy._best_ip_snapshot()
                    stats_parts.append(f"\nЛучшие IP по DC:\n{best_ip}")
                except Exception:
                    pass

            if not stats_parts:
                stats_parts.append("Статистика недоступна")

            self.stats_text.setPlainText("\n".join(stats_parts))
        except Exception as exc:
            self.stats_text.setPlainText(f"Ошибка обновления статистики: {exc}")

        self.update_status()

    def refresh_log(self) -> None:
        content = read_log_tail(self.log_tail_lines)
        self.log_text.setPlainText(content)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    def clear_log_display(self) -> None:
        self.log_text.clear()
        self.status_bar.showMessage("Окно логов очищено", 2000)

    def open_log_file(self) -> None:
        ensure_dirs()

        if not LOG_FILE.exists():
            try:
                LOG_FILE.touch()
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка", f"Не удалось создать лог-файл:\n{exc}")
                return

        result = subprocess.run(["open", str(LOG_FILE)], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть лог-файл")

    def open_in_telegram(self) -> None:
        port = _config.get("port", DEFAULT_CONFIG["port"])
        url = f"tg://socks?server=127.0.0.1&port={port}"

        try:
            ok = webbrowser.open(url)
            if ok:
                self.status_bar.showMessage("Telegram открыт", 2500)
                return
        except Exception:
            pass

        try:
            escaped = url.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'set the clipboard to "{escaped}"'],
                capture_output=True,
                text=True,
            )
            QMessageBox.information(
                self,
                "Ссылка скопирована",
                f"Не удалось открыть Telegram автоматически.\n\nСсылка скопирована в буфер обмена:\n{url}",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть Telegram:\n{exc}")

    def show_settings(self) -> None:
        dialog = SettingsDialog(_config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            new_config = parse_and_validate_config(dialog.get_config())
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return

        save_config(new_config)
        _config.update(new_config)
        setup_logging(_config.get("verbose", False))
        self.apply_runtime_info()

        reply = QMessageBox.question(
            self,
            "Настройки сохранены",
            "Настройки сохранены. Перезапустить прокси сейчас?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_proxy_action()
        else:
            self.status_bar.showMessage("Настройки сохранены", 2500)

    def restart_proxy_action(self) -> None:
        self.status_bar.showMessage("Перезапуск прокси...")
        try:
            restart_proxy()
            self.update_status()
            self.update_stats()
            self.status_bar.showMessage("Прокси перезапущен", 2500)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось перезапустить прокси:\n{exc}")

    def closeEvent(self, event) -> None:
        if self._force_quit:
            event.accept()
            return

        if self.tray_icon and self.tray_icon.isVisible():
            event.ignore()
            self.hide()

            if not self._tray_message_shown:
                self._tray_message_shown = True
                self.tray_icon.showMessage(
                    APP_NAME,
                    "Окно скрыто. Приложение продолжает работать в трее.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            return

        event.accept()

    def quit_app(self) -> None:
        self._force_quit = True
        try:
            stop_proxy()
        finally:
            if self.tray_icon:
                self.tray_icon.hide()
            release_lock()
            self.close()
            QApplication.quit()


def main() -> None:
    setup_macos_accessory_mode()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if not acquire_lock():
        QMessageBox.critical(None, APP_NAME, "Приложение уже запущено")
        return

    window = MainWindow()
    window.show()
    activate_macos_app()

    exit_code = app.exec()

    stop_proxy()
    release_lock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()