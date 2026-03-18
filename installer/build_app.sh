#!/bin/bash

# Конфигурация
APP_NAME="TG WS Proxy"
VERSION="1.1.1"
BUILD_DIR="build"
DIST_DIR="dist"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}🔨 Building $APP_NAME v$VERSION for macOS (Universal)...${NC}"

# Очистка предыдущей сборки
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# Создаём структуру .app
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Копируем файлы приложения - ВАЖНО: кладём всё в корень Resources, а не в proxy
echo "📦 Copying application files..."
if [ -d "../app" ]; then
    # Копируем все файлы в корень Resources (так проще для импортов)
    cp ../app/macos.py "$RESOURCES_DIR/"
    cp ../app/tg_ws_proxy.py "$RESOURCES_DIR/"
    cp ../app/__init__.py "$RESOURCES_DIR/" 2>/dev/null || true
    
    # Создаем пустой __init__.py чтобы папка стала модулем
    touch "$RESOURCES_DIR/__init__.py"
else
    echo -e "${RED}❌ Error: Cannot find application files (../app/)${NC}"
    exit 1
fi

# Копируем requirements
if [ -f "../requirements-mac.txt" ]; then
    cp ../requirements-mac.txt "$RESOURCES_DIR/"
else
    echo -e "${RED}⚠️  Warning: requirements-mac.txt not found${NC}"
fi

# Копируем README если есть
if [ -f "../README.md" ]; then
    cp ../README.md "$RESOURCES_DIR/"
fi

# Создаём иконку (используем готовую или генерируем)
echo "🎨 Creating icon..."
if [ -f "icon.icns" ]; then
    # Используем существующую иконку
    cp icon.icns "$RESOURCES_DIR/"
else
    # Генерируем базовую иконку если нет готовой
    mkdir -p icon.iconset
    python3 -c "
from PIL import Image, ImageDraw
import os

size = 1024
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
margin = size // 8
draw.ellipse([margin, margin, size - margin, size - margin], 
             fill=(51, 144, 236, 255))  # Telegram blue
img.save('icon.iconset/icon_512x512.png')
"
    sips -z 16 16 icon.iconset/icon_512x512.png --out icon.iconset/icon_16x16.png 2>/dev/null
    sips -z 32 32 icon.iconset/icon_512x512.png --out icon.iconset/icon_32x32.png 2>/dev/null
    sips -z 64 64 icon.iconset/icon_512x512.png --out icon.iconset/icon_64x64.png 2>/dev/null
    sips -z 128 128 icon.iconset/icon_512x512.png --out icon.iconset/icon_128x128.png 2>/dev/null
    sips -z 256 256 icon.iconset/icon_512x512.png --out icon.iconset/icon_256x256.png 2>/dev/null
    iconutil -c icns icon.iconset -o icon.icns
    cp icon.icns "$RESOURCES_DIR/"
fi

# Создаём Info.plist
cat > "$CONTENTS_DIR/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleIdentifier</key>
    <string>org.telegram.tgwsproxy</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>LSUIElement</key>
    <true/>
    <key>Application is agent (UIElement)</key>
    <string>1</string>
    <key>NSUIElement</key>
    <string>1</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Создаём виртуальное окружение с Python 3.11 прямо в .app
echo "📦 Creating virtual environment in .app with Python 3.11..."
cd "$RESOURCES_DIR"

# Определяем путь к Python 3.11
if [ -f "/opt/homebrew/bin/python3.11" ]; then
    PYTHON_PATH="/opt/homebrew/bin/python3.11"
elif [ -f "/usr/local/bin/python3.11" ]; then
    PYTHON_PATH="/usr/local/bin/python3.11"
else
    echo -e "${RED}⚠️  Python 3.11 not found. Please install: brew install python@3.11${NC}"
    PYTHON_PATH="python3"
fi

# Создаём виртуальное окружение
$PYTHON_PATH -m venv venv
source venv/bin/activate

# Устанавливаем все зависимости
echo "📚 Installing dependencies in .app..."
pip install --upgrade pip
pip install cryptography==41.0.7
pip install psutil==5.9.8
pip install rumps==0.4.0
pip install pyperclip==1.9.0

# Отмечаем архитектуру
echo "$(uname -m)" > .deps_installed

# Деактивируем и возвращаемся
deactivate
cd "$OLDPWD"

echo "✅ Virtual environment created with all dependencies"

# Создаём лаунчер
echo "🚀 Creating launcher..."
cat > "$MACOS_DIR/launcher" << 'EOF'
#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../Resources"

# Функция для показа диалога
show_info() {
    osascript -e "display dialog \"$1\" buttons {\"OK\"} default button \"OK\" with icon note"
}

show_error() {
    osascript -e "display dialog \"$1\" buttons {\"OK\"} default button \"OK\" with icon stop"
}

# Определяем архитектуру
ARCH=$(uname -m)
echo "🔧 Architecture: $ARCH"

# Проверяем наличие виртуального окружения
if [ ! -d "venv" ]; then
    show_error "Виртуальное окружение не найдено!\n\nПереустановите приложение."
    exit 1
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Проверяем, что все зависимости работают
python -c "import psutil; import cryptography; import rumps; import pyperclip" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Dependencies check failed, reinstalling..."
    pip install --upgrade pip
    pip install cryptography==41.0.7 psutil==5.9.8 rumps==0.4.0 pyperclip==1.9.0
fi

# Исправляем импорт в macos.py если нужно
if [ -f "macos.py" ] && grep -q "import proxy.tg_ws_proxy" macos.py; then
    echo "🔧 Fixing import in macos.py..."
    cp macos.py macos.py.bak
    sed -i '' 's/import proxy.tg_ws_proxy/import tg_ws_proxy/g' macos.py
fi

# Запускаем приложение
echo "🚀 Starting TG WS Proxy..."
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python3 macos.py

# Если приложение закрылось, показываем сообщение
if [ $? -eq 0 ]; then
    show_info "TG WS Proxy остановлен.\n\nЛоги: ~/Library/Application Support/TgWsProxy/proxy.log"
fi
EOF

chmod +x "$MACOS_DIR/launcher"

# Создаем README для пользователя
cat > "$RESOURCES_DIR/README.txt" << EOF
TG WS Proxy v$VERSION

Приложение запущено! Иконка появится в меню-баре.

Если не работает:
1. Проверьте логи: ~/Library/Application Support/TgWsProxy/proxy.log
2. Перезапустите приложение

Для настройки Telegram:
- Настройки → Продвинутые → Тип подключения → Прокси
- SOCKS5: 127.0.0.1:1080 (без логина/пароля)
EOF

echo -e "${GREEN}✅ Build complete: $APP_BUNDLE${NC}"
echo ""
echo "📦 To create DMG, run:"
echo "    brew install create-dmg"
echo "    create-dmg --volname \"$APP_NAME\" --volicon \"icon.icns\" --window-pos 200 120 --window-size 800 400 --icon-size 100 --icon \"$APP_NAME.app\" 200 190 --hide-extension \"$APP_NAME.app\" --app-drop-link 600 185 \"$DIST_DIR/$APP_NAME.dmg\" \"$DIST_DIR/$APP_NAME.app\""