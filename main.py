import asyncio
import os
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, AuthKeyDuplicatedError
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DEFAULT_AD_DELAY = int(os.getenv("AD_DELAY", 3600))
DB_PATH = "bot_database.db"

if not os.path.exists("sessions"):
    os.makedirs("sessions")
if not os.path.exists("payments"):
    os.makedirs("payments")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
users_data = {}

class AuthState(StatesGroup):
    phone = State()
    code_pass = State()
    ad_text = State()
    ad_interval = State()
    admin_broadcast_message = State()
    admin_search_user = State()
    admin_extend_sub = State()
    payment_screenshot = State()
    add_profile_phone = State()
    add_profile_code = State()
    add_group_name = State()
    add_group_ids = State()
    create_group_folder_name = State()
    add_admin_id = State()
    remove_admin_id = State()
    edit_payment_info = State()

# --- Ma'lumotlar bazasi ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                expiry_date TEXT,
                plan_type TEXT DEFAULT 'free'
            )
        """)
        
        # Migration: plan_type column'ini qo'shish (agar bo'lmasa)
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN plan_type TEXT DEFAULT 'free'")
            await db.commit()
            logging.info("Added plan_type column to subscriptions table")
        except Exception as e:
            if "duplicate column name" in str(e):
                logging.info("plan_type column already exists")
            else:
                logging.error(f"Error adding plan_type column: {e}")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                session_name TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                folder_name TEXT,
                group_ids TEXT,
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_type TEXT,
                amount INTEGER,
                screenshot_path TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ad_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                image_path TEXT,
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER UNIQUE,
                username TEXT,
                added_by INTEGER,
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pricing (
                plan_type TEXT PRIMARY KEY,
                duration_days INTEGER,
                price INTEGER
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                is_running INTEGER DEFAULT 0,
                interval INTEGER,
                ad_text TEXT,
                image_path TEXT,
                video_path TEXT,
                voice_path TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payment_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_number TEXT,
                card_holder TEXT,
                amount INTEGER,
                created_at TEXT
            )
        """)
        
        # Unique index for groups to prevent duplicates
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_folder ON groups(user_id, folder_name)")
        except:
            pass

        await db.commit()
        
        # Default narxlarni qo'shish
        await db.execute("DELETE FROM pricing")
        await db.execute("""
            INSERT INTO pricing (plan_type, duration_days, price) VALUES
            ('start', 30, 50000),
            ('3month', 90, 120000),
            ('pro', 180, 200000),
            ('year', 365, 350000),
            ('vip', 9999, 500000)
        """)
        await db.commit()

async def add_subscription(user_id: int, days: int, plan_type: str = "free"):
    expiry_date = datetime.now() + timedelta(days=days)
    if days == 9999:
        expiry_date_str = "2099-12-31 23:59:59"
    else:
        expiry_date_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO subscriptions (user_id, expiry_date, plan_type)
            VALUES (?, ?, ?)
        """, (user_id, expiry_date_str, plan_type))
        await db.commit()

async def check_subscription(user_id: int):
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                expiry_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                return expiry_date > datetime.now()
    return False

# --- Admin Tekshirish ---
async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
    return result is not None

# --- Klaviaturalar ---
async def get_main_keyboard(user_id, is_connected=False):
    is_admin_user = await is_admin(user_id)
    has_sub = await check_subscription(user_id)
    
    if not is_connected:
        buttons = [[KeyboardButton(text="📱 Akkountga ulanish")]]
        if is_admin_user:
            buttons.append([KeyboardButton(text="👑 Admin Panel (Inline)")])
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        
    kb = []
    
    # Faqat obunasi borlarga boshqaruv tugmalarini ko'rsatamiz
    if has_sub:
        kb.extend([
            [InlineKeyboardButton(text="👥 Profillar", callback_data="main_profillar"), InlineKeyboardButton(text="💬 Xabar matni", callback_data="main_xabar")],
            [InlineKeyboardButton(text="📋 Guruhlar", callback_data="main_groups"), InlineKeyboardButton(text="▶️ Ishga tushirish", callback_data="main_start_sender")],
            [InlineKeyboardButton(text="⏱ Interval", callback_data="main_interval"), InlineKeyboardButton(text="👤 Profil", callback_data="main_profile")],
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="main_settings")]
        ])
    
    if is_admin_user:
        kb.append([InlineKeyboardButton(text="👨‍💻 Admin Panel", callback_data="main_admin")])
    
    # Agar obuna yo'q bo'lsa va admin bo'lmasa, faqat obuna tugmasini qaytaramiz (aslida bu start_handlerda boshqariladi)
    if not has_sub and not is_admin_user:
        return await get_subscription_keyboard()

    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(F.text == "👑 Admin Panel (Inline)")
async def admin_panel_text_btn(message: types.Message):
    if await is_admin(message.from_user.id):
        await show_admin_panel(message)

async def get_subscription_keyboard():
    """Bazadagi narxlardan obuna tugmalarini yaratadi"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type, duration_days, price FROM pricing ORDER BY duration_days") as cursor:
            prices = await cursor.fetchall()
    
    plan_buttons = {
        "start": "buy_start",
        "3month": "buy_3month",
        "pro": "buy_pro_plan",
        "year": "buy_year",
        "vip": "buy_vip",
    }
    plan_labels = {
        "start": "Start — 1 oy",
        "3month": "Pro — 3 oy",
        "pro": "Pro — 6 oy",
        "year": "VIP — 1 yil",
        "vip": "VIP — Umrbod",
    }
    kb = []
    for plan_type, days, price in prices:
        if plan_type in plan_buttons:
            kb.append([InlineKeyboardButton(
                text=f"🔹 {plan_labels[plan_type]} ({price:,} so'm)",
                callback_data=plan_buttons[plan_type]
            )])
    kb.append([InlineKeyboardButton(text="👤 Admin bilan bog'lanish", url=f"tg://user?id={ADMIN_ID}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def send_sub_msg(message: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type, duration_days, price FROM pricing ORDER BY duration_days") as cursor:
            prices = await cursor.fetchall()
    plan_names = {"start": "Start — 1 oy", "3month": "Pro — 3 oy", "pro": "Pro — 6 oy", "year": "VIP — 1 yil", "vip": "VIP — Umrbod"}
    text = "🔥 **Obuna turlarini tanlang:**\n\n"
    for plan, days, price in prices:
        if plan in plan_names:
            text += f"🔹 {plan_names[plan]}: {price:,} so'm\n"
    text += "\n⏱ Istalgan vaqtda, istalgan guruhga, istagan e'loningizni avtomatik yuboradi!"
    await message.answer(text, reply_markup=await get_subscription_keyboard(), parse_mode="Markdown")

# --- Client Helper ---
_active_clients = {}

async def get_user_client(user_id, session_name=None):
    key = f"sess_{user_id}" if not session_name else session_name
    
    if key in _active_clients:
        client = _active_clients[key]
        if client.is_connected():
            try:
                if await client.is_user_authorized():
                    return client
            except Exception:
                pass
        # If not connected or authorized, try to clean up
        try:
            await client.disconnect()
        except:
            pass
        del _active_clients[key]

    session_path = f"sessions/{key}"
    if os.path.exists(session_path + ".session"):
        client = TelegramClient(session_path, API_ID, API_HASH)
        try:
            await client.connect()
            if await client.is_user_authorized():
                _active_clients[key] = client
                return client
            else:
                await client.disconnect()
        except AuthKeyDuplicatedError:
            logging.error(f"Duplicate session for {key}. Deleting corrupted session file.")
            try: await client.disconnect() 
            except: pass
            
            # Delete the corrupted session file
            try:
                if os.path.exists(session_path + ".session"):
                    os.remove(session_path + ".session")
                if os.path.exists(session_path + ".session-journal"):
                    os.remove(session_path + ".session-journal")
            except Exception as e:
                logging.error(f"Failed to delete corrupted session {key}: {e}")
        except Exception as e:
            logging.error(f"Error connecting client {key}: {e}")
            try: await client.disconnect() 
            except: pass
            
    return None

def get_interval_keyboard():
    kb = [
        [InlineKeyboardButton(text="1 minut", callback_data="setint_60"), InlineKeyboardButton(text="5 minut", callback_data="setint_300")],
        [InlineKeyboardButton(text="10 minut", callback_data="setint_600"), InlineKeyboardButton(text="20 minut", callback_data="setint_1200")],
        [InlineKeyboardButton(text="30 minut", callback_data="setint_1800"), InlineKeyboardButton(text="1 soat", callback_data="setint_3600")],
        [InlineKeyboardButton(text="2 soat", callback_data="setint_7200"), InlineKeyboardButton(text="3 soat", callback_data="setint_10800")],
        [InlineKeyboardButton(text="✏️ Boshqa", callback_data="setint_custom")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Handlerlar ---
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    
    # Foydalanuvchini ro'yxatga olish
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                username = excluded.username,
                full_name = excluded.full_name
        """, (user_id, message.from_user.username, message.from_user.full_name, datetime.now().isoformat()))
        await db.commit()
    
    is_admin_user = await is_admin(user_id)
    client = await get_user_client(user_id)
    is_connected = client is not None
    has_sub = await check_subscription(user_id)
    
    if not is_connected:
        await message.answer(
            "👋 Assalomu alaykum! Botdan foydalanish uchun avval profilingizni ulashingiz kerak.",
            reply_markup=await get_main_keyboard(user_id, is_connected=False)
        )
        return
    
    if has_sub:
        await message.answer("🏠 **Asosiy boshqaruv paneli:**", reply_markup=await get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
    else:
        # Obuna yo'q, lekin admin bo'lsa admin panel tugmasini qo'shib ko'rsatamiz
        kb = await get_subscription_keyboard()
        if is_admin_user:
            # Admin uchun obuna xabari tagiga admin panel tugmasini qo'shamiz
            new_kb = []
            for row in kb.inline_keyboard:
                new_kb.append(row)
            new_kb.append([InlineKeyboardButton(text="👨‍💻 Admin Panel", callback_data="main_admin")])
            kb = InlineKeyboardMarkup(inline_keyboard=new_kb)
            
        await message.answer(
            "❌ **Sizda faol obuna mavjud emas!**\n\nBot imkoniyatlaridan foydalanish uchun obuna sotib oling:",
            reply_markup=kb,
            parse_mode="Markdown"
        )

@dp.message(F.text == "📱 Akkountga ulanish")
async def prompt_phone(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Tugmani bosish orqali raqamingizni yuboring yoki qo'lda kiriting:", reply_markup=kb)
    await state.set_state(AuthState.phone)

@dp.message(AuthState.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.replace(" ", "")
    if not phone.startswith("+"): phone = "+" + phone
    user_id = message.from_user.id
    session_path = f"sessions/sess_{user_id}"
    await message.answer("Tekshirilmoqda...", reply_markup=types.ReplyKeyboardRemove())
    client = TelegramClient(session_path, API_ID, API_HASH)
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        users_data[user_id] = {'client': client, 'phone': phone, 'is_running': False, 'ad_text': '', 'interval': DEFAULT_AD_DELAY, 'phone_code_hash': sent_code.phone_code_hash}
        await message.answer("📩 **Tasdiqlash kodi yuborildi.**\nKodni vergul bilan ajratib yuboring (Masalan: `1,2,3,4,5`):", parse_mode="Markdown")
        await state.set_state(AuthState.code_pass)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        await state.clear()

@dp.message(AuthState.code_pass)
async def process_auth_step(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.replace(",", "").replace(" ", "")
    data = await state.get_data()
    
    if user_id not in users_data:
        await message.answer("❌ Xatolik: Avtorizatsiya jarayoni topilmadi. Qayta urinib ko'ring.")
        await state.clear()
        return

    client = users_data[user_id]['client']
    phone = users_data[user_id]['phone']
    phone_code_hash = users_data[user_id]['phone_code_hash']
    saved_code = data.get('saved_code') # This is for 2FA password

    async def finish_auth():
        # Clientni _active_clients ga saqlash
        session_key = f"sess_{user_id}"
        _active_clients[session_key] = client
        
        is_sub = await check_subscription(user_id)
        if is_sub:
            await message.answer("✅ Muvaffaqiyatli ulandi!", reply_markup=await get_main_keyboard(user_id, is_connected=True))
        else:
            await message.answer("✅ Akkount muvaffaqiyatli ulandi!")
            await send_sub_msg(message)
        await state.clear()

    if saved_code: # This means we are expecting a 2FA password
        try:
            await client.sign_in(password=message.text.strip())
            await finish_auth()
        except Exception as e:
            await message.answer(f"❌ Xato: {e}")
        return

    # Otherwise, we are expecting the phone code
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        await finish_auth()
    except SessionPasswordNeededError:
        await state.update_data(saved_code=code) # Store the code, next message will be the password
        await message.answer("🔑 2FA Parolni yuboring:")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        await state.clear()


# --- To'lov Tizimi ---
@dp.callback_query(F.data.startswith("buy_"))
async def buy_subscription(callback: types.CallbackQuery, state: FSMContext):
    # extend_buy_ callback'larini o'tkazib yuborish
    if callback.data.startswith("extend_buy_"):
        return
    
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    
    # Fallback: users_data dan tekshirish
    if not client and user_id in users_data and 'client' in users_data[user_id]:
        client = users_data[user_id]['client']
        try:
            if client.is_connected() and await client.is_user_authorized():
                _active_clients[f"sess_{user_id}"] = client
            else:
                client = None
        except Exception:
            client = None
    
    if not client:
        await callback.answer("❌ Avval akkauntingizni ulashingiz kerak!", show_alert=True)
        return

    # Narxlarni bazadan olish
    plan_key = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT duration_days, price FROM pricing WHERE plan_type = ?", (plan_key,)) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        await callback.answer("❌ Reja topilmadi!", show_alert=True)
        return
    
    days, amount = row
    plan_names = {
        "start": "Start (1 oy)",
        "3month": "Pro (3 oy)",
        "pro": "Pro (6 oy)",
        "year": "VIP (1 yil)",
        "vip": "VIP (Umrbod)"
    }
    plan_name = plan_names.get(plan_key, "Noma'lum")
    
    await state.update_data(plan_type=plan_key, plan_name=plan_name, days=days, amount=amount)
    
    # Admin panel'dan to'lov ma'lumotlarini olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_number, card_holder, amount FROM payment_info ORDER BY created_at DESC LIMIT 1") as cursor:
            payment_row = await cursor.fetchone()
    
    if payment_row:
        card_number, card_holder, payment_amount = payment_row
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi karta raqamiga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"💳 **Karta raqami:** `{card_number}`\n"
            f"👤 **Karta egasi:** `{card_holder}`"
        )
    else:
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi raqamga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"⚠️ To'lov ma'lumotlari hali kiritilmagan. Admin bilan bog'laning."
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Chekni yuborish", callback_data=f"payment_screenshot_{plan_key}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_payment")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buy_pro_plan")
async def buy_pro_plan_handler(callback: types.CallbackQuery, state: FSMContext):
    """Obuna keyboard'idan Pro (6 oy) rejasini tanlash"""
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    
    if not client:
        await callback.answer("❌ Avval akkauntingizni ulashingiz kerak!", show_alert=True)
        return

    plan_key = "pro"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT duration_days, price FROM pricing WHERE plan_type = ?", (plan_key,)) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        await callback.answer("❌ Reja topilmadi!", show_alert=True)
        return
    
    days, amount = row
    plan_name = "Pro (6 oy)"
    
    await state.update_data(plan_type=plan_key, plan_name=plan_name, days=days, amount=amount)
    
    # Admin panel'dan to'lov ma'lumotlarini olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_number, card_holder, amount FROM payment_info ORDER BY created_at DESC LIMIT 1") as cursor:
            payment_row = await cursor.fetchone()
    
    if payment_row:
        card_number, card_holder, payment_amount = payment_row
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi karta raqamiga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"💳 **Karta raqami:** `{card_number}`\n"
            f"👤 **Karta egasi:** `{card_holder}`"
        )
    else:
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi raqamga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"⚠️ To'lov ma'lumotlari hali kiritilmagan. Admin bilan bog'laning."
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Chekni yuborish", callback_data=f"payment_screenshot_{plan_key}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_payment")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("payment_screenshot_"))
async def payment_screenshot_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 **Chekni rasm sifatida yuboring:**\n\nTo'lov qilganingizni tasdiqlovchi rasm yuboring.")
    await state.set_state(AuthState.payment_screenshot)
    await callback.answer()

@dp.message(AuthState.payment_screenshot)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Iltimos, rasm yuboring!")
        return
    
    user_id = message.from_user.id
    data = await state.get_data()
    
    logging.info(f"Payment screenshot received from user {user_id}")
    logging.info(f"State data: {data}")
    
    # Rasmni saqlash
    photo = message.photo[-1]
    file_path = f"payments/{user_id}_{datetime.now().timestamp()}.jpg"
    await bot.download(photo, destination=file_path)
    logging.info(f"Screenshot saved to {file_path}")
    
    # To'lov so'rovini bazaga qo'shish
    request_id = None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO payment_requests (user_id, plan_type, amount, screenshot_path, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (user_id, data.get('plan_type'), data.get('amount'), file_path, datetime.now().isoformat()))
        request_id = cursor.lastrowid
        await db.commit()
    
    # Foydalanuvchiga xabar
    await message.answer(
        f"✅ **So'rovingiz adminga yuborildi!**\n\n"
        f"📦 Reja: {data.get('plan_name')}\n"
        f"💰 Summa: {data.get('amount'):,} so'm\n\n"
        f"⏳ Admin tasdiqlashi kutib turing...\n"
        f"Tasdiqlansa, obunangiz avtomatik faollashtiriladi.",
        parse_mode="Markdown"
    )
    
    # To'lov haqida xabar tayyorlash
    try:
        plan_name = data.get('plan_name', 'Noma`lum')
        amount_val = data.get('amount', 0)
        amount_fmt = f"{int(amount_val):,}" if amount_val else "0"
    except:
        amount_fmt = str(data.get('amount', '0'))

    # Foydalanuvchi ma'lumotlarini olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT username, full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_info = await cursor.fetchone()
    
    username = user_info[0] if user_info and user_info[0] else "Noma'lum"
    full_name = user_info[1] if user_info and user_info[1] else "Noma'lum"

    admin_text = (
        f"🔔 **Yangi To'lov So'rovi**\n\n"
        f"👤 Foydalanuvchi: `{user_id}`\n"
        f"📝 Ism: {full_name}\n"
        f"🔗 Username: @{username}\n"
        f"📦 Reja: **{plan_name}**\n"
        f"💰 Summa: **{amount_fmt} so'm**\n\n"
        f"✅ Tasdiqlash uchun quyidagi tugmani bosing:"
    )
    
    # Request ID bilan unique callback (bir xil user bir necha marta yuborganda ham)
    req_id = request_id or 0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_payment_{req_id}_{user_id}_{data.get('plan_type', 'none')}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_payment_{req_id}_{user_id}")]
    ])
    
    # Barcha adminlarga xabar yuborish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id FROM admins") as cursor:
            admins = await cursor.fetchall()
            
    # Asosiy adminni ham qo'shish
    admin_ids = {ADMIN_ID}
    for (a_id,) in admins:
        admin_ids.add(a_id)
    
    logging.info(f"Sending payment notification to admins: {admin_ids}")
        
    for a_id in admin_ids:
        try:
            # Chek rasmini adminga yuborish
            from aiogram.types import FSInputFile
            screenshot_file = FSInputFile(file_path)
            await bot.send_photo(a_id, photo=screenshot_file, caption=admin_text, reply_markup=kb, parse_mode="Markdown")
            logging.info(f"Payment notification sent to admin {a_id}")
        except Exception as e:
            logging.error(f"Error sending payment photo to admin {a_id}: {e}")
            # Agar rasm yuborilmasa, matn yuborish
            try:
                await bot.send_message(a_id, admin_text, reply_markup=kb, parse_mode="Markdown")
                logging.info(f"Payment notification (text) sent to admin {a_id}")
            except Exception as e2:
                logging.error(f"Error sending payment text to admin {a_id}: {e2}")
    
    await state.clear()

@dp.callback_query(F.data.startswith("approve_payment_"))
async def approve_payment(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    parts = callback.data.split("_")
    # Format: approve_payment_{request_id}_{user_id}_{plan_type} yoki eski: approve_payment_{user_id}_{plan_type}
    if len(parts) >= 5:
        request_id, user_id, plan_type = int(parts[2]), int(parts[3]), parts[4]
    else:
        user_id, plan_type = int(parts[2]), parts[3]
        request_id = None
    
    plan_days = {
        "start": 30,
        "3month": 90,
        "pro": 180,
        "year": 365,
        "vip": 9999
    }
    
    days = plan_days.get(plan_type, 30)
    await add_subscription(user_id, days, plan_type)
    
    # payment_requests statusni yangilash
    if request_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE payment_requests SET status = 'approved' WHERE id = ?", (request_id,))
            await db.commit()
    
    # Foydalanuvchiga xabar va asosiy menyuni yuborish
    await bot.send_message(user_id, "✅ **To'lovingiz tasdiqlandi!**\n\nObunangiz faollashtirildi. Botdan foydalanishni boshlashingiz mumkin.", parse_mode="Markdown")
    await bot.send_message(user_id, "🏠 **Asosiy boshqaruv paneli:**", reply_markup=await get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
    
    try:
        await callback.message.edit_caption(caption="✅ To'lov tasdiqlandi!", reply_markup=None)
    except Exception:
        try:
            await callback.message.edit_text("✅ To'lov tasdiqlandi!", reply_markup=None)
        except Exception:
            await callback.message.answer("✅ To'lov tasdiqlandi!")
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    parts = callback.data.split("_")
    # Format: reject_payment_{request_id}_{user_id} yoki eski: reject_payment_{user_id}
    if len(parts) >= 4:
        request_id, user_id = int(parts[2]), int(parts[3])
        if request_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE payment_requests SET status = 'rejected' WHERE id = ?", (request_id,))
                await db.commit()
    else:
        user_id = int(parts[-1])
    
    await bot.send_message(user_id, "❌ **To'lovingiz rad etildi.**\n\nIltimos, admin bilan bog'laning.", parse_mode="Markdown")
    try:
        await callback.message.edit_caption(caption="❌ To'lov rad etildi!", reply_markup=None)
    except Exception:
        try:
            await callback.message.edit_text("❌ To'lov rad etildi!", reply_markup=None)
        except Exception:
            await callback.message.answer("❌ To'lov rad etildi!")
    await callback.answer()

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ To'lov bekor qilindi.", reply_markup=await get_subscription_keyboard())
    await state.clear()
    await callback.answer()

# --- Profillar Tizimi ---
@dp.callback_query(F.data == "main_profillar")
async def show_profiles(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Obuna tekshirish (admin'lar uchun o'tkazib yuborish)
    is_admin_user = await is_admin(user_id)
    if not is_admin_user and not await check_subscription(user_id):
        await callback.answer("❌ Bu xizmat faqat obuna bo'lgan foydalanuvchilar uchun!", show_alert=True)
        return await send_sub_msg(callback.message)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, phone, is_active FROM profiles WHERE user_id = ?", (user_id,)) as cursor:
            profiles = await cursor.fetchall()
    
    text = "👥 **Sizning Profillaringiz**\n\n"
    
    if not profiles:
        text += "Hozircha profil yo'q.\n\n"
    else:
        for idx, (pid, phone, is_active) in enumerate(profiles, 1):
            status = "✅" if is_active else "❌"
            text += f"{idx}. {status} `{phone}`\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Profil qo'shish", callback_data="add_profile")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_profile")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "add_profile")
async def add_profile_prompt(callback: types.CallbackQuery, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.answer("📱 **Yangi profil qo'shish**\n\nTugmani bosish orqali raqamingizni yuboring yoki qo'lda kiriting:", reply_markup=kb)
    await state.set_state(AuthState.add_profile_phone)
    await callback.answer()

@dp.message(AuthState.add_profile_phone)
async def process_add_profile_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.replace(" ", "")
    if not phone.startswith("+"): phone = "+" + phone
    
    user_id = message.from_user.id
    session_name = f"profile_{user_id}_{int(datetime.now().timestamp())}"
    session_path = f"sessions/{session_name}"
    
    await message.answer("🔍 **Tekshirilmoqda...**", reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    client = TelegramClient(session_path, API_ID, API_HASH)
    
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        
        await state.update_data(
            profile_phone=phone,
            profile_session_name=session_name,
            profile_phone_code_hash=sent_code.phone_code_hash
        )
        
        # Don't disconnect here, keep it in shared storage or we'll have to reconnect with same session
        if user_id not in users_data:
            users_data[user_id] = {}
        users_data[user_id][f"temp_client_{session_name}"] = client
        
        await message.answer(
            f"📩 **Tasdiqlash kodi yuborildi.**\n\n"
            f"Raqam: `{phone}`\n"
            f"Kodni vergul bilan ajratib yuboring (Masalan: `1,2,3,4,5`):", 
            parse_mode="Markdown"
        )
        await state.set_state(AuthState.add_profile_code)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        try: await client.disconnect()
        except: pass
        await state.clear()

@dp.message(AuthState.add_profile_code)
async def process_add_profile_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    phone = data.get('profile_phone')
    session_name = data.get('profile_session_name')
    phone_code_hash = data.get('profile_phone_code_hash')
    saved_2fa = data.get('profile_saved_2fa') # If already requested
    
    user_id = message.from_user.id
    temp_key = f"temp_client_{session_name}"
    
    # Get existing client or reconnect
    if user_id in users_data and temp_key in users_data[user_id]:
        client = users_data[user_id][temp_key]
    else:
        session_path = f"sessions/{session_name}"
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if user_id not in users_data: users_data[user_id] = {}
        users_data[user_id][temp_key] = client

    async def finish_auth():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO profiles (user_id, phone, session_name, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, phone, session_name, datetime.now().isoformat()))
            await db.commit()
        await message.answer(f"✅ **Profil qo'shildi:** `{phone}`", parse_mode="Markdown")
        try: await client.disconnect()
        except: pass
        if temp_key in users_data.get(user_id, {}):
            del users_data[user_id][temp_key]
        await state.clear()

    if saved_2fa:
        try:
            await client.sign_in(password=message.text.strip())
            await finish_auth()
        except Exception as e:
            await message.answer(f"❌ Xato (2FA): {e}")
        return

    # Process code
    code = "".join(message.text.replace(" ", "").split(","))
    if not code.isdigit():
        await message.answer("❌ Noto'g'ri format! Kodni kiriting (Masalan: `1,2,3,4,5` yoki `12345`):")
        return

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        await finish_auth()
    except SessionPasswordNeededError:
        await state.update_data(profile_saved_2fa=True)
        await message.answer("🔑 **2FA Parol talab qilinadi.**\nParolni yuboring:")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        # Only clear if it's a fatal error, otherwise let them try again
        if "expired" in str(e).lower() or "invalid" in str(e).lower():
            try: await client.disconnect()
            except: pass
            if temp_key in users_data.get(user_id, {}):
                del users_data[user_id][temp_key]
            await state.clear()

# --- Guruhlar Tizimi ---
@dp.callback_query(F.data == "main_groups")
async def show_groups(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Obuna tekshirish (admin'lar uchun o'tkazib yuborish)
    is_admin_user = await is_admin(user_id)
    if not is_admin_user and not await check_subscription(user_id):
        await callback.answer("❌ Bu xizmat faqat obuna bo'lgan foydalanuvchilar uchun!", show_alert=True)
        return await send_sub_msg(callback.message)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, folder_name, group_ids FROM groups WHERE user_id = ?", (user_id,)) as cursor:
            groups = await cursor.fetchall()
    
    text = "📋 **Guruh Folderlar**\n\n"
    
    if not groups:
        text += "Hozircha folder yo'q.\n\n"
    else:
        for idx, (gid, folder_name, group_ids) in enumerate(groups, 1):
            count = len(group_ids.split(",")) if group_ids else 0
            text += f"{idx}. 📁 {folder_name} ({count} guruh)\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Yangi folder ochish", callback_data="create_group_folder")],
        [InlineKeyboardButton(text="📥 Mavjud folderni qo'shish", callback_data="import_group_folder")],
        [InlineKeyboardButton(text="🗑 Folder o'chirish", callback_data="delete_group")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_profile")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "delete_group")
async def delete_group_prompt(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, folder_name FROM groups WHERE user_id = ?", (user_id,)) as cursor:
            groups = await cursor.fetchall()
    
    if not groups:
        await callback.answer("❌ O'chirish uchun folder yo'q!", show_alert=True)
        return

    kb = []
    for gid, folder_name in groups:
        kb.append([InlineKeyboardButton(text=f"🗑 {folder_name}", callback_data=f"del_g_{gid}")])
    kb.append([InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="main_groups")])
    
    await callback.message.edit_text("🗑 **O'chirish uchun folderni tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("del_g_"))
async def process_delete_group(callback: types.CallbackQuery):
    group_id = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        await db.commit()
    await callback.answer("✅ Folder o'chirildi!")
    await show_groups(callback)

@dp.callback_query(F.data == "create_group_folder")
async def create_group_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🆕 **Yangi folder yaratish**\n\nYaratmoqchi bo'lgan papka nomini kiriting (Bu papka Telegramingizda ham hosil bo'ladi):")
    await state.set_state(AuthState.create_group_folder_name)
    await callback.answer()

@dp.message(AuthState.create_group_folder_name)
async def process_create_folder_name(message: types.Message, state: FSMContext):
    folder_name = message.text.strip()
    user_id = message.from_user.id
    client = await get_user_client(user_id)
    if not client:
        await message.answer("❌ Akkountga ulanmagan! Avval profil ulanishi kerak.")
        await state.clear()
        return

    await message.answer("🔄 Telegramda papka yaratilmoqda...")
    try:
        from telethon.tl.functions.messages import GetDialogFiltersRequest, UpdateDialogFilterRequest
        from telethon.tl.types import DialogFilter
        
        # Get existing filters to find a free ID
        filters = await client(GetDialogFiltersRequest())
        existing_ids = [f.id for f in filters if hasattr(f, 'id')]
        new_id = 2 
        while new_id in existing_ids:
            new_id += 1
            
        # Create a basic folder in Telegram
        # Added contacts=True to make it valid
        await client(UpdateDialogFilterRequest(
            id=new_id,
            filter=DialogFilter(
                id=new_id,
                title=folder_name,
                contacts=True,
                non_contacts=False,
                groups=False,
                broadcasts=False,
                bots=False,
                exclude_muted=False,
                exclude_read=False,
                exclude_archived=False,
                include_peers=[],
                exclude_peers=[]
            )
        ))
        
        # Add to database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO groups (user_id, folder_name, group_ids, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, folder_name, "", datetime.now().isoformat()))
            await db.commit()
            
        await message.answer(
            f"✅ Telegramda **{folder_name}** nomli yangi papka yaratildi va botga qo'shildi!\n\n"
            f"📱 Endi Telegram ilovangizda ushbu papkaga chatlarni qo'shishingiz mumkin, bot ulardan foydalanadi.",
            parse_mode="Markdown",
            reply_markup=await get_main_keyboard(user_id, is_connected=True)
        )
        await state.clear()
    except Exception as e:
        logging.error(f"Error creating folder: {e}")
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        await state.clear()

@dp.callback_query(F.data == "import_group_folder")
async def import_group_folder(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    if not client:
        await callback.answer("❌ Akkountga ulanmagan!", show_alert=True)
        return
    
    try:
        from telethon.tl.functions.messages import GetDialogFiltersRequest
        filters = await client(GetDialogFiltersRequest())
        kb = []
        for f in filters:
            if hasattr(f, 'title') and f.title:
                kb.append([InlineKeyboardButton(text=f"📁 {f.title}", callback_data=f"import_folder_select_{f.id}")])
        
        if not kb:
            await callback.answer("❌ Telegramda birorta ham papka topilmadi!", show_alert=True)
            return

        kb.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_groups")])
        await callback.message.edit_text("📥 **Telegramdagi papkalaringiz:**\n\nBotga qo'shish uchun papkani tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error listing folders: {e}")
        await callback.answer(f"❌ Xatolik: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("import_folder_select_"))
async def process_import_folder_select(callback: types.CallbackQuery):
    try:
        folder_id = int(callback.data.split("_")[-1])
        user_id = callback.from_user.id
        client = await get_user_client(user_id)
        if not client:
            await callback.answer("❌ Akkountga ulanmagan!", show_alert=True)
            return

        from telethon.tl.functions.messages import GetDialogFiltersRequest
        filters = await client(GetDialogFiltersRequest())
        target_filter = None
        for f in filters:
            if hasattr(f, 'id') and f.id == folder_id:
                target_filter = f
                break
        
        if not target_filter:
            await callback.answer("❌ Papka topilmadi!", show_alert=True)
            return
        
        folder_name = target_filter.title
        await callback.message.edit_text(f"🔄 **{folder_name}** papkasidagi chatlar yig'ilmoqda...")
        
        found_groups = []
        async for dialog in client.iter_dialogs(folder=folder_id):
            found_groups.append(str(dialog.id))
        
        group_ids = ",".join(found_groups)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO groups (user_id, folder_name, group_ids, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, folder_name) DO UPDATE SET group_ids = excluded.group_ids
            """, (user_id, folder_name, group_ids, datetime.now().isoformat()))
            await db.commit()
        
        await callback.message.edit_text(
            f"✅ Folder muvaffaqiyatli qo'shildi: **{folder_name}**\n\n"
            f"🔄 Telegramdan **{len(found_groups)}** ta chat aniqlandi va botga biriktirildi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_groups")]])
        )
    except Exception as e:
        logging.error(f"Error importing folder: {e}")
        await callback.answer(f"❌ Xatolik: {e}", show_alert=True)

@dp.callback_query(F.data == "add_group")
async def add_group_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📁 **Yangi folder qo'shish**\n\nTelegramdagi papkangiz (folder) nomini kiriting:")
    await state.set_state(AuthState.add_group_name)
    await callback.answer()

@dp.message(AuthState.add_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    folder_name = message.text.strip()
    
    # Telegram folders check
    client = await get_user_client(user_id)
    found_groups = []
    available_folders = []
    if client:
        try:
            from telethon.tl.functions.messages import GetDialogFiltersRequest
            filters = await client(GetDialogFiltersRequest())
            for f in filters:
                if hasattr(f, 'title'):
                    available_folders.append(f.title)
                    if f.title.lower() == folder_name.lower():
                        # Barcha dialog turlarini qo'shish (chat, group, channel, bot, user)
                        async for dialog in client.iter_dialogs(folder=f.id):
                            found_groups.append(str(dialog.id))
                        break
        except Exception as e:
            logging.error(f"Sync error: {e}")

    group_ids = ",".join(found_groups)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO groups (user_id, folder_name, group_ids, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, folder_name, group_ids, datetime.now().isoformat()))
        await db.commit()
    
    if found_groups:
        await message.answer(
            f"✅ Folder qo'shildi: **{folder_name}**\n\n"
            f"🔄 Telegramdan **{len(found_groups)}** ta chat/guruh/kanal aniqlandi va avtomatik qo'shildi.",
            parse_mode="Markdown"
        )
        await state.clear()
    else:
        folders_list = ", ".join([f"`{f}`" for f in available_folders]) if available_folders else "Papkalar topilmadi"
        await message.answer(
            f"✅ Folder yaratildi: **{folder_name}**\n\n"
            f"⚠️ Telegramdan bunday papka topilmadi.\n"
            f"🔍 **Mavjud papkalaringiz:** {folders_list}\n\n"
            f"Endi shu folderga tegishli chat/guruh/kanal IDlarini yuboring (har birini yangi qatordan) yoki hamma chatlarni qo'shish uchun `/all` deb yozing:",
            parse_mode="Markdown"
        )
        await state.update_data(current_folder_name=folder_name)
        await state.set_state(AuthState.add_group_ids)

@dp.message(AuthState.add_group_ids)
async def process_group_ids(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    folder_name = data.get('current_folder_name')
    
    ids = []
    if message.text == "/all":
        client = await get_user_client(user_id)
        if client:
            await message.answer("🔄 Barcha chat/guruh/kanallar yig'ilmoqda, kuting...")
            # Barcha dialog turlarini qo'shish
            async for dialog in client.iter_dialogs():
                ids.append(str(dialog.id))
    else:
        ids = [i.strip() for i in message.text.split("\n") if i.strip()]

    group_ids = ",".join(ids)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE groups SET group_ids = ? WHERE user_id = ? AND folder_name = ?", (group_ids, user_id, folder_name))
        await db.commit()
    
    await message.answer(f"✅ {len(ids)} ta chat/guruh/kanal saqlandi!", reply_markup=await get_main_keyboard(user_id, is_connected=True))
    await state.clear()

# --- Reklama Matni va Rasm ---
@dp.callback_query(F.data == "main_xabar")
async def set_ad_text(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 **Reklama xabaringizni yuboring.**\n\n✅ Quyidagilarni yuborishingiz mumkin:\n• Faqat matn\n• Rasm + matn\n• Video + matn\n• Ovozli xabar + matn\n\nBot aynan shu ko'rinishda tarqatadi.")
    await state.set_state(AuthState.ad_text)
    await callback.answer()

@dp.message(AuthState.ad_text)
async def save_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {'is_running': False, 'interval': DEFAULT_AD_DELAY}
    
    ad_text = message.caption or message.text or ""
    image_path = None
    video_path = None
    voice_path = None
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        image_path = f"payments/ad_{user_id}_img.jpg" # payments folderini rasm saqlash uchun Ham ishlatamiz
        await bot.download_file(file.file_path, image_path)
    elif message.video:
        file_id = message.video.file_id
        file = await bot.get_file(file_id)
        video_path = f"payments/ad_{user_id}_vid.mp4"
        await bot.download_file(file.file_path, video_path)
    elif message.voice:
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        voice_path = f"payments/ad_{user_id}_voice.ogg"
        await bot.download_file(file.file_path, voice_path)

    users_data[user_id]['ad_text'] = ad_text
    users_data[user_id]['image_path'] = image_path
    users_data[user_id]['video_path'] = video_path
    users_data[user_id]['voice_path'] = voice_path
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_settings (user_id, ad_text, interval, image_path, video_path, voice_path)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                ad_text = excluded.ad_text,
                image_path = excluded.image_path,
                video_path = excluded.video_path,
                voice_path = excluded.voice_path
        """, (user_id, ad_text, users_data[user_id].get('interval', DEFAULT_AD_DELAY), image_path, video_path, voice_path))
        await db.commit()
    
    await message.answer("✅ Reklama xabari saqlandi!", reply_markup=await get_main_keyboard(user_id, is_connected=True))
    await state.clear()

# --- Interval Sozlash ---
@dp.callback_query(F.data == "main_interval")
async def set_interval(callback: types.CallbackQuery):
    await callback.message.answer("⏱ **Xabar yuborish oralig'ini tanlang:**", reply_markup=get_interval_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("setint_"))
async def process_interval(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    val = callback.data.split("_")[1]
    
    if val == "custom":
        await callback.message.answer("⏱ O'zingiz xohlagan vaqtni **soniyalarda** kiriting (minimal 60 sekund):")
        await state.set_state(AuthState.ad_interval)
    else:
        seconds = int(val)
        if user_id not in users_data:
            users_data[user_id] = {'is_running': False, 'ad_text': ''}
        users_data[user_id]['interval'] = seconds
        
        display_time = ""
        if seconds < 3600:
            display_time = f"{seconds // 60} minut"
        else:
            display_time = f"{seconds // 3600} soat"
        
        await callback.message.answer(f"✅ Vaqt oralig'i **{display_time}** qilib belgilandi!", reply_markup=await get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
    
    await callback.answer()

@dp.message(AuthState.ad_interval)
async def process_custom_interval(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        seconds = int(message.text.strip())
        if seconds < 60:
            await message.answer("❌ Minimal 60 sekund bo'lishi kerak!")
            return
        if user_id not in users_data:
            users_data[user_id] = {'is_running': False, 'ad_text': ''}
        users_data[user_id]['interval'] = seconds
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO user_settings (user_id, interval, ad_text)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET interval = excluded.interval
            """, (user_id, seconds, users_data[user_id].get('ad_text', '')))
            await db.commit()
        
        await message.answer(f"✅ Interval **{seconds} sekund** qilib belgilandi!", reply_markup=await get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")

# --- Sender Ishga Tushirish ---
@dp.callback_query(F.data == "main_start_sender")
async def start_sender_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in users_data or not users_data[user_id].get('ad_text'):
        await callback.answer("❌ Avval reklama xabarini sozlang!", show_alert=True)
        return
    
    if users_data[user_id].get('is_running'):
        await callback.answer("⚠️ Sender allaqachon ishlamoqda.", show_alert=True)
        return
    
    users_data[user_id]['is_running'] = True
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_settings SET is_running = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    asyncio.create_task(start_sender(user_id))
    await callback.message.answer("🚀 Reklama tarqatish boshlandi!")
    await callback.answer()


async def start_sender(user_id):
    """Reklama yuborish tsikli"""
    logging.info(f"Starting sender for user {user_id}")
    try:
        data = users_data[user_id]
    except KeyError:
        logging.error(f"User data not found for {user_id}")
        return
    
    # Barcha faol klientlarni yig'ish
    clients = []
    
    # 1. Asosiy klient
    c_main = await get_user_client(user_id)
    if c_main:
        clients.append(c_main)
            
    # 2. Qo'shimcha profillar
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT session_name FROM profiles WHERE user_id = ? AND is_active = 1", (user_id,)) as cursor:
            profiles_db = await cursor.fetchall()
            
    for (session_name,) in profiles_db:
        c_prof = await get_user_client(user_id, session_name=session_name)
        if c_prof:
            clients.append(c_prof)
                
    if not clients:
        data['is_running'] = False
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE user_settings SET is_running = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
        await bot.send_message(user_id, "❌ Hech qanday faol Telegram akkaunt topilmadi! Iltimos, akkauntingizni qaytadan ulang.")
        return

    # Guruhlarni bazadan olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT folder_name, group_ids FROM groups WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            user_folders = [r[0].lower() for r in rows]
            manual_group_ids = {}
            for row in rows:
                if row[1]:
                    manual_group_ids[row[0].lower()] = [int(gid) for gid in row[1].split(",") if gid]

    await bot.send_message(user_id, f"🔍 Guruhlar tahlil qilinmoqda ({len(clients)} akkaunt)...")

    while data.get('is_running'):
        if not await check_subscription(user_id):
            data['is_running'] = False
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE user_settings SET is_running = 0 WHERE user_id = ?", (user_id,))
                await db.commit()
            await bot.send_message(user_id, "❌ Obunangiz tugadi! Xizmat to'xtatildi.")
            break
            
        try:
            total_sent = 0
            for client in clients:
                if not data.get('is_running'): break
                
                # Jo'natilishi kerak bo'lgan IDlar
                final_target_ids = set()

                if user_folders:
                    # 1. Manual saqlangan IDlarni qo'shish
                    for folder, ids in manual_group_ids.items():
                        final_target_ids.update(ids)

                    # 2. Telegram papkalarini tekshirish
                    try:
                        from telethon.tl.functions.messages import GetDialogFiltersRequest
                        filters = await client(GetDialogFiltersRequest())
                        for f in filters:
                            if hasattr(f, 'title') and f.title.lower() in user_folders:
                                # Barcha dialog turlarini qo'shish (chat, group, channel, bot, user)
                                async for dialog in client.iter_dialogs(folder=f.id):
                                    final_target_ids.add(dialog.id)
                    except Exception as e:
                        logging.error(f"Error getting DialogFilters: {e}")

                if final_target_ids:
                    for target_id in final_target_ids:
                        if not data.get('is_running'): break
                        try:
                            # Media yuborishni tekshirish
                            media_file = None
                            if data.get('image_path') and os.path.exists(data['image_path']):
                                media_file = data['image_path']
                            elif data.get('video_path') and os.path.exists(data['video_path']):
                                media_file = data['video_path']
                            elif data.get('voice_path') and os.path.exists(data['voice_path']):
                                media_file = data['voice_path']

                            if media_file:
                                await client.send_file(target_id, media_file, caption=data.get('ad_text', ''))
                            else:
                                await client.send_message(target_id, data.get('ad_text', ''))
                            
                            total_sent += 1
                            await asyncio.sleep(15)
                        except Exception as e:
                            logging.warning(f"Failed to send to {target_id}: {e}")
                else:
                    # Agar folderlar aniqlanmagan bo'lsa, barcha guruhlarga yuboradi
                    async for dialog in client.iter_dialogs():
                        if not data.get('is_running'): break
                        if dialog.is_group or dialog.is_channel:
                            try:
                                # Media yuborishni tekshirish
                                media_file = None
                                if data.get('image_path') and os.path.exists(data['image_path']):
                                    media_file = data['image_path']
                                elif data.get('video_path') and os.path.exists(data['video_path']):
                                    media_file = data['video_path']
                                elif data.get('voice_path') and os.path.exists(data['voice_path']):
                                    media_file = data['voice_path']

                                if media_file:
                                    await client.send_file(dialog.id, media_file, caption=data.get('ad_text', ''))
                                else:
                                    await client.send_message(dialog.id, data.get('ad_text', ''))
                                
                                total_sent += 1
                                await asyncio.sleep(15)
                            except Exception as e:
                                logging.warning(f"Failed to send to {dialog.id}: {e}")
            
            if total_sent == 0:
                await bot.send_message(user_id, "⚠️ Hech qanday guruh topilmadi. Folderlaringizni tekshiring.")
                data['is_running'] = False
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE user_settings SET is_running = 0 WHERE user_id = ?", (user_id,))
                    await db.commit()
                break

            if total_sent > 0:
                await bot.send_message(user_id, f"✅ Reklama tarqatish tsikli tugadi. **{total_sent}** ta guruhga yuborildi.\n⏱ Navbatdagi tsikl {data['interval']} soniyadan keyin boshlanadi.", parse_mode="Markdown")

            logging.info(f"Cycle finished for {user_id}. Sent: {total_sent}. Waiting {data['interval']} seconds.")
            for _ in range(data['interval']):
                if not data.get('is_running'): break
                await asyncio.sleep(1)
                
        except Exception as e:
            logging.error(f"Error in start_sender loop: {e}")
            await asyncio.sleep(60)

# --- Profil va Sozlamalar ---
@dp.callback_query(F.data == "main_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    me = None
    if client:
        try:
            me = await client.get_me()
        except Exception as e:
            logging.error(f"Error getting user info: {e}")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    
    expiry = row[0] if row else "Obuna yo'q"
    
    # Ism va username - Telethon, users jadvali yoki callback dan
    display_name = "Noma'lum"
    display_username = "yo'q"
    
    if me:
        display_name = me.first_name or "Noma'lum"
        display_username = f"@{me.username}" if me.username else "yo'q"
    else:
        # Avval users jadvalidan tekshirish
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (user_id,)) as cur:
                urow = await cur.fetchone()
        
        if urow and urow[0]:
            display_name = urow[0]
            display_username = f"@{urow[1]}" if urow[1] else "yo'q"
        else:
            # Agar bazada yo'q bo'lsa, callback dan olish
            display_name = callback.from_user.full_name or "Noma'lum"
            display_username = f"@{callback.from_user.username}" if callback.from_user.username else "yo'q"
    
    text = (
        f"👤 **Foydalanuvchi ma'lumotlari**\n\n"
        f"🔹 Ism: **{display_name}**\n"
        f"🔹 Username: {display_username}\n"
        f"🔹 Telegram ID: `{user_id}`\n"
        f"🔹 Obuna: **{expiry}**"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="main_settings")],
        [InlineKeyboardButton(text="🔄 Akkauntni o'zgartirish", callback_data="main_relogin")],
        [InlineKeyboardButton(text="🚪 Chiqish", callback_data="main_logout")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "main_settings")
async def show_settings(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱ Intervalni o'zgartirish", callback_data="main_interval")],
        [InlineKeyboardButton(text="🛑 Senderni to'xtatish", callback_data="main_stop_sender")],
        [InlineKeyboardButton(text="💎 Obuna uzaytirish", callback_data="user_extend_sub")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_profile")]
    ])
    await callback.message.answer("⚙️ **Sozlamalar**", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "user_extend_sub")
async def user_extend_sub(callback: types.CallbackQuery, state: FSMContext):
    """Foydalanuvchi o'z obunasini uzaytirish uchun"""
    user_id = callback.from_user.id
    await state.update_data(extend_user_id=user_id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type, duration_days, price FROM pricing ORDER BY duration_days") as cursor:
            prices = await cursor.fetchall()
    plan_btn = {"start": "extend_buy_start", "3month": "extend_buy_3month", "pro": "extend_buy_pro", "year": "extend_buy_year", "vip": "extend_buy_vip"}
    plan_names = {"start": "Start — 1 oy", "3month": "Pro — 3 oy", "pro": "Pro — 6 oy", "year": "VIP — 1 yil", "vip": "VIP — Umrbod"}
    kb = []
    for plan, days, price in prices:
        if plan in plan_btn:
            kb.append([InlineKeyboardButton(text=f"🔹 {plan_names[plan]} ({price:,} so'm)", callback_data=plan_btn[plan])])
    kb.append([InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="main_settings")])
    
    await callback.message.answer("💎 **Obuna uzaytirish uchun reja tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("extend_buy_"))
async def extend_buy_subscription(callback: types.CallbackQuery, state: FSMContext):
    """Foydalanuvchi obunasini uzaytirish uchun to'lov"""
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    
    if not client:
        await callback.answer("❌ Avval akkauntingizni ulashingiz kerak!", show_alert=True)
        return

    plan_key = callback.data.split("_")[2]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT duration_days, price FROM pricing WHERE plan_type = ?", (plan_key,)) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        await callback.answer("❌ Reja topilmadi!", show_alert=True)
        return
    
    days, amount = row
    plan_names = {
        "start": "Start (1 oy)",
        "3month": "Pro (3 oy)",
        "pro": "Pro (6 oy)",
        "year": "VIP (1 yil)",
        "vip": "VIP (Umrbod)"
    }
    plan_name = plan_names.get(plan_key, "Noma'lum")
    
    await state.update_data(plan_type=plan_key, plan_name=plan_name, days=days, amount=amount)
    logging.info(f"State updated for user {user_id}: plan_type={plan_key}, plan_name={plan_name}, amount={amount}")
    
    # Mudat tanlash uchun tugmalar
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 kun", callback_data="user_extend_days_30")],
        [InlineKeyboardButton(text="90 kun", callback_data="user_extend_days_90")],
        [InlineKeyboardButton(text="180 kun", callback_data="user_extend_days_180")],
        [InlineKeyboardButton(text="365 kun", callback_data="user_extend_days_365")],
        [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="user_extend_sub")]
    ])
    
    text = (
        f"💎 **{plan_name}** rejasi tanlandi\n\n"
        f"💰 Summa: **{amount:,} so'm**\n\n"
        f"⏱ **Muddatni tanlang:**"
    )
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "main_stop_sender")
async def stop_sender_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users_data:
        users_data[user_id]['is_running'] = False
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE user_settings SET is_running = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
        await callback.message.answer("✅ Sender to'xtatildi!")
    await callback.answer()

@dp.callback_query(F.data == "main_logout")
async def logout(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    if client:
        await client.disconnect()
    
    for ext in [".session", ".session-journal"]:
        path = f"sessions/sess_{user_id}{ext}"
        if os.path.exists(path):
            os.remove(path)
    
    if user_id in users_data:
        del users_data[user_id]
    
    await callback.message.answer("✅ Chiqildi!", reply_markup=await get_main_keyboard(user_id, is_connected=False))
    await callback.answer()

@dp.callback_query(F.data == "main_relogin")
async def relogin(callback: types.CallbackQuery, state: FSMContext):
    await prompt_phone(callback.message, state)
    await callback.answer()

# --- Admin Panel ---
async def show_admin_panel(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Foydalanuvchilar")],
        [KeyboardButton(text="🔍 Qidirish"), KeyboardButton(text="⏰ Obuna uzaytirish")],
        [KeyboardButton(text="💳 To'lov ma'lumotlari"), KeyboardButton(text="💰 Narxlarni sozlash")],
        [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="👨‍💼 Admin qo'shish")],
        [KeyboardButton(text="👥 Admin ro'yxati"), KeyboardButton(text="📱 Akkauntga ulanish")],
        [KeyboardButton(text="🏠 Asosiy menu")]
    ], resize_keyboard=True)
    await message.answer("👑 **Admin Boshqaruv Paneli**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "main_admin")
async def admin_panel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Admin tekshirish
    is_admin_user = await is_admin(user_id)
    
    if not is_admin_user:
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    await show_admin_panel(callback.message)
    await callback.answer()

# --- Admin Menu Message Handlers ---
@dp.message(F.text == "📊 Statistika")
async def admin_stats_msg(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM subscriptions") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM user_settings WHERE is_running = 1") as cursor:
            active_bots = (await cursor.fetchone())[0]
    
    text = (
        f"📈 **Tizim Statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: `{total_users}`\n"
        f"⚡️ Faol senderlar: `{active_bots}`\n"
        f"📅 Bugungi sana: `{datetime.now().strftime('%Y-%m-%d')}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "👥 Foydalanuvchilar")
async def admin_users_list_msg(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, expiry_date FROM subscriptions") as cursor:
            subs = await cursor.fetchall()
    
    text = "👥 **Foydalanuvchilar:**\n\n"
    if not subs:
        text += "Hozircha foydalanuvchilar yo'q."
    else:
        for uid, expiry in subs[:30]:
            status = "🟢" if datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S") > datetime.now() else "🔴"
            text += f"{status} `{uid}` | {expiry.split()[0]}\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🔍 Qidirish")
async def admin_search_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    await message.answer("🔍 Foydalanuvchi ID'sini kiriting:")
    await state.set_state(AuthState.admin_search_user)

@dp.message(F.text == "⏰ Obuna uzaytirish")
async def admin_extend_btn_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    await message.answer("⏰ Obunasini uzaytirmoqchi bo'lgan foydalanuvchi ID'sini kiriting:")
    await state.set_state(AuthState.admin_search_user)

@dp.message(F.text == "💳 To'lov ma'lumotlari")
async def admin_payment_info_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_number, card_holder, amount FROM payment_info ORDER BY created_at DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
    
    if row:
        card_number, card_holder, amount = row
        text = (
            f"💳 **To'lov Ma'lumotlari**\n\n"
            f"💳 Karta raqami: `{card_number}`\n"
            f"👤 Karta egasi: `{card_holder}`\n"
            f"💰 Summa: `{amount:,} so'm`"
        )
    else:
        text = "💳 **To'lov Ma'lumotlari**\n\n⚠️ Hali kiritilmagan"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="edit_payment_info")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.message(F.text == "💰 Narxlarni sozlash")
async def admin_pricing_msg(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type, duration_days, price FROM pricing ORDER BY duration_days") as cursor:
            prices = await cursor.fetchall()
    
    text = "💰 **Obuna Narxlari**\n\n"
    for plan, days, price in prices:
        dur = "Umrbod" if days == 9999 else f"{days} kun"
        text += f"🔹 {plan.upper()}: {price:,} so'm ({dur})\n"
    text += "\n✏️ Narxni o'zgartirish uchun tugmani bosing:"
    
    kb = []
    for plan, days, price in prices:
        kb.append([InlineKeyboardButton(text=f"✏️ {plan.upper()}", callback_data=f"edit_price_{plan}")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.message(F.text == "📢 Xabar yuborish")
async def admin_broadcast_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    await message.answer("📢 Barcha foydalanuvchilarga yuborish uchun xabar yuboring:")
    await state.set_state(AuthState.admin_broadcast_message)

@dp.message(F.text == "👨‍💼 Admin qo'shish")
async def add_admin_prompt_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    logging.info(f"Admin add prompt triggered by {message.from_user.id}")
    await message.answer("👨‍💼 **Yangi admin qo'shish**\n\nAdmin ID raqamini kiriting:")
    await state.set_state(AuthState.add_admin_id)

@dp.message(AuthState.add_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logging.info(f"Admin add message received from {user_id}: {message.text}")
    
    if not await is_admin(user_id):
        await message.answer("❌ Siz admin emassiz!")
        await state.clear()
        return
    
    try:
        new_admin_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")
        return
    
    # Tekshirish - allaqachon admin bo'lsa
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (new_admin_id,)) as cursor:
            existing = await cursor.fetchone()
        
        if existing:
            await message.answer(f"❌ Foydalanuvchi `{new_admin_id}` allaqachon admin!", parse_mode="Markdown")
            await state.clear()
            return
        
        # Yangi admin qo'shish
        try:
            await db.execute("""
                INSERT INTO admins (admin_id, added_by, created_at)
                VALUES (?, ?, ?)
            """, (new_admin_id, message.from_user.id, datetime.now().isoformat()))
            await db.commit()
            logging.info(f"New admin added: {new_admin_id} by {message.from_user.id}")
        except Exception as e:
            logging.error(f"Error adding admin: {e}")
            await message.answer(f"❌ Xatolik: {e}")
            await state.clear()
            return
    
    await message.answer(f"✅ Foydalanuvchi `{new_admin_id}` admin qilib belgilandi!", parse_mode="Markdown")
    
    # Yangi admin'ga xabar
    try:
        await bot.send_message(new_admin_id, "🎉 **Siz admin qilib belgilandi!**\n\nAdmin panel uchun `/start` yuboring.", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Failed to send message to new admin {new_admin_id}: {e}")
    
    await state.clear()
    
    # Admin panel'ni qaytarish
    await show_admin_panel(message)

@dp.message(F.text == "👥 Admin ro'yxati")
async def list_admins_msg(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id, created_at FROM admins ORDER BY created_at DESC") as cursor:
            admins = await cursor.fetchall()
    
    text = "👥 **Admin Ro'yxati**\n\n"
    text += f"👑 Asosiy Admin: `{ADMIN_ID}`\n\n"
    
    if admins:
        text += "**Qo'shimcha Adminlar:**\n"
        kb = []
        for admin_id, created_at in admins:
            if created_at:
                date = created_at.split("T")[0] if isinstance(created_at, str) else str(created_at).split("T")[0]
                text += f"🔹 `{admin_id}` (Qo'shilgan: {date})\n"
            else:
                text += f"🔹 `{admin_id}` (Sana noma'lum)\n"
            kb.append([InlineKeyboardButton(text=f"🗑 O'chirish {admin_id}", callback_data=f"remove_admin_{admin_id}")])
        kb.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")])
    else:
        text += "Qo'shimcha adminlar yo'q"
        kb = [[InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")]]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.message(F.text == "📱 Akkauntga ulanish")
async def admin_connect_account_msg(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    await prompt_phone(message, state)

@dp.message(F.text == "🏠 Asosiy menu")
async def admin_back_to_main(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz!")
        return
    
    client = await get_user_client(message.from_user.id)
    is_connected = client is not None
    await message.answer("🏠 **Asosiy boshqaruv paneli:**", reply_markup=await get_main_keyboard(message.from_user.id, is_connected=is_connected), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM subscriptions") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM user_settings WHERE is_running = 1") as cursor:
            active_bots = (await cursor.fetchone())[0]
    
    text = (
        f"📈 **Tizim Statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: `{total_users}`\n"
        f"⚡️ Faol senderlar: `{active_bots}`\n"
        f"📅 Bugungi sana: `{datetime.now().strftime('%Y-%m-%d')}`"
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.message(AuthState.admin_search_user)
async def process_admin_search(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        search_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ?", (search_id,)) as cursor:
            row = await cursor.fetchone()
    
    if row:
        expiry = row[0]
        is_active = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S") > datetime.now()
        status = "🟢 Faol" if is_active else "🔴 Tugagan"
    else:
        expiry = "Obuna yo'q"
        status = "❌ Obuna yo'q"
    
    text = f"👤 **Foydalanuvchi: `{search_id}`**\n\nStatus: {status}\nTugash: `{expiry}`"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Uzaytirish", callback_data=f"admin_extend_user_{search_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"admin_remove_sub_{search_id}")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data.startswith("admin_extend_user_"))
async def admin_extend_user(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    await state.update_data(extend_user_id=user_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 kun", callback_data="extend_days_30")],
        [InlineKeyboardButton(text="90 kun", callback_data="extend_days_90")],
        [InlineKeyboardButton(text="180 kun", callback_data="extend_days_180")],
        [InlineKeyboardButton(text="365 kun", callback_data="extend_days_365")]
    ])
    
    await callback.message.answer(f"⏰ Muddatni tanlang:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("extend_days_"))
async def extend_days(callback: types.CallbackQuery, state: FSMContext):
    """Admin panel'dan obuna uzaytirish uchun"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    data = await state.get_data()
    user_id = data.get('extend_user_id')
    days = int(callback.data.split("_")[-1])
    
    await add_subscription(user_id, days)
    await callback.message.answer(f"✅ Foydalanuvchi `{user_id}` ga {days} kun berildi!", parse_mode="Markdown")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data.startswith("user_extend_days_"))
async def user_extend_days(callback: types.CallbackQuery, state: FSMContext):
    """Foydalanuvchi o'z obunasini uzaytirish uchun"""
    user_id = callback.from_user.id
    days = int(callback.data.split("_")[-1])
    
    logging.info(f"user_extend_days called for user {user_id} with days={days}")
    
    data = await state.get_data()
    plan_type = data.get('plan_type')
    plan_name = data.get('plan_name')
    amount = data.get('amount')
    
    logging.info(f"State data: plan_type={plan_type}, plan_name={plan_name}, amount={amount}")
    
    # Agar state'da ma'lumot bo'lmasa, xatolik
    if not plan_type or not plan_name or not amount:
        logging.error(f"State data missing for user {user_id}: plan_type={plan_type}, plan_name={plan_name}, amount={amount}")
        await callback.answer("❌ Xatolik! Qayta urinib ko'ring.", show_alert=True)
        await callback.message.answer("💎 **Obuna uzaytirish uchun reja tanlang:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔹 Start — 1 oy (50,000 so'm)", callback_data="extend_buy_start")],
            [InlineKeyboardButton(text="🔹 Pro — 3 oy (120,000 so'm)", callback_data="extend_buy_3month")],
            [InlineKeyboardButton(text="🔹 Pro — 6 oy (200,000 so'm)", callback_data="extend_buy_pro")],
            [InlineKeyboardButton(text="🔹 VIP — 1 yil (350,000 so'm)", callback_data="extend_buy_year")],
            [InlineKeyboardButton(text="🔹 VIP — Umrbod (500,000 so'm)", callback_data="extend_buy_vip")],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="main_settings")]
        ]), parse_mode="Markdown")
        return
    
    await state.update_data(plan_type=plan_type, plan_name=plan_name, days=days, amount=amount)
    
    # Admin panel'dan to'lov ma'lumotlarini olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_number, card_holder, amount FROM payment_info ORDER BY created_at DESC LIMIT 1") as cursor:
            payment_row = await cursor.fetchone()
    
    if payment_row:
        card_number, card_holder, payment_amount = payment_row
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi karta raqamiga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"💳 **Karta raqami:** `{card_number}`\n"
            f"👤 **Karta egasi:** `{card_holder}`"
        )
    else:
        text = (
            f"💳 **To'lov Tizimi**\n\n"
            f"📦 Tanlangan reja: **{plan_name}**\n"
            f"💰 Summa: **{amount:,} so'm**\n\n"
            f"📝 **To'lov qilish:**\n"
            f"1. Quyidagi raqamga pul o'tkazing\n"
            f"2. Chekni rasm sifatida yuboring\n"
            f"3. Admin tasdiqlashi kutib turing\n\n"
            f"⚠️ To'lov ma'lumotlari hali kiritilmagan. Admin bilan bog'laning."
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Chekni yuborish", callback_data=f"payment_screenshot_{plan_type}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_payment")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error editing message: {e}")
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_remove_sub_"))
async def admin_remove_sub(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        await db.commit()
    
    await callback.message.answer(f"✅ Obuna o'chirildi!", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await callback.message.answer("📢 Xabar matnini kiriting:")
    await state.set_state(AuthState.admin_broadcast_message)
    await callback.answer()

@dp.message(AuthState.admin_broadcast_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    success = 0
    for user_id in users_data.keys():
        try:
            await bot.send_message(user_id, message.text, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.1)
        except:
            pass
    
    await message.answer(f"✅ {success} ta foydalanuvchiga yuborildi!")
    await state.clear()

# --- Admin Narx Sozlash ---
@dp.callback_query(F.data == "admin_pricing")
async def admin_pricing(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type, duration_days, price FROM pricing ORDER BY duration_days") as cursor:
            prices = await cursor.fetchall()
    
    text = "💰 **Obuna Narxlari**\n\n"
    for plan, days, price in prices:
        if days == 9999:
            duration = "Umrbod"
        else:
            duration = f"{days} kun"
        text += f"🔹 {plan.upper()}: {price:,} so'm ({duration})\n"
    
    text += "\n✏️ Narxni o'zgartirish uchun tugmani bosing:"
    
    kb = []
    for plan, days, price in prices:
        kb.append([InlineKeyboardButton(text=f"✏️ {plan.upper()}", callback_data=f"edit_price_{plan}")])
    
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    
    plan = callback.data.split("_")[-1]
    await state.update_data(edit_plan=plan)
    
    await callback.message.answer(f"💰 **{plan.upper()} reja uchun yangi narxni kiriting** (so'm):")
    await state.set_state(AuthState.admin_extend_sub)
    await callback.answer()

@dp.message(AuthState.admin_extend_sub)
async def process_price_update(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        new_price = int(message.text.strip())
        data = await state.get_data()
        plan = data.get('edit_plan')
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE pricing SET price = ? WHERE plan_type = ?", (new_price, plan))
            await db.commit()
        
        await message.answer(f"✅ {plan.upper()} reja narxi **{new_price:,} so'm** qilib o'zgartirildi!", parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")

# --- Admin To'lov Ma'lumotlari ---
@dp.callback_query(F.data == "admin_payment_info")
async def admin_payment_info(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_number, card_holder, amount FROM payment_info ORDER BY created_at DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
    
    if row:
        card_number, card_holder, amount = row
        text = (
            f"💳 **To'lov Ma'lumotlari**\n\n"
            f"💳 Karta raqami: `{card_number}`\n"
            f"👤 Karta egasi: `{card_holder}`\n"
            f"💰 Summa: `{amount:,} so'm`"
        )
    else:
        text = "💳 **To'lov Ma'lumotlari**\n\nHali ma'lumot kiritilmagan."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="edit_payment_info")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "edit_payment_info")
async def edit_payment_info_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    await callback.message.answer(
        "💳 **To'lov ma'lumotlarini kiriting**\n\n"
        "Quyidagi formatda yuboring (har biri alohida qatorda):\n"
        "`9860 1234 5678 9012` — Karta raqami\n"
        "`Ism Familiya` — Karta egasi\n"
        "`50000` — Summa (so'm)\n\n"
        "Bekor qilish uchun /cancel yuboring.",
        parse_mode="Markdown"
    )
    await state.set_state(AuthState.edit_payment_info)
    await callback.answer()

@dp.message(AuthState.edit_payment_info)
async def process_payment_info(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    
    lines = message.text.strip().split('\n') if message.text else []
    if len(lines) < 3:
        await message.answer("❌ Noto'g'ri format! 3 ta qator kerak.")
        return
    
    try:
        card_number = lines[0].strip()
        card_holder = lines[1].strip()
        amount = int(lines[2].strip())
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM payment_info")
            await db.execute(
                "INSERT INTO payment_info (card_number, card_holder, amount, created_at) VALUES (?, ?, ?, ?)",
                (card_number, card_holder, amount, datetime.now().isoformat())
            )
            await db.commit()
        
        await message.answer(
            f"✅ To'lov ma'lumotlari saqlandi!\n\n"
            f"💳 Karta: `{card_number}`\n"
            f"👤 Egasi: `{card_holder}`\n"
            f"💰 Summa: `{amount:,} so'm`",
            parse_mode="Markdown"
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Summa noto'g'ri! Faqat raqam kiriting.")

async def resume_senders():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, interval, ad_text, image_path, video_path, voice_path FROM user_settings WHERE is_running = 1") as cursor:
            running_users = await cursor.fetchall()
    
    for user_id, interval, ad_text, img, vid, voice in running_users:
        users_data[user_id] = {
            'is_running': True,
            'interval': interval,
            'ad_text': ad_text,
            'image_path': img,
            'video_path': vid,
            'voice_path': voice
        }
        asyncio.create_task(start_sender(user_id))
        logging.info(f"Resumed sender for user {user_id}")

# --- Main ---
async def main():
    await init_db()
    print("Bot ishga tushdi...")
    asyncio.create_task(resume_senders())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

# --- Pro Status o'chirildi, xabar matni bo'limiga media qo'shish imkoniyati qo'shildi ---

@dp.callback_query(F.data == "buy_pro_menu")
async def buy_pro_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("💎 **Obuna bo'lish uchun reja tanlang:**", reply_markup=await get_subscription_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buy_pro")
async def buy_pro_handler(callback: types.CallbackQuery):
    """Settings'dan obuna uzaytirish uchun"""
    await callback.message.answer("💎 **Obuna bo'lish uchun reja tanlang:**", reply_markup=await get_subscription_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Amal bekor qilindi.", reply_markup=await get_main_keyboard(message.from_user.id, is_connected=True))

@dp.callback_query(F.data == "main_stats")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Faqat admin uchun
    if not await is_admin(user_id):
        await callback.answer("❌ Bu xizmat faqat admin uchun!", show_alert=True)
        return
    
    status_emoji = "🟢 Ishlamoqda" if users_data.get(user_id, {}).get('is_running') else "🔴 To'xtatilgan"
    interval = users_data.get(user_id, {}).get('interval', DEFAULT_AD_DELAY)
    ad_text = users_data.get(user_id, {}).get('ad_text', '')
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM subscriptions") as cursor:
            total_users_count = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (user_id,)) as cursor:
            profiles_count = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM groups WHERE user_id = ?", (user_id,)) as cursor:
            groups_count = (await cursor.fetchone())[0]

    text = (
        f"📊 **Bot Statistikasi**\n\n"
        f"👥 Botdagi jami foydalanuvchilar: `{total_users_count}`\n"
        f"🔹 Sizning holatingiz: **{status_emoji}**\n"
        f"⏱ Interval: `{interval} sekund`\n"
        f"📝 Reklama: {'✅ Sozlangan' if ad_text else '❌ Yo`q'}\n"
        f"📱 Ulangan akkauntlaringiz: `{profiles_count + 1} ta`\n"
        f"📁 Folderlaringiz: `{groups_count} ta`"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="main_stats")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


# --- Admin Qo'shish ---
# (Message handlers allaqachon qo'shilgan - ular admin panel menu'dan ishlatiladi)

@dp.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id, created_at FROM admins ORDER BY created_at DESC") as cursor:
            admins = await cursor.fetchall()
    
    text = "👥 **Admin Ro'yxati**\n\n"
    text += f"👑 Asosiy Admin: `{ADMIN_ID}`\n\n"
    
    kb_list = []
    if not admins:
        text += "Qo'shimcha adminlar yo'q."
    else:
        text += "**Qo'shimcha Adminlar:**\n"
        for admin_id, created_at in admins:
            if created_at:
                date = created_at.split("T")[0] if isinstance(created_at, str) else str(created_at).split("T")[0]
                text += f"🔹 `{admin_id}` (Qo'shilgan: {date})\n"
            else:
                text += f"🔹 `{admin_id}` (Sana noma'lum)\n"
            kb_list.append([InlineKeyboardButton(text=f"🗑 O'chirish {admin_id}", callback_data=f"remove_admin_{admin_id}")])
    
    kb_list.append([InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add_admin_btn")]) # Using a specific callback for clarity
    kb_list.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin_btn")
async def admin_add_admin_btn_handler(callback: types.CallbackQuery, state: FSMContext):
    """Admin panel button to trigger add admin prompt"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await add_admin_prompt_msg(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("remove_admin_"))
async def process_remove_admin_callback(callback: types.CallbackQuery):
    """Inline tugma orqali admin o'chirish"""
    try:
        if not await is_admin(callback.from_user.id):
            await callback.answer("❌ Siz admin emassiz!", show_alert=True)
            return
        
        try:
            remove_admin_id = int(callback.data.split("_")[-1])
        except ValueError:
            await callback.answer("❌ Xatolik! Admin ID noto'g'ri formatda.", show_alert=True)
            return
        
        if remove_admin_id == ADMIN_ID:
            await callback.answer("❌ Asosiy admin o'chirilmaydi!", show_alert=True)
            return
        
        # Admin o'zini o'chirishga harakat qilmasligi kerak
        if remove_admin_id == callback.from_user.id:
            await callback.answer("❌ O'zingizni o'chira olmaysiz!", show_alert=True)
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Avval admin mavjudligini tekshirish
            async with db.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (remove_admin_id,)) as cursor:
                exists = await cursor.fetchone()
            
            if not exists:
                await callback.answer("❌ Admin topilmadi!", show_alert=True)
                return
            
            # Oxirgi adminni o'chirishni tekshirish (asosiy admindan tashqari)
            async with db.execute("SELECT COUNT(*) FROM admins") as cursor:
                admin_count = (await cursor.fetchone())[0]
            
            if admin_count <= 1:
                await callback.answer("❌ Oxirgi adminni o'chira olmaysiz!", show_alert=True)
                return
            
            # Adminni o'chirish
            await db.execute("DELETE FROM admins WHERE admin_id = ?", (remove_admin_id,))
            await db.commit()
        
        await callback.answer("✅ Admin o'chirildi!", show_alert=True)
        await callback.message.edit_text(
            f"✅ Admin `{remove_admin_id}` muvaffaqiyatli o'chirildi!\n\n"
            "👥 Admin ro'yxatini ko'rish uchun '👥 Admin ro'yxati' tugmasini bosing.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error in process_remove_admin_callback: {e}")
        await callback.answer(f"❌ Xatolik: {str(e)[:50]}", show_alert=True)

@dp.callback_query(F.data == "admin_remove_admin")
async def remove_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    await callback.message.answer("🗑 **Admin o'chirish**\n\nO'chirilishi kerak bo'lgan admin ID'sini kiriting:")
    await state.set_state(AuthState.remove_admin_id)
    await callback.answer()

@dp.message(AuthState.remove_admin_id)
async def process_remove_admin(message: types.Message, state: FSMContext):
    try:
        if not await is_admin(message.from_user.id):
            return
        
        try:
            remove_admin_id = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")
            return
        
        if remove_admin_id == ADMIN_ID:
            await message.answer("❌ Asosiy admin'ni o'chira olmaysiz!")
            await state.clear()
            return
        
        # Admin o'zini o'chira olmasligi kerak
        if remove_admin_id == message.from_user.id:
            await message.answer("❌ O'zingizni o'chira olmaysiz!")
            await state.clear()
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Avval admin mavjudligini tekshirish
            async with db.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (remove_admin_id,)) as cursor:
                exists = await cursor.fetchone()
            
            if not exists:
                await message.answer(f"❌ Admin `{remove_admin_id}` topilmadi!", parse_mode="Markdown")
                await state.clear()
                return
            
            # Oxirgi adminni o'chirishni tekshirish (asosiy admindan tashqari)
            async with db.execute("SELECT COUNT(*) FROM admins") as cursor:
                admin_count = (await cursor.fetchone())[0]
            
            if admin_count <= 1:
                await message.answer("❌ Oxirgi adminni o'chira olmaysiz!", parse_mode="Markdown")
                await state.clear()
                return
            
            # Adminni o'chirish
            await db.execute("DELETE FROM admins WHERE admin_id = ?", (remove_admin_id,))
            await db.commit()
        
        await message.answer(f"✅ Admin `{remove_admin_id}` o'chirildi!", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logging.error(f"Error in process_remove_admin: {e}")
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)[:50]}")

# --- Admin Tekshirish (boshida ta'riflanadi) ---


# --- Admin Akkaunt Ulash ---
@dp.callback_query(F.data == "admin_connect_account")
async def admin_connect_account(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    await prompt_phone(callback.message, state)
    await callback.answer()
