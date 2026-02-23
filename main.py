import asyncio
import os
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
# ... rest of the imports remain the same
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
DB_PATH = "bot_database.db"

# Papkalarni yaratish
if not os.path.exists("sessions"):
    os.makedirs("sessions")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Foydalanuvchilar ma'lumotlari
users_data = {}

class AuthState(StatesGroup):
    phone = State()
    code_pass = State()
    ad_text = State()
    ad_interval = State()
    admin_broadcast_message = State()
    admin_search_user = State()
    admin_extend_sub = State()
    admin_custom_interval = State()

# --- Ma'lumotlar bazasi ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                expiry_date TEXT
            )
        """)
        await db.commit()

async def add_subscription(user_id: int, days: int):
    expiry_date = datetime.now() + timedelta(days=days)
    if days == 9999: # Umrbod
        expiry_date_str = "2099-12-31 23:59:59"
    else:
        expiry_date_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO subscriptions (user_id, expiry_date)
            VALUES (?, ?)
        """, (user_id, expiry_date_str))
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
        [InlineKeyboardButton(text="🔹 Start — 1 oy obuna (50,000 so‘m)", callback_data="buy_start")],
        [InlineKeyboardButton(text="🔹 Pro — 6 oy obuna (250,000 so‘m)", callback_data="buy_pro")],
        [InlineKeyboardButton(text="🔹 VIP — Umrbod obuna (500,000 so‘m)", callback_data="buy_vip")],
        [InlineKeyboardButton(text="👤 Admin bilan bog'lanish", url=f"tg://user?id={ADMIN_ID}")]
    ])

async def send_sub_msg(message: types.Message):
    text = (
        "Telegram guruhlarga qo‘lda yozib o‘tirmang — e’lonlaringizni bot o‘zi yuboradi!\n\n"
        "🔥 **Endi siz uchun 3 xil obuna mavjud:**\n\n"
        "🔹 Start — 1 oy: 50 000 so‘m\n"
        "🔹 Pro — 6 oy: 250 000 so‘m\n"
        "🔹 VIP — Umrbod: 500 000 so‘m\n\n"
        "⏱ Istalgan vaqtda, istalgan guruhga, istagan e’loningizni avtomatik yuboradi! **Obuna turini tanlang!**"
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
        [InlineKeyboardButton(text="5 minut", callback_data="setint_300"), InlineKeyboardButton(text="10 minut", callback_data="setint_600")],
        [InlineKeyboardButton(text="20 minut", callback_data="setint_1200"), InlineKeyboardButton(text="30 minut", callback_data="setint_1800")],
        [InlineKeyboardButton(text="1 soat", callback_data="setint_3600"), InlineKeyboardButton(text="2 soat", callback_data="setint_7200")],
        [InlineKeyboardButton(text="3 soat", callback_data="setint_10800"), InlineKeyboardButton(text="4 soat", callback_data="setint_14400")],
        [InlineKeyboardButton(text="5 soat", callback_data="setint_18000"), InlineKeyboardButton(text="24 soat", callback_data="setint_86400")],
        [InlineKeyboardButton(text="✏️ Boshqa (soniyalarda)", callback_data="setint_custom")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Handlerlar ---
@dp.callback_query(F.data.startswith("setint_"))
async def process_interval_selection(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    val = callback.data.split("_")[1]
    
    if val == "custom":
        await callback.message.answer("⏱ O'zingiz xohlagan vaqtni **soniyalarda** kiriting:")
        await state.set_state(AuthState.ad_interval)
    else:
        seconds = int(val)
        if user_id not in users_data: users_data[user_id] = {'is_running': False, 'ad_text': ''}
        users_data[user_id]['interval'] = seconds
        
        # UI'da chiroyli ko'rsatish
        display_time = ""
        if seconds < 3600: display_time = f"{seconds // 60} minut"
        else: display_time = f"{seconds // 3600} soat"
        
        await callback.message.answer(f"✅ Vaqt oralig'i **{display_time}** qilib belgilandi!", reply_markup=get_main_keyboard(user_id, is_connected=True))
    
    await callback.answer()

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

@dp.message(Command("addsub"))
async def add_sub_command(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        user_id = int(args[1])
        days = int(args[2])
        await add_subscription(user_id, days)
        await message.answer(f"✅ Foydalanuvchi {user_id} ga {days} kunlik obuna berildi.")
    except Exception as e:
        await message.answer("Xato! Format: `/addsub user_id kun`", parse_mode="Markdown")

# --- Admin Panel Funksiyalari ---
@dp.callback_query(F.data == "admin_stats")
async def admin_stats_modern(callback: types.CallbackQuery):
    total_users = len(users_data)
    active_bots = sum(1 for u in users_data.values() if u.get('is_running'))
    text = (
        "📈 **Tizim Statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: `{total_users}`\n"
        f"⚡️ Faol senderlar: `{active_bots}`\n"
        f"📅 Bugungi sana: `{datetime.now().strftime('%Y-%m-%d')}`"
    )
    await callback.message.edit_text(text, reply_markup=callback.message.reply_markup, parse_mode="Markdown")

async def show_admin_panel(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"), InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="🔍 Foydalanuvchi qidirish", callback_data="admin_search"), InlineKeyboardButton(text="⏰ Obuna uzaytirish", callback_data="admin_extend")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast"), InlineKeyboardButton(text="🔑 Obuna berish", callback_data="admin_sub_help")],
        [InlineKeyboardButton(text="⚙️ Tizim sozlamalari", callback_data="admin_sys_settings"), InlineKeyboardButton(text="🗑 Foydalanuvchi o'chirish", callback_data="admin_delete_user")]
    ])
    await message.answer("👑 **Admin Boshqaruv Paneli**\n\nKerakli bo'limni tanlang:", reply_markup=kb, parse_mode="Markdown")

@dp.message(F.text == "👨‍💻 Admin Panel")
async def admin_panel_text_message(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await show_admin_panel(message)

@dp.callback_query(F.data == "admin_sub_help")
async def sub_help(callback: types.CallbackQuery):
    await callback.message.answer("Obuna berish uchun:\n`/addsub ID KUN` yuboring.\nMasalan: `/addsub 1234567 30` (1 oy uchun)", parse_mode="Markdown")

@dp.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: types.CallbackQuery):
    # Placeholder for listing users
    user_ids = list(users_data.keys())
    text = "👥 **Foydalanuvchilar Ro'yxati:**\n\n"
    if user_ids:
        text += "\n".join([f"🔹 `{uid}`" for uid in user_ids[:20]]) # Show first 20 users
        if len(user_ids) > 20:
            text += "\n..."
    else:
        text += "Hozircha foydalanuvchilar yo'q."
    await callback.message.edit_text(text, reply_markup=callback.message.reply_markup, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 **Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:**")
    await state.set_state(AuthState.admin_broadcast_message)

@dp.message(AuthState.admin_broadcast_message)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    broadcast_text = message.text
    success_count = 0
    for user_id in users_data.keys():
        try:
            await bot.send_message(user_id, broadcast_text, parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.1) # Small delay to avoid rate limits
        except Exception as e:
            logging.error(f"Failed to send broadcast to user {user_id}: {e}")
    await message.answer(f"✅ Xabar {success_count} ta foydalanuvchiga yuborildi.")
    await state.clear()

@dp.callback_query(F.data == "admin_sys_settings")
async def admin_sys_settings(callback: types.CallbackQuery):
    # Placeholder for system settings
    await callback.message.edit_text("⚙️ **Tizim sozlamalari:**\n\nBu bo'lim tez orada ishga tushadi.", reply_markup=callback.message.reply_markup, parse_mode="Markdown")


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
        await message.answer(f"❌ Xatolik: {e}"); await state.clear()

@dp.message(AuthState.code_pass)
async def process_auth_step(message: types.Message, state: FSMContext):
    data = await state.get_data(); saved_code = data.get('saved_code'); user_id = message.from_user.id
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
        await message.answer(f"❌ Xato: {e}"); await state.clear()

# Callback handler for the new Inline Menu
@dp.callback_query(F.data.startswith("main_"))
async def main_menu_callbacks(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]
    
    if not await check_subscription(user_id):
        await callback.answer("❌ Obuna talab etiladi!", show_alert=True)
        return await send_sub_msg(callback.message)

    if action == "xabar":
        await callback.message.answer("📝 Reklama xabari matnini yuboring:")
        await state.set_state(AuthState.ad_text)
    
    elif action == "interval":
        await callback.message.answer("⏱ **Xabar yuborish oralig'ini tanlang:**", reply_markup=get_interval_keyboard(), parse_mode="Markdown")
        
    elif action == "start_sender":
        if user_id not in users_data or not users_data[user_id].get('ad_text'):
            return await callback.answer("❌ Avval reklama xabarini sozlang!", show_alert=True)
        if users_data[user_id].get('is_running'):
            return await callback.answer("⚠️ Sender allaqachon ishlamoqda.", show_alert=True)
            
        users_data[user_id]['is_running'] = True
        asyncio.create_task(start_sender(user_id))
        await callback.message.answer("🚀 Reklama tarqatish boshlandi!")

    elif action == "profillar":
        client = await get_user_client(user_id)
        phone = users_data.get(user_id, {}).get('phone', 'Noma`lum')
        status = "✅ Faol" if client else "❌ Ulanmagan"
        text = (
            "👥 **Sizning Profillaringiz**\n\n"
            f"� **Asosiy akkaunt:**\n"
            f"🔹 Telefon: `{phone}`\n"
            f"🔹 Holat: {status}\n\n"
            "💡 _Yangi profil qo'shish xizmati tez kunda ishga tushadi._"
        )
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "stats":
        status = "Ishlamoqda" if users_data.get(user_id, {}).get('is_running') else "To'xtatilgan"
        interval = users_data.get(user_id, {}).get('interval', DEFAULT_AD_DELAY)
        text = (
            "📊 **Shaxsiy Statistika**\n\n"
            f"� Holat: `{status}`\n"
            f"⏱ Tanlangan interval: `{interval} sekund`\n"
            f"📝 Reklama matni: {'✅ Sozlangan' if users_data.get(user_id, {}).get('ad_text') else '❌ Yo`q'}"
        )
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "pro":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                expiry = row[0] if row else "Noma'lum"
        text = (
            "⭐ **Premium (Pro) Status**\n\n"
            "Sizda barcha imkoniyatlar ochiq!\n"
            f"📅 Obuna tugash muddati: `{expiry}`\n\n"
            "🚀 _Cheksiz guruhlarga reklama tarqatish imkoniyati faol._"
        )
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "profile":
        client = await get_user_client(user_id)
        me = await client.get_me() if client else None
        text = (
            "👤 **Foydalanuvchi ma'lumotlari**\n\n"
            f"🔹 Ism: **{me.first_name if me else 'Noma`lum'}**\n"
            f"🔹 Username: @{me.username if me and me.username else 'yo`q'}\n"
            f"🔹 Telegram ID: `{user_id}`\n"
            f"🔹 Xabar yuborish: {'✅ Ishlamoqda' if users_data.get(user_id, {}).get('is_running') else '💤 To`xtatilgan'}\n"
            f"🔹 Holat: {'✅ Ulangan' if me else '❌ Ulanmagan'}"
        )
        
        kb = []
        if me:
            kb.append([InlineKeyboardButton(text="🚪 Akkauntdan chiqish", callback_data="main_logout")])
        kb.append([InlineKeyboardButton(text="🔄 Akkauntni o'zgartirish", callback_data="main_relogin")])
        
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

    elif action == "logout":
        client = await get_user_client(user_id)
        if client:
            await client.disconnect()
        
        # Sessiya fayllarini o'chirish
        for ext in [".session", ".session-journal"]:
            path = f"sessions/sess_{user_id}{ext}"
            if os.path.exists(path):
                os.remove(path)
        
        if user_id in users_data:
            del users_data[user_id]
            
        await callback.message.answer("✅ Akkauntdan muvaffaqiyatli chiqildi va barcha ma'lumotlar ochi rildi.", reply_markup=get_main_keyboard(user_id, is_connected=False))

    elif action == "relogin":
        await prompt_phone(callback.message, state)

    elif action == "settings":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Profilni yangilash", callback_data="main_profile_refresh")],
            [InlineKeyboardButton(text="⏱ Intervalni o'zgartirish", callback_data="main_interval")],
            [InlineKeyboardButton(text="🛑 Barcha ishlarni to'xtatish", callback_data="main_stop_all")]
        ])
        await callback.message.answer("⚙️ **Sozlamalar bo'limi**\n\nKerakli amalni tanlang:", reply_markup=kb)

    elif action == "admin" and user_id == ADMIN_ID:
        await show_admin_panel(callback.message)

    else:
        await callback.answer("✅ Amal bajarildi!", show_alert=False)
    
    await callback.answer()

@dp.callback_query(F.data == "admin_users_list")
async def admin_users_list_functional(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, expiry_date FROM subscriptions") as cursor:
            subs = await cursor.fetchall()
    
    text = "👥 **Foydalanuvchilar va Obunalar:**\n\n"
    if not subs:
        text += "Hozircha hech kimda obuna yo'q."
    else:
        for uid, expiry in subs[:30]:
            status = "🟢" if datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S") > datetime.now() else "�"
            is_running = "⚡️" if users_data.get(uid, {}).get('is_running') else "💤"
            text += f"{status} `{uid}` | {is_running} | {expiry.split()[0]}\n"
    
    text += "\n💡 *Legend:* 🟢-Faol sub, 🔴-Tugagan, ⚡️-Sender yoqilgan"
    await callback.message.edit_text(text, reply_markup=callback.message.reply_markup, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_sys_settings")
async def admin_sys_settings_functional(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    # Simple system info
    db_size = os.path.getsize(DB_PATH) / 1024
    sessions_count = len(os.listdir("sessions")) // 2 # .session and .journal files
    
    text = (
        "⚙️ **Tizim Texnik Holati**\n\n"
        f"📂 Ma'lumotlar bazasi: `{db_size:.1f} KB`\n"
        f"🔑 Jami sessiyalar: `{sessions_count} ta`\n"
        f"🤖 Bot holati: `Ishlamoqda`\n"
        f"🕒 Server vaqti: `{datetime.now().strftime('%H:%M:%S')}`"
    )
    await callback.message.edit_text(text, reply_markup=callback.message.reply_markup, parse_mode="Markdown")

# --- Yangi Admin Funksiyalari ---

@dp.callback_query(F.data == "admin_search")
async def admin_search_user(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("🔍 **Foydalanuvchi qidirish**\n\nFoydalanuvchi ID raqamini kiriting:")
    await state.set_state(AuthState.admin_search_user)
    await callback.answer()

@dp.message(AuthState.admin_search_user)
async def process_admin_search(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    try:
        search_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")
        return
    
    # Ma'lumotlar bazasidan qidirish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, expiry_date FROM subscriptions WHERE user_id = ?", (search_id,)) as cursor:
            row = await cursor.fetchone()
    
    # Foydalanuvchi ma'lumotlari
    user_info = users_data.get(search_id, {})
    is_connected = search_id in users_data and 'client' in users_data[search_id]
    is_running = user_info.get('is_running', False)
    phone = user_info.get('phone', 'Noma\'lum')
    ad_text = user_info.get('ad_text', '')
    interval = user_info.get('interval', DEFAULT_AD_DELAY)
    
    # Obuna holati
    if row:
        expiry_date = row[1]
        is_active = datetime.strptime(expiry_date, "%Y-%m-%d %H:%M:%S") > datetime.now()
        sub_status = "🟢 Faol" if is_active else "🔴 Tugagan"
    else:
        expiry_date = "Obuna yo'q"
        sub_status = "❌ Obuna yo'q"
    
    text = (
        f"👤 **Foydalanuvchi: `{search_id}`**\n\n"
        f"📱 Telefon: `{phone}`\n"
        f"🔗 Holat: {'✅ Ulangan' if is_connected else '❌ Ulanmagan'}\n"
        f"⚡️ Sender: {'🟢 Ishlamoqda' if is_running else '🔴 To\'xtatilgan'}\n"
        f"⏱ Interval: `{interval} sekund`\n"
        f"📝 Reklama matni: {'✅ Bor' if ad_text else '❌ Yo\'q'}\n\n"
        f"💎 **Obuna:**\n"
        f"Status: {sub_status}\n"
        f"Tugash sanasi: `{expiry_date}`"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Obuna uzaytirish", callback_data=f"admin_extend_user_{search_id}")],
        [InlineKeyboardButton(text="🗑 Obunani o'chirish", callback_data=f"admin_remove_sub_{search_id}")],
        [InlineKeyboardButton(text="🚫 Senderni to'xtatish", callback_data=f"admin_stop_sender_{search_id}")],
        [InlineKeyboardButton(text="📊 Batafsil", callback_data=f"admin_detail_{search_id}")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data.startswith("admin_extend_user_"))
async def admin_extend_user_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    
    user_id = int(callback.data.split("_")[-1])
    await state.update_data(extend_user_id=user_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 kun", callback_data="extend_days_7"), InlineKeyboardButton(text="30 kun", callback_data="extend_days_30")],
        [InlineKeyboardButton(text="90 kun", callback_data="extend_days_90"), InlineKeyboardButton(text="180 kun", callback_data="extend_days_180")],
        [InlineKeyboardButton(text="365 kun", callback_data="extend_days_365"), InlineKeyboardButton(text="Umrbod", callback_data="extend_days_9999")],
        [InlineKeyboardButton(text="✏️ Boshqa", callback_data="extend_days_custom")]
    ])
    
    await callback.message.answer(f"⏰ **Foydalanuvchi `{user_id}` uchun obuna muddatini tanlang:**", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("extend_days_"))
async def admin_extend_process(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    
    data = await state.get_data()
    user_id = data.get('extend_user_id')
    
    if not user_id:
        await callback.answer("❌ Xatolik! Qaytadan urinib ko'ring.", show_alert=True)
        return
    
    days_str = callback.data.split("_")[-1]
    
    if days_str == "custom":
        await callback.message.answer("✏️ Kunlar sonini kiriting (masalan: 45):")
        await state.set_state(AuthState.admin_extend_sub)
        await callback.answer()
        return
    
    days = int(days_str)
    await add_subscription(user_id, days)
    
    display_text = "Umrbod" if days == 9999 else f"{days} kun"
    await callback.message.answer(f"✅ Foydalanuvchi `{user_id}` ga **{display_text}** obuna berildi!", parse_mode="Markdown")
    await state.clear()
    await callback.answer()

@dp.message(AuthState.admin_extend_sub)
async def admin_extend_custom_days(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    try:
        days = int(message.text.strip())
        data = await state.get_data()
        user_id = data.get('extend_user_id')
        
        if not user_id:
            await message.answer("❌ Xatolik! Qaytadan urinib ko'ring.")
            await state.clear()
            return
        
        await add_subscription(user_id, days)
        await message.answer(f"✅ Foydalanuvchi `{user_id}` ga **{days} kun** obuna berildi!", parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting.")

@dp.callback_query(F.data.startswith("admin_remove_sub_"))
async def admin_remove_subscription(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    user_id = int(callback.data.split("_")[-1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        await db.commit()
    
    await callback.message.answer(f"✅ Foydalanuvchi `{user_id}` ning obunasi o'chirildi!", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_stop_sender_"))
async def admin_stop_user_sender(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    user_id = int(callback.data.split("_")[-1])
    
    if user_id in users_data:
        users_data[user_id]['is_running'] = False
        await callback.message.answer(f"✅ Foydalanuvchi `{user_id}` ning senderi to'xtatildi!", parse_mode="Markdown")
    else:
        await callback.message.answer(f"❌ Foydalanuvchi `{user_id}` topilmadi yoki sender ishlamagan.", parse_mode="Markdown")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_detail_"))
async def admin_user_detail(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    user_id = int(callback.data.split("_")[-1])
    user_info = users_data.get(user_id, {})
    
    # Client ma'lumotlari
    client = await get_user_client(user_id)
    me = None
    if client:
        try:
            me = await client.get_me()
        except:
            pass
    
    text = (
        f"📋 **Batafsil Ma'lumot: `{user_id}`**\n\n"
        f"👤 Ism: {me.first_name if me else 'Noma\'lum'}\n"
        f"🆔 Username: @{me.username if me and me.username else 'yo\'q'}\n"
        f"📱 Telefon: `{user_info.get('phone', 'Noma\'lum')}`\n"
        f"⚡️ Sender: {'🟢 Ishlamoqda' if user_info.get('is_running') else '🔴 To\'xtatilgan'}\n"
        f"⏱ Interval: `{user_info.get('interval', DEFAULT_AD_DELAY)} sekund`\n\n"
        f"📝 **Reklama matni:**\n"
        f"{user_info.get('ad_text', 'Hali sozlanmagan')[:200]}"
    )
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_extend")
async def admin_extend_direct(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("⏰ **Obuna uzaytirish**\n\nFoydalanuvchi ID raqamini kiriting:")
    await state.set_state(AuthState.admin_search_user)
    await callback.answer()

@dp.callback_query(F.data == "admin_delete_user")
async def admin_delete_user_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("🗑 **Foydalanuvchi o'chirish**\n\n⚠️ Bu amal foydalanuvchining barcha ma'lumotlarini o'chiradi!\n\nFoydalanuvchi ID raqamini kiriting:")
    await state.set_state(AuthState.admin_search_user)
    await callback.answer()

# Support for old text-based buttons if user clicks them (from previous messages)
@dp.message(F.text.in_({"💬 Xabar", "▶️ Ishga tushirish", "📋 Guruhlar", "📊 Statistika", "⏱ Interval", "⭐ Pro", "👤 Profil", "⚙️ Sozlamalar", "👥 Profillar"}))
async def legacy_features(message: types.Message, state: FSMContext):
    # Map text to callbacks logic
    user_id = message.from_user.id
    if not await check_subscription(user_id): return await send_sub_msg(message)
    await message.answer("⚠️ Iltimos, xabardagi tugmalardan foydalaning.", reply_markup=get_main_keyboard(user_id, is_connected=True))

@dp.message(AuthState.ad_text)
async def save_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users_data: users_data[user_id] = {'is_running': False, 'interval': DEFAULT_AD_DELAY}
    users_data[user_id]['ad_text'] = message.text
    await message.answer("✅ Xabar matni saqlandi!", reply_markup=get_main_keyboard(user_id, is_connected=True))
    await state.clear()

async def start_sender(user_id):
    client = await get_user_client(user_id)
    if not client: return
    
    data = users_data[user_id]
    while data.get('is_running'):
        if not await check_subscription(user_id):
            data['is_running'] = False
            await bot.send_message(user_id, "❌ Obunangiz tugadi! Xizmat to'xtatildi.")
            break
        try:
            async for dialog in client.iter_dialogs():
                if not data.get('is_running'): break
                if dialog.is_group or dialog.is_channel:
                    try:
                        await client.send_message(dialog.id, data['ad_text'])
                        await asyncio.sleep(15) 
                    except: pass
            for _ in range(data['interval']):
                if not data.get('is_running'): break
                await asyncio.sleep(1)
        except: await asyncio.sleep(60)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    client = await get_user_client(user_id)
    
    if not client:
        await callback.answer("❌ Avval akkauntingizni ulashingiz kerak!", show_alert=True)
        return

    plan_name = ""
    if "start" in callback.data: plan_name = "Start (1 oy)"
    elif "pro" in callback.data: plan_name = "Pro (6 oy)"
    elif "vip" in callback.data: plan_name = "VIP (Umrbod)"

    await callback.message.answer("⏳ Admin va dasturchiga so'rov yuborilmoqda, kuting...")

    # Admin va dasturchi ID'lari
    admin_target = 6262775861
    dev_target = 2114098498
    
    success_count = 0
    failed_targets = []
    
    # Admin'ga xabar yuborish
    try:
        entity = await client.get_entity(admin_target)
        await client.send_message(entity, f"Salom, men Avto Habar botida obuna bo'lmoqchiman.\n\n📦 Tanlangan reja: {plan_name}\n\nMenga karta raqamini yuboring.")
        success_count += 1
    except Exception as e:
        logging.error(f"Admin'ga xabar yuborishda xatolik: {e}")
        failed_targets.append("Admin")
    
    # Dasturchi'ga xabar yuborish
    try:
        entity = await client.get_entity(dev_target)
        await client.send_message(entity, f"Salom, men Avto Habar botidan foydalanuvchiman.\n\n📦 Tanlangan reja: {plan_name}\n\nSavolim bor edi.")
        success_count += 1
    except Exception as e:
        logging.error(f"Dasturchi'ga xabar yuborishda xatolik: {e}")
        failed_targets.append("Dasturchi")
    
    # Natijani ko'rsatish
    if success_count > 0:
        msg = f"✅ **So'rov yuborildi!**\n\nSiz tanlagan reja: `{plan_name}`\n\n"
        if success_count == 2:
            msg += "Admin va dasturchi bilan bog'lanish muvaffaqiyatli amalga oshirildi. Tez orada javob olasiz."
        else:
            msg += f"Qisman muvaffaqiyatli: {success_count}/2 ta xabar yuborildi."
            if failed_targets:
                msg += f"\n\n⚠️ Quyidagilarga xabar yuborib bo'lmadi: {', '.join(failed_targets)}"
                msg += f"\n\nIltimos, to'g'ridan-to'g'ri @admin yoki admin bilan bog'laning."
        
        await callback.message.answer(msg, parse_mode="Markdown")
    else:
        await callback.message.answer(
            f"❌ Xabar yuborishda xatolik yuz berdi.\n\n"
            f"Sabab: Sizning akkauntingiz bu foydalanuvchilar bilan hech qachon muloqot qilmagan.\n\n"
            f"✅ **Yechim:** Iltimos, avval qo'lda admin bilan bog'laning:\n"
            f"👤 Admin ID: `{admin_target}`\n"
            f"👨‍💻 Dasturchi ID: `{dev_target}`\n\n"
            f"Yoki admin username'ini so'rang va shu yerga yozing.",
            parse_mode="Markdown"
        )
    
    await callback.answer()

async def main():
    await init_db()
    print("Bot ishga tushdssi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
