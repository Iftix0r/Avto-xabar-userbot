# 🚀 Telegram Multi-User Ads Bot (Userbot)

Ushbu loyiha Telegram akauntlari orqali guruhlarga avtomatik tarzda reklama matnlarini tarqatuvchi kuchli va qulay UserBot tizimidir. Bot `Aiogram 3` va `Telethon` kutubxonalari asosida yaratilgan.

## ✨ Imkoniyatlar

- 👥 **Ko'p foydalanuvchilik tizim:** Bir vaqtning o'zida bir nechta foydalanuvchi o'z akauntini ulay oladi.
- 👨‍💻 **Admin Panel:** Jami foydalanuvchilar va faol userbotlar statistikasini kuzatish.
- 📱 **Oson ulanish:** Bot orqali telefon raqami va kod yuborish orqali profilga ulanish.
- 🔐 **2FA Qo'llab-quvvatlash:** Ikki bosqichli tasdiqlash paroli mavjud akauntlarni ham ulay oladi.
- 📢 **Avtomatik Sender:** Ma'lum bir vaqt oralig'ida (interval) avtomatik xabar yuborish.
- ⚙️ **Shaxsiy Sozlamalar:** Har bir foydalanuvchi o'z reklama matni va yuborish oralig'ini o'zi sozlaydi.
- 📁 **Xavfsiz Sessiyalar:** Sessiya fayllari alohida `sessions/` papkasida tartibli saqlanadi.

## 🛠 Texnologiyalar

- **Python 3.10+**
- **Aiogram 3** (Bot interfeysi uchun)
- **Telethon** (Userbot funksiyasi uchun)
- **Python-dotenv** (Konfiguratsiya uchun)

## 🚀 O'rnatish

1. Loyihani yuklab oling:
```bash
git clone https://github.com/Iftix0r/Avto-xabar-userbot.git
cd Avto-xabar-userbot
```

2. Virtual muhitni yarating va faollashtiring:
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# yoki
venv\Scripts\activate  # Windows
```

3. Kerakli kutubxonalarni o'rnating:
```bash
pip install -r requirements.txt
```

4. `.env` faylini yarating va quyidagi ma'lumotlarni kiriting:
```env
BOT_TOKEN=Sizning_Bot_Tokeningiz
API_ID=Sizning_API_IDingiz
API_HASH=Sizning_API_Hashlingiz
ADMIN_ID=Sizning_IDingiz
AD_DELAY=3600
```

## 📖 Foydalanish

1. Botni ishga tushiring: `python main.py`
2. Botga `/start` buyrug'ini yuboring.
3. "📱 Akkountga ulanish" tugmasini bosing va raqamingizni kiriting.
4. Telegram'dan kelgan kodni yozing (agar 2FA bo'lsa `kod,parol` ko'rinishida).
5. Reklama matni va vaqtni sozlab, "🚀 Ishni boshlash" tugmasini bosing.

## ⚠️ Ogohlantirish

Ushbu bot faqat tanishuv va yaxshi maqsadlar uchun ishlab chiqilgan. Telegram qoidalariga ko'ra, juda ko'p guruhlarga spam xabarlar yuborish akkauntingiz bloklanishiga (spam-block) olib kelishi mumkin. Muallif har qanday blok holatiga mas'uliyatni o'z zimmasiga olmaydi.

## 🤝 Aloqa

Agar savollaringiz bo'lsa, @Iftix0r` ga murojaat qilishingiz mumkin.

---
⭐ Agar loyiha sizga yoqqan bo'lsa, **Star** berishni unutmang!
