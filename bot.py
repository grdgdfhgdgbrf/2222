import asyncio
import logging
import random
import sqlite3
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Tuple
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc"
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"
ADMIN_ID = 5356400377

DEFAULT_EXCHANGE_RATE = 10
DAILY_BONUS_STARS = 10
DAILY_BONUS_TCOIN = 5
REFERRAL_BONUS = 5
MAX_TASKS_PER_DAY = 10
MIN_BET = 10
MAX_BET = 50000

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_current_task: Dict[int, Dict] = {}
api_cache: Dict[str, Tuple] = {}

# ================= FSM =================
class AdminStates(StatesGroup):
    waiting_broadcast = State()

class UserStates(StatesGroup):
    waiting_promo = State()
    waiting_transfer_id = State()
    waiting_transfer_amount = State()

# ================= БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        stars_balance INTEGER DEFAULT 0,
        tcoin_balance INTEGER DEFAULT 0,
        referral_code TEXT,
        referred_by INTEGER,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        last_daily_bonus TEXT,
        tasks_completed_today INTEGER DEFAULT 0,
        last_task_date TEXT,
        total_tasks_completed INTEGER DEFAULT 0,
        total_referrals INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        is_verified INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        stars_reward INTEGER DEFAULT 0,
        tcoin_reward INTEGER DEFAULT 0,
        max_uses INTEGER DEFAULT 100,
        current_uses INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS used_promo (
        user_id INTEGER, promo_code TEXT,
        PRIMARY KEY (user_id, promo_code)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, type TEXT,
        amount INTEGER, description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, req_type TEXT,
        amount INTEGER, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    for k, v in [("exchange_rate", str(DEFAULT_EXCHANGE_RATE)),
                 ("bot_active", "1"), ("maintenance_mode", "0"),
                 ("min_bet", str(MIN_BET)), ("max_bet", str(MAX_BET))]:
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()

def db():
    return sqlite3.connect("bot_database.db")

def get_user(uid: int):
    c = db(); r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone(); c.close(); return r

def create_user(uid, uname, fname, rcode, ref_by=None, verified=1):
    c = db()
    c.execute("INSERT INTO users (user_id,username,first_name,referral_code,referred_by,is_admin,is_verified) VALUES (?,?,?,?,?,?,?)",
              (uid, uname, fname, rcode, ref_by, 1 if uid == ADMIN_ID else 0, verified))
    c.commit(); c.close()

def update_balance(uid, stars=0, tcoin=0, desc=""):
    c = db()
    c.execute("UPDATE users SET stars_balance=stars_balance+?, tcoin_balance=tcoin_balance+? WHERE user_id=?", (stars, tcoin, uid))
    if stars != 0:
        c.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                  (uid, "stars", stars, desc or ("+" if stars > 0 else "") + " Звезды"))
    if tcoin != 0:
        c.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                  (uid, "tcoin", tcoin, desc or ("+" if tcoin > 0 else "") + " T Coin"))
    c.commit(); c.close()

def get_setting(key):
    c = db(); r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone(); c.close()
    return r[0] if r else None

def set_setting(key, val):
    c = db(); c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(val))); c.commit(); c.close()

def get_transactions(uid, limit=10):
    c = db()
    r = c.execute("SELECT type,amount,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    c.close(); return r

def can_daily(uid):
    u = get_user(uid)
    if not u or not u[9]: return True
    return (datetime.now() - datetime.strptime(u[9], "%Y-%m-%d")).days >= 1

def set_daily(uid):
    c = db(); c.execute("UPDATE users SET last_daily_bonus=? WHERE user_id=?", (datetime.now().strftime("%Y-%m-%d"), uid)); c.commit(); c.close()

def inc_tasks(uid):
    c = db(); t = datetime.now().strftime("%Y-%m-%d")
    c.execute("UPDATE users SET tasks_completed_today=tasks_completed_today+1, last_task_date=?, total_tasks_completed=total_tasks_completed+1 WHERE user_id=?", (t, uid))
    c.commit(); c.close()

def check_daily_reset(uid):
    u = get_user(uid); t = datetime.now().strftime("%Y-%m-%d")
    if u and u[11] and u[11] != t:
        c = db(); c.execute("UPDATE users SET tasks_completed_today=0 WHERE user_id=?", (uid,)); c.commit(); c.close()

def get_stats():
    c = db(); s = {}
    s['users'] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s['active'] = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=0").fetchone()[0]
    r = c.execute("SELECT COALESCE(SUM(stars_balance),0), COALESCE(SUM(tcoin_balance),0) FROM users").fetchone()
    s['stars'], s['tcoin'] = r
    t = datetime.now().strftime("%Y-%m-%d")
    s['new_today'] = c.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['tx_today'] = c.execute("SELECT COUNT(*) FROM transactions WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['pending'] = c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    c.close(); return s

init_db()

# ================= PIARFLOW =================
async def pf_get_task(uid, cid):
    ck = f"t_{uid}"
    if ck in api_cache and datetime.now().timestamp() - api_cache[ck][1] < 300:
        return api_cache[ck][0]
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors", json={"user_id": uid, "chat_id": cid, "max_sponsors": 1}, headers=h) as r:
                d = await r.json(); api_cache[ck] = (d, datetime.now().timestamp()); return d
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def pf_check(uid, link):
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json={"user_id": uid, "links": [link]}, headers=h) as r:
                return await r.json()
        except:
            return {"status": "error"}

# ================= УТИЛИТЫ =================
def fmt(n):
    if n >= 1000000: return f"{n/1000000:.1f}M"
    if n >= 1000: return f"{n/1000:.1f}K"
    return str(n)

def back_btn():
    return InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")

def back_profile():
    return InlineKeyboardButton(text="🔙 Профиль", callback_data="profile")

def verify_check(uid):
    u = get_user(uid)
    return u and u[15] == 1

# ================= СТАРТ =================
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    u = get_user(msg.from_user.id)
    if u and u[8]:
        return await msg.answer("❌ Вы заблокированы.")
    maint = get_setting("maintenance_mode")
    if maint == "1" and msg.from_user.id != ADMIN_ID:
        return await msg.answer("🔧 Технические работы. Попробуйте позже.")

    if not u:
        args = msg.text.split()
        ref_by = None
        verified = 1
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_by = int(args[1].replace("ref_", ""))
                if ref_by == msg.from_user.id: ref_by = None
                else: verified = 0
            except ValueError: pass
        create_user(msg.from_user.id, msg.from_user.username or "User",
                     msg.from_user.first_name or "User", f"ref_{msg.from_user.id}", ref_by, verified)
        if ref_by and verified:
            update_balance(ref_by, stars=REFERRAL_BONUS, desc="Реферальный бонус")
            c = db(); c.execute("UPDATE users SET total_referrals=total_referrals+1 WHERE user_id=?", (ref_by,)); c.commit(); c.close()
            try: await bot.send_message(ref_by, f"🎉 Друг зарегистрировался! +{REFERRAL_BONUS} ⭐️")
            except: pass

    u = get_user(msg.from_user.id)
    if not u[15]:
        return await show_verify(msg)
    await show_main_menu(msg)

async def show_verify(msg: Message):
    text = ("⚠️ <b>Подтверждение регистрации</b>\n\n"
            "Вы перешли по реферальной ссылке.\n"
            "Для доступа к боту подпишитесь на спонсора:")
    td = await pf_get_task(msg.from_user.id, msg.from_user.id)
    b = InlineKeyboardBuilder()
    if td.get("status") == "ok" and td.get("sponsors"):
        sp = td["sponsors"][0]
        user_current_task[msg.from_user.id] = {"link": sp["link"], "price": sp.get("price", 5), "verify": True}
        b.row(InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"]))
        b.row(InlineKeyboardButton(text="✅ Проверить", callback_data="task_check"))
    else:
        c = db(); c.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (msg.from_user.id,)); c.commit(); c.close()
        return await show_main_menu(msg)
    await msg.answer(text, parse_mode="HTML", reply_markup=b.as_markup())

async def show_main_menu(msg: Message):
    u = get_user(msg.from_user.id)
    bi = await bot.get_me()
    rl = f"https://t.me/{bi.username}?start=ref_{u[5]}"
    text = (f"👋 <b>Привет, {msg.from_user.first_name}!</b>\n\n"
            f"💰 <b>Баланс:</b>\n"
            f"⭐️ Звезды: <code>{fmt(u[3])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u[4])}</code>\n\n"
            f"🔗 Реферальная ссылка:\n<code>{rl}</code>\n"
            f"<i>+{REFERRAL_BONUS} ⭐️ за друга</i>")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📋 Задания", callback_data="task_get"))
    b.row(InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu"))
    b.row(InlineKeyboardButton(text="💰 Обмен", callback_data="exchange"))
    b.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    if u[7]: b.row(InlineKeyboardButton(text="👑 Админ", callback_data="admin"))
    await msg.answer(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ПРОФИЛЬ =================
@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    text = (f"👤 <b>Профиль</b>\n\n"
            f"🆔 ID: <code>{u[0]}</code>\n"
            f"📝 @{u[1] or 'N/A'}\n"
            f"⭐️ Звезды: <code>{fmt(u[3])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u[4])}</code>\n"
            f"✅ Заданий: {u[12]}\n"
            f"👥 Друзей: {u[13]}\n"
            f"📅 С: {u[14][:10]}")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🎁 Бонус", callback_data="daily"),
          InlineKeyboardButton(text="🎟 Промокод", callback_data="promo"))
    b.row(InlineKeyboardButton(text="📊 История", callback_data="history"),
          InlineKeyboardButton(text="💸 Перевод", callback_data="transfer"))
    b.row(InlineKeyboardButton(text="⭐ Пополнить", callback_data="deposit"),
          InlineKeyboardButton(text="💳 Вывести", callback_data="withdraw"))
    b.row(back_btn())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ЗАДАНИЯ =================
@dp.callback_query(F.data == "task_get")
async def cb_task_get(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    check_daily_reset(cb.from_user.id)
    u = get_user(cb.from_user.id)
    if u[10] >= MAX_TASKS_PER_DAY:
        b = InlineKeyboardBuilder(); b.row(back_btn())
        return await cb.message.edit_text(f"⏰ Лимит {MAX_TASKS_PER_DAY} заданий на сегодня исчерпан.", parse_mode="HTML", reply_markup=b.as_markup())
    td = await pf_get_task(cb.from_user.id, cb.from_user.id)
    if td.get("status") == "ok" and td.get("sponsors"):
        sp = td["sponsors"][0]
        user_current_task[cb.from_user.id] = {"link": sp["link"], "price": sp.get("price", 5), "verify": False}
        text = f"📋 <b>Задание:</b>\nПодпишись и получи <b>{sp.get('price', 5)} ⭐️</b>"
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"]))
        b.row(InlineKeyboardButton(text="✅ Проверить", callback_data="task_check"))
        b.row(back_btn())
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
    else:
        b = InlineKeyboardBuilder(); b.row(back_btn())
        await cb.message.edit_text("🎉 Заданий пока нет.", parse_mode="HTML", reply_markup=b.as_markup())

@dp.callback_query(F.data == "task_check")
async def cb_task_check(cb: CallbackQuery):
    await cb.answer()
    task = user_current_task.get(cb.from_user.id)
    if not task:
        return await cb.answer("❌ Сначала возьмите задание.", show_alert=True)
    cd = await pf_check(cb.from_user.id, task["link"])
    if cd.get("status") == "ok":
        done = [s for s in cd.get("sponsors", []) if s.get("status") == "subscribed"]
        if done:
            reward = task["price"]
            update_balance(cb.from_user.id, stars=reward, desc="Задание")
            if task.get("verify"):
                c = db(); c.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (cb.from_user.id,)); c.commit(); c.close()
                u = get_user(cb.from_user.id)
                if u[6]:
                    update_balance(u[6], stars=REFERRAL_BONUS, desc="Реферал")
                    try: await bot.send_message(u[6], f"🎉 Реферал подтверждён! +{REFERRAL_BONUS} ⭐️")
                    except: pass
                user_current_task.pop(cb.from_user.id, None)
                await cb.message.edit_text(f"✅ <b>Верификация пройдена!</b>\n+{reward} ⭐️\nДобро пожаловать!", parse_mode="HTML",
                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn()]]))
                return
            inc_tasks(cb.from_user.id)
            user_current_task.pop(cb.from_user.id, None)
            u = get_user(cb.from_user.id)
            text = f"✅ <b>Выполнено!</b> +{reward} ⭐️\n📊 Сегодня: {u[10]}/{MAX_TASKS_PER_DAY}"
            b = InlineKeyboardBuilder()
            if u[10] < MAX_TASKS_PER_DAY:
                b.row(InlineKeyboardButton(text="📋 Следующее", callback_data="task_get"))
            b.row(back_btn())
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
        else:
            await cb.answer("⏳ Не подписаны. Подпишитесь и нажмите снова.", show_alert=True)
    else:
        await cb.answer("❌ Ошибка проверки.", show_alert=True)

# ================= ОБМЕН =================
@dp.callback_query(F.data == "exchange")
async def cb_exchange(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    rate = int(get_setting("exchange_rate"))
    avail = u[3] // rate
    text = (f"🔄 <b>Обмен</b>\n\n💱 Курс: <code>{rate} ⭐️ = 1 🪙</code>\n"
            f"⭐️ Баланс: <code>{fmt(u[3])}</code>\n🪙 Доступно: <code>{fmt(avail)}</code>")
    b = InlineKeyboardBuilder()
    if avail > 0:
        b.row(InlineKeyboardButton(text=f"🔄 Обменять всё ({avail} 🪙)", callback_data=f"do_ex_{avail}"))
    b.row(back_btn())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("do_ex_"))
async def cb_do_exchange(cb: CallbackQuery):
    await cb.answer()
    amt = int(cb.data.split("_")[-1])
    u = get_user(cb.from_user.id)
    rate = int(get_setting("exchange_rate"))
    cost = amt * rate
    if u[3] >= cost:
        update_balance(cb.from_user.id, stars=-cost, tcoin=amt, desc=f"Обмен {cost}⭐→{amt}🪙")
        b = InlineKeyboardBuilder(); b.row(back_btn())
        await cb.message.edit_text(f"✅ Обмен: -{cost} ⭐️ → +{amt} 🪙", parse_mode="HTML", reply_markup=b.as_markup())
    else:
        await cb.answer("❌ Недостаточно звёзд!", show_alert=True)

# ================= ИГРЫ МЕНЮ =================
@dp.callback_query(F.data == "games_menu")
async def cb_games(cb: CallbackQuery):
    await cb.answer()
    text = ("🎮 <b>Игровой зал</b>\n\n"
            "🎰 <code>/сл [сумма]</code> — Слоты (×10)\n"
            "🎲 <code>/кости [режим] [сумма] [параметр]</code>\n"
            "🎯 <code>/дротик [сумма]</code> / <code>/дротик промах [сумма]</code>\n"
            "🏀 <code>/баскет [сумма]</code> / <code>/баскет промах [сумма]</code>\n"
            "⚽ <code>/футбол [сумма]</code>\n"
            "🎡 <code>/рул [тип] [сумма] [параметр]</code>\n"
            "🪙 <code>/мон [сумма] [о/р]</code>\n"
            "📊 <code>/больше [сумма]</code> / <code>/меньше [сумма]</code>\n"
            "💣 <code>/мины [сумма] [1-5]</code>\n"
            "🚀 <code>/краш [сумма] [множитель]</code>\n\n"
            f"💵 Ставки: {get_setting('min_bet')}–{get_setting('max_bet')} 🪙")
    b = InlineKeyboardBuilder(); b.row(back_btn())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ИГРЫ: ОБЩИЕ ФУНКЦИИ =================
def parse_bet(args, idx=1):
    """Извлекает ставку из аргументов. Возвращает (bet, error_msg)"""
    if len(args) <= idx:
        return None, "⚠️ Укажите ставку!"
    try:
        bet = int(args[idx])
    except ValueError:
        return None, "❌ Ставка — число!"
    mn = int(get_setting("min_bet") or MIN_BET)
    mx = int(get_setting("max_bet") or MAX_BET)
    if bet < mn: return None, f"❌ Мин. ставка: {mn} 🪙"
    if bet > mx: return None, f"❌ Макс. ставка: {mx} 🪙"
    return bet, None

def check_balance(uid, bet):
    u = get_user(uid)
    if not u: return False
    if u[4] < bet: return False
    return True

async def send_result(msg, emoji_text, bet, win, multiplier, is_dice=True, dice_emoji="🎲"):
    if win:
        payout = int(bet * multiplier)
        update_balance(msg.from_user.id, tcoin=payout, desc=f"Выигрыш {emoji_text}")
        await msg.answer(f"{dice_emoji} <b>ПОБЕДА!</b>\n\n💰 Ставка: {bet} 🪙\n📈 ×{multiplier}\n✅ Выигрыш: <b>{payout} 🪙</b>", parse_mode="HTML")
    else:
        await msg.answer(f"{dice_emoji} <b>Проигрыш.</b>\n\n😔 Потеряно: {bet} 🪙", parse_mode="HTML")

# ================= 1. СЛОТЫ =================
@dp.message(Command("сл", "слоты", "slot"))
async def game_slots(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Сначала пройдите верификацию.")
    bet, err = parse_bet(msg.text.split())
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка слоты")
    dm = await msg.answer_dice(emoji="🎰")
    val = dm.dice.value
    if val == 1:
        await send_result(msg, "Слоты ДЖЕКПОТ", bet, True, 10, dice_emoji="🎰")
    elif val <= 10:
        await send_result(msg, "Слоты", bet, True, 2, dice_emoji="🎰")
    else:
        await send_result(msg, "Слоты", bet, False, 0, dice_emoji="🎰")

# ================= 2. КОСТИ =================
@dp.message(Command("кости"))
async def game_dice(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Сначала верификация.")
    args = msg.text.split()
    if len(args) < 3:
        return await msg.answer("🎲 <b>Режимы:</b>\n<code>/кости число [сумма] [1-6]</code>\n<code>/кости чет [сумма] [чет/нечет]</code>\n<code>/кости больше [сумма] [б/м]</code>", parse_mode="HTML")
    mode = args[1].lower()
    if mode == "число":
        if len(args) < 4: return await msg.answer("⚠️ Укажите число: /кости число 100 3")
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err)
        try: target = int(args[3])
        except: return await msg.answer("❌ Число от 1 до 6!")
        if target < 1 or target > 6: return await msg.answer("❌ Число от 1 до 6!")
        if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка кости-число")
        dm = await msg.answer_dice(emoji="🎲")
        win = dm.dice.value == target
        await send_result(msg, f"Кости число {target}", bet, win, 6, dice_emoji="🎲")
    elif mode == "чет":
        if len(args) < 4: return await msg.answer("⚠️ /кости чет 100 чет")
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err)
        choice = args[3].lower()
        if choice in ["чет", "ч"]: want_even = True
        elif choice in ["нечет", "нч", "н"]: want_even = False
        else: return await msg.answer("❌ Укажите: чет/нечет")
        if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка кости-чет")
        dm = await msg.answer_dice(emoji="🎲")
        is_even = dm.dice.value % 2 == 0
        win = is_even == want_even
        await send_result(msg, f"Кости {'чет' if want_even else 'нечет'}", bet, win, 2, dice_emoji="🎲")
    elif mode == "больше":
        if len(args) < 4: return await msg.answer("⚠️ /кости больше 100 б")
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err)
        choice = args[3].lower()
        if choice in ["больше", "б"]: want_high = True
        elif choice in ["меньше", "м"]: want_high = False
        else: return await msg.answer("❌ Укажите: б/м")
        if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка кости-больше")
        dm = await msg.answer_dice(emoji="🎲")
        is_high = dm.dice.value >= 4
        win = is_high == want_high
        await send_result(msg, f"Кости {'больше' if want_high else 'меньше'}", bet, win, 2, dice_emoji="🎲")
    else:
        await msg.answer("❌ Режимы: число, чет, больше")

# ================= 3. ДРОТИК =================
@dp.message(Command("дротик"))
async def game_darts(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    want_miss = False
    bet_idx = 1
    if len(args) > 1 and args[1].lower() == "промах":
        want_miss = True; bet_idx = 2
    bet, err = parse_bet(args, bet_idx)
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка дротик")
    dm = await msg.answer_dice(emoji="🎯")
    hit = dm.dice.value >= 4
    if want_miss: win = not hit
    else: win = hit
    await send_result(msg, f"Дротик {'промах' if want_miss else 'попадание'}", bet, win, 1.9, dice_emoji="🎯")

# ================= 4. БАСКЕТБОЛ =================
@dp.message(Command("баскет"))
async def game_basket(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    want_miss = False; bet_idx = 1
    if len(args) > 1 and args[1].lower() == "промах":
        want_miss = True; bet_idx = 2
    bet, err = parse_bet(args, bet_idx)
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка баскет")
    dm = await msg.answer_dice(emoji="🏀")
    hit = dm.dice.value == 5
    if want_miss: win = not hit
    else: win = hit
    await send_result(msg, f"Баскет {'промах' if want_miss else 'попадание'}", bet, win, 1.9, dice_emoji="🏀")

# ================= 5. ФУТБОЛ =================
@dp.message(Command("футбол"))
async def game_foot(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    bet, err = parse_bet(msg.text.split())
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка футбол")
    dm = await msg.answer_dice(emoji="⚽")
    win = dm.dice.value >= 4
    await send_result(msg, "Футбол", bet, win, 2, dice_emoji="⚽")

# ================= 6. РУЛЕТКА =================
@dp.message(Command("рул"))
async def game_roulette(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    if len(args) < 4:
        return await msg.answer("🎡 <b>Рулетка:</b>\n<code>/рул цвет 100 к</code> (к/ч/з)\n<code>/рул чет 100 чет</code>\n<code>/рул половина 100 верх</code>\n<code>/рул число 100 17</code>\n<code>/рул дюжина 100 1</code>", parse_mode="HTML")
    mode = args[1].lower()
    bet, err = parse_bet(args, 2)
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Рулетка {mode}")
    num = random.randint(0, 36)
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    win = False; mult = 0
    param = args[3].lower()

    if mode == "цвет":
        if param in ["к", "красное"]:
            win = num in reds; mult = 2
        elif param in ["ч", "черное", "чёрное"]:
            win = num != 0 and num not in reds; mult = 2
        elif param in ["з", "зеро", "зеленое"]:
            win = num == 0; mult = 14
        else: return await msg.answer("❌ к/ч/з")
    elif mode == "чет":
        if param in ["чет", "ч"]:
            win = num != 0 and num % 2 == 0; mult = 2
        elif param in ["нечет", "нч", "н"]:
            win = num != 0 and num % 2 != 0; mult = 2
        else: return await msg.answer("❌ чет/нечет")
    elif mode == "половина":
        if param in ["низ", "н"]:
            win = 1 <= num <= 18; mult = 2
        elif param in ["верх", "в"]:
            win = 19 <= num <= 36; mult = 2
        else: return await msg.answer("❌ верх/низ")
    elif mode == "число":
        try: target = int(param)
        except: return await msg.answer("❌ Число 0-36!")
        if target < 0 or target > 36: return await msg.answer("❌ 0-36!")
        win = num == target; mult = 36
    elif mode == "дюжина":
        try: d = int(param)
        except: return await msg.answer("❌ Дюжина 1/2/3!")
        if d == 1: win = 1 <= num <= 12; mult = 3
        elif d == 2: win = 13 <= num <= 24; mult = 3
        elif d == 3: win = 25 <= num <= 36; mult = 3
        else: return await msg.answer("❌ 1/2/3!")
    else:
        return await msg.answer("❌ Режимы: цвет, чет, половина, число, дюжина")

    color = "🔴" if num in reds else ("🟢" if num == 0 else "⚫")
    if win:
        payout = int(bet * mult)
        update_balance(msg.from_user.id, tcoin=payout, desc=f"Рулетка выигрыш {num}")
        await msg.answer(f"🎡 <b>Рулетка: {color} {num}</b>\n\n🎉 <b>ПОБЕДА!</b> ×{mult}\n✅ +{payout} 🪙", parse_mode="HTML")
    else:
        await msg.answer(f"🎡 <b>Рулетка: {color} {num}</b>\n\n😔 Проигрыш. -{bet} 🪙", parse_mode="HTML")

# ================= 7. МОНЕТКА =================
@dp.message(Command("мон"))
async def game_coin(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("⚠️ <code>/мон 100 о</code> (о/р)", parse_mode="HTML")
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err)
    choice = args[2].lower()
    if choice not in ["о", "р", "орел", "орёл", "решка"]:
        return await msg.answer("❌ Укажите: о (орёл) или р (решка)")
    want_heads = choice in ["о", "орел", "орёл"]
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка монетка")
    result = random.choice(["орёл", "решка"])
    win = (result == "орёл") == want_heads
    emoji = "🦅" if result == "орёл" else "🪙"
    if win:
        payout = bet * 2
        update_balance(msg.from_user.id, tcoin=payout, desc="Монетка выигрыш")
        await msg.answer(f"{emoji} <b>{result.capitalize()}!</b>\n\n🎉 ПОБЕДА! +{payout} 🪙", parse_mode="HTML")
    else:
        await msg.answer(f"{emoji} <b>{result.capitalize()}!</b>\n\n😔 Проигрыш. -{bet} 🪙", parse_mode="HTML")

# ================= 8. БОЛЬШЕ / МЕНЬШЕ =================
@dp.message(Command("больше", "меньше"))
async def game_hilo(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    cmd = args[0].replace("/", "").lower()
    bet, err = parse_bet(args)
    if err: return await msg.answer(err)
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка {cmd}")
    num = random.randint(1, 100)
    if num == 50:
        update_balance(msg.from_user.id, tcoin=bet, desc="High/Low ничья")
        await msg.answer(f"📊 <b>Число: {num}</b>\n\n🤝 Ничья! Ставка возвращена.", parse_mode="HTML")
        return
    if cmd == "больше":
        win = num >= 51
    else:
        win = num <= 49
    if win:
        payout = int(bet * 1.9)
        update_balance(msg.from_user.id, tcoin=payout, desc=f"High/Low выигрыш {num}")
        await msg.answer(f"📊 <b>Число: {num}</b>\n\n🎉 ПОБЕДА! +{payout} 🪙", parse_mode="HTML")
    else:
        await msg.answer(f"📊 <b>Число: {num}</b>\n\n😔 Проигрыш. -{bet} 🪙", parse_mode="HTML")

# ================= 9. МИНЫ =================
@dp.message(Command("мины"))
async def game_mines(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("⚠️ <code>/мины 100 3</code> (мины 1-5)", parse_mode="HTML")
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err)
    try: mines = int(args[2])
    except: return await msg.answer("❌ Мины: 1-5!")
    if mines < 1 or mines > 5: return await msg.answer("❌ Мины: 1-5!")
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка мины {mines}")

    mult = 1.0
    safe_tiles = 0
    total_tiles = 6
    tiles = list(range(1, total_tiles + 1))
    mine_positions = random.sample(tiles, mines)
    results = []

    for i in range(total_tiles - mines):
        dm = await msg.answer_dice(emoji="🎲")
        val = dm.dice.value
        if val in mine_positions and val not in results:
            results.append(val)
            await msg.answer(f"💣 <b>МИНА!</b> (кубик {val})\n\n😔 Потеряно: {bet} 🪙\nОткрыто: {safe_tiles} плиток", parse_mode="HTML")
            return
        safe_tiles += 1
        results.append(val)
        mult += mines * 0.4
        await asyncio.sleep(0.5)

    payout = int(bet * mult)
    update_balance(msg.from_user.id, tcoin=payout, desc=f"Мины выигрыш ×{mult:.1f}")
    await msg.answer(f"💎 <b>Все мины обойдены!</b>\n\n🎉 ПОБЕДА! ×{mult:.1f}\n✅ +{payout} 🪙", parse_mode="HTML")

# ================= 10. КРАШ =================
@dp.message(Command("краш"))
async def game_crash(msg: Message):
    u = get_user(msg.from_user.id)
    if not u or u[8]: return
    if not verify_check(msg.from_user.id): return await msg.answer("⚠️ Верификация.")
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("⚠️ <code>/краш 100 2.0</code> (авто-вывод)", parse_mode="HTML")
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err)
    try: cashout = float(args[2])
    except: return await msg.answer("❌ Множитель — число (напр. 1.5, 2.0, 5.0)!")
    if cashout < 1.1 or cashout > 100:
        return await msg.answer("❌ Множитель от 1.1 до 100!")
    if not check_balance(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!")
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка краш ×{cashout}")

    crash_point = max(1.0, round(100 / random.randint(1, 100), 2))

    steps = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]
    anim = "🚀 <b>Краш:</b>\n"
    for s in steps:
        if s > crash_point: break
        anim += f"  📈 ×{s}...\n"
        await asyncio.sleep(0.3)

    if crash_point >= cashout:
        payout = int(bet * cashout)
        update_balance(msg.from_user.id, tcoin=payout, desc=f"Краш выигрыш ×{cashout}")
        anim += f"\n💥 Краш на ×{crash_point}\n\n🎉 <b>Успели вывести на ×{cashout}!</b>\n✅ +{payout} 🪙"
    else:
        anim += f"\n💥 <b>КРАШ на ×{crash_point}!</b>\n\n😔 Не успели. -{bet} 🪙"
    await msg.answer(anim, parse_mode="HTML")

# ================= ЕЖЕДНЕВНЫЙ БОНУС =================
@dp.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    await cb.answer()
    if can_daily(cb.from_user.id):
        update_balance(cb.from_user.id, stars=DAILY_BONUS_STARS, tcoin=DAILY_BONUS_TCOIN, desc="Ежедневный бонус")
        set_daily(cb.from_user.id)
        text = f"🎁 <b>Бонус получен!</b>\n⭐️ +{DAILY_BONUS_STARS}\n🪙 +{DAILY_BONUS_TCOIN}"
    else:
        u = get_user(cb.from_user.id)
        lb = datetime.strptime(u[9], "%Y-%m-%d")
        nb = lb + timedelta(days=1)
        tl = nb - datetime.now()
        text = f"⏰ Бонус через {tl.seconds//3600}ч {(tl.seconds%3600)//60}мин"
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ПРОМОКОД =================
@dp.callback_query(F.data == "promo")
async def cb_promo(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    b = InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="profile"))
    await cb.message.edit_text("🎟 Отправьте промокод сообщением:", parse_mode="HTML", reply_markup=b.as_markup())
    await state.set_state(UserStates.waiting_promo)

@dp.message(UserStates.waiting_promo)
async def process_promo(msg: Message, state: FSMContext):
    await state.clear()
    code = msg.text.strip().upper()
    c = db()
    p = c.execute("SELECT * FROM promo_codes WHERE code=? AND is_active=1", (code,)).fetchone()
    if not p:
        c.close(); return await msg.answer("❌ Промокод не найден.")
    if p[4] >= p[3]:
        c.close(); return await msg.answer("❌ Промокод исчерпан.")
    used = c.execute("SELECT 1 FROM used_promo WHERE user_id=? AND promo_code=?", (msg.from_user.id, code)).fetchone()
    if used:
        c.close(); return await msg.answer("❌ Уже использован.")
    c.execute("UPDATE promo_codes SET current_uses=current_uses+1 WHERE code=?", (code,))
    c.execute("INSERT INTO used_promo (user_id,promo_code) VALUES (?,?)", (msg.from_user.id, code))
    c.commit(); c.close()
    update_balance(msg.from_user.id, stars=p[1], tcoin=p[2], desc=f"Промокод {code}")
    text = f"✅ <b>Промокод активирован!</b>\n"
    if p[1]: text += f"⭐️ +{p[1]}\n"
    if p[2]: text += f"🪙 +{p[2]}\n"
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await msg.answer(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ИСТОРИЯ =================
@dp.callback_query(F.data == "history")
async def cb_history(cb: CallbackQuery):
    await cb.answer()
    txs = get_transactions(cb.from_user.id)
    if not txs:
        text = "📊 История пуста."
    else:
        text = "📊 <b>Последние операции:</b>\n\n"
        for t in txs:
            e = "🟢" if t[1] > 0 else "🔴"
            cur = "⭐️" if t[0] == "stars" else "🪙"
            s = "+" if t[1] > 0 else ""
            text += f"{e} {s}{t[1]} {cur} — <i>{t[2]}</i>\n"
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

# ================= ПЕРЕВОД =================
@dp.callback_query(F.data == "transfer")
async def cb_transfer(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await cb.message.edit_text("💸 <b>Перевод T Coin</b>\n\nОтправьте: <code>USER_ID СУММА</code>\nПример: <code>123456789 100</code>", parse_mode="HTML", reply_markup=b.as_markup())
    await state.set_state(UserStates.waiting_transfer_id)

@dp.message(UserStates.waiting_transfer_id)
async def process_transfer(msg: Message, state: FSMContext):
    await state.clear()
    args = msg.text.split()
    if len(args) < 2:
        return await msg.answer("❌ Формат: ID СУММА")
    try:
        target = int(args[0]); amount = int(args[1])
    except ValueError:
        return await msg.answer("❌ Числа!")
    if target == msg.from_user.id:
        return await msg.answer("❌ Себе нельзя!")
    if amount <= 0:
        return await msg.answer("❌ Сумма > 0!")
    u = get_user(msg.from_user.id)
    if not u or u[4] < amount:
        return await msg.answer("❌ Недостаточно T Coin!")
    t = get_user(target)
    if not t:
        return await msg.answer("❌ Пользователь не найден!")
    update_balance(msg.from_user.id, tcoin=-amount, desc=f"Перевод → {target}")
    update_balance(target, tcoin=amount, desc=f"Перевод ← {msg.from_user.id}")
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await msg.answer(f"✅ Переведено {amount} 🪙 пользователю {target}", parse_mode="HTML", reply_markup=b.as_markup())
    try:
        await bot.send_message(target, f"💸 Вам перевели {amount} 🪙 от {msg.from_user.id}!")
    except: pass

# ================= ПОПОЛНЕНИЕ / ВЫВОД =================
@dp.callback_query(F.data == "deposit")
async def cb_deposit(cb: CallbackQuery):
    await cb.answer()
    text = ("⭐ <b>Пополнение звёзд</b>\n\n"
            "Отправьте заявку командой:\n<code>/пополнить [сумма]</code>\n\n"
            "Администратор обработает заявку.")
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    text = (f"💳 <b>Вывод звёзд</b>\n\n"
            f"⭐️ Баланс: <code>{u[3]}</code>\n\n"
            f"Отправьте заявку:\n<code>/вывести [сумма]</code>")
    b = InlineKeyboardBuilder(); b.row(back_profile())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

@dp.message(Command("пополнить"))
async def cmd_deposit(msg: Message):
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("⚠️ <code>/пополнить 100</code>", parse_mode="HTML")
    try: amount = int(args[1])
    except: return await msg.answer("❌ Число!")
    if amount <= 0: return await msg.answer("❌ Сумма > 0!")
    c = db()
    c.execute("INSERT INTO requests (user_id,req_type,amount) VALUES (?,?,?)", (msg.from_user.id, "deposit", amount))
    c.commit(); c.close()
    await msg.answer(f"✅ Заявка на пополнение {amount} ⭐️ создана.\nОжидайте подтверждения админа.")
    try:
        await bot.send_message(ADMIN_ID, f"📥 Новая заявка на пополнение!\n👤 {msg.from_user.id}\n💰 {amount} ⭐️\n<code>/approve {c.lastrowid}</code>", parse_mode="HTML")
    except: pass

@dp.message(Command("вывести"))
async def cmd_withdraw(msg: Message):
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("⚠️ <code>/вывести 100</code>", parse_mode="HTML")
    try: amount = int(args[1])
    except: return await msg.answer("❌ Число!")
    if amount <= 0: return await msg.answer("❌ Сумма > 0!")
    u = get_user(msg.from_user.id)
    if not u or u[3] < amount: return await msg.answer("❌ Недостаточно звёзд!")
    update_balance(msg.from_user.id, stars=-amount, desc="Заявка на вывод (заморозка)")
    c = db()
    c.execute("INSERT INTO requests (user_id,req_type,amount) VALUES (?,?,?)", (msg.from_user.id, "withdraw", amount))
    c.commit(); c.close()
    await msg.answer(f"✅ Заявка на вывод {amount} ⭐️ создана.\nСредства заморожены.")
    try:
        await bot.send_message(ADMIN_ID, f"📤 Заявка на вывод!\n👤 {msg.from_user.id}\n💰 {amount} ⭐️\n<code>/approve {c.lastrowid}</code> / <code>/reject {c.lastrowid}</code>", parse_mode="HTML")
    except: pass

# ================= АДМИН =================
@dp.callback_query(F.data == "admin")
async def cb_admin(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    if not u or not u[7]: return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    s = get_stats()
    rate = get_setting("exchange_rate")
    maint = get_setting("maintenance_mode")
    text = (f"👑 <b>Админ-панель</b>\n\n"
            f"👥 Юзеров: {s['users']} | Активных: {s['active']}\n"
            f"🆕 Сегодня: {s['new_today']} | TX: {s['tx_today']}\n"
            f"⭐️ {fmt(s['stars'])} | 🪙 {fmt(s['tcoin'])}\n"
            f"📋 Заявок: {s['pending']}\n\n"
            f"💱 Курс: {rate} | 🔧 Обслуж: {'Вкл' if maint=='1' else 'Выкл'}\n\n"
            f"<b>Команды:</b>\n"
            f"<code>/addstars ID КОЛ</code>\n"
            f"<code>/addtcoin ID КОЛ</code>\n"
            f"<code>/reset ID</code> — сброс баланса\n"
            f"<code>/ban ID</code> / <code>/unban ID</code>\n"
            f"<code>/makeadmin ID 1/0</code>\n"
            f"<code>/setrate ЧИСЛО</code>\n"
            f"<code>/setminbet ЧИСЛО</code>\n"
            f"<code>/setmaxbet ЧИСЛО</code>\n"
            f"<code>/maintenance</code> — обсл.\n"
            f"<code>/createpromo КОД ЗВ TCOIN ЛИМИТ</code>\n"
            f"<code>/broadcast</code> — рассылка\n"
            f"<code>/approve ID</code> / <code>/reject ID</code>\n"
            f"<code>/requests</code> — все заявки\n"
            f"<code>/userstats ID</code>")
    b = InlineKeyboardBuilder(); b.row(back_btn())
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())

def is_admin(uid):
    u = get_user(uid); return u and u[7]

@dp.message(Command("addstars"))
async def a_addstars(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("/addstars ID КОЛ")
    try: uid, val = int(args[1]), int(args[2])
    except: return await msg.answer("❌ Числа!")
    update_balance(uid, stars=val, desc="Админ начисление")
    await msg.answer(f"✅ +{val} ⭐️ → {uid}")

@dp.message(Command("addtcoin"))
async def a_addtcoin(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("/addtcoin ID КОЛ")
    try: uid, val = int(args[1]), int(args[2])
    except: return await msg.answer("❌ Числа!")
    update_balance(uid, tcoin=val, desc="Админ начисление")
    await msg.answer(f"✅ +{val} 🪙 → {uid}")

@dp.message(Command("reset"))
async def a_reset(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/reset ID")
    try: uid = int(args[1])
    except: return await msg.answer("❌ Число!")
    c = db(); c.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (uid,)); c.commit(); c.close()
    await msg.answer(f"🔄 Баланс {uid} сброшен.")

@dp.message(Command("ban", "unban"))
async def a_ban(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/ban ID")
    try: uid = int(args[1])
    except: return await msg.answer("❌ Число!")
    val = 1 if "ban" == args[0].replace("/", "") else 0
    c = db(); c.execute("UPDATE users SET is_banned=? WHERE user_id=?", (val, uid)); c.commit(); c.close()
    await msg.answer(f"{'🚫 Забанен' if val else '✅ Разбанен'}: {uid}")

@dp.message(Command("makeadmin"))
async def a_makeadmin(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 3: return await msg.answer("/makeadmin ID 1/0")
    try: uid, val = int(args[1]), int(args[2])
    except: return await msg.answer("❌ Числа!")
    if val not in [0, 1]: return await msg.answer("❌ 0 или 1!")
    c = db(); c.execute("UPDATE users SET is_admin=? WHERE user_id=?", (val, uid)); c.commit(); c.close()
    await msg.answer(f"✅ Админ {uid} → {val}")

@dp.message(Command("setrate"))
async def a_setrate(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/setrate ЧИСЛО")
    try: v = int(args[1])
    except: return await msg.answer("❌ Число!")
    if v <= 0: return await msg.answer("❌ > 0!")
    set_setting("exchange_rate", v)
    await msg.answer(f"✅ Курс: {v} ⭐️ = 1 🪙")

@dp.message(Command("setminbet"))
async def a_setminbet(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/setminbet ЧИСЛО")
    try: v = int(args[1])
    except: return await msg.answer("❌ Число!")
    set_setting("min_bet", v)
    await msg.answer(f"✅ Мин. ставка: {v} 🪙")

@dp.message(Command("setmaxbet"))
async def a_setmaxbet(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/setmaxbet ЧИСЛО")
    try: v = int(args[1])
    except: return await msg.answer("❌ Число!")
    set_setting("max_bet", v)
    await msg.answer(f"✅ Макс. ставка: {v} 🪙")

@dp.message(Command("maintenance"))
async def a_maint(msg: Message):
    if not is_admin(msg.from_user.id): return
    cur = get_setting("maintenance_mode")
    nv = "0" if cur == "1" else "1"
    set_setting("maintenance_mode", nv)
    await msg.answer(f"🔧 Обслуживание: {'ВКЛ' if nv=='1' else 'ВЫКЛ'}")

@dp.message(Command("createpromo"))
async def a_promo(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 5: return await msg.answer("/createpromo КОД ЗВЁЗДЫ TCOIN ЛИМИТ")
    try:
        code = args[1].upper(); st = int(args[2]); tc = int(args[3]); mx = int(args[4])
    except: return await msg.answer("❌ Формат!")
    c = db()
    c.execute("INSERT OR REPLACE INTO promo_codes (code,stars_reward,tcoin_reward,max_uses) VALUES (?,?,?,?)", (code, st, tc, mx))
    c.commit(); c.close()
    await msg.answer(f"✅ Промокод <code>{code}</code>: ⭐️{st} 🪙{tc} лимит {mx}", parse_mode="HTML")

@dp.message(Command("broadcast"))
async def a_broadcast(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await msg.answer("📢 Отправьте сообщение для рассылки:")
    await state.set_state(AdminStates.waiting_broadcast)

@dp.message(AdminStates.waiting_broadcast)
async def process_broadcast(msg: Message, state: FSMContext):
    await state.clear()
    c = db(); users = [r[0] for r in c.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()]; c.close()
    ok = 0; fail = 0
    sm = await msg.answer(f"📤 Рассылка {len(users)} юзерам...")
    for uid in users:
        try:
            await bot.send_message(uid, msg.text, parse_mode="HTML")
            ok += 1; await asyncio.sleep(0.05)
        except: fail += 1
    await sm.edit_text(f"✅ Рассылка: {ok} ок, {fail} ошибок")

@dp.message(Command("approve"))
async def a_approve(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/approve ID_ЗАЯВКИ")
    try: rid = int(args[1])
    except: return await msg.answer("❌ Число!")
    c = db()
    req = c.execute("SELECT * FROM requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not req:
        c.close(); return await msg.answer("❌ Заявка не найдена.")
    c.execute("UPDATE requests SET status='approved' WHERE id=?", (rid,))
    if req[2] == "deposit":
        update_balance(req[1], stars=req[3], desc="Пополнение одобрено")
    elif req[2] == "withdraw":
        pass
    c.commit(); c.close()
    await msg.answer(f"✅ Заявка #{rid} одобрена.")
    try: await bot.send_message(req[1], f"✅ Ваша заявка #{rid} одобрена!")
    except: pass

@dp.message(Command("reject"))
async def a_reject(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/reject ID_ЗАЯВКИ")
    try: rid = int(args[1])
    except: return await msg.answer("❌ Число!")
    c = db()
    req = c.execute("SELECT * FROM requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not req:
        c.close(); return await msg.answer("❌ Заявка не найдена.")
    c.execute("UPDATE requests SET status='rejected' WHERE id=?", (rid,))
    if req[2] == "withdraw":
        update_balance(req[1], stars=req[3], desc="Возврат (заявка отклонена)")
    c.commit(); c.close()
    await msg.answer(f"❌ Заявка #{rid} отклонена.")
    try: await bot.send_message(req[1], f"❌ Ваша заявка #{rid} отклонена.")
    except: pass

@dp.message(Command("requests"))
async def a_requests(msg: Message):
    if not is_admin(msg.from_user.id): return
    c = db()
    reqs = c.execute("SELECT id,user_id,req_type,amount,status,created_at FROM requests ORDER BY id DESC LIMIT 20").fetchall()
    c.close()
    if not reqs:
        return await msg.answer("📋 Заявок нет.")
    text = "📋 <b>Заявки:</b>\n\n"
    for r in reqs:
        icon = "📥" if r[2] == "deposit" else "📤"
        st = "⏳" if r[4] == "pending" else ("✅" if r[4] == "approved" else "❌")
        text += f"{st} #{r[0]} {icon} {r[3]}⭐ 👤{r[1]} ({r[4]})\n"
    await msg.answer(text, parse_mode="HTML")

@dp.message(Command("userstats"))
async def a_userstats(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("/userstats ID")
    try: uid = int(args[1])
    except: return await msg.answer("❌ Число!")
    u = get_user(uid)
    if not u: return await msg.answer("❌ Не найден.")
    text = (f"📊 <b>Юзер {u[0]}</b>\n"
            f"📝 @{u[1]} | {u[2]}\n"
            f"⭐️ {u[3]} | 🪙 {u[4]}\n"
            f"✅ Заданий: {u[12]} | 👥 Друзей: {u[13]}\n"
            f"🚫 Бан: {'Да' if u[8] else 'Нет'} | 👑 Админ: {'Да' if u[7] else 'Нет'}\n"
            f"✅ Вериф: {'Да' if u[15] else 'Нет'}\n"
            f"📅 {u[14][:10]}")
    await msg.answer(text, parse_mode="HTML")

# ================= НАЗАД =================
@dp.callback_query(F.data == "back_menu")
async def cb_back(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not u or not u[15]:
        return await show_verify(cb.message)
    await show_main_menu(cb.message)

# ================= ЗАПУСК =================
async def main():
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
