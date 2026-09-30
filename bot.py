# =============================================================================
# TELEGRAM БОТ — ФИНАЛЬНАЯ ВЕРСИЯ (ВСЕ КНОПКИ ВЫДАЮТ ИНТЕРФЕЙС)
# =============================================================================

import asyncio
import logging
import random
import sqlite3
import re
import html
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# =============================================================================
# ========================= КОНФИГУРАЦИЯ ====================================
# =============================================================================

BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc"
PIARFLOW_API_KEY = "MSnWP-9zGC1ZProz_dUSrj5TqeQ--khK"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"
ADMIN_ID = 5356400377

DEFAULT_SETTINGS = {
    "exchange_rate": "10", "bot_active": "1", "maintenance_mode": "0",
    "min_bet": "10", "max_bet": "50000", "daily_bonus_stars": "10",
    "daily_bonus_tcoin": "5", "referral_bonus": "5", "max_tasks_per_day": "10",
    "deposit_enabled": "1", "withdraw_enabled": "1", "games_enabled": "1",
    "transfer_enabled": "1", "verification_required": "1", "min_withdraw": "50",
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_current_task: Dict[int, Dict] = {}
api_cache: Dict[str, Tuple] = {}

# =============================================================================
# ========================= FSM =============================================
# =============================================================================

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_user_id = State()
    waiting_amount = State()
    waiting_promo_code = State()
    waiting_promo_stars = State()
    waiting_promo_tcoin = State()
    waiting_promo_limit = State()
    waiting_promo_delete = State()
    waiting_setting_value = State()

class UserStates(StatesGroup):
    waiting_promo = State()
    waiting_transfer_target = State()
    waiting_transfer_amount = State()
    waiting_withdraw_amount = State()

# =============================================================================
# ========================= БАЗА ДАННЫХ =====================================
# =============================================================================

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect("bot_database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        stars_balance INTEGER DEFAULT 0, tcoin_balance INTEGER DEFAULT 0,
        referral_code TEXT, referred_by INTEGER, is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0, last_daily_bonus TEXT,
        tasks_completed_today INTEGER DEFAULT 0, last_task_date TEXT,
        total_tasks_completed INTEGER DEFAULT 0, total_referrals INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_verified INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY, stars_reward INTEGER DEFAULT 0,
        tcoin_reward INTEGER DEFAULT 0, max_uses INTEGER DEFAULT 100,
        current_uses INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS used_promo (
        user_id INTEGER, promo_code TEXT, used_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, promo_code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
        amount INTEGER, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, req_type TEXT,
        amount INTEGER, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT)""")
    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_user(uid: int):
    conn = get_db()
    r = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    conn.close()
    return r

def get_user_by_username(uname: str):
    conn = get_db()
    r = conn.execute("SELECT * FROM users WHERE username = ?", (uname.lstrip('@'),)).fetchone()
    conn.close()
    return r

def create_user(uid, uname, fname, rcode, ref_by=None, verified=0):
    conn = get_db()
    conn.execute("INSERT INTO users (user_id,username,first_name,referral_code,referred_by,is_admin,is_verified) VALUES (?,?,?,?,?,?,?)",
                 (uid, uname, fname, rcode, ref_by, 1 if uid == ADMIN_ID else 0, verified))
    conn.commit()
    conn.close()

def update_user_field(uid, field, value):
    conn = get_db()
    conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, uid))
    conn.commit()
    conn.close()

def update_balance(uid, stars=0, tcoin=0, desc=""):
    conn = get_db()
    conn.execute("UPDATE users SET stars_balance=stars_balance+?, tcoin_balance=tcoin_balance+? WHERE user_id=?", (stars, tcoin, uid))
    if stars != 0:
        conn.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                     (uid, 'stars', stars, desc or ("Звёзды" if stars > 0 else "Списание звёзд")))
    if tcoin != 0:
        conn.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                     (uid, 'tcoin', tcoin, desc or ("T Coin" if tcoin > 0 else "Списание T Coin")))
    conn.commit()
    conn.close()

def get_transactions(uid, limit=15):
    conn = get_db()
    rows = conn.execute("SELECT type,amount,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    conn.close()
    return rows

def can_claim_daily(uid):
    u = get_user(uid)
    if not u or not u['last_daily_bonus']: return True
    try: return (datetime.now() - datetime.strptime(u['last_daily_bonus'], "%Y-%m-%d")).days >= 1
    except: return True

def set_daily_claimed(uid):
    update_user_field(uid, "last_daily_bonus", datetime.now().strftime("%Y-%m-%d"))

def check_daily_task_reset(uid):
    u = get_user(uid)
    if u and u['last_task_date'] and u['last_task_date'] != datetime.now().strftime("%Y-%m-%d"):
        update_user_field(uid, "tasks_completed_today", 0)

def increment_tasks(uid):
    conn = get_db()
    t = datetime.now().strftime("%Y-%m-%d")
    conn.execute("UPDATE users SET tasks_completed_today=tasks_completed_today+1, last_task_date=?, total_tasks_completed=total_tasks_completed+1 WHERE user_id=?", (t, uid))
    conn.commit()
    conn.close()

def increment_referrals(uid):
    conn = get_db()
    conn.execute("UPDATE users SET total_referrals=total_referrals+1 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return r['value'] if r else None

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

def get_promo(code):
    conn = get_db()
    r = conn.execute("SELECT * FROM promo_codes WHERE code=? AND is_active=1", (code,)).fetchone()
    conn.close()
    return r

def create_promo(code, stars, tcoin, max_uses):
    conn = get_db()
    try:
        conn.execute("INSERT INTO promo_codes (code,stars_reward,tcoin_reward,max_uses) VALUES (?,?,?,?)", (code, stars, tcoin, max_uses))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_promo(code):
    conn = get_db()
    c = conn.execute("DELETE FROM promo_codes WHERE code=?", (code,))
    conn.execute("DELETE FROM used_promo WHERE promo_code=?", (code,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def use_promo(uid, code):
    conn = get_db()
    if conn.execute("SELECT 1 FROM used_promo WHERE user_id=? AND promo_code=?", (uid, code)).fetchone():
        conn.close()
        return False, "already_used"
    conn.execute("UPDATE promo_codes SET current_uses=current_uses+1 WHERE code=?", (code,))
    conn.execute("INSERT INTO used_promo (user_id,promo_code) VALUES (?,?)", (uid, code))
    conn.commit()
    conn.close()
    return True, "success"

def list_promos(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def create_request(uid, rtype, amount):
    conn = get_db()
    c = conn.execute("INSERT INTO requests (user_id,req_type,amount) VALUES (?,?,?)", (uid, rtype, amount))
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid

def get_request(rid):
    conn = get_db()
    r = conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    conn.close()
    return r

def update_request_status(rid, status):
    conn = get_db()
    conn.execute("UPDATE requests SET status=?, processed_at=? WHERE id=?", (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rid))
    conn.commit()
    conn.close()

def get_pending_requests(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM requests WHERE status='pending' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def get_bot_stats():
    conn = get_db()
    s = {}
    s['total_users'] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s['active_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=0").fetchone()[0]
    s['banned_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    r = conn.execute("SELECT COALESCE(SUM(stars_balance),0), COALESCE(SUM(tcoin_balance),0) FROM users").fetchone()
    s['total_stars'], s['total_tcoin'] = r
    t = datetime.now().strftime("%Y-%m-%d")
    s['new_today'] = conn.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['tx_today'] = conn.execute("SELECT COUNT(*) FROM transactions WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['pending_requests'] = conn.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    s['active_promos'] = conn.execute("SELECT COUNT(*) FROM promo_codes WHERE is_active=1").fetchone()[0]
    conn.close()
    return s

init_db()

# =============================================================================
# ========================= PIARFLOW API ====================================
# =============================================================================

async def pf_get_task(uid, cid):
    ck = f"task_{uid}"
    if ck in api_cache and datetime.now().timestamp() - api_cache[ck][1] < 300:
        return api_cache[ck][0]
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors", json={"user_id": uid, "chat_id": cid, "max_sponsors": 1}, headers=h) as r:
                d = await r.json()
                api_cache[ck] = (d, datetime.now().timestamp())
                return d
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def pf_check_task(uid, link):
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json={"user_id": uid, "links": [link]}, headers=h) as r:
                return await r.json()
        except:
            return {"status": "error"}

# =============================================================================
# ========================= УТИЛИТЫ =========================================
# =============================================================================

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

async def resolve_user_id(arg, reply_msg=None):
    if reply_msg and reply_msg.from_user: return reply_msg.from_user.id
    if not arg: return None
    arg = arg.strip()
    if arg.isdigit(): return int(arg)
    if arg.startswith('@'): uname = arg[1:]
    elif re.match(r'^[a-zA-Z0-9_]{3,}$', arg): uname = arg
    else: return None
    u = get_user_by_username(uname)
    return u['user_id'] if u else None

def is_admin(uid):
    u = get_user(uid)
    return bool(u and u['is_admin'])

def is_verified(uid):
    u = get_user(uid)
    return bool(u and u['is_verified'])

def is_bot_active(): return get_setting("bot_active") == "1"
def is_maintenance(): return get_setting("maintenance_mode") == "1"
def safe_html(text): return html.escape(text)

def btn_menu(): return InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_menu")
def btn_profile(): return InlineKeyboardButton(text="🔙 Профиль", callback_data="profile")
def btn_admin(): return InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin")
def btn_games(): return InlineKeyboardButton(text="🎮 К играм", callback_data="games_menu")

def build_keyboard(rows):
    b = InlineKeyboardBuilder()
    for row in rows: b.row(*row)
    return b.as_markup()

def nav_kb(adm=False, extra=None):
    rows = []
    if extra:
        if isinstance(extra[0], list): rows.extend(extra)
        else: rows.append(extra)
    rows.append([btn_menu()])
    if adm: rows.append([btn_admin()])
    return build_keyboard(rows)

# =============================================================================
# ========================= РЕНДЕР ==========================================
# =============================================================================

async def render(target, text, markup, is_cb=False):
    try:
        if is_cb: await target.edit_text(text, parse_mode="HTML", reply_markup=markup)
        else: await target.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e): logging.error(f"Render error: {e}")

async def render_main_menu(target, is_cb=False):
    uid = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    u = get_user(uid)
    if not u: return
    fn = target.from_user.first_name if hasattr(target, 'from_user') else target.message.from_user.first_name
    bi = await bot.get_me()
    rl = f"https://t.me/{bi.username}?start=ref_{u['referral_code']}"
    text = (f"👋 <b>Привет, {fn}!</b>\n\n💰 <b>Баланс:</b>\n"
            f"⭐️ Звёзды: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"🔗 <b>Реферальная ссылка:</b>\n<code>{rl}</code>\n"
            f"<i>+{get_setting('referral_bonus')} ⭐️ за друга</i>")
    kb = build_keyboard([
        [InlineKeyboardButton(text="📋 Задания", callback_data="task_get"),
         InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton(text="💱 Обмен", callback_data="exchange"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]])
    if u['is_admin']:
        kb = build_keyboard([
            [InlineKeyboardButton(text="📋 Задания", callback_data="task_get"),
             InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu")],
            [InlineKeyboardButton(text="💱 Обмен", callback_data="exchange"),
             InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin")]])
    await render(target, text, kb, is_cb)

async def render_verify(target, is_cb=False):
    uid = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    text = "⚠️ <b>Подтверждение регистрации</b>\n\nВы перешли по реферальной ссылке.\nДля доступа подпишитесь на спонсора:"
    td = await pf_get_task(uid, uid)
    if td.get("status") == "ok" and td.get("sponsors"):
        sp = td["sponsors"][0]
        user_current_task[uid] = {"link": sp["link"], "price": sp.get("price", 5), "verify": True}
        kb = build_keyboard([
            [InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"])],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_check")],
            [btn_menu()]])
    else:
        update_user_field(uid, "is_verified", 1)
        await render_main_menu(target, is_cb)
        return
    await render(target, text, kb, is_cb)

# =============================================================================
# ========================= СТАРТ ===========================================
# =============================================================================

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    if not is_bot_active() and uid != ADMIN_ID:
        return await msg.answer("🔧 Бот временно недоступен.", reply_markup=nav_kb())
    if is_maintenance() and uid != ADMIN_ID:
        return await msg.answer("🔧 Технические работы.", reply_markup=nav_kb())
    u = get_user(uid)
    if u and u['is_banned']:
        return await msg.answer("❌ Вы заблокированы.", reply_markup=nav_kb())
    if not u:
        args = msg.text.split()
        ref_by = None
        verified = 1
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                rid = int(args[1].replace("ref_", ""))
                if rid != uid and get_user(rid):
                    ref_by = rid
                    if get_setting("verification_required") == "1": verified = 0
            except ValueError: pass
        create_user(uid, msg.from_user.username or "user", msg.from_user.first_name or "User", f"ref_{uid}", ref_by, verified)
        if ref_by and verified:
            bonus = int(get_setting("referral_bonus") or 5)
            update_balance(ref_by, stars=bonus, desc="Реферальный бонус")
            increment_referrals(ref_by)
            try: await bot.send_message(ref_by, f"🎉 <b>Друг зарегистрировался!</b>\n+{bonus} ⭐️", parse_mode="HTML")
            except: pass
    u = get_user(uid)
    if not u['is_verified'] and get_setting("verification_required") == "1":
        return await render_verify(msg, is_cb=False)
    await render_main_menu(msg, is_cb=False)

# =============================================================================
# ========================= ПРОФИЛЬ =========================================
# =============================================================================

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not u: return
    text = (f"👤 <b>Ваш профиль</b>\n\n🆔 ID: <code>{u['user_id']}</code>\n"
            f"📝 @{u['username'] or 'N/A'}\n👤 {u['first_name']}\n\n"
            f"💰 <b>Баланс:</b>\n⭐️ <code>{fmt(u['stars_balance'])}</code>\n🪙 <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"📈 Заданий: {u['total_tasks_completed']}\n👥 Друзей: {u['total_referrals']}\n📅 {u['created_at'][:10]}")
    kb = build_keyboard([
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="daily"), InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_enter")],
        [InlineKeyboardButton(text="📊 История", callback_data="history"), InlineKeyboardButton(text="💸 Перевод", callback_data="transfer")],
        [InlineKeyboardButton(text="⭐ Пополнить", callback_data="deposit"), InlineKeyboardButton(text="💳 Вывести", callback_data="withdraw")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

# =============================================================================
# ========================= ЕЖЕДНЕВНЫЙ БОНУС ================================
# =============================================================================

@dp.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    await cb.answer()
    if can_claim_daily(cb.from_user.id):
        bs = int(get_setting("daily_bonus_stars") or 10)
        bt = int(get_setting("daily_bonus_tcoin") or 5)
        update_balance(cb.from_user.id, stars=bs, tcoin=bt, desc="Ежедневный бонус")
        set_daily_claimed(cb.from_user.id)
        text = f"🎁 <b>Бонус получен!</b>\n\n⭐️ +{bs}\n🪙 +{bt}\n\nВозвращайтесь завтра!"
    else:
        u = get_user(cb.from_user.id)
        try:
            d = datetime.strptime(u['last_daily_bonus'], "%Y-%m-%d") + timedelta(days=1) - datetime.now()
            text = f"⏰ <b>Бонус уже получен!</b>\n\nСледующий через: {d.seconds//3600}ч {(d.seconds%3600)//60}мин"
        except: text = "⏰ Бонус уже получен. Возвращайтесь завтра!"
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

# =============================================================================
# ========================= ПРОМОКОДЫ (ПОЛЬЗОВАТЕЛЬ) ========================
# =============================================================================

@dp.callback_query(F.data == "promo_enter")
async def cb_promo_enter(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await render(cb.message, "🎟 <b>Ввод промокода</b>\n\nОтправьте промокод сообщением.",
                 build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_promo")]]), is_cb=True)
    await state.set_state(UserStates.waiting_promo)

@dp.callback_query(F.data == "cancel_promo")
async def cb_cancel_promo(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "profile"
    await cb_profile(cb)

@dp.message(UserStates.waiting_promo)
async def process_promo(msg: Message, state: FSMContext):
    await state.clear()
    code = msg.text.strip().upper()
    promo = get_promo(code)
    kb_back = nav_kb(False, [btn_profile()])
    if not promo: return await msg.answer("❌ Промокод не найден.", reply_markup=kb_back)
    if promo['current_uses'] >= promo['max_uses']: return await msg.answer("❌ Промокод исчерпан.", reply_markup=kb_back)
    ok, st = use_promo(msg.from_user.id, code)
    if not ok:
        if st == "already_used": return await msg.answer("❌ Уже использован.", reply_markup=kb_back)
        return
    sr, tr = promo['stars_reward'], promo['tcoin_reward']
    if sr > 0 or tr > 0: update_balance(msg.from_user.id, stars=sr, tcoin=tr, desc=f"Промокод: {code}")
    text = f"✅ <b>Промокод активирован!</b>\n\n🎟 <code>{code}</code>\n\n"
    if sr > 0: text += f"⭐️ +{sr}\n"
    if tr > 0: text += f"🪙 +{tr}\n"
    await msg.answer(text, parse_mode="HTML", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 Ввести ещё", callback_data="promo_enter")], [btn_profile()], [btn_menu()]]))

# =============================================================================
# ========================= ИСТОРИЯ =========================================
# =============================================================================

@dp.callback_query(F.data == "history")
async def cb_history(cb: CallbackQuery):
    await cb.answer()
    txs = get_transactions(cb.from_user.id)
    if not txs: text = "📊 <b>История</b>\n\nПока нет операций."
    else:
        text = "📊 <b>Последние операции:</b>\n\n"
        for tx in txs:
            e = "🟢" if tx['amount'] > 0 else "🔴"
            c = "⭐️" if tx['type'] == "stars" else "🪙"
            s = "+" if tx['amount'] > 0 else ""
            text += f"{e} {s}{tx['amount']} {c} — <i>{tx['description']}</i>\n   <code>{tx['created_at']}</code>\n\n"
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

# =============================================================================
# ========================= ПЕРЕВОДЫ ========================================
# =============================================================================

@dp.callback_query(F.data == "transfer")
async def cb_transfer(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    if get_setting("transfer_enabled") != "1": return await cb.answer("❌ Переводы отключены", show_alert=True)
    await render(cb.message, "💸 <b>Перевод T Coin</b>\n\nОтправьте ID или @username получателя:",
                 build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_transfer")]]), is_cb=True)
    await state.set_state(UserStates.waiting_transfer_target)

@dp.callback_query(F.data == "cancel_transfer")
async def cb_cancel_transfer(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "profile"
    await cb_profile(cb)

@dp.message(UserStates.waiting_transfer_target)
async def process_transfer_target(msg: Message, state: FSMContext):
    tid = await resolve_user_id(msg.text.strip(), msg.reply_to_message)
    cancel_kb = build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_transfer")]])
    if not tid: return await msg.answer("❌ Не найден! Попробуйте ещё или нажмите Отмена.", reply_markup=cancel_kb)
    if tid == msg.from_user.id: return await msg.answer("❌ Себе нельзя!", reply_markup=cancel_kb)
    await state.update_data(transfer_target=tid)
    await state.set_state(UserStates.waiting_transfer_amount)
    await msg.answer(f"💸 Сколько T Coin отправить <code>{tid}</code>?", parse_mode="HTML", reply_markup=cancel_kb)

@dp.message(UserStates.waiting_transfer_amount)
async def process_transfer_amount(msg: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("transfer_target")
    await state.clear()
    kb_back = nav_kb(False, [btn_profile()])
    try: amount = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=kb_back)
    if amount <= 0: return await msg.answer("❌ Сумма > 0!", reply_markup=kb_back)
    u = get_user(msg.from_user.id)
    if not u or u['tcoin_balance'] < amount: return await msg.answer("❌ Недостаточно T Coin!", reply_markup=kb_back)
    t = get_user(tid)
    if not t: return await msg.answer("❌ Получатель не найден!", reply_markup=kb_back)
    update_balance(msg.from_user.id, tcoin=-amount, desc=f"Перевод → {tid}")
    update_balance(tid, tcoin=amount, desc=f"Перевод ← {msg.from_user.id}")
    await msg.answer(f"✅ Переведено <b>{amount} 🪙</b> → {tid}", parse_mode="HTML",
                     reply_markup=build_keyboard([[InlineKeyboardButton(text="💸 Ещё перевод", callback_data="transfer")], [btn_profile()], [btn_menu()]]))
    try: await bot.send_message(tid, f"💸 Вам перевели <b>{amount} 🪙</b> от @{msg.from_user.username or msg.from_user.id}!", parse_mode="HTML")
    except: pass

@dp.message(Command("перевод"))
async def cmd_transfer_reply(msg: Message):
    kb = nav_kb(is_admin(msg.from_user.id))
    if not msg.reply_to_message: return await msg.answer("❌ Ответьте на сообщение получателя", reply_markup=kb)
    args = msg.text.split()
    if len(args) < 2: return await msg.answer("❌ Укажите сумму: /перевод 100", reply_markup=kb)
    try: amount = int(args[1])
    except ValueError: return await msg.answer("❌ Сумма — число!", reply_markup=kb)
    tid = msg.reply_to_message.from_user.id
    if tid == msg.from_user.id: return await msg.answer("❌ Себе нельзя!", reply_markup=kb)
    if amount <= 0: return await msg.answer("❌ Сумма > 0!", reply_markup=kb)
    u = get_user(msg.from_user.id)
    if not u or u['tcoin_balance'] < amount: return await msg.answer("❌ Недостаточно T Coin!", reply_markup=kb)
    update_balance(msg.from_user.id, tcoin=-amount, desc=f"Перевод → {tid}")
    update_balance(tid, tcoin=amount, desc=f"Перевод ← {msg.from_user.id}")
    await msg.answer(f"✅ Переведено <b>{amount} 🪙</b>", parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= ЗАДАНИЯ =========================================
# =============================================================================

@dp.callback_query(F.data == "task_get")
async def cb_task_get(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    check_daily_task_reset(uid)
    u = get_user(uid)
    mx = int(get_setting("max_tasks_per_day") or 10)
    if u['tasks_completed_today'] >= mx:
        return await render(cb.message, f"⏰ <b>Лимит заданий исчерпан!</b> ({mx}/{mx})", build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)
    td = await pf_get_task(uid, uid)
    if td.get("status") == "ok" and td.get("sponsors"):
        sp = td["sponsors"][0]
        user_current_task[uid] = {"link": sp["link"], "price": sp.get("price", 5), "verify": False}
        kb = build_keyboard([[InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"])], [InlineKeyboardButton(text="✅ Проверить", callback_data="task_check")], [btn_menu()]])
        await render(cb.message, f"📋 <b>Задание:</b>\nПодпишитесь и получите <b>{sp.get('price', 5)} ⭐️</b>", kb, is_cb=True)
    else:
        await render(cb.message, "🎉 <b>Заданий пока нет.</b>", build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

@dp.callback_query(F.data == "task_check")
async def cb_task_check(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    task = user_current_task.get(uid)
    if not task: return await cb.answer("❌ Сначала возьмите задание!", show_alert=True)
    cd = await pf_check_task(uid, task["link"])
    if cd.get("status") == "ok":
        done = [s for s in cd.get("sponsors", []) if s.get("status") == "subscribed"]
        if done:
            reward = task["price"]
            update_balance(uid, stars=reward, desc="Выполнение задания")
            if task.get("verify"):
                update_user_field(uid, "is_verified", 1)
                u = get_user(uid)
                if u['referred_by']:
                    bonus = int(get_setting("referral_bonus") or 5)
                    update_balance(u['referred_by'], stars=bonus, desc="Реферал верифицирован")
                    increment_referrals(u['referred_by'])
                user_current_task.pop(uid, None)
                return await render(cb.message, f"✅ <b>Верификация пройдена!</b>\n+{reward} ⭐️", build_keyboard([[btn_menu()]]), is_cb=True)
            increment_tasks(uid)
            user_current_task.pop(uid, None)
            u = get_user(uid)
            mx = int(get_setting("max_tasks_per_day") or 10)
            rows = []
            if u['tasks_completed_today'] < mx: rows.append([InlineKeyboardButton(text="📋 Следующее", callback_data="task_get")])
            rows.append([btn_profile()])
            rows.append([btn_menu()])
            await render(cb.message, f"✅ <b>Выполнено!</b> +{reward} ⭐️\n📊 Сегодня: {u['tasks_completed_today']}/{mx}\n📈 Всего: {u['total_tasks_completed']}", build_keyboard(rows), is_cb=True)
        else: await cb.answer("⏳ Не подписаны!", show_alert=True)
    else: await cb.answer("❌ Ошибка проверки.", show_alert=True)

# =============================================================================
# ========================= ОБМЕН ===========================================
# =============================================================================

@dp.callback_query(F.data == "exchange")
async def cb_exchange(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    avail = u['stars_balance'] // rate
    text = f"💱 <b>Обмен</b>\n\n💱 Курс: <code>{rate} ⭐️ = 1 🪙</code>\n⭐️ Баланс: <code>{fmt(u['stars_balance'])}</code>\n🪙 Доступно: <code>{fmt(avail)}</code>"
    rows = []
    if avail > 0: rows.append([InlineKeyboardButton(text=f"🔄 Обменять всё ({avail} 🪙)", callback_data=f"do_ex_{avail}")])
    rows.append([btn_profile()])
    rows.append([btn_menu()])
    await render(cb.message, text, build_keyboard(rows), is_cb=True)

@dp.callback_query(F.data.startswith("do_ex_"))
async def cb_do_exchange(cb: CallbackQuery):
    await cb.answer()
    amt = int(cb.data.split("_")[-1])
    u = get_user(cb.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    cost = amt * rate
    if u['stars_balance'] >= cost:
        update_balance(cb.from_user.id, stars=-cost, tcoin=amt, desc=f"Обмен {cost}⭐→{amt}🪙")
        u = get_user(cb.from_user.id)
        text = f"✅ <b>Обмен выполнен!</b>\n\n📉 -{cost} ⭐️\n📈 +{amt} 🪙\n\n⭐️ {u['stars_balance']}\n🪙 {u['tcoin_balance']}"
        kb = build_keyboard([[InlineKeyboardButton(text="💱 Ещё обмен", callback_data="exchange")], [btn_profile()], [btn_menu()]])
    else:
        text = "❌ Недостаточно звёзд!"
        kb = build_keyboard([[btn_profile()], [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

# =============================================================================
# ========================= ПОПОЛНЕНИЕ ======================================
# =============================================================================

@dp.callback_query(F.data == "deposit")
async def cb_deposit(cb: CallbackQuery):
    await cb.answer()
    if get_setting("deposit_enabled") != "1": return await cb.answer("❌ Пополнение отключено", show_alert=True)
    kb = build_keyboard([
        [InlineKeyboardButton(text="💎 100 ⭐️", callback_data="dep_100"), InlineKeyboardButton(text="💎 500 ⭐️", callback_data="dep_500")],
        [InlineKeyboardButton(text="💎 1000 ⭐️", callback_data="dep_1000")],
        [btn_profile()], [btn_menu()]])
    await render(cb.message, "⭐ <b>Пополнение звёзд</b>\n\nВыберите пакет:", kb, is_cb=True)

@dp.callback_query(F.data.startswith("dep_"))
async def cb_dep_amount(cb: CallbackQuery):
    await cb.answer()
    amt = int(cb.data.split("_")[-1])
    if amt <= 0 or amt > 100000: return await cb.answer("❌ Неверная сумма", show_alert=True)
    try:
        link = await bot.create_invoice_link(title=f"Пополнение {amt} ⭐️", description=f"{amt} звёзд",
            payload=f"deposit_{cb.from_user.id}_{amt}", provider_token="", currency="XTR",
            prices=[LabeledPrice(label=f"{amt} Stars", amount=amt * 100)])
        kb = build_keyboard([[InlineKeyboardButton(text="💳 Оплатить", url=link)], [btn_profile()], [btn_menu()]])
        await render(cb.message, f"💳 <b>Оплата</b>\n\nСумма: <b>{amt} ⭐️</b>", kb, is_cb=True)
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        await cb.answer("❌ Ошибка создания инвойса", show_alert=True)

@dp.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery): await pq.answer(ok=True)

@dp.message(F.successful_payment)
async def process_payment(msg: Message):
    try:
        parts = msg.successful_payment.invoice_payload.split("_")
        if parts[0] == "deposit" and len(parts) >= 3:
            uid, amt = int(parts[1]), int(parts[2])
            update_balance(uid, stars=amt, desc="Пополнение через инвойс")
            rid = create_request(uid, "deposit", amt)
            update_request_status(rid, "approved")
            await msg.answer(f"✅ <b>Платёж успешен!</b>\n⭐️ +{amt} звёзд зачислено!", parse_mode="HTML",
                             reply_markup=nav_kb(is_admin(uid), [InlineKeyboardButton(text="⭐ Ещё пополнить", callback_data="deposit")]))
            try: await bot.send_message(ADMIN_ID, f"💰 Пополнение: {uid} → {amt} ⭐️", parse_mode="HTML")
            except: pass
    except Exception as e:
        logging.error(f"Payment error: {e}")
        await msg.answer("❌ Ошибка обработки платежа.", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ВЫВОД ===========================================
# =============================================================================

@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    if get_setting("withdraw_enabled") != "1": return await cb.answer("❌ Вывод отключён", show_alert=True)
    u = get_user(cb.from_user.id)
    mw = int(get_setting("min_withdraw") or 50)
    await render(cb.message, f"💳 <b>Вывод звёзд</b>\n\n⭐️ Баланс: <code>{u['stars_balance']}</code>\n💵 Мин: {mw} ⭐️\n\nОтправьте сумму:",
                 build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_withdraw")]]), is_cb=True)
    await state.set_state(UserStates.waiting_withdraw_amount)

@dp.callback_query(F.data == "cancel_withdraw")
async def cb_cancel_withdraw(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "profile"
    await cb_profile(cb)

@dp.message(UserStates.waiting_withdraw_amount)
async def process_withdraw(msg: Message, state: FSMContext):
    await state.clear()
    retry_kb = build_keyboard([[InlineKeyboardButton(text="💳 Попробовать ещё", callback_data="withdraw")], [btn_profile()], [btn_menu()]])
    try: amount = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=retry_kb)
    mw = int(get_setting("min_withdraw") or 50)
    if amount < mw: return await msg.answer(f"❌ Минимум: {mw} ⭐️", reply_markup=retry_kb)
    u = get_user(msg.from_user.id)
    if not u or u['stars_balance'] < amount: return await msg.answer("❌ Недостаточно звёзд!", reply_markup=retry_kb)
    update_balance(msg.from_user.id, stars=-amount, desc="Заявка на вывод (заморозка)")
    rid = create_request(msg.from_user.id, "withdraw", amount)
    await msg.answer(f"✅ Заявка #{rid} на вывод {amount} ⭐️ создана.\nСредства заморожены.", reply_markup=nav_kb(False, [btn_profile()]))
    try: await bot.send_message(ADMIN_ID, f"📤 Вывод #{rid}: {msg.from_user.id} → {amount} ⭐️\n<code>/approve {rid}</code> / <code>/reject {rid}</code>", parse_mode="HTML")
    except: pass

# =============================================================================
# ========================= ИГРЫ МЕНЮ =======================================
# =============================================================================

@dp.callback_query(F.data == "games_menu")
async def cb_games_menu(cb: CallbackQuery):
    await cb.answer()
    if get_setting("games_enabled") != "1": return await cb.answer("❌ Игры отключены", show_alert=True)
    text = (f"🎮 <b>Игровой зал</b>\n\n"
            f"🎰 <code>/сл [сумма]</code> — Слоты (×10)\n"
            f"🎲 <code>/кости [режим] [сумма] [параметр]</code>\n"
            f"🎯 <code>/дротик [сумма]</code> / <code>/дротик промах [сумма]</code>\n"
            f"🏀 <code>/баскет [сумма]</code> / <code>/баскет промах [сумма]</code>\n"
            f"⚽ <code>/футбол [сумма]</code>\n"
            f"🎡 <code>/рул [тип] [сумма] [параметр]</code>\n"
            f"🪙 <code>/мон [сумма] [о/р]</code>\n"
            f"📊 <code>/больше [сумма]</code> / <code>/меньше [сумма]</code>\n"
            f"💣 <code>/мины [сумма] [1-5]</code>\n"
            f"🚀 <code>/краш [сумма] [множитель]</code>\n\n"
            f"💵 Ставки: {get_setting('min_bet') or '10'}–{get_setting('max_bet') or '50000'} 🪙")
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

# =============================================================================
# ========================= ИГРОВЫЕ УТИЛИТЫ =================================
# =============================================================================

def parse_bet(args, idx=1):
    if len(args) <= idx: return None, "⚠️ Укажите ставку!"
    try: bet = int(args[idx])
    except ValueError: return None, "❌ Ставка — число!"
    mn, mx = int(get_setting("min_bet") or 10), int(get_setting("max_bet") or 50000)
    if bet < mn: return None, f"❌ Мин. ставка: {mn} 🪙"
    if bet > mx: return None, f"❌ Макс. ставка: {mx} 🪙"
    return bet, None

def check_bal(uid, bet):
    u = get_user(uid)
    return bool(u and u['tcoin_balance'] >= bet)

def dice_emoji(emoji, val):
    if emoji == "🎰":
        if val >= 60: return "🔥💎🔥 ДЖЕКПОТ!"
        if val >= 40: return "🍒🍒🍒 Отличный выигрыш!"
        if val >= 20: return "🍋🍒🍋 Почти!"
        return "🍋🍋🍋 Не повезло"
    if emoji == "🎲": return f"{({1:'⚀',2:'⚁',3:'⚂',4:'⚃',5:'⚄',6:'⚅'}).get(val, val)} ({val})"
    if emoji == "🎯":
        if val == 6: return "🎯 ЯБЛОЧКО!"
        if val >= 4: return "🎯 Попадание!"
        return "💨 Мимо!"
    if emoji == "🏀":
        if val == 5: return "🏀 СЛЭМ-ДАНК!"
        if val >= 3: return "🏀 Почти!"
        return "🏀 Промах"
    if emoji == "⚽":
        if val >= 4: return "⚽ ГООООЛ!"
        if val == 3: return "⚽ В штангу!"
        return "⚽ Вратарь спас!"
    return f"🎮 Результат: {val}"

async def game_result(msg, emoji, val, bet, won, mult, name):
    adm = is_admin(msg.from_user.id)
    kb = nav_kb(adm, [[btn_games()]])
    re = dice_emoji(emoji, val)
    if won:
        pay = int(bet * mult)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Выигрыш {name}")
        await msg.answer(f"🎮 <b>{name}</b>\n\n{re}\n\n🎉 <b>ПОБЕДА!</b>\n\n💰 Ставка: {bet} 🪙\n📈 ×{mult}\n✅ Выигрыш: <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"🎮 <b>{name}</b>\n\n{re}\n\n😔 <b>Проигрыш</b>\n\nПотеряно: {bet} 🪙", parse_mode="HTML", reply_markup=kb)

async def game_ready(msg):
    u = get_user(msg.from_user.id)
    if not u: return False
    kb = nav_kb()
    if u['is_banned']: await msg.answer("❌ Заблокированы.", reply_markup=kb); return False
    if not is_verified(msg.from_user.id): await msg.answer("⚠️ Верификация: /start", reply_markup=kb); return False
    if get_setting("games_enabled") != "1": await msg.answer("❌ Игры отключены.", reply_markup=kb); return False
    return True

# =============================================================================
# ========================= 10 ИГР ==========================================
# =============================================================================

@dp.message(Command("сл", "слоты", "slot", "slots"))
async def g_slots(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(msg.text.split())
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно T Coin!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Слоты")
    dm = await msg.answer_dice(emoji="🎰")
    v = dm.dice.value
    if v == 1: await game_result(msg, "🎰", v, bet, True, 10, "Слоты")
    elif v <= 10: await game_result(msg, "🎰", v, bet, True, 2, "Слоты")
    else: await game_result(msg, "🎰", v, bet, False, 0, "Слоты")

@dp.message(Command("кости", "dice"))
async def g_dice(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    if len(args) < 3:
        return await msg.answer("🎲 <b>Режимы:</b>\n<code>/кости число 100 3</code> (×6)\n<code>/кости чет 100 чет</code> (×2)\n<code>/кости больше 100 б</code> (×2)", parse_mode="HTML", reply_markup=ke)
    mode = args[1].lower()
    if mode == "число":
        if len(args) < 4: return await msg.answer("⚠️ /кости число 100 3", reply_markup=ke)
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err, reply_markup=ke)
        try: tgt = int(args[3])
        except: return await msg.answer("❌ Число 1-6!", reply_markup=ke)
        if not 1 <= tgt <= 6: return await msg.answer("❌ Число 1-6!", reply_markup=ke)
        if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
        update_balance(msg.from_user.id, tcoin=-bet, desc="Кости-число")
        dm = await msg.answer_dice(emoji="🎲")
        await game_result(msg, "🎲", dm.dice.value, bet, dm.dice.value == tgt, 6, f"Кости ({tgt})")
    elif mode in ["чет", "чёт"]:
        if len(args) < 4: return await msg.answer("⚠️ /кости чет 100 чет", reply_markup=ke)
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err, reply_markup=ke)
        c = args[3].lower()
        if c in ["чет", "чёт", "ч"]: we = True
        elif c in ["нечет", "нечёт", "нч", "н"]: we = False
        else: return await msg.answer("❌ чет/нечет", reply_markup=ke)
        if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
        update_balance(msg.from_user.id, tcoin=-bet, desc="Кости-чет")
        dm = await msg.answer_dice(emoji="🎲")
        await game_result(msg, "🎲", dm.dice.value, bet, (dm.dice.value % 2 == 0) == we, 2, f"Кости ({'чёт' if we else 'нечёт'})")
    elif mode in ["больше", "меньше", "б", "м"]:
        if len(args) < 4: return await msg.answer("⚠️ /кости больше 100 б", reply_markup=ke)
        bet, err = parse_bet(args, 2)
        if err: return await msg.answer(err, reply_markup=ke)
        c = args[3].lower()
        if c in ["больше", "б"]: wh = True
        elif c in ["меньше", "м"]: wh = False
        else: return await msg.answer("❌ б/м", reply_markup=ke)
        if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
        update_balance(msg.from_user.id, tcoin=-bet, desc="Кости-больше")
        dm = await msg.answer_dice(emoji="🎲")
        await game_result(msg, "🎲", dm.dice.value, bet, (dm.dice.value >= 4) == wh, 2, f"Кости ({'больше' if wh else 'меньше'})")
    else: await msg.answer("❌ Режимы: число, чет, больше", reply_markup=ke)

@dp.message(Command("дротик", "darts"))
async def g_darts(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    wm = len(args) > 1 and args[1].lower() == "промах"
    bi = 2 if wm else 1
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(args, bi)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Дротик")
    dm = await msg.answer_dice(emoji="🎯")
    hit = dm.dice.value >= 4
    await game_result(msg, "🎯", dm.dice.value, bet, (not hit) if wm else hit, 1.9, f"Дротик ({'промах' if wm else 'попадание'})")

@dp.message(Command("баскет", "basket"))
async def g_basket(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    wm = len(args) > 1 and args[1].lower() == "промах"
    bi = 2 if wm else 1
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(args, bi)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Баскет")
    dm = await msg.answer_dice(emoji="🏀")
    hit = dm.dice.value == 5
    await game_result(msg, "🏀", dm.dice.value, bet, (not hit) if wm else hit, 1.9, f"Баскет ({'промах' if wm else 'попадание'})")

@dp.message(Command("футбол", "foot"))
async def g_foot(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(msg.text.split())
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Футбол")
    dm = await msg.answer_dice(emoji="⚽")
    await game_result(msg, "⚽", dm.dice.value, bet, dm.dice.value >= 4, 2, "Футбол")

@dp.message(Command("рул", "roulette"))
async def g_roulette(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    if len(args) < 4:
        return await msg.answer("🎡 <b>Рулетка:</b>\n<code>/рул цвет 100 к</code> (×2/×14)\n<code>/рул чет 100 чет</code> (×2)\n<code>/рул половина 100 верх</code> (×2)\n<code>/рул число 100 17</code> (×36)\n<code>/рул дюжина 100 1</code> (×3)", parse_mode="HTML", reply_markup=ke)
    mode = args[1].lower()
    bet, err = parse_bet(args, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Рулетка {mode}")
    num = random.randint(0, 36)
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    p = args[3].lower()
    won, mult = False, 0
    if mode == "цвет":
        if p in ["к","красное"]: won, mult = num in reds, 2
        elif p in ["ч","черное","чёрное"]: won, mult = num != 0 and num not in reds, 2
        elif p in ["з","зеро"]: won, mult = num == 0, 14
        else: return await msg.answer("❌ к/ч/з", reply_markup=ke)
    elif mode == "чет":
        if p in ["чет","чёт","ч"]: won, mult = num != 0 and num % 2 == 0, 2
        elif p in ["нечет","нечёт","нч","н"]: won, mult = num != 0 and num % 2 != 0, 2
        else: return await msg.answer("❌ чет/нечет", reply_markup=ke)
    elif mode == "половина":
        if p in ["низ","н"]: won, mult = 1 <= num <= 18, 2
        elif p in ["верх","в"]: won, mult = 19 <= num <= 36, 2
        else: return await msg.answer("❌ верх/низ", reply_markup=ke)
    elif mode == "число":
        try: tgt = int(p)
        except: return await msg.answer("❌ 0-36!", reply_markup=ke)
        if not 0 <= tgt <= 36: return await msg.answer("❌ 0-36!", reply_markup=ke)
        won, mult = num == tgt, 36
    elif mode == "дюжина":
        try: d = int(p)
        except: return await msg.answer("❌ 1/2/3!", reply_markup=ke)
        if d == 1: won, mult = 1 <= num <= 12, 3
        elif d == 2: won, mult = 13 <= num <= 24, 3
        elif d == 3: won, mult = 25 <= num <= 36, 3
        else: return await msg.answer("❌ 1/2/3!", reply_markup=ke)
    else: return await msg.answer("❌ Режимы: цвет, чет, половина, число, дюжина", reply_markup=ke)
    ce = "🟢" if num == 0 else ("🔴" if num in reds else "⚫")
    cn = "Зеро" if num == 0 else ("Красное" if num in reds else "Чёрное")
    kb = nav_kb(adm, [btn_games()])
    if won:
        pay = int(bet * mult)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Рулетка {num}")
        await msg.answer(f"🎡 <b>Рулетка:</b> {ce} <b>{num}</b> ({cn})\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙 ×{mult}\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"🎡 <b>Рулетка:</b> {ce} <b>{num}</b> ({cn})\n\n😔 <b>Проигрыш</b>\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(Command("мон", "coin"))
async def g_coin(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    if len(args) < 3: return await msg.answer("⚠️ <code>/мон 100 о</code> (о/р)", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    c = args[2].lower()
    if c in ["о","орел","орёл"]: wh = True
    elif c in ["р","решка"]: wh = False
    else: return await msg.answer("❌ о/р", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Монетка")
    res = random.choice(["орёл", "решка"])
    won = (res == "орёл") == wh
    em = "🦅" if res == "орёл" else "🪙"
    kb = nav_kb(adm, [btn_games()])
    if won:
        pay = bet * 2
        update_balance(msg.from_user.id, tcoin=pay, desc="Монетка выигрыш")
        await msg.answer(f"{em} <b>{res.capitalize()}!</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"{em} <b>{res.capitalize()}!</b>\n\n😔 <b>Проигрыш</b>\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(Command("больше", "меньше", "hilo"))
async def g_hilo(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    cmd = args[0].replace("/","").lower()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(args)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc=cmd)
    num = random.randint(1, 100)
    kb = nav_kb(adm, [btn_games()])
    if num == 50:
        update_balance(msg.from_user.id, tcoin=bet, desc="Hilo ничья")
        return await msg.answer(f"📊 <b>Число: {num}</b>\n\n🤝 <b>Ничья!</b> Ставка возвращена.", parse_mode="HTML", reply_markup=kb)
    won = num >= 51 if cmd == "больше" else num <= 49
    gn = "Больше" if cmd == "больше" else "Меньше"
    em = "🔥" if num >= 75 else ("📈" if num >= 51 else ("❄️" if num <= 25 else "📉"))
    if won:
        pay = int(bet * 1.9)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"{gn} {num}")
        await msg.answer(f"{em} <b>Число: {num}</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙 ×1.9\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"{em} <b>Число: {num}</b>\n\n😔 <b>Проигрыш</b>\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(Command("мины", "mines"))
async def g_mines(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    if len(args) < 3: return await msg.answer("⚠️ <code>/мины 100 3</code> (1-5)", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    try: mc = int(args[2])
    except: return await msg.answer("❌ Мины: 1-5!", reply_markup=ke)
    if not 1 <= mc <= 5: return await msg.answer("❌ Мины: 1-5!", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Мины {mc}")
    mines = set(random.sample(range(1, 7), mc))
    mult, safe = 1.0, 0
    kb = nav_kb(adm, [btn_games()])
    for _ in range(6):
        if safe == 6 - mc: break
        dm = await msg.answer_dice(emoji="🎲")
        v = dm.dice.value
        if v in mines:
            return await msg.answer(f"💣 <b>МИНА!</b> 🎲 {v}\n\n😔 Проигрыш!\nОткрыто: {safe}\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)
        safe += 1
        mult += mc * 0.4
        await asyncio.sleep(0.5)
    pay = int(bet * mult)
    update_balance(msg.from_user.id, tcoin=pay, desc=f"Мины ×{mult:.1f}")
    await msg.answer(f"💎 <b>Все мины обойдены!</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙 ×{mult:.1f}\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)

@dp.message(Command("краш", "crash"))
async def g_crash(msg: Message):
    if not await game_ready(msg): return
    args = msg.text.split()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    if len(args) < 3: return await msg.answer("⚠️ <code>/краш 100 2.0</code>", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(args, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    try: co = float(args[2])
    except: return await msg.answer("❌ Множитель 1.1-100!", reply_markup=ke)
    if not 1.1 <= co <= 100: return await msg.answer("❌ 1.1-100!", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Краш ×{co}")
    cp = round(100 / random.randint(1, 100), 2)
    anim = "🚀 <b>Краш:</b>\n"
    for s in [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]:
        if s > cp: break
        anim += f"  📈 ×{s}...\n"
        await asyncio.sleep(0.3)
    kb = nav_kb(adm, [btn_games()])
    if cp >= co:
        pay = int(bet * co)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Краш ×{co}")
        anim += f"\n💥 Краш на ×{cp}\n\n🎉 <b>Успели на ×{co}!</b>\n✅ <b>{pay} 🪙</b>"
    else:
        anim += f"\n💥 <b>КРАШ на ×{cp}!</b>\n\n😔 Не успели.\n-{bet} 🪙"
    await msg.answer(anim, parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= АДМИН-ПАНЕЛЬ ====================================
# =============================================================================

@dp.callback_query(F.data == "admin")
async def cb_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    s = get_bot_stats()
    text = (f"👑 <b>Админ-панель</b>\n\n📊 <b>Статистика:</b>\n"
            f"👥 Пользователей: {s['total_users']}\n✅ Активных: {s['active_users']}\n🚫 Забанено: {s['banned_users']}\n"
            f"🆕 Сегодня: {s['new_today']}\n💰 Звёзд: {fmt(s['total_stars'])}\n🪙 T Coin: {fmt(s['total_tcoin'])}\n"
            f"📝 TX сегодня: {s['tx_today']}\n📋 Заявок: {s['pending_requests']}\n🎟 Промокодов: {s['active_promos']}")
    kb = build_keyboard([
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings"), InlineKeyboardButton(text="💱 Курсы", callback_data="admin_rates")],
        [InlineKeyboardButton(text="👥 Юзеры", callback_data="admin_users"), InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promos")],
        [InlineKeyboardButton(text="📋 Заявки", callback_data="admin_requests"), InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "admin_settings")
async def cb_admin_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    s = get_all_settings()
    text = "⚙️ <b>Настройки бота</b>\n\n"
    toggles = [("bot_active","🟢 Бот"),("maintenance_mode","🔧 Обслуж."),("games_enabled","🎮 Игры"),
               ("transfer_enabled","💸 Переводы"),("deposit_enabled","⭐ Пополнение"),
               ("withdraw_enabled","💳 Вывод"),("verification_required","✅ Вериф.")]
    for k, l in toggles:
        text += f"{'✅' if s.get(k)=='1' else '❌'} {l}: <b>{'Вкл' if s.get(k)=='1' else 'Выкл'}</b>\n"
    rows = [[InlineKeyboardButton(text=f"{'✅' if s.get(k)=='1' else '❌'} {l}", callback_data=f"toggle_{k}")] for k, l in toggles]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin")])
    await render(cb.message, text, build_keyboard(rows), is_cb=True)

@dp.callback_query(F.data.startswith("toggle_"))
async def cb_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    # НЕ вызываем cb.answer() — его вызовет cb_admin_settings
    key = cb.data.replace("toggle_", "")
    cur = get_setting(key)
    set_setting(key, "0" if cur == "1" else "1")
    cb.data = "admin_settings"
    await cb_admin_settings(cb)

@dp.callback_query(F.data == "admin_rates")
async def cb_admin_rates(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    s = get_all_settings()
    text = (f"💱 <b>Курсы и лимиты</b>\n\n💱 Курс: <code>{s.get('exchange_rate')}</code> ⭐️=1🪙\n"
            f"💵 Мин. ставка: <code>{s.get('min_bet')}</code>\n💰 Макс. ставка: <code>{s.get('max_bet')}</code>\n"
            f"🎁 Бонус ⭐️: <code>{s.get('daily_bonus_stars')}</code>\n🎁 Бонус 🪙: <code>{s.get('daily_bonus_tcoin')}</code>\n"
            f"👥 Реф. бонус: <code>{s.get('referral_bonus')}</code>\n📋 Лимит заданий: <code>{s.get('max_tasks_per_day')}</code>\n"
            f"💳 Мин. вывод: <code>{s.get('min_withdraw')}</code>")
    keys = [("set_exchange_rate","💱 Курс"),("set_min_bet","💵 Мин. ставка"),("set_max_bet","💰 Макс. ставка"),
            ("set_daily_stars","🎁 Бонус ⭐️"),("set_daily_tcoin","🎁 Бонус 🪙"),("set_referral_bonus","👥 Реф. бонус"),
            ("set_max_tasks","📋 Лимит заданий"),("set_min_withdraw","💳 Мин. вывод")]
    rows = [[InlineKeyboardButton(text=l, callback_data=d)] for d, l in keys]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin")])
    await render(cb.message, text, build_keyboard(rows), is_cb=True)

SK = {"set_exchange_rate":("exchange_rate","💱 Новый курс:"),"set_min_bet":("min_bet","💵 Мин. ставка:"),
      "set_max_bet":("max_bet","💰 Макс. ставка:"),"set_daily_stars":("daily_bonus_stars","🎁 Бонус ⭐️:"),
      "set_daily_tcoin":("daily_bonus_tcoin","🎁 Бонус 🪙:"),"set_referral_bonus":("referral_bonus","👥 Реф. бонус:"),
      "set_max_tasks":("max_tasks_per_day","📋 Лимит:"),"set_min_withdraw":("min_withdraw","💳 Мин. вывод:")}

@dp.callback_query(F.data.startswith("set_"))
async def cb_set_val(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    kd = SK.get(cb.data)
    if not kd: return
    key, prompt = kd
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.waiting_setting_value)
    await cb.message.edit_text(f"{prompt}\nТекущее: <code>{get_setting(key)}</code>", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_setting")]]))

@dp.callback_query(F.data == "cancel_setting")
async def cb_cancel_setting(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "admin_rates"
    await cb_admin_rates(cb)

@dp.message(AdminStates.waiting_setting_value)
async def proc_setting(msg: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()
    if not key or not is_admin(msg.from_user.id): return
    try:
        v = int(msg.text.strip())
        if v < 0: raise ValueError
    except ValueError:
        return await msg.answer("❌ Положительное число!", reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 К курсам", callback_data="admin_rates")], [btn_admin()], [btn_menu()]]))
    set_setting(key, v)
    await msg.answer(f"✅ <b>{key}</b> = <code>{v}</code>", parse_mode="HTML",
                     reply_markup=build_keyboard([[InlineKeyboardButton(text="🔧 Ещё изменить", callback_data="admin_rates")], [btn_admin()], [btn_menu()]]))

# ==================== ЮЗЕРЫ ====================

@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    await render(cb.message, "👥 <b>Управление юзерами</b>\n\nОтправьте ID или @username:",
                 build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_ua")], [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]]), is_cb=True)
    await state.set_state(AdminStates.waiting_user_id)

@dp.callback_query(F.data == "cancel_ua")
async def cb_cancel_ua(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_user_id)
async def proc_uid(msg: Message, state: FSMContext):
    await state.clear()
    tid = await resolve_user_id(msg.text.strip(), msg.reply_to_message)
    retry_kb = build_keyboard([[InlineKeyboardButton(text="🔍 Ещё поиск", callback_data="admin_users_search")], [btn_admin()], [btn_menu()]])
    if not tid: return await msg.answer("❌ Не найден!", reply_markup=retry_kb)
    t = get_user(tid)
    if not t: return await msg.answer("❌ Не найден в БД!", reply_markup=retry_kb)
    text = f"👤 <b>Юзер:</b>\n🆔 <code>{t['user_id']}</code>\n📝 @{t['username'] or 'N/A'}\n👤 {t['first_name']}\n⭐️ {t['stars_balance']} | 🪙 {t['tcoin_balance']}"
    kb = build_keyboard([
        [InlineKeyboardButton(text="💰 +⭐️", callback_data=f"ua_as_{tid}"), InlineKeyboardButton(text="🪙 +🪙", callback_data=f"ua_at_{tid}")],
        [InlineKeyboardButton(text="🔄 Сброс", callback_data=f"ua_rst_{tid}"), InlineKeyboardButton(text="🚫 Бан", callback_data=f"ua_ban_{tid}")],
        [InlineKeyboardButton(text="✅ Разбан", callback_data=f"ua_ub_{tid}"), InlineKeyboardButton(text="👑 Админ", callback_data=f"ua_adm_{tid}")],
        [InlineKeyboardButton(text="🔍 Другой", callback_data="admin_users_search")], [btn_admin()], [btn_menu()]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_users_search")
async def cb_ua_search(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_user_id)
    await cb.message.edit_text("🔍 Отправьте ID или @username:",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_ua")]]))

@dp.callback_query(F.data.startswith("ua_as_"))
async def cb_ua_as(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    tid = int(cb.data.split("_")[-1])
    await state.update_data(action="addstars", target_user_id=tid)
    await state.set_state(AdminStates.waiting_amount)
    await cb.message.edit_text(f"💰 Кол-во звёзд для <code>{tid}</code>:", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_amt")]]))

@dp.callback_query(F.data.startswith("ua_at_"))
async def cb_ua_at(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    tid = int(cb.data.split("_")[-1])
    await state.update_data(action="addtcoin", target_user_id=tid)
    await state.set_state(AdminStates.waiting_amount)
    await cb.message.edit_text(f"🪙 Кол-во T Coin для <code>{tid}</code>:", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_amt")]]))

@dp.callback_query(F.data == "cancel_amt")
async def cb_cancel_amt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_amount)
async def proc_amt(msg: Message, state: FSMContext):
    data = await state.get_data()
    act, tid = data.get("action"), data.get("target_user_id")
    await state.clear()
    if not act or not tid or not is_admin(msg.from_user.id): return
    try: amt = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=nav_kb(True))
    if act == "addstars":
        update_balance(tid, stars=amt, desc="Админ")
        await msg.answer(f"✅ +{amt} ⭐️ → {tid}", reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))
    elif act == "addtcoin":
        update_balance(tid, tcoin=amt, desc="Админ")
        await msg.answer(f"✅ +{amt} 🪙 → {tid}", reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_rst_"))
async def cb_ua_rst(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    conn = get_db()
    conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (tid,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"🔄 Баланс <code>{tid}</code> сброшен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_ban_"))
async def cb_ua_ban(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    update_user_field(tid, "is_banned", 1)
    await cb.message.edit_text(f"🚫 <code>{tid}</code> забанен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_ub_"))
async def cb_ua_ub(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    update_user_field(tid, "is_banned", 0)
    await cb.message.edit_text(f"✅ <code>{tid}</code> разбанен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_adm_"))
async def cb_ua_adm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    u = get_user(tid)
    nv = 0 if u['is_admin'] else 1
    update_user_field(tid, "is_admin", nv)
    await cb.message.edit_text(f"👑 <code>{tid}</code> → {'админ' if nv else 'юзер'}.", parse_mode="HTML",
                               reply_markup=build_keyboard([[InlineKeyboardButton(text="👥 К юзерам", callback_data="admin_users")], [btn_admin()], [btn_menu()]]))

# ==================== ПРОМОКОДЫ АДМИН ====================

@dp.callback_query(F.data == "admin_promos")
async def cb_admin_promos(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    ps = list_promos()
    if not ps: text = "🎟 <b>Промокоды</b>\n\nНет промокодов."
    else:
        text = "🎟 <b>Промокоды:</b>\n\n"
        for p in ps: text += f"{'✅' if p['is_active'] else '❌'} <code>{p['code']}</code> ⭐️{p['stars_reward']} 🪙{p['tcoin_reward']} ({p['current_uses']}/{p['max_uses']})\n"
    kb = build_keyboard([[InlineKeyboardButton(text="➕ Создать", callback_data="promo_create")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="promo_delete")], [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "promo_create")
async def cb_pc(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_code)
    await cb.message.edit_text("🎟 Код промокода (A-Z, 0-9):", reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pa")]]))

@dp.callback_query(F.data == "cancel_pa")
async def cb_cancel_pa(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "admin_promos"
    await cb_admin_promos(cb)

@dp.message(AdminStates.waiting_promo_code)
async def proc_pc(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    code = msg.text.strip().upper()
    if not re.match(r'^[A-Z0-9_]{3,30}$', code):
        return await msg.answer("❌ 3-30 символов A-Z 0-9 _", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.waiting_promo_stars)
    await msg.answer("⭐️ Сколько звёзд?")

@dp.message(AdminStates.waiting_promo_stars)
async def proc_ps(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: stars = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_stars=stars)
    await state.set_state(AdminStates.waiting_promo_tcoin)
    await msg.answer("🪙 Сколько T Coin?")

@dp.message(AdminStates.waiting_promo_tcoin)
async def proc_pt(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: tc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_tcoin=tc)
    await state.set_state(AdminStates.waiting_promo_limit)
    await msg.answer("🔢 Макс. использований?")

@dp.message(AdminStates.waiting_promo_limit)
async def proc_pl(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: lim = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))
    d = await state.get_data()
    await state.clear()
    code, stars, tc = d['promo_code'], d.get('promo_stars', 0), d.get('promo_tcoin', 0)
    if create_promo(code, stars, tc, lim):
        await msg.answer(f"✅ <code>{code}</code> создан! ⭐️{stars} 🪙{tc} x{lim}", parse_mode="HTML",
                         reply_markup=build_keyboard([[InlineKeyboardButton(text="➕ Ещё", callback_data="promo_create")], [InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))
    else:
        await msg.answer("❌ Уже существует!", reply_markup=build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data == "promo_delete")
async def cb_pd(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_delete)
    await cb.message.edit_text("🗑 Код промокода для удаления:", reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pa")]]))

@dp.message(AdminStates.waiting_promo_delete)
async def proc_pd(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.clear()
    code = msg.text.strip().upper()
    kb = build_keyboard([[InlineKeyboardButton(text="🎟 К промокодам", callback_data="admin_promos")], [btn_admin()], [btn_menu()]])
    if delete_promo(code): await msg.answer(f"✅ <code>{code}</code> удалён!", parse_mode="HTML", reply_markup=kb)
    else: await msg.answer(f"❌ <code>{code}</code> не найден!", parse_mode="HTML", reply_markup=kb)

# ==================== ЗАЯВКИ ====================

@dp.callback_query(F.data == "admin_requests")
async def cb_admin_reqs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    rs = get_pending_requests()
    if not rs: text = "📋 <b>Заявки</b>\n\nНет ожидающих."
    else:
        text = "📋 <b>Заявки:</b>\n\n"
        for r in rs: text += f"{'📥' if r['req_type']=='deposit' else '📤'} #{r['id']} {r['amount']}⭐️ 👤{r['user_id']} {r['created_at'][:16]}\n"
    await render(cb.message, text, build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]]), is_cb=True)

# ==================== РАССЫЛКА ====================

@dp.callback_query(F.data == "admin_broadcast")
async def cb_ab(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_broadcast)
    await cb.message.edit_text("📢 Сообщение для рассылки:", reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_bc")]]))

@dp.callback_query(F.data == "cancel_bc")
async def cb_cancel_bc(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_broadcast)
async def proc_bc(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.clear()
    conn = get_db()
    users = [r['user_id'] for r in conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()]
    conn.close()
    st = safe_html(msg.text)
    sm = await msg.answer(f"📤 Рассылка {len(users)} юзерам...")
    ok = fail = 0
    for uid in users:
        try: await bot.send_message(uid, st); ok += 1; await asyncio.sleep(0.05)
        except: fail += 1
    await sm.edit_text(f"✅ Рассылка: {ok} ок, {fail} ошибок",
                       reply_markup=build_keyboard([[InlineKeyboardButton(text="📢 Ещё рассылка", callback_data="admin_broadcast")], [btn_admin()], [btn_menu()]]))

# =============================================================================
# ========================= ТЕКСТОВЫЕ АДМИН-КОМАНДЫ =========================
# =============================================================================

@dp.message(Command("addstars","addtcoin","reset","ban","unban","makeadmin","setrate","setminbet","setmaxbet","userstats","stats","createpromo","approve","reject","requests","deletepromo"))
async def admin_cmds(msg: Message):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    cmd = args[0].replace("/","").lower()
    kb = build_keyboard([[btn_admin()], [btn_menu()]])

    if cmd == "stats":
        s = get_bot_stats()
        return await msg.answer(f"📊 <b>Статистика:</b>\n👥 {s['total_users']} | ✅ {s['active_users']} | 🚫 {s['banned_users']}\n🆕 {s['new_today']} | ⭐️ {fmt(s['total_stars'])} | 🪙 {fmt(s['total_tcoin'])}\n📝 TX: {s['tx_today']} | 📋 Заявок: {s['pending_requests']}", parse_mode="HTML", reply_markup=kb)
    if cmd == "requests":
        rs = get_pending_requests()
        if not rs: return await msg.answer("📋 Нет заявок.", reply_markup=kb)
        t = "📋 <b>Заявки:</b>\n\n"
        for r in rs: t += f"{'📥' if r['req_type']=='deposit' else '📤'} #{r['id']} {r['amount']}⭐️ 👤{r['user_id']}\n"
        return await msg.answer(t, parse_mode="HTML", reply_markup=kb)
    if cmd in ["addstars","addtcoin","reset","ban","unban","makeadmin","userstats"]:
        if len(args) < 2 and not msg.reply_to_message: return await msg.answer(f"⚠️ /{cmd} ID [значение]", reply_markup=kb)
        tid = await resolve_user_id(args[1] if len(args) > 1 else "", msg.reply_to_message)
        if not tid: return await msg.answer("❌ Не найден!", reply_markup=kb)
        if cmd == "addstars":
            if len(args) < 3: return await msg.answer("⚠️ /addstars ID 100", reply_markup=kb)
            try: v = int(args[2])
            except: return await msg.answer("❌ Число!", reply_markup=kb)
            update_balance(tid, stars=v, desc="Админ")
            return await msg.answer(f"✅ +{v} ⭐️ → {tid}", reply_markup=kb)
        if cmd == "addtcoin":
            if len(args) < 3: return await msg.answer("⚠️ /addtcoin ID 100", reply_markup=kb)
            try: v = int(args[2])
            except: return await msg.answer("❌ Число!", reply_markup=kb)
            update_balance(tid, tcoin=v, desc="Админ")
            return await msg.answer(f"✅ +{v} 🪙 → {tid}", reply_markup=kb)
        if cmd == "reset":
            conn = get_db(); conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (tid,)); conn.commit(); conn.close()
            return await msg.answer(f"🔄 Баланс {tid} сброшен.", reply_markup=kb)
        if cmd == "ban":
            update_user_field(tid, "is_banned", 1)
            return await msg.answer(f"🚫 {tid} забанен.", reply_markup=kb)
        if cmd == "unban":
            update_user_field(tid, "is_banned", 0)
            return await msg.answer(f"✅ {tid} разбанен.", reply_markup=kb)
        if cmd == "makeadmin":
            if len(args) < 3: return await msg.answer("⚠️ /makeadmin ID 1/0", reply_markup=kb)
            try: v = int(args[2])
            except: return await msg.answer("❌ 1 или 0!", reply_markup=kb)
            if v not in [0,1]: return await msg.answer("❌ 1 или 0!", reply_markup=kb)
            update_user_field(tid, "is_admin", v)
            return await msg.answer(f"👑 {tid} → {'админ' if v else 'юзер'}", reply_markup=kb)
        if cmd == "userstats":
            u = get_user(tid)
            if not u: return await msg.answer("❌ Не найден.", reply_markup=kb)
            return await msg.answer(f"📊 <b>{u['user_id']}</b>\n@{u['username'] or 'N/A'} | {u['first_name']}\n⭐️ {u['stars_balance']} | 🪙 {u['tcoin_balance']}\n✅ {u['total_tasks_completed']} | 👥 {u['total_referrals']}\n🚫 {'Да' if u['is_banned'] else 'Нет'} | 👑 {'Да' if u['is_admin'] else 'Нет'}\n✅ Вериф: {'Да' if u['is_verified'] else 'Нет'}", parse_mode="HTML", reply_markup=kb)
    if cmd in ["setrate","setminbet","setmaxbet"]:
        if len(args) < 2: return await msg.answer(f"⚠️ /{cmd} ЧИСЛО", reply_markup=kb)
        try:
            v = int(args[1])
            if v < 0: raise ValueError
        except: return await msg.answer("❌ Число > 0!", reply_markup=kb)
        km = {"setrate":"exchange_rate","setminbet":"min_bet","setmaxbet":"max_bet"}
        set_setting(km[cmd], v)
        return await msg.answer(f"✅ {km[cmd]} = {v}", reply_markup=kb)
    if cmd == "createpromo":
        if len(args) < 5: return await msg.answer("⚠️ /createpromo КОД ЗВ TCOIN ЛИМИТ", reply_markup=kb)
        try: code, st, tc, lim = args[1].upper(), int(args[2]), int(args[3]), int(args[4])
        except: return await msg.answer("❌ Формат!", reply_markup=kb)
        if create_promo(code, st, tc, lim): return await msg.answer(f"✅ <code>{code}</code> создан! ⭐️{st} 🪙{tc} x{lim}", parse_mode="HTML", reply_markup=kb)
        return await msg.answer("❌ Уже существует!", reply_markup=kb)
    if cmd == "deletepromo":
        if len(args) < 2: return await msg.answer("⚠️ /deletepromo КОД", reply_markup=kb)
        code = args[1].upper()
        if delete_promo(code): return await msg.answer(f"✅ <code>{code}</code> удалён!", parse_mode="HTML", reply_markup=kb)
        return await msg.answer(f"❌ Не найден!", parse_mode="HTML", reply_markup=kb)
    if cmd in ["approve","reject"]:
        if len(args) < 2: return await msg.answer(f"⚠️ /{cmd} ID", reply_markup=kb)
        try: rid = int(args[1])
        except: return await msg.answer("❌ Число!", reply_markup=kb)
        req = get_request(rid)
        if not req or req['status'] != "pending": return await msg.answer("❌ Заявка не найдена!", reply_markup=kb)
        if cmd == "approve":
            update_request_status(rid, "approved")
            if req['req_type'] == "deposit": update_balance(req['user_id'], stars=req['amount'], desc="Одобрено")
            await msg.answer(f"✅ #{rid} одобрена.", reply_markup=kb)
            try: await bot.send_message(req['user_id'], f"✅ Заявка #{rid} одобрена!")
            except: pass
        else:
            update_request_status(rid, "rejected")
            if req['req_type'] == "withdraw": update_balance(req['user_id'], stars=req['amount'], desc="Возврат")
            await msg.answer(f"❌ #{rid} отклонена.", reply_markup=kb)
            try: await bot.send_message(req['user_id'], f"❌ Заявка #{rid} отклонена.")
            except: pass

# =============================================================================
# ========================= НАЗАД ===========================================
# =============================================================================

@dp.callback_query(F.data.startswith("back_"))
async def cb_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    tgt = cb.data.replace("back_", "")
    u = get_user(cb.from_user.id)
    if not u: return
    if not u['is_verified'] and get_setting("verification_required") == "1": return await render_verify(cb, is_cb=True)
    if tgt == "profile":
        cb.data = "profile"
        await cb_profile(cb)
    else:
        await render_main_menu(cb, is_cb=True)

# =============================================================================
# ========================= ЗАПУСК ==========================================
# =============================================================================

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("✅ Бот запущен!")
    try: await bot.delete_webhook(drop_pending_updates=True)
    except: pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("🛑 Остановлен")
    except Exception as e: logging.error(f"Error: {e}")
