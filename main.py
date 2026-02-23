import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError
from dotenv import load_dotenv

# Log sozlamalari
logging.basicConfig(level=logging.INFO)

# .env yuklash
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DEFAULT_AD_DELAY = int(os.getenv("AD_DELAY", 3600))

# Papkalarni yaratish
if not os.path.exists("sessions"):
    os.makedirs("sessions")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Foydalanuvchilar ma'lumotlari (Amalda bazadan foydalanish tavsiya etiladi)
# user_id: {client, phone, is_running, ad_text, interval, session_path}
users_data = {}

class AuthState(StatesGroup):
    phone = State()
    code_pass = State()
    ad_text = State()
    ad_interval = State()

# Klaviaturalar
def get_main_keyboard(user_id):
    kb = [
        [KeyboardButton(text="📱 Akkountga ulanish")],
        [KeyboardButton(text="📢 Reklamani sozlash"), KeyboardButton(text="🚀 Ishni boshlash")],
        [KeyboardButton(text="⏹ To'xtatish")]
    ]
    if user_id == ADMIN_ID:
        kb.append([KeyboardButton(text="👨‍💻 Admin Panel")])
    
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")]
    ])

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "👋 Assalomu alaykum! Bu bot orqali o'z profilingizni guruhlarga avtomatik reklama yuborishga sozlashingiz mumkin.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- Admin Panel ---
@dp.message(F.text == "👨‍💻 Admin Panel")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Boshqaruv paneliga xush kelibsiz:", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    total_users = len(users_data)
    active_bots = sum(1 for u in users_data.values() if u.get('is_running'))
    await callback.message.edit_text(
        f"📊 **Statistika:**\n\n"
        f"🔹 Jami foydalanuvchilar: {total_users}\n"
        f"⚡️ Faol userbotlar: {active_bots}",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query(F.data == "admin_users")
async def admin_users_list(callback: types.CallbackQuery):
    if not users_data:
        text = "Hozircha hech kim yo'q."
    else:
        text = "👥 **Foydalanuvchilar:**\n\n"
        for uid, data in users_data.items():
            status = "✅" if data.get('is_running') else "💤"
            text += f"ID: `{uid}` - {data.get('phone', 'Noma`lum')} {status}\n"
    
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())

# --- Userbot Ulash ---
@dp.message(F.text == "📱 Akkountga ulanish")
async def prompt_phone(message: types.Message, state: FSMContext):
    await message.answer("Telefon raqamingizni xalqaro formatda kiriting:\n(Masalan: `+998901234567`)", parse_mode="Markdown")
    await state.set_state(AuthState.phone)

@dp.message(AuthState.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.replace(" ", "")
    user_id = message.from_user.id
    
    session_path = f"sessions/sess_{user_id}"
    client = TelegramClient(session_path, API_ID, API_HASH)
    
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        
        users_data[user_id] = {
            'client': client,
            'phone': phone,
            'is_running': False,
            'ad_text': '',
            'interval': DEFAULT_AD_DELAY,
            'phone_code_hash': sent_code.phone_code_hash
        }
        
        await message.answer(
            "📩 Tasdiqlash kodi yuborildi.\n\n"
            "Iltimos, kodni va agar parolingiz (2FA) bo'lsa parolni vergul bilan ajratib yuboring.\n"
            "Format: `kod,parol` yoki faqat `kod`",
            parse_mode="Markdown"
        )
        await state.set_state(AuthState.code_pass)
        
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        await state.clear()

@dp.message(AuthState.code_pass)
async def process_code_pass(message: types.Message, state: FSMContext):
    # Foydalanuvchi kiritgan matnni tahlil qilish
    text = message.text.split(",")
    code = text[0].strip()
    provided_password = text[1].strip() if len(text) > 1 else None
    
    user_id = message.from_user.id
    if user_id not in users_data:
        await message.answer("Xatolik! Qaytadan /start bosing.")
        await state.clear()
        return

    client = users_data[user_id]['client']
    phone = users_data[user_id]['phone']
    code_hash = users_data[user_id]['phone_code_hash']

    try:
        # Avval faqat kod bilan urinib ko'ramiz
        await client.sign_in(phone, code, phone_code_hash=code_hash)
        await message.answer("✅ Muvaffaqiyatli ulandi!", reply_markup=get_main_keyboard(user_id))
        await state.clear()
        
    except SessionPasswordNeededError:
        # Agar 2FA so'rasa va foydalanuvchi parolni yozgan bo'lsa
        if provided_password:
            try:
                await client.sign_in(password=provided_password)
                await message.answer("✅ Parol orqali muvaffaqiyatli ulandi!", reply_markup=get_main_keyboard(user_id))
                await state.clear()
            except PasswordHashInvalidError:
                await message.answer("❌ Ikki bosqichli parol noto'g'ri. Qaytadan kiriting (kod,parol):")
            except Exception as e:
                await message.answer(f"❌ Kutilmagan xato: {e}")
        else:
            # Agar parol yozilmagan bo'lsa, foydalanuvchidan so'raymiz
            await message.answer(
                "🔑 Akkauntingizda ikki bosqichli tasdiqlash (2FA) yoqilgan.\n\n"
                "Iltimos, parolni yuboring yoki kod bilan birga qaytadan yozing:\n"
                "Masalan: `kod,parol`",
                parse_mode="Markdown"
            )
            # state.code_pass holatida qolamiz, foydalanuvchi parolni yuborishi uchun
            
    except PhoneCodeInvalidError:
        await message.answer("❌ Tasdiqlash kodi noto'g'ri. Iltimos, tekshirib qaytadan yuboring:")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        await state.clear()

# --- Reklama Sozlamalari ---
@dp.message(F.text == "📢 Reklamani sozlash")
async def set_ad_text(message: types.Message, state: FSMContext):
    await message.answer("Reklama matnini kiriting:")
    await state.set_state(AuthState.ad_text)

@dp.message(AuthState.ad_text)
async def save_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {'is_running': False, 'interval': DEFAULT_AD_DELAY}
    
    users_data[user_id]['ad_text'] = message.text
    await message.answer("Vaxtni (sekundda) kiriting (masalan: 3600):")
    await state.set_state(AuthState.ad_interval)

@dp.message(AuthState.ad_interval)
async def save_interval(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        interval = int(message.text)
        if interval < 60:
            return await message.answer("Kamida 60 sekund bo'lishi kerak!")
        
        users_data[user_id]['interval'] = interval
        await message.answer("✅ Saqlandi!", reply_markup=get_main_keyboard(user_id))
        await state.clear()
    except ValueError:
        await message.answer("Faqat raqam kiriting!")

# --- Sender Logikasi ---
async def start_sender(user_id):
    data = users_data[user_id]
    client = data['client']
    
    while data.get('is_running'):
        try:
            # Guruhlarni aniqlash
            async for dialog in client.iter_dialogs():
                if not data.get('is_running'): break
                if dialog.is_group or dialog.is_channel:
                    try:
                        await client.send_message(dialog.id, data['ad_text'])
                        await asyncio.sleep(5) # Har bir guruh orasida 5 sekund
                    except Exception as e:
                        logging.error(f"Error sending to {dialog.id}: {e}")
            
            # Kutish
            for _ in range(data['interval']):
                if not data.get('is_running'): break
                await asyncio.sleep(1)
                
        except Exception as e:
            logging.error(f"Global sender error: {e}")
            await asyncio.sleep(60)

@dp.message(F.text == "🚀 Ishni boshlash")
async def run_bot(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users_data or not users_data[user_id].get('ad_text'):
        return await message.answer("Avval akkountni ulang va reklamani sozlang!")
    
    if users_data[user_id].get('is_running'):
        return await message.answer("Allaqachon ishlamoqda.")

    users_data[user_id]['is_running'] = True
    asyncio.create_task(start_sender(user_id))
    await message.answer("🚀 Userbot ishga tushirildi!")

@dp.message(F.text == "⏹ To'xtatish")
async def stop_bot(message: types.Message):
    user_id = message.from_user.id
    if user_id in users_data:
        users_data[user_id]['is_running'] = False
        await message.answer("🛑 To'xtatildi.")

async def main():
    print("Bot @ADMIN_ID orqali boshqariladi va ishga tushdi.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
