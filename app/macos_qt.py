#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TG WS Proxy - простое оконное приложение
"""

import sys
import os
import json
import time
import threading
import logging
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, Dict, List
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QDialog, QDialogButtonBox,
    QSpinBox, QLineEdit, QGroupBox, QFormLayout, QCheckBox,
    QPlainTextEdit, QMessageBox, QStatusBar
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QTextCursor

import asyncio
import tg_ws_proxy

# ============== CONFIG ==============
APP_NAME = "TG WS Proxy"
APP_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "proxy.log"

DEFAULT_CONFIG = {
    "port": 1080,
    "host": "127.0.0.1",
    "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
    "verbose": False,
}

# ============== LOGGING ==============
log = logging.getLogger("tg-ws-qt")
_logging_initialized = False

def setup_logging(verbose: bool = False):
    global _logging_initialized
    APP_DIR.mkdir(parents=True, exist_ok=True)
    
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    if _logging_initialized:
        return
    
    fh = RotatingFileHandler(
        str(LOG_FILE), maxBytes=3 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(fh)
    _logging_initialized = True

# ============== CONFIG HELPERS ==============
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            log.warning(f"Failed to load config: {e}")
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ============== PROXY THREAD ==============
_proxy_thread: Optional[threading.Thread] = None
_async_stop: Optional[object] = None
_config: dict = {}

def start_proxy():
    global _proxy_thread, _config
    if _proxy_thread and _proxy_thread.is_alive():
        return
    
    cfg = _config
    port = cfg.get("port", DEFAULT_CONFIG["port"])
    host = cfg.get("host", DEFAULT_CONFIG["host"])
    dc_ip_list = cfg.get("dc_ip", DEFAULT_CONFIG["dc_ip"])
    verbose = cfg.get("verbose", False)
    
    try:
        dc_opt = tg_ws_proxy.parse_dc_ip_list(dc_ip_list)
    except ValueError as e:
        log.error(f"Bad config: {e}")
        return
    
    log.info(f"Starting proxy on {host}:{port}")
    _proxy_thread = threading.Thread(
        target=_run_proxy_thread,
        args=(port, dc_opt, verbose, host),
        daemon=True,
        name="proxy"
    )
    _proxy_thread.start()

def _run_proxy_thread(port: int, dc_opt: Dict[int, List[str]], verbose: bool, host: str):
    global _async_stop
    setup_logging(verbose)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_ev = asyncio.Event()
    _async_stop = (loop, stop_ev)
    
    try:
        loop.run_until_complete(
            tg_ws_proxy._run(port, dc_opt, stop_event=stop_ev, host=host)
        )
    except Exception as e:
        log.error(f"Proxy crashed: {e}")
    finally:
        loop.close()
        _async_stop = None

def stop_proxy():
    global _proxy_thread, _async_stop
    if _async_stop:
        loop, stop_ev = _async_stop
        loop.call_soon_threadsafe(stop_ev.set)
        if _proxy_thread:
            _proxy_thread.join(timeout=5)
    _proxy_thread = None
    log.info("Proxy stopped")

def restart_proxy():
    stop_proxy()
    time.sleep(0.3)
    start_proxy()

# ============== SIGNALS ==============
class ProxySignals(QObject):
    stats_updated = pyqtSignal(str)
    log_updated = pyqtSignal(str)

signals = ProxySignals()

# ============== SETTINGS DIALOG ==============
class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.setWindowTitle("Настройки TG WS Proxy")
        self.setMinimumWidth(550)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Form
        form = QFormLayout()
        
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.config.get("port", 1080))
        form.addRow("Порт прокси:", self.port_spin)
        
        self.host_edit = QLineEdit(self.config.get("host", "127.0.0.1"))
        form.addRow("Хост:", self.host_edit)
        
        self.verbose_check = QCheckBox("Подробное логирование (verbose)")
        self.verbose_check.setChecked(self.config.get("verbose", False))
        form.addRow(self.verbose_check)
        
        layout.addLayout(form)
        
        # DC mappings
        dc_group = QGroupBox("DC → IP маппинги (формат DC:IP, каждый с новой строки)")
        dc_layout = QVBoxLayout(dc_group)
        
        self.dc_text = QPlainTextEdit()
        self.dc_text.setPlainText("\n".join(self.config.get("dc_ip", DEFAULT_CONFIG["dc_ip"])))
        self.dc_text.setFont(QFont("Menlo", 10))
        self.dc_text.setMinimumHeight(150)
        dc_layout.addWidget(self.dc_text)
        
        hint = QLabel("Пример: 2:149.154.167.220\nРекомендуется: DC2 (основной), DC4 (медиа)")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        dc_layout.addWidget(hint)
        
        layout.addWidget(dc_group)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)
    
    def restore_defaults(self):
        self.port_spin.setValue(DEFAULT_CONFIG["port"])
        self.host_edit.setText(DEFAULT_CONFIG["host"])
        self.verbose_check.setChecked(DEFAULT_CONFIG["verbose"])
        self.dc_text.setPlainText("\n".join(DEFAULT_CONFIG["dc_ip"]))
    
    def get_config(self) -> dict:
        lines = [l.strip() for l in self.dc_text.toPlainText().strip().splitlines() if l.strip()]
        if not lines:
            lines = DEFAULT_CONFIG["dc_ip"]
        
        return {
            "port": self.port_spin.value(),
            "host": self.host_edit.text().strip(),
            "dc_ip": lines,
            "verbose": self.verbose_check.isChecked(),
        }

# ============== MAIN WINDOW ==============
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Load config
        global _config
        _config = load_config()
        setup_logging(_config.get("verbose", False))
        
        # Setup window
        self.setWindowTitle(f"{APP_NAME} — Прокси для Telegram")
        self.setMinimumSize(700, 600)
        self.setWindowFlags(Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # === Status section ===
        status_group = QGroupBox("Статус прокси")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("🟡 Запуск...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        self.info_label = QLabel(f"Прокси слушает: {_config['host']}:{_config['port']}")
        status_layout.addWidget(self.info_label)
        
        layout.addWidget(status_group)
        
        # === Stats section ===
        stats_group = QGroupBox("Статистика")
        stats_layout = QVBoxLayout(stats_group)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(120)
        self.stats_text.setFont(QFont("Menlo", 10))
        stats_layout.addWidget(self.stats_text)
        
        layout.addWidget(stats_group)
        
        # === Log section ===
        log_group = QGroupBox("Логи работы")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Menlo", 9))
        log_layout.addWidget(self.log_text)
        
        # Log controls
        log_controls = QHBoxLayout()
        self.clear_log_btn = QPushButton("Очистить лог")
        self.clear_log_btn.clicked.connect(self.clear_log_display)
        self.refresh_log_btn = QPushButton("Обновить")
        self.refresh_log_btn.clicked.connect(self.refresh_log)
        self.open_log_btn = QPushButton("Открыть файл лога")
        self.open_log_btn.clicked.connect(self.open_log_file)
        
        log_controls.addWidget(self.clear_log_btn)
        log_controls.addWidget(self.refresh_log_btn)
        log_controls.addWidget(self.open_log_btn)
        log_controls.addStretch()
        log_layout.addLayout(log_controls)
        
        layout.addWidget(log_group)
        
        # === Buttons ===
        btn_layout = QHBoxLayout()
        
        self.open_tg_btn = QPushButton("🌍 Открыть в Telegram")
        self.open_tg_btn.clicked.connect(self.open_in_telegram)
        self.open_tg_btn.setMinimumHeight(40)
        
        self.settings_btn = QPushButton("⚙️ Настройки")
        self.settings_btn.clicked.connect(self.show_settings)
        self.settings_btn.setMinimumHeight(40)
        
        self.restart_btn = QPushButton("🔄 Перезапустить прокси")
        self.restart_btn.clicked.connect(self.restart_proxy)
        self.restart_btn.setMinimumHeight(40)
        
        btn_layout.addWidget(self.open_tg_btn)
        btn_layout.addWidget(self.settings_btn)
        btn_layout.addWidget(self.restart_btn)
        
        layout.addLayout(btn_layout)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готов")
        
        # Timers
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(2000)
        
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.refresh_log)
        self.log_timer.start(3000)
        
        # Start proxy
        start_proxy()
        
        # Initial update
        self.update_status()
        self.update_stats()
        self.refresh_log()
    
    def update_status(self):
        if _proxy_thread and _proxy_thread.is_alive():
            self.status_label.setText("🟢 Прокси: РАБОТАЕТ")
            self.status_label.setStyleSheet("color: green; font-size: 14px; font-weight: bold;")
            self.status_bar.showMessage(f"Прокси работает на порту {_config['port']}")
        else:
            self.status_label.setText("🔴 Прокси: ОСТАНОВЛЕН")
            self.status_label.setStyleSheet("color: red; font-size: 14px; font-weight: bold;")
            self.status_bar.showMessage("Прокси остановлен")
    
    def update_stats(self):
        if hasattr(tg_ws_proxy, '_stats'):
            stats = tg_ws_proxy._stats.summary()
            self.stats_text.setPlainText(stats)
        
        self.update_status()
    
    def refresh_log(self):
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    # Последние 200 строк
                    content = ''.join(lines[-200:])
                    self.log_text.setPlainText(content)
                    # Скроллим вниз
                    cursor = self.log_text.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self.log_text.setTextCursor(cursor)
            except Exception as e:
                pass
    
    def clear_log_display(self):
        self.log_text.clear()
    
    def open_log_file(self):
        if LOG_FILE.exists():
            subprocess.run(["open", str(LOG_FILE)])
        else:
            QMessageBox.information(self, "Лог", "Лог-файл еще не создан")
    
    def open_in_telegram(self):
        port = _config.get("port", 1080)
        url = f"tg://socks?server=127.0.0.1&port={port}"
        try:
            webbrowser.open(url)
            self.status_bar.showMessage("Открыт Telegram", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть Telegram: {e}")
    
    def show_settings(self):
        dialog = SettingsDialog(_config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_config()
            
            # Validate DC mappings
            try:
                tg_ws_proxy.parse_dc_ip_list(new_config["dc_ip"])
            except ValueError as e:
                QMessageBox.critical(self, "Ошибка", f"Некорректные DC маппинги:\n{e}")
                return
            
            # Save
            save_config(new_config)
            _config.update(new_config)
            setup_logging(_config.get("verbose", False))
            
            # Update UI
            self.info_label.setText(f"Прокси слушает: {_config['host']}:{_config['port']}")
            
            # Ask for restart
            reply = QMessageBox.question(
                self, "Настройки сохранены",
                "Настройки сохранены. Перезапустить прокси сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.restart_proxy()
            else:
                self.status_bar.showMessage("Настройки сохранены, перезапустите прокси вручную", 3000)
    
    def restart_proxy(self):
        self.status_bar.showMessage("Перезапуск прокси...")
        restart_proxy()
        self.update_status()
        self.status_bar.showMessage("Прокси перезапущен", 3000)
    
    def closeEvent(self, event):
        """При закрытии окна спрашиваем"""
        reply = QMessageBox.question(
            self, "Выход",
            "Закрыть приложение? Прокси остановится.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            stop_proxy()
            event.accept()
        else:
            event.ignore()


# ============== MAIN ==============
def main():
    # Hide from Dock
    if sys.platform == 'darwin':
        try:
            from Foundation import NSBundle
            bundle = NSBundle.mainBundle()
            info = bundle.infoDictionary()
            if info:
                info['LSUIElement'] = '1'
        except:
            pass
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    
    # Check if already running
    import fcntl
    lock_file = Path("/tmp/tg_ws_proxy_window.lock")
    try:
        with open(lock_file, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        QMessageBox.critical(None, APP_NAME, "Приложение уже запущено")
        return
    
    # Create and show window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()