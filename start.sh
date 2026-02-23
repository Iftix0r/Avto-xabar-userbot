#!/bin/bash

# Papka ichiga kirish
cd "$(dirname "$0")"

# Virtual muhitni tekshirish
if [ ! -d "venv" ]; then
    echo "Virtual muhit yaratilmoqda..."
    python3 -m venv venv
fi

# Virtual muhitni faollashtirish
source venv/bin/activate

# Kutubxonalarni o'rnatish/yangilash
echo "Kutubxonalar o'rnatilmoqda..."
pip install --upgrade pip
pip install -r requirements.txt

# Eski jarayonni to'xtatish (agar bo'lsa)
if [ -f "bot.pid" ]; then
    PID=$(cat bot.pid)
    if ps -p $PID > /dev/null; then
        echo "Eski jarayon (PID: $PID) to'xtatilmoqda..."
        kill $PID
        sleep 2
    fi
fi

# Botni backgroundda ishga tushirish
echo "Bot background rejimida ishga tushirilmoqda..."
nohup python3 main.py > bot.log 2>&1 &

# Yangi PID-ni saqlash
echo $! > bot.pid

echo "✅ Bot ishga tushdi!"
echo "🔹 PID: $(cat bot.pid)"
echo "🔹 Loglarni ko'rish: tail -f bot.log"
