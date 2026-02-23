#!/bin/bash

# Papka ichiga kirish
cd "$(dirname "$0")"

if [ -f "bot.pid" ]; then
    PID=$(cat bot.pid)
    echo "Bot to'xtatilmoqda (PID: $PID)..."
    
    if ps -p $PID > /dev/null; then
        kill $PID
        rm bot.pid
        echo "✅ Bot muvaffaqiyatli to'xtatildi."
    else
        echo "⚠️ Jarayon topilmadi, lekin pid fayli o'chirildi."
        rm bot.pid
    fi
else
    echo "❌ bot.pid fayli topilmadi. Bot ishlamayotgan bo'lishi mumkin."
fi
