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
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError
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
    add_group_name = State()
    add_group_ids = State()
    add_admin_id = State()

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

# --- Klaviaturalar ---
def get_main_keyboard(user_id, is_connected=False):
    if not is_connected:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Akkountga ulanish")]], resize_keyboard=True)
        
    kb = [
        [InlineKeyboardButton(text="👥 Profillar", callback_data="main_profillar"), InlineKeyboardButton(text="📊 Statistika", callback_data="main_stats")],
        [InlineKeyboardButton(text="💬 Xabar matni", callback_data="main_xabar"), InlineKeyboardButton(text="📋 Guruhlar", callback_data="main_groups")],
        [InlineKeyboardButton(text="▶️ Ishga tushirish", callback_data="main_start_sender"), InlineKeyboardButton(text="⏱ Interval", callback_data="main_interval")],
        [InlineKeyboardButton(text="⭐ Pro status", callback_data="main_pro")],
        [InlineKeyboardButton(text="👤 Profil", callback_data="main_profile"), InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="main_settings")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="👨‍💻 Admin Panel", callback_data="main_admin")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Start — 1 oy (50,000 so'm)", callback_data="buy_start")],
        [InlineKeyboardButton(text="🔹 Pro — 3 oy (120,000 so'm)", callback_data="buy_3month")],
        [InlineKeyboardButton(text="🔹 Pro — 6 oy (200,000 so'm)", callback_data="buy_pro")],
        [InlineKeyboardButton(text="🔹 VIP — 1 yil (350,000 so'm)", callback_data="buy_year")],
        [InlineKeyboardButton(text="🔹 VIP — Umrbod (500,000 so'm)", callback_data="buy_vip")],
        [InlineKeyboardButton(text="👤 Admin bilan bog'lanish", url=f"tg://user?id={ADMIN_ID}")]
    ])

async def send_sub_msg(message: types.Message):
    text = (
        "🔥 **Obuna turlarini tanlang:**\n\n"
        "🔹 Start — 1 oy: 50 000 so'm\n"
        "🔹 Pro — 3 oy: 120 000 so'm\n"
        "🔹 Pro — 6 oy: 200 000 so'm\n"
        "🔹 VIP — 1 yil: 350 000 so'm\n"
        "🔹 VIP — Umrbod: 500 000 so'm\n\n"
        "⏱ Istalgan vaqtda, istalgan guruhga, istagan e'loningizni avtomatik yuboradi!"
    )
    await message.answer(text, reply_markup=get_subscription_keyboard(), parse_mode="Markdown")

# --- Client Helper ---
async def get_user_client(user_id):
    if user_id in users_data and 'client' in users_data[user_id]:
        return users_data[user_id]['client']
    
    session_path = f"sessions/sess_{user_id}"
    if os.path.exists(session_path + ".session"):
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            if user_id not in users_data:
                users_data[user_id] = {'is_running': False, 'interval': DEFAULT_AD_DELAY, 'ad_text': ''}
            users_data[user_id]['client'] = client
            return client
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
    client = await get_user_client(user_id)
    
    if not client:
        await message.answer(
            "👋 Assalomu alaykum! Botdan foydalanish uchun avval profilingizni ulashingiz kerak.",
            reply_markup=get_main_keyboard(user_id, is_connected=False)
        )
    else:
        if await check_subscription(user_id):
            await message.answer("🏠 **Asosiy boshqaruv paneli:**", reply_markup=get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
        else:
            await send_sub_msg(message)

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
    data = await state.get_data()
    saved_code = data.get('saved_code')
    user_id = message.from_user.id
    if user_id not in users_data: return
    client = users_data[user_id]['client']
    
    async def finish_auth():
        is_sub = await check_subscription(user_id)
        if is_sub:
            await message.answer("✅ Muvaffaqiyatli ulandi!", reply_markup=get_main_keyboard(user_id, is_connected=True))
        else:
            await message.answer("✅ Akkount muvaffaqiyatli ulandi!", reply_markup=get_main_keyboard(user_id, is_connected=True))
            await send_sub_msg(message)
        await state.clear()

    if saved_code:
        try:
            await client.sign_in(password=message.text.strip())
            await finish_auth()
        except Exception as e:
            await message.answer(f"❌ Xato: {e}")
        return

    code = "".join(message.text.replace(" ", "").split(","))
    try:
        await client.sign_in(users_data[user_id]['phone'], code, phone_code_hash=users_data[user_id]['phone_code_hash'])
        await finish_auth()
    except SessionPasswordNeededError:
        await state.update_data(saved_code=code)
        await message.answer("🔑 2FA Parolni yuboring:")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        await state.clear()

# --- To'lov Tizimi ---
@dp.callback_query(F.data.startswith("buy_"))
async def buy_subscription(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    
    if not client:
        await callback.answer("❌ Avval akkauntingizni ulashingiz kerak!", show_alert=True)
        return

    plan_data = {
        "buy_start": ("Start (1 oy)", 1, 50000),
        "buy_3month": ("Pro (3 oy)", 90, 120000),
        "buy_pro": ("Pro (6 oy)", 180, 200000),
        "buy_year": ("VIP (1 yil)", 365, 350000),
        "buy_vip": ("VIP (Umrbod)", 9999, 500000)
    }
    
    plan_name, days, amount = plan_data.get(callback.data, ("Noma'lum", 0, 0))
    
    await state.update_data(plan_type=callback.data.split("_")[1], plan_name=plan_name, days=days, amount=amount)
    
    text = (
        f"💳 **To'lov Tizimi**\n\n"
        f"📦 Tanlangan reja: **{plan_name}**\n"
        f"💰 Summa: **{amount:,} so'm**\n\n"
        f"📝 **To'lov qilish:**\n"
        f"1. Quyidagi raqamga pul o'tkazing\n"
        f"2. Chekni rasm sifatida yuboring\n"
        f"3. Admin tasdiqlashi kutib turing\n\n"
        f"👤 Admin: @admin_username\n"
        f"💳 Karta: 9860 12XX XXXX XXXX"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Chekni yuborish", callback_data=f"payment_screenshot_{callback.data.split('_')[1]}")],
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
    
    # Rasmni saqlash
    photo = message.photo[-1]
    file_path = f"payments/{user_id}_{datetime.now().timestamp()}.jpg"
    await bot.download(photo, destination=file_path)
    
    # To'lov so'rovini bazaga qo'shish
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO payment_requests (user_id, plan_type, amount, screenshot_path, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (user_id, data.get('plan_type'), data.get('amount'), file_path, datetime.now().isoformat()))
        await db.commit()
    
    await message.answer(
        f"✅ **Chek qabul qilindi!**\n\n"
        f"📦 Reja: {data.get('plan_name')}\n"
        f"💰 Summa: {data.get('amount'):,} so'm\n\n"
        f"⏳ Admin tasdiqlashi kutib turing...",
        parse_mode="Markdown"
    )
    
    # Admin'ga xabar
    admin_text = (
        f"🔔 **Yangi To'lov So'rovi**\n\n"
        f"👤 Foydalanuvchi: `{user_id}`\n"
        f"📦 Reja: {data.get('plan_name')}\n"
        f"💰 Summa: {data.get('amount'):,} so'm\n\n"
        f"Tasdiqlaysizmi?"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_payment_{user_id}_{data.get('plan_type')}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_payment_{user_id}")]
    ])
    
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb, parse_mode="Markdown")
    
    await state.clear()

@dp.callback_query(F.data.startswith("approve_payment_"))
async def approve_payment(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    parts = callback.data.split("_")
    user_id = int(parts[2])
    plan_type = parts[3]
    
    plan_days = {
        "start": 30,
        "3month": 90,
        "pro": 180,
        "year": 365,
        "vip": 9999
    }
    
    days = plan_days.get(plan_type, 30)
    await add_subscription(user_id, days, plan_type)
    
    # Foydalanuvchiga xabar
    await bot.send_message(user_id, "✅ **To'lovingiz tasdiqlandi!**\n\nObunangiz faollashtirildi. Botdan foydalanishni boshlashingiz mumkin.", parse_mode="Markdown")
    
    await callback.message.edit_text("✅ To'lov tasdiqlandi!", reply_markup=None)
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    user_id = int(callback.data.split("_")[-1])
    
    await bot.send_message(user_id, "❌ **To'lovingiz rad etildi.**\n\nIltimos, admin bilan bog'laning.", parse_mode="Markdown")
    await callback.message.edit_text("❌ To'lov rad etildi!", reply_markup=None)
    await callback.answer()

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ To'lov bekor qilindi.", reply_markup=get_subscription_keyboard())
    await state.clear()
    await callback.answer()

# --- Profillar Tizimi ---
@dp.callback_query(F.data == "main_profillar")
async def show_profiles(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
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
    await callback.message.answer("📱 **Yangi profil qo'shish**\n\nTelefon raqamini kiriting:")
    await state.set_state(AuthState.add_profile_phone)
    await callback.answer()

@dp.message(AuthState.add_profile_phone)
async def process_add_profile(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO profiles (user_id, phone, session_name, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, phone, f"profile_{user_id}_{datetime.now().timestamp()}", datetime.now().isoformat()))
        await db.commit()
    
    await message.answer(f"✅ Profil qo'shildi: `{phone}`", parse_mode="Markdown")
    await state.clear()

# --- Guruhlar Tizimi ---
@dp.callback_query(F.data == "main_groups")
async def show_groups(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, folder_name FROM groups WHERE user_id = ?", (user_id,)) as cursor:
            groups = await cursor.fetchall()
    
    text = "📋 **Guruh Folderlar**\n\n"
    
    if not groups:
        text += "Hozircha folder yo'q.\n\n"
    else:
        for idx, (gid, folder_name) in enumerate(groups, 1):
            text += f"{idx}. 📁 {folder_name}\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Folder qo'shish", callback_data="add_group")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_profile")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "add_group")
async def add_group_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📁 **Yangi folder qo'shish**\n\nFolder nomini kiriting:")
    await state.set_state(AuthState.add_group_name)
    await callback.answer()

@dp.message(AuthState.add_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    await state.update_data(folder_name=message.text)
    await message.answer("🔗 **Guruh ID'larini kiriting** (vergul bilan ajratib):\n\nMasalan: `-1001234567890, -1001234567891`")
    await state.set_state(AuthState.add_group_ids)

@dp.message(AuthState.add_group_ids)
async def process_group_ids(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    folder_name = data.get('folder_name')
    group_ids = message.text.strip()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO groups (user_id, folder_name, group_ids, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, folder_name, group_ids, datetime.now().isoformat()))
        await db.commit()
    
    await message.answer(f"✅ Folder qo'shildi: **{folder_name}**", parse_mode="Markdown")
    await state.clear()

# --- Reklama Matni va Rasm ---
@dp.callback_query(F.data == "main_xabar")
async def set_ad_text(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 **Reklama matnini kiriting:**")
    await state.set_state(AuthState.ad_text)
    await callback.answer()

@dp.message(AuthState.ad_text)
async def save_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {'is_running': False, 'interval': DEFAULT_AD_DELAY}
    users_data[user_id]['ad_text'] = message.text
    
    await message.answer("✅ Xabar matni saqlandi!", reply_markup=get_main_keyboard(user_id, is_connected=True))
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
        
        await callback.message.answer(f"✅ Vaqt oralig'i **{display_time}** qilib belgilandi!", reply_markup=get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
    
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
        
        await message.answer(f"✅ Interval **{seconds} sekund** qilib belgilandi!", reply_markup=get_main_keyboard(user_id, is_connected=True), parse_mode="Markdown")
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
    asyncio.create_task(start_sender(user_id))
    await callback.message.answer("🚀 Reklama tarqatish boshlandi!")
    await callback.answer()

async def start_sender(user_id):
    client = await get_user_client(user_id)
    if not client:
        return
    
    data = users_data[user_id]
    while data.get('is_running'):
        if not await check_subscription(user_id):
            data['is_running'] = False
            await bot.send_message(user_id, "❌ Obunangiz tugadi! Xizmat to'xtatildi.")
            break
        try:
            async for dialog in client.iter_dialogs():
                if not data.get('is_running'):
                    break
                if dialog.is_group or dialog.is_channel:
                    try:
                        await client.send_message(dialog.id, data['ad_text'])
                        await asyncio.sleep(15)
                    except:
                        pass
            for _ in range(data['interval']):
                if not data.get('is_running'):
                    break
                await asyncio.sleep(1)
        except:
            await asyncio.sleep(60)

# --- Profil va Sozlamalar ---
@dp.callback_query(F.data == "main_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    me = await client.get_me() if client else None
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    
    expiry = row[0] if row else "Obuna yo'q"
    
    text = (
        f"👤 **Foydalanuvchi ma'lumotlari**\n\n"
        f"🔹 Ism: **{me.first_name if me else 'Noma`lum'}**\n"
        f"🔹 Username: @{me.username if me and me.username else 'yo`q'}\n"
        f"🔹 Telegram ID: `{user_id}`\n"
        f"🔹 Obuna: **{expiry}**"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
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
        [InlineKeyboardButton(text="💎 Obuna uzaytirish", callback_data="buy_pro")]
    ])
    await callback.message.answer("⚙️ **Sozlamalar**", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "main_stop_sender")
async def stop_sender(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users_data:
        users_data[user_id]['is_running'] = False
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
    
    await callback.message.answer("✅ Chiqildi!", reply_markup=get_main_keyboard(user_id, is_connected=False))
    await callback.answer()

@dp.callback_query(F.data == "main_relogin")
async def relogin(callback: types.CallbackQuery, state: FSMContext):
    await prompt_phone(callback.message, state)
    await callback.answer()

# --- Admin Panel ---
async def show_admin_panel(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="🔍 Qidirish", callback_data="admin_search")],
        [InlineKeyboardButton(text="⏰ Obuna uzaytirish", callback_data="admin_extend")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👨‍💼 Admin qo'shish", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="👥 Admin ro'yxati", callback_data="admin_list_admins")]
    ])
    await message.answer("👑 **Admin Boshqaruv Paneli**", reply_markup=kb)

@dp.callback_query(F.data == "main_admin")
async def admin_panel(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await show_admin_panel(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    
    total_users = len(users_data)
    active_bots = sum(1 for u in users_data.values() if u.get('is_running'))
    
    text = (
        f"📈 **Tizim Statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: `{total_users}`\n"
        f"⚡️ Faol senderlar: `{active_bots}`\n"
        f"📅 Bugungi sana: `{datetime.now().strftime('%Y-%m-%d')}`"
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
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
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_search")
async def admin_search(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await callback.message.answer("🔍 Foydalanuvchi ID'sini kiriting:")
    await state.set_state(AuthState.admin_search_user)
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

# --- Main ---
async def main():
    await init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

# --- Pro Status (Rasm yuborish) ---
@dp.callback_query(F.data == "main_pro")
async def show_pro_status(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT plan_type FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    
    plan = row[0] if row else "free"
    
    text = (
        f"⭐ **Premium Status**\n\n"
        f"📦 Sizning reja: **{plan.upper()}**\n\n"
        f"✨ **Imkoniyatlar:**\n"
        f"✅ Cheksiz guruhlar\n"
        f"✅ Rasm bilan reklama\n"
        f"✅ Avtomatik yuborish\n"
        f"✅ Prioritet qo'llab-quvvatlash"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Yanada yaxshi reja", callback_data="buy_vip")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_profile")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "main_stats")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    status = "Ishlamoqda" if users_data.get(user_id, {}).get('is_running') else "To'xtatilgan"
    interval = users_data.get(user_id, {}).get('interval', DEFAULT_AD_DELAY)
    ad_text = users_data.get(user_id, {}).get('ad_text', '')
    
    text = (
        f"📊 **Shaxsiy Statistika**\n\n"
        f"🔹 Holat: `{status}`\n"
        f"⏱ Interval: `{interval} sekund`\n"
        f"📝 Reklama: {'✅ Sozlangan' if ad_text else '❌ Yo`q'}\n"
        f"👥 Profillar: `{len(users_data.get(user_id, {}).get('profiles', []))} ta`"
    )
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# --- Admin Qo'shish ---
@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.answer("👨‍💼 **Yangi admin qo'shish**\n\nAdmin ID raqamini kiriting:")
    await state.set_state(AuthState.add_admin_id)
    await callback.answer()

@dp.message(AuthState.add_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
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
            await message.answer(f"❌ Foydalanuvchi `{new_admin_id}` allaqachon admin!")
            await state.clear()
            return
        
        # Yangi admin qo'shish
        await db.execute("""
            INSERT INTO admins (admin_id, added_by, created_at)
            VALUES (?, ?, ?)
        """, (new_admin_id, message.from_user.id, datetime.now().isoformat()))
        await db.commit()
    
    await message.answer(f"✅ Foydalanuvchi `{new_admin_id}` admin qilib belgilandi!", parse_mode="Markdown")
    
    # Yangi admin'ga xabar
    try:
        await bot.send_message(new_admin_id, "🎉 **Siz admin qilib belgilandi!**\n\nAdmin panel uchun `/start` yuboring.", parse_mode="Markdown")
    except:
        pass
    
    await state.clear()

@dp.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id, created_at FROM admins ORDER BY created_at DESC") as cursor:
            admins = await cursor.fetchall()
    
    text = "👥 **Admin Ro'yxati**\n\n"
    text += f"👑 Asosiy Admin: `{ADMIN_ID}`\n\n"
    
    if not admins:
        text += "Qo'shimcha adminlar yo'q."
    else:
        text += "**Qo'shimcha Adminlar:**\n"
        for admin_id, created_at in admins:
            date = created_at.split("T")[0]
            text += f"🔹 `{admin_id}` (Qo'shilgan: {date})\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Admin o'chirish", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_admin")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_remove_admin")
async def remove_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.answer("🗑 **Admin o'chirish**\n\nO'chirilishi kerak bo'lgan admin ID'sini kiriting:")
    await state.set_state(AuthState.add_admin_id)
    await callback.answer()

@dp.message(AuthState.add_admin_id)
async def process_remove_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        remove_admin_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format!")
        return
    
    if remove_admin_id == ADMIN_ID:
        await message.answer("❌ Asosiy admin'ni o'chira olmaysiz!")
        await state.clear()
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE admin_id = ?", (remove_admin_id,))
        await db.commit()
    
    await message.answer(f"✅ Admin `{remove_admin_id}` o'chirildi!", parse_mode="Markdown")
    await state.clear()

# Admin tekshirish funksiyasi
async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
    
    return result is not None
