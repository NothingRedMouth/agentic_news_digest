#!/bin/bash
set -e

# Log start time
echo "=== Скрипт создания еженедельных дайджестов запущен: $(date) ==="

MODEL_PATH="/app/models/gemma-4-31B-it-UD-Q4_K_XL.gguf"
MODEL_URL="https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/resolve/main/gemma-4-31B-it-UD-Q4_K_XL.gguf"

if [ ! -f "$MODEL_PATH" ]; then
    echo "Модель не найдена. Загрузка..."
    curl -L "$MODEL_URL" -o "$MODEL_PATH"
fi

cd /app
python3 main.py

echo "=== Еженедельный дайджест сгенерирован: $(date) ==="
