#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../Resources"

# Создаем отладочный лог
DEBUG_LOG="/tmp/tgws_debug.log"
echo "$(date): Starting TG WS Proxy" > "$DEBUG_LOG"
echo "Architecture: $(uname -m)" >> "$DEBUG_LOG"
echo "Current directory: $(pwd)" >> "$DEBUG_LOG"

# Проверяем наличие виртуального окружения
if [ ! -d "venv" ]; then
    echo "ERROR: venv not found!" >> "$DEBUG_LOG"
    exit 1
fi

# Активируем виртуальное окружение
source venv/bin/activate 2>> "$DEBUG_LOG"
echo "Python: $(which python)" >> "$DEBUG_LOG"
echo "Python version: $(python --version 2>&1)" >> "$DEBUG_LOG"

# Проверяем установленные пакеты
echo "Installed packages:" >> "$DEBUG_LOG"
pip list >> "$DEBUG_LOG" 2>&1

# Проверяем наличие основных модулей
python -c "import psutil; import cryptography; import rumps; import tg_ws_proxy" 2>> "$DEBUG_LOG"
echo "Import check exit code: $?" >> "$DEBUG_LOG"

# Запускаем с подробным выводом
echo "Starting macos.py..." >> "$DEBUG_LOG"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python macos.py 2>&1 | tee -a "$DEBUG_LOG"

EXIT_CODE=$?
echo "$(date): Application exited with code $EXIT_CODE" >> "$DEBUG_LOG"
