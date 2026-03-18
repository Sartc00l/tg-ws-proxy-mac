#!/bin/bash
echo "🔧 Установка TG WS Proxy..."

# Создаем папку Applications если её нет
mkdir -p /Applications/TG\ WS\ Proxy.app

# Копируем приложение
cp -r installer/dist/TG\ WS\ Proxy.app /Applications/

# Снимаем карантин
xattr -d com.apple.quarantine /Applications/TG\ WS\ Proxy.app 2>/dev/null || true

# Даем права на выполнение
chmod -R 755 /Applications/TG\ WS\ Proxy.app

echo "✅ Установка завершена!"
echo "🚀 Запустите приложение из папки Программы"
