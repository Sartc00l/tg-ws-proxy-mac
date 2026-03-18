#!/bin/bash

# Создание .app бандла для macOS
APP_NAME="TG WS Proxy"
APP_DIR="dist/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Создаем структуру папок
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Устанавливаем зависимости
pip3 install -r requirements-mac.txt
pip3 install pyinstaller

# Сборка с помощью pyinstaller
pyinstaller --onefile \
            --name "$APP_NAME" \
            --add-data "proxy:proxy" \
            --hidden-import rumps \
            --hidden-import tkinter \
            macos.py

# Копируем бинарник в .app
cp "dist/$APP_NAME" "$MACOS_DIR/"

# Создаем Info.plist
cat > "$CONTENTS_DIR/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
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
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

# Если есть иконка, копируем её
if [ -f "icon.icns" ]; then
    cp icon.icns "$RESOURCES_DIR/"
fi

echo "✅ .app bundle создан: $APP_DIR"