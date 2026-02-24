# Avto Habar Bot - Telegram Reklama Yuborish Tizimi

## 🎯 Xususiyatlari

### 👤 Foydalanuvchi Imkoniyatlari
- **Profillar** - Bir nechta Telegram akkauntlarini qo'shish va boshqarish
- **Guruhlar** - Guruhlarni folderlar bo'yicha tashkil etish
- **Reklama Matni** - Avtomatik yuborish uchun xabar matni sozlash
- **Rasm Yuborish** - Pro rejada rasm bilan reklama yuborish
- **Interval** - 1 minutdan boshlab istalgan vaqt oralig'ini sozlash
- **Avtomatik Yuborish** - Tanlangan guruhlardan guruhlarga avtomatik xabar yuborish

### 💳 To'lov Tizimi
- **Start** - 1 oy (50,000 so'm)
- **Pro** - 3 oy (120,000 so'm), 6 oy (200,000 so'm)
- **VIP** - 1 yil (350,000 so'm), Umrbod (500,000 so'm)

**To'lov jarayoni:**
1. Obuna turini tanlash
2. Chekni rasm sifatida yuborish
3. Admin tasdiqlashi kutish
4. Obuna faollashtirilish

### 👨‍💻 Admin Paneli
- **Statistika** - Jami foydalanuvchilar va faol senderlar
- **Foydalanuvchilar Ro'yxati** - Barcha foydalanuvchilar va ularning obunalari
- **Qidirish** - ID orqali foydalanuvchini topish
- **Obuna Uzaytirish** - Foydalanuvchiga obuna berish yoki uzaytirish
- **Narxlarni Sozlash** - Har bir obuna rejasining narxini o'zgartirish
- **Xabar Yuborish** - Barcha foydalanuvchilarga xabar yuborish
- **To'lov Tasdiqlash** - Foydalanuvchi to'lovlarini tasdiqlash yoki rad etish

## 🚀 O'rnatish

### Talablar
- Python 3.8+
- Telegram Bot Token
- Telegram API ID va API Hash

### Qadamlar

1. **Repozitoriyani klonlash**
```bash
git clone <repo-url>
cd bot
```

2. **Virtual muhitni yaratish**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# yoki
venv\Scripts\activate  # Windows
```

3. **Kutubxonalarni o'rnatish**
```bash
pip install -r requirements.txt
```

4. **.env faylini yaratish**
```
BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
ADMIN_ID=your_admin_id
AD_DELAY=3600
```

5. **Botni ishga tushirish**
```bash
python main.py
```

## 📋 Foydalanish

### Foydalanuvchi uchun
1. `/start` - Botni ishga tushirish
2. "📱 Akkountga ulanish" - Telegram akkauntini ulash
3. "👥 Profillar" - Qo'shimcha profillar qo'shish
4. "📋 Guruhlar" - Guruhlarni folderlar bo'yicha tashkil etish
5. "💬 Xabar matni" - Reklama matnini kiritish
6. "⏱ Interval" - Yuborish vaqt oralig'ini sozlash
7. "▶️ Ishga tushirish" - Avtomatik yuborishni boshlash

### Admin uchun
1. `/addsub <user_id> <kun>` - Foydalanuvchiga obuna berish
2. Admin Panel → Qidirish → Foydalanuvchini boshqarish
3. Admin Panel → To'lov Tasdiqlash → Foydalanuvchi to'lovlarini tasdiqlash

## 📁 Fayl Tuzilishi

```
.
├── main.py              # Asosiy bot kodi
├── requirements.txt     # Python kutubxonalari
├── .env                 # Muhit o'zgaruvchilari
├── bot_database.db      # SQLite ma'lumotlar bazasi
├── sessions/            # Telegram sessiyalari
├── payments/            # To'lov cheklari
└── README.md            # Bu fayl
```

## 🗄️ Ma'lumotlar Bazasi

### Jadvallar
- **subscriptions** - Foydalanuvchi obunalari
- **profiles** - Foydalanuvchi profillar
- **groups** - Guruh folderlar
- **payment_requests** - To'lov so'rovlari
- **ad_templates** - Reklama shablonlari

## ⚙️ Konfiguratsiya

### .env Fayli
```
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
API_ID=123456
API_HASH=abcdef1234567890abcdef1234567890
ADMIN_ID=123456789
AD_DELAY=3600
```

## 🔒 Xavfsizlik

- Sessiyalar `sessions/` papkasida saqlanadi
- To'lov cheklari `payments/` papkasida saqlanadi
- Admin ID orqali admin huquqlari tekshiriladi
- Obuna muddati avtomatik tekshiriladi

## 📞 Qo'llab-quvvatlash

Muammolar yoki savollar bo'lsa, admin bilan bog'laning.

## 📝 Litsenziya

Bu loyiha shaxsiy foydalanish uchun.
