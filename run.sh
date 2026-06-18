#!/bin/bash
set -e

echo "=== Скрипт запуска новостного агента: $(date) ==="

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

MODEL_PATH="${LOCAL_MODEL_PATH:-/app/models/gemma-4-31B-it-UD-Q4_K_XL.gguf}"
MODEL_URL="https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/resolve/main/gemma-4-31B-it-UD-Q4_K_XL.gguf"

if [ ! -f "$MODEL_PATH" ]; then
    echo "Модель не найдена. Загрузка..."
    mkdir -p "$(dirname "$MODEL_PATH")"
    curl -L "$MODEL_URL" -o "$MODEL_PATH"
fi

echo "Запуск основного приложения..."
python3 main.py

echo "=== Агент остановлен: $(date) ==="
