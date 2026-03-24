from setuptools import setup
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP = [os.path.join(BASE_DIR, "..", "app", "macos_qt.py")]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": os.path.join(BASE_DIR, "..", "installer", "icon.icns"),
    "plist": {
        "CFBundleName": "TG WS Proxy",
        "CFBundleDisplayName": "TG WS Proxy",
        "CFBundleIdentifier": "com.tgwsproxy.macos.qt",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
    "packages": [
        "PyQt6",
        "cryptography",
        "cffi",
    ],
    "includes": [
        "app",
        "app.tg_ws_proxy",
        "_cffi_backend",
        "cffi",
        "cryptography",
        "asyncio",
        "threading",
        "json",
        "logging",
        "subprocess",
        "webbrowser",
    ],
    "excludes": [
        "tkinter",
    ],
}

setup(
    app=APP,
    name="TG WS Proxy",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)