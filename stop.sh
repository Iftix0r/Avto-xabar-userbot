#!/bin/bash

# Papka ichiga kirish
cd "$(dirname "$0")"

echo "Bot to'xtatilmoqda..."

# 1. PID orqali to'xtatish
if [ -f "bot.pid" ]; then
    PID=$(cat bot.pid)
    if ps -p $PID > /dev/null; then
        kill $PID
        echo "✅ Bot (PID: $PID) to'xtatildi."
    fi
    rm bot.pid
fi

# 2. Qolgan main.py jarayonlarini ham o'chirish
pkill -f main.py
echo "✅ Barcha main.py jarayonlari to'xtatildi."
