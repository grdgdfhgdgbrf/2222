#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚔️ АРЕНА ДУЭЛЯНТОВ — v20.1 Hotfix Edition
Все ошибки v20.0 исправлены:
• Опечатка в generate_settings_screen (return без запятой)
• Опечатка в adm_cmd_stats (bed_players → banned_players)
• Опечатка в cb_duel_profile (отсутствовала проверка tid)
• Отсутствующие callback'и для casino:dice:even_odd, casino:dice:high_low
• Отсутствующие callback'и для casino:darts, casino:basket, casino:roulette, casino:coin, casino:highlow
• Исправлен синтаксис во всех обработчиках
"""

import asyncio
import html
import logging
import math
import os
import random
import re
import sqlite3
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any, Union, Callable, Set

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

class Config:
    BOT_TOKEN: str = os.getenv("8996813076:AAEPRaOZ8O6WoIagzMUdnV49K2zP293vyDg")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "5356400377"))
    DB_PATH: str = os.getenv("DB_PATH", "arena_ultimate.db")
    PROVIDER_TOKEN: str = os.getenv("PROVIDER_TOKEN", "")
    
    START_CRYSTALS: int = 500
    TURN_TIMEOUT: int = 45
    RP_COOLDOWN: int = 5
    TRANSFER_TAX: float = 0.05
    MIN_TRANSFER: int = 10
    MAX_TRANSFER: int = 100000
    
    CASINO_MIN_BET: int = 10
    CASINO_MAX_BET: int = 50000
    CASINO_BETS: List[int] = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000]
    
    MINES_FIELD_SIZE: int = 25
    MINES_MIN_COUNT: int = 1
    MINES_MAX_COUNT: int = 24
    
    CRASH_MIN_MULTIPLIER: float = 1.01
    CRASH_TICK_INTERVAL: float = 0.1
    CRASH_MAX_MULTIPLIER: float = 100.0
    
    DONATION_PACKAGES: List[Tuple[str, int]] = [
        ("☕ Кофе", 50),
        ("🍕 Пицца", 150),
        ("🎁 Поддержка", 500),
        ("💎 VIP", 1500),
        ("👑 Легенда", 5000),
    ]
    DONATION_AFTER_LOSSES: int = 3
    
    BOT_GENERATION_COUNT: int = 50
    BOT_WIN_DISTRIBUTION: Dict[str, float] = {"bronze": 0.5, "silver": 0.35, "gold": 0.15}
    
    EVENT_MIN_DAMAGE: int = 50
    EVENT_MAX_DAMAGE: int = 200
    EVENT_CRIT_CHANCE: float = 0.15
    EVENT_CRIT_MULT: float = 2.5
    
    PROMO_MIN_CODE_LENGTH: int = 3
    PROMO_MAX_CODE_LENGTH: int = 20
    PROMO_MAX_USES: int = 1000
    PROMO_MAX_HOURS: int = 8760
    
    TOP_LEADERBOARD_SIZE: int = 20
    TOP_PAGE_SIZE: int = 10
    CHALLENGE_TIMEOUT: int = 60
    
    LOG_LEVEL: int = logging.INFO
    LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"


BASE_HP: int = 150
MIN_NAME_LENGTH: int = 2
MAX_NAME_LENGTH: int = 16
DUEL_LOG_LIMIT: int = 10
DUEL_LOG_DISPLAY_LIMIT: int = 5
BROADCAST_DELAY: float = 0.05
BOT_NAME_GENERATION_ATTEMPTS: int = 300
MAX_NOTIFICATIONS_PER_USER: int = 15
PAGINATION_PAGE_SIZE: int = 5


# ============================================================================
# ЭМОДЗИ
# ============================================================================

E_FIRE = "🔥"; E_SWORD = "⚔️"; E_SHIELD = "🛡"; E_HEART = "❤️"
E_SKULL = "💀"; E_TROPHY = "🏆"; E_CRYSTAL = "💎"; E_COIN = "🪙"
E_SLOT = "🎰"; E_DICE = "🎲"; E_GIFT = "🎁"; E_PROMO = "🎟"
E_BOSS = "👹"; E_GLOVE = "🧤"; E_STAR = "⭐"; E_MAGIC = "✨"
E_ZONE_HEAD = "🧠"; E_ZONE_TORSO = "🫀"; E_ZONE_ARMS = "💪"; E_ZONE_LEGS = "🦵"
E_DARTS = "🎯"; E_BASKET = "🏀"; E_SETTINGS = "⚙️"
E_BACK = "⬅️"; E_REFRESH = "🔄"; E_ACCEPT = "✅"; E_REJECT = "❌"
E_INFO = "ℹ️"; E_WARNING = "⚠️"; E_CROWN = "👑"
E_RED = "🔴"; E_BLACK = "⚫"; E_GREEN = "🟢"; E_BLUE = "🔵"
E_STATS = "📊"; E_USERS = "👥"; E_PROFILE = "👤"
E_PREV = "◀️"; E_NEXT = "▶️"
E_MINE = "💣"; E_GEM = "💎"; E_CLOSED = "🟦"
E_ROCKET = "🚀"; E_CRASH = "💥"; E_CASHOUT = "💰"
E_DONATE = "💝"; E_BOMB = "💣"


# ============================================================================
# ИГРОВЫЕ ДАННЫЕ
# ============================================================================

ZONES: List[str] = ["head", "torso", "arms", "legs"]
ZONE_INFO: Dict[str, Dict[str, Any]] = {
    "head": {"name": "Голова", "emoji": E_ZONE_HEAD, "mult": 1.5},
    "torso": {"name": "Торс", "emoji": E_ZONE_TORSO, "mult": 1.0},
    "arms": {"name": "Руки", "emoji": E_ZONE_ARMS, "mult": 0.8},
    "legs": {"name": "Ноги", "emoji": E_ZONE_LEGS, "mult": 0.9},
}


@dataclass
class AttackVariant:
    name: str; description: str; damage_mult: float
    armor_penetration: float; cooldown_rounds: int
    effect: Optional[str] = None


WEAPONS: Dict[str, Dict[str, Any]] = {
    "fists": {"emoji": "👊", "name": "Кулаки", "base_dmg": 10, "price": 0,
              "description": "Базовое оружие новичка.",
              "variants": [
                  AttackVariant("Джеб", "Быстрый удар", 0.8, 0.0, 0, None),
                  AttackVariant("Серия ударов", "3 удара", 1.5, 0.0, 2, "triple"),
                  AttackVariant("Апперкот", "Оглушает", 1.2, 0.1, 3, "stun"),
              ]},
    "dagger": {"emoji": "🗡", "name": "Кинжал", "base_dmg": 14, "price": 200,
               "description": "Быстрое оружие убийцы.",
               "variants": [
                   AttackVariant("Укол", "Пробивает 20%", 1.0, 0.2, 0, None),
                   AttackVariant("Рассечение", "Кровотечение", 1.1, 0.1, 2, "bleed"),
                   AttackVariant("Тысяча порезов", "3 удара, игнор 30%", 1.4, 0.3, 3, "triple"),
               ]},
    "sword": {"emoji": E_SWORD, "name": "Меч", "base_dmg": 20, "price": 500,
              "description": "Классическое оружие воина.",
              "variants": [
                  AttackVariant("Размах", "Стандартная", 1.0, 0.0, 0, None),
                  AttackVariant("Пронзающий выпад", "Игнор 50%", 1.2, 0.5, 2, "pierce"),
                  AttackVariant("Казнь", "Двойной урон", 2.0, 0.0, 4, "exec"),
              ]},
    "axe": {"emoji": "🪓", "name": "Топор", "base_dmg": 26, "price": 800,
            "description": "Тяжёлое оружие варвара.",
            "variants": [
                AttackVariant("Рубящий удар", "Тяжелая", 1.0, 0.1, 0, None),
                AttackVariant("Кровопускание", "Кровотечение", 1.1, 0.0, 3, "bleed"),
                AttackVariant("Сокрушение", "Огромный урон", 1.8, 0.2, 4, None),
            ]},
    "bow": {"emoji": "🏹", "name": "Лук", "base_dmg": 32, "price": 1200,
            "description": "Дальнобойное оружие.",
            "variants": [
                AttackVariant("Прицельный выстрел", "Стандартная", 1.0, 0.3, 0, None),
                AttackVariant("Залп", "2 выстрела", 1.6, 0.2, 2, "triple"),
                AttackVariant("Бронебойная стрела", "Полный игнор", 1.3, 1.0, 3, "pierce"),
            ]},
    "staff": {"emoji": E_FIRE, "name": "Посох", "base_dmg": 38, "price": 1700,
              "description": "Магическое оружие.",
              "variants": [
                  AttackVariant("Магический импульс", "Базовая", 1.0, 0.4, 0, None),
                  AttackVariant("Огненный шар", "Поджигает", 1.2, 0.2, 2, "burn"),
                  AttackVariant("Метеор", "Массовый", 2.2, 0.0, 4, "burn"),
              ]},
    "hammer": {"emoji": "🔨", "name": "Молот", "base_dmg": 46, "price": 2500,
               "description": "Тяжёлое оружие паладина.",
               "variants": [
                   AttackVariant("Удар молотом", "Тяжелая", 1.0, 0.3, 0, None),
                   AttackVariant("Землетрясение", "Оглушает", 1.3, 0.4, 3, "stun"),
                   AttackVariant("Разрушение", "Ломает защиту", 2.0, 0.6, 5, None),
               ]},
    "spear": {"emoji": "🔱", "name": "Копьё", "base_dmg": 28, "price": 950,
              "description": "Длинное оружие.",
              "variants": [
                  AttackVariant("Колющий удар", "Точный", 1.0, 0.25, 0, None),
                  AttackVariant("Круговой взмах", "По площади", 1.3, 0.15, 2, "triple"),
                  AttackVariant("Пронзание", "Полное пробитие", 1.5, 0.7, 3, "pierce"),
              ]},
    "whip": {"emoji": "🪢", "name": "Кнут", "base_dmg": 18, "price": 600,
             "description": "Гибкое оружие.",
             "variants": [
                 AttackVariant("Хлёсткий удар", "Быстрая", 1.0, 0.1, 0, None),
                 AttackVariant("Обвивание", "Замедляет", 1.1, 0.2, 2, "stun"),
                 AttackVariant("Шквал ударов", "Серия", 1.6, 0.15, 3, "triple"),
             ]},
    "scythe": {"emoji": "⚰️", "name": "Коса", "base_dmg": 42, "price": 2200,
               "description": "Оружие Жнеца.",
               "variants": [
                   AttackVariant("Широкий взмах", "По площади", 1.0, 0.2, 0, None),
                   AttackVariant("Жатва душ", "Кровотечение", 1.4, 0.3, 3, "bleed"),
                   AttackVariant("Приговор", "Смертельный", 2.5, 0.4, 5, "exec"),
               ]},
    "wand": {"emoji": "🪄", "name": "Жезл", "base_dmg": 35, "price": 1500,
             "description": "Магический жезл.",
             "variants": [
                 AttackVariant("Искра", "Быстрая", 1.0, 0.35, 0, None),
                 AttackVariant("Молния", "Оглушает", 1.3, 0.45, 2, "stun"),
                 AttackVariant("Цунами огня", "Массовое", 2.0, 0.3, 4, "burn"),
             ]},
    "crossbow": {"emoji": "🏹", "name": "Арбалет", "base_dmg": 30, "price": 1100,
                 "description": "Мощное дальнобойное.",
                 "variants": [
                     AttackVariant("Тяжёлый болт", "Мощный", 1.0, 0.4, 0, None),
                     AttackVariant("Двойной выстрел", "Два болта", 1.5, 0.3, 2, "triple"),
                     AttackVariant("Бронебойный болт", "Пробивает всё", 1.4, 0.9, 3, "pierce"),
                 ]},
}


ARMOR_DATA: Dict[str, List[Dict[str, Any]]] = {
    "head": [
        {"key": "head_none", "name": "Без шлема", "emoji": "👕", "df": 0, "hp": 0, "price": 0, "chance": 0, "dmg_bonus": 0, "desc": "Полная уязвимость"},
        {"key": "head_leather", "name": "Кожаный капюшон", "emoji": "🧢", "df": 2, "hp": 3, "price": 120, "chance": 3, "dmg_bonus": 0, "desc": "+3% шанс"},
        {"key": "head_iron", "name": "Железный шлем", "emoji": "⛑", "df": 4, "hp": 8, "price": 380, "chance": 0, "dmg_bonus": 0, "desc": "Базовая защита"},
        {"key": "head_steel", "name": "Стальной шлем", "emoji": "🪖", "df": 7, "hp": 15, "price": 850, "chance": 0, "dmg_bonus": 10, "desc": "+10% урон"},
        {"key": "head_mithril", "name": "Мифриловый шлем", "emoji": "🎩", "df": 9, "hp": 20, "price": 1400, "chance": 5, "dmg_bonus": 15, "desc": "+5% шанс"},
        {"key": "head_dragon", "name": "Драконий шлем", "emoji": "🐲", "df": 11, "hp": 25, "price": 1800, "chance": 8, "dmg_bonus": 20, "desc": "+8% шанс"},
        {"key": "head_crown", "name": "Корона Лорда", "emoji": "👑", "df": 14, "hp": 30, "price": 3000, "chance": 12, "dmg_bonus": 25, "desc": "Максимальная"},
        {"key": "head_divine", "name": "Божественный венец", "emoji": "👼", "df": 16, "hp": 35, "price": 4500, "chance": 15, "dmg_bonus": 30, "desc": "Легендарная"},
    ],
    "torso": [
        {"key": "torso_none", "name": "Без брони", "emoji": "👕", "df": 0, "hp": 0, "price": 0, "chance": 0, "dmg_bonus": 0, "desc": "Полная уязвимость"},
        {"key": "torso_robe", "name": "Мантия", "emoji": "🥋", "df": 3, "hp": 5, "price": 150, "chance": 4, "dmg_bonus": 0, "desc": "+4% шанс"},
        {"key": "torso_chain", "name": "Кольчуга", "emoji": E_SHIELD, "df": 6, "hp": 12, "price": 480, "chance": 0, "dmg_bonus": 0, "desc": "Надежная"},
        {"key": "torso_plate", "name": "Латный доспех", "emoji": "🏋️", "df": 11, "hp": 22, "price": 1000, "chance": 0, "dmg_bonus": 15, "desc": "+15% урон"},
        {"key": "torso_mithril", "name": "Мифриловая кираса", "emoji": "🦺", "df": 14, "hp": 28, "price": 1600, "chance": 6, "dmg_bonus": 18, "desc": "+6% шанс"},
        {"key": "torso_titan", "name": "Титановый панцирь", "emoji": E_STAR, "df": 17, "hp": 35, "price": 2200, "chance": 10, "dmg_bonus": 25, "desc": "+10% шанс"},
        {"key": "torso_aegis", "name": "Эгида", "emoji": "🌟", "df": 22, "hp": 45, "price": 3500, "chance": 15, "dmg_bonus": 30, "desc": "Легендарная"},
        {"key": "torso_divine", "name": "Божественная броня", "emoji": "✨", "df": 25, "hp": 55, "price": 5000, "chance": 18, "dmg_bonus": 35, "desc": "Абсолютная"},
    ],
    "arms": [
        {"key": "arms_none", "name": "Без наручей", "emoji": "👕", "df": 0, "hp": 0, "price": 0, "chance": 0, "dmg_bonus": 0, "desc": "Полная уязвимость"},
        {"key": "arms_cloth", "name": "Тканевые бинты", "emoji": "🩹", "df": 2, "hp": 2, "price": 100, "chance": 3, "dmg_bonus": 0, "desc": "+3% шанс"},
        {"key": "arms_iron", "name": "Железные наручи", "emoji": E_SHIELD, "df": 4, "hp": 8, "price": 350, "chance": 0, "dmg_bonus": 0, "desc": "Базовая"},
        {"key": "arms_steel", "name": "Стальные латы", "emoji": "⚙️", "df": 7, "hp": 14, "price": 800, "chance": 0, "dmg_bonus": 10, "desc": "+10% урон"},
        {"key": "arms_mithril", "name": "Мифриловые наручи", "emoji": "💍", "df": 9, "hp": 18, "price": 1300, "chance": 5, "dmg_bonus": 15, "desc": "+5% шанс"},
        {"key": "arms_runic", "name": "Рунические наручи", "emoji": "🔮", "df": 11, "hp": 22, "price": 1700, "chance": 8, "dmg_bonus": 20, "desc": "+8% шанс"},
        {"key": "arms_berserk", "name": "Наручи Берсерка", "emoji": "🩸", "df": 9, "hp": 18, "price": 1500, "chance": 5, "dmg_bonus": 35, "desc": "+35% урона"},
        {"key": "arms_divine", "name": "Божественные перчатки", "emoji": "🙏", "df": 13, "hp": 26, "price": 4000, "chance": 12, "dmg_bonus": 28, "desc": "Священная"},
    ],
    "legs": [
        {"key": "legs_none", "name": "Без поножей", "emoji": "👕", "df": 0, "hp": 0, "price": 0, "chance": 0, "dmg_bonus": 0, "desc": "Полная уязвимость"},
        {"key": "legs_cloth", "name": "Тканевые штаны", "emoji": "👖", "df": 2, "hp": 3, "price": 110, "chance": 3, "dmg_bonus": 0, "desc": "+3% шанс"},
        {"key": "legs_iron", "name": "Железные поножи", "emoji": E_SHIELD, "df": 5, "hp": 10, "price": 400, "chance": 0, "dmg_bonus": 0, "desc": "Базовая"},
        {"key": "legs_steel", "name": "Стальные поножи", "emoji": "⚙️", "df": 8, "hp": 16, "price": 900, "chance": 0, "dmg_bonus": 10, "desc": "+10% урон"},
        {"key": "legs_mithril", "name": "Мифриловые поножи", "emoji": "🦿", "df": 10, "hp": 20, "price": 1400, "chance": 6, "dmg_bonus": 15, "desc": "+6% шанс"},
        {"key": "legs_demon", "name": "Демонические поножи", "emoji": "😈", "df": 12, "hp": 25, "price": 1900, "chance": 8, "dmg_bonus": 20, "desc": "+8% шанс"},
        {"key": "legs_wind", "name": "Поножи Ветра", "emoji": E_ZONE_LEGS, "df": 6, "hp": 12, "price": 1100, "chance": 10, "dmg_bonus": 5, "desc": "+10% уворот"},
        {"key": "legs_divine", "name": "Божественные сапоги", "emoji": "👢", "df": 14, "hp": 28, "price": 4200, "chance": 13, "dmg_bonus": 25, "desc": "Священная"},
    ],
}


ARMOR_CACHE: Dict[str, Dict[str, Any]] = {}
def _build_armor_cache() -> None:
    for slot, items in ARMOR_DATA.items():
        for it in items:
            ARMOR_CACHE[it["key"]] = {**it, "slot": slot}
_build_armor_cache()


START_ARMOR_KEYS: List[str] = ["head_none", "torso_none", "arms_none", "legs_none"]
START_WEAPON: str = "fists"
BASE_STATS: Dict[str, int] = {"hp": BASE_HP}


ARENAS: Dict[str, Dict[str, Any]] = {
    "bronze": {"name": "Бронзовая арена", "emoji": "🥉", "min_wins": 0, "max_wins": 9, "prize": 50},
    "silver": {"name": "Серебряная арена", "emoji": "🥈", "min_wins": 10, "max_wins": 29, "prize": 100},
    "gold": {"name": "Золотая арена", "emoji": "🥇", "min_wins": 30, "max_wins": 10**9, "prize": 200},
}
ARENA_ORDER: List[str] = ["bronze", "silver", "gold"]


BOSSES: Dict[str, Dict[str, Any]] = {
    "goblin": {"key": "goblin", "name": "👺 Гоблин-Вождь", "desc": "Хитрый и злой.", "hp": 160, "weapon": "dagger",
               "armor_keys": {"head": "head_leather", "torso": "torso_robe", "arms": "arms_none", "legs": "legs_none"},
               "reward_mult": 3, "min_wins": 0},
    "skeleton": {"key": "skeleton", "name": "💀 Скелет-Воин", "desc": "Нежить с мечом.", "hp": 200, "weapon": "sword",
                 "armor_keys": {"head": "head_iron", "torso": "torso_chain", "arms": "arms_iron", "legs": "legs_iron"},
                 "reward_mult": 4, "min_wins": 3},
    "dragon": {"key": "dragon", "name": "🐉 Древний Дракон", "desc": "Огнедышащий ужас.", "hp": 260, "weapon": "staff",
               "armor_keys": {"head": "head_steel", "torso": "torso_plate", "arms": "arms_iron", "legs": "legs_iron"},
               "reward_mult": 5, "min_wins": 5},
    "orc": {"key": "orc", "name": "👹 Орк-Берсерк", "desc": "Яростный воин.", "hp": 320, "weapon": "axe",
            "armor_keys": {"head": "head_steel", "torso": "torso_plate", "arms": "arms_berserk", "legs": "legs_steel"},
            "reward_mult": 7, "min_wins": 10},
    "lord": {"key": "lord", "name": "👹 Древний Лорд", "desc": "Владыка арены.", "hp": 380, "weapon": "hammer",
             "armor_keys": {"head": "head_dragon", "torso": "torso_titan", "arms": "arms_runic", "legs": "legs_demon"},
             "reward_mult": 10, "min_wins": 15},
    "lich": {"key": "lich", "name": "🧙 Лич-Повелитель", "desc": "Могущественный некромант.", "hp": 420, "weapon": "wand",
             "armor_keys": {"head": "head_mithril", "torso": "torso_mithril", "arms": "arms_runic", "legs": "legs_mithril"},
             "reward_mult": 12, "min_wins": 25},
    "titan": {"key": "titan", "name": "🗿 Каменный Титан", "desc": "Неуязвимая глыба.", "hp": 500, "weapon": "fists",
              "armor_keys": {"head": "head_crown", "torso": "torso_aegis", "arms": "arms_berserk", "legs": "legs_wind"},
              "reward_mult": 15, "min_wins": 35},
    "demon_king": {"key": "demon_king", "name": "😈 Король Демонов", "desc": "Повелитель преисподней.", "hp": 750, "weapon": "scythe",
                   "armor_keys": {"head": "head_divine", "torso": "torso_divine", "arms": "arms_divine", "legs": "legs_divine"},
                   "reward_mult": 25, "min_wins": 50},
}


CHAT_EVENT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "boss": {"name_template": "{emoji} Рейдовый Босс", "emoji": E_BOSS, "base_hp": 2000, "duration_hours": 2.0,
             "reward_per_participant": (50, 150),
             "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n{emoji} <b>Рейдовый Босс</b> появился!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
    "caravan": {"name_template": "🐪 Золотой Караван", "emoji": "🐪", "base_hp": 1000, "duration_hours": 1.0,
                "reward_per_participant": (30, 100),
                "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n🐪 <b>Золотой Караван</b>!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
    "raid": {"name_template": "⚔️ Набег Орков", "emoji": "⚔️", "base_hp": 3000, "duration_hours": 3.0,
             "reward_per_participant": (80, 200),
             "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n⚔️ <b>Набег Орков</b>!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
    "dragon_raid": {"name_template": "🐉 Нашествие Драконов", "emoji": "🐉", "base_hp": 5000, "duration_hours": 4.0,
                    "reward_per_participant": (150, 350),
                    "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n🐉 <b>Нашествие Драконов</b>!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
    "demon_invasion": {"name_template": "😈 Вторжение Демонов", "emoji": "😈", "base_hp": 8000, "duration_hours": 6.0,
                       "reward_per_participant": (250, 600),
                       "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n😈 <b>Вторжение Демонов</b>!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
    "ancient_golem": {"name_template": "🗿 Древний Голем", "emoji": "🗿", "base_hp": 10000, "duration_hours": 8.0,
                      "reward_per_participant": (400, 1000),
                      "announce_text": "🚨 <b>ВНИМАНИЕ!</b>\n\n🗿 <b>Древний Голем</b> пробудился!\nHP: {hp}\n\nКоманда <code>атака</code>!"},
}


# ============================================================================
# УТИЛИТЫ
# ============================================================================

def esc(text: Any) -> str:
    return html.escape(str(text))


def create_mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def build_horizontal_keyboard(buttons: List[Tuple[str, str]], buttons_per_row: int = 2) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not buttons:
        return builder.as_markup()
    row: List[InlineKeyboardButton] = []
    for text, callback_data in buttons:
        row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
        if len(row) == buttons_per_row:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    return builder.as_markup()


def build_vertical_keyboard_with_styles(buttons: List[Tuple[str, str, Optional[str]]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for text, callback_data, style in buttons:
        if style:
            builder.row(InlineKeyboardButton(text=text, callback_data=callback_data, style=style))
        else:
            builder.row(InlineKeyboardButton(text=text, callback_data=callback_data))
    return builder.as_markup()


def build_vertical_keyboard(buttons: List[Tuple[str, str]]) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([(t, c, None) for t, c in buttons])


def build_pagination_keyboard(current_page: int, total_pages: int, base_callback: str,
                              back_callback: str = "arena:menu") -> InlineKeyboardMarkup:
    if total_pages <= 0:
        total_pages = 1
    current_page = max(0, min(current_page, total_pages - 1))
    if total_pages <= 1:
        return build_vertical_keyboard_with_styles([(f"{E_BACK} Назад", back_callback, "success")])
    flat_buttons: List[Tuple[str, str, str]] = []
    if current_page > 0:
        flat_buttons.append((f"{E_PREV} Назад", f"{base_callback}:page:{current_page - 1}", "primary"))
    if current_page < total_pages - 1:
        flat_buttons.append((f"Вперёд {E_NEXT}", f"{base_callback}:page:{current_page + 1}", "primary"))
    flat_buttons.append((f"{E_BACK} Назад", back_callback, "success"))
    return build_vertical_keyboard_with_styles(flat_buttons)


async def safe_edit_message(cb: CallbackQuery, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> bool:
    try:
        await cb.message.edit_text(text[:4090], reply_markup=markup, parse_mode=ParseMode.HTML)
        return True
    except TelegramBadRequest as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str:
            return True
        try:
            await cb.message.answer(text[:4090], reply_markup=markup, parse_mode=ParseMode.HTML)
            return True
        except Exception:
            return False
    except Exception as e:
        logging.error(f"Edit error: {e}")
        return False


async def safe_edit_message_by_id(bot: Bot, chat_id: int, message_id: int, text: str,
                                   markup: Optional[InlineKeyboardMarkup] = None) -> bool:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text[:4090],
                                     reply_markup=markup, parse_mode=ParseMode.HTML)
        return True
    except TelegramBadRequest as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str:
            return True
        return False
    except Exception as e:
        logging.error(f"Edit by id error: {e}")
        return False


def format_number(num: int) -> str:
    return f"{num:,}".replace(",", " ")


def safe_int_parse(value: Any, default: int = 0, min_val: Optional[int] = None,
                   max_val: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and result < min_val:
        return min_val
    if max_val is not None and result > max_val:
        return max_val
    return result


def safe_row_get(row: sqlite3.Row, key: str, default: Any = 0) -> Any:
    try:
        if key in row.keys():
            return row[key]
    except (KeyError, IndexError, TypeError):
        pass
    return default


# ============================================================================
# БАЗА ДАННЫХ
# ============================================================================

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL;")
        self._connection.execute("PRAGMA synchronous=NORMAL;")
        self._connection.execute("PRAGMA cache_size=10000;")
        self._init_schema()
        self._migrate()

    def _init_schema(self) -> None:
        schema = """
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT NOT NULL,
                crystals INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                weapon TEXT NOT NULL DEFAULT 'fists',
                armor_head TEXT NOT NULL DEFAULT 'head_none',
                armor_torso TEXT NOT NULL DEFAULT 'torso_none',
                armor_arms TEXT NOT NULL DEFAULT 'arms_none',
                armor_legs TEXT NOT NULL DEFAULT 'legs_none',
                weapons_owned TEXT NOT NULL DEFAULT 'fists',
                armors_owned TEXT NOT NULL DEFAULT 'head_none,torso_none,arms_none,legs_none',
                banned INTEGER NOT NULL DEFAULT 0,
                is_bot INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL DEFAULT 0,
                last_active REAL NOT NULL DEFAULT 0,
                total_duels INTEGER NOT NULL DEFAULT 0,
                total_crystals_earned INTEGER NOT NULL DEFAULT 0,
                auto_accept INTEGER NOT NULL DEFAULT 0,
                allow_duels INTEGER NOT NULL DEFAULT 1,
                consecutive_losses INTEGER NOT NULL DEFAULT 0,
                total_stars_donated INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                ts REAL NOT NULL,
                seen INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                reward_crystals INTEGER NOT NULL DEFAULT 0,
                reward_wins INTEGER NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 1,
                current_uses INTEGER NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL DEFAULT 0,
                created_by INTEGER NOT NULL,
                created_at REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS promo_activations (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                activated_at REAL NOT NULL,
                PRIMARY KEY (user_id, code)
            );
            CREATE TABLE IF NOT EXISTS chat_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                name TEXT NOT NULL,
                hp INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                started_by INTEGER NOT NULL,
                started_at REAL NOT NULL,
                ends_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                participants TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS player_stats (
                user_id INTEGER PRIMARY KEY,
                boss_kills INTEGER NOT NULL DEFAULT 0,
                casino_wins INTEGER NOT NULL DEFAULT 0,
                casino_losses INTEGER NOT NULL DEFAULT 0,
                event_participations INTEGER NOT NULL DEFAULT 0,
                rp_actions_used INTEGER NOT NULL DEFAULT 0,
                crystals_spent INTEGER NOT NULL DEFAULT 0,
                items_bought INTEGER NOT NULL DEFAULT 0,
                mines_games INTEGER NOT NULL DEFAULT 0,
                mines_wins INTEGER NOT NULL DEFAULT 0,
                crash_games INTEGER NOT NULL DEFAULT 0,
                crash_wins INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, seen);
            CREATE INDEX IF NOT EXISTS ix_players_wins ON players(wins, is_bot, banned);
            CREATE INDEX IF NOT EXISTS ix_events_active ON chat_events(active, ends_at);
        """
        try:
            self._connection.executescript(schema)
            logging.info("Database schema initialized.")
        except sqlite3.Error as e:
            logging.critical(f"Failed to initialize schema: {e}")
            raise

    def _migrate(self) -> None:
        try:
            cols = {row[1] for row in self._connection.execute("PRAGMA table_info(players)").fetchall()}
            if "allow_duels" not in cols:
                self._connection.execute("ALTER TABLE players ADD COLUMN allow_duels INTEGER NOT NULL DEFAULT 1")
            if "consecutive_losses" not in cols:
                self._connection.execute("ALTER TABLE players ADD COLUMN consecutive_losses INTEGER NOT NULL DEFAULT 0")
            if "total_stars_donated" not in cols:
                self._connection.execute("ALTER TABLE players ADD COLUMN total_stars_donated INTEGER NOT NULL DEFAULT 0")
            
            cols_stats = {row[1] for row in self._connection.execute("PRAGMA table_info(player_stats)").fetchall()}
            if "mines_games" not in cols_stats:
                self._connection.execute("ALTER TABLE player_stats ADD COLUMN mines_games INTEGER NOT NULL DEFAULT 0")
            if "mines_wins" not in cols_stats:
                self._connection.execute("ALTER TABLE player_stats ADD COLUMN mines_wins INTEGER NOT NULL DEFAULT 0")
            if "crash_games" not in cols_stats:
                self._connection.execute("ALTER TABLE player_stats ADD COLUMN crash_games INTEGER NOT NULL DEFAULT 0")
            if "crash_wins" not in cols_stats:
                self._connection.execute("ALTER TABLE player_stats ADD COLUMN crash_wins INTEGER NOT NULL DEFAULT 0")
        except sqlite3.Error as e:
            logging.warning(f"Migration warning: {e}")

    def fetch_one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        try:
            return self._connection.execute(sql, args).fetchone()
        except sqlite3.Error as e:
            logging.error(f"DB fetch_one error: {e}")
            return None

    def fetch_all(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        try:
            return self._connection.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            logging.error(f"DB fetch_all error: {e}")
            return []

    def execute(self, sql: str, args: tuple = ()) -> bool:
        try:
            self._connection.execute(sql, args)
            return True
        except sqlite3.Error as e:
            logging.error(f"DB execute error: {e}")
            return False

    def execute_transaction(self, statements: List[Tuple[str, tuple]]) -> bool:
        try:
            self._connection.execute("BEGIN TRANSACTION;")
            for sql, args in statements:
                self._connection.execute(sql, args)
            self._connection.execute("COMMIT;")
            return True
        except sqlite3.Error as e:
            logging.error(f"DB transaction error: {e}")
            try:
                self._connection.execute("ROLLBACK;")
            except sqlite3.Error:
                pass
            return False

    def close(self) -> None:
        if self._connection:
            self._connection.close()


db = DatabaseManager(Config.DB_PATH)


# ============================================================================
# МОДЕЛИ
# ============================================================================

@dataclass
class Fighter:
    name: str; max_hp: int; hp: int; weapon: str
    armor_slots: Dict[str, str] = field(default_factory=dict)
    dots: List[Dict[str, Any]] = field(default_factory=list)
    stun: bool = False
    attack_cooldowns: Dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.weapon not in WEAPONS:
            self.weapon = "fists"
        self.base_weapon_dmg = WEAPONS[self.weapon]["base_dmg"]
        slots = self.armor_slots or {}
        fixed_slots = {}
        for s in ZONES:
            key = slots.get(s) or f"{s}_none"
            if not get_armor_item_by_key(key):
                key = f"{s}_none"
            fixed_slots[s] = key
        self.armor_slots = fixed_slots
        self.armor_def = {}
        total_chance = 0
        total_bonus = 0
        for slot in ZONES:
            item = get_armor_item_by_key(self.armor_slots[slot]) or get_armor_item_by_key(f"{slot}_none")
            self.armor_def[slot] = item["df"]
            total_chance += item["chance"]
            total_bonus += item["dmg_bonus"]
        self.spec_chance = min(total_chance, 70)
        self.spec_dmg_bonus = total_bonus / 100.0

    def is_alive(self) -> bool:
        return self.hp > 0

    def get_armor_def(self, zone: str) -> int:
        return self.armor_def.get(zone, 0)

    def get_weapon_dmg_for_zone(self, zone: str, variant_mult: float = 1.0) -> int:
        zone_mult = ZONE_INFO.get(zone, {}).get("mult", 1.0)
        base = self.base_weapon_dmg * zone_mult * variant_mult
        return max(1, round(base))

    def reduce_cooldowns(self) -> None:
        for idx in list(self.attack_cooldowns.keys()):
            self.attack_cooldowns[idx] -= 1
            if self.attack_cooldowns[idx] <= 0:
                del self.attack_cooldowns[idx]

    def get_available_variants(self) -> List[int]:
        all_variants = list(range(len(WEAPONS[self.weapon]["variants"])))
        return [i for i in all_variants if i not in self.attack_cooldowns]


def get_armor_item_by_key(key: str) -> Optional[Dict[str, Any]]:
    return ARMOR_CACHE.get(key)


def generate_hp_bar(fighter: Fighter, width: int = 12) -> str:
    if fighter.max_hp <= 0:
        return "⬛" * width
    filled = max(0, min(width, int(round(width * fighter.hp / fighter.max_hp))))
    ratio = fighter.hp / fighter.max_hp
    if ratio > 0.6:
        char = "🟩"
    elif ratio > 0.3:
        char = "🟨"
    else:
        char = "🟥"
    return char * filled + "⬛" * (width - filled)


def format_fighter_card(fighter: Fighter) -> str:
    w = WEAPONS[fighter.weapon]
    ad = fighter.armor_def
    cd_str = ""
    if fighter.attack_cooldowns:
        cd_info = [f"Атака {i + 1}: {c}р" for i, c in fighter.attack_cooldowns.items()]
        cd_str = f"\n│ ⏳ КД: {', '.join(cd_info)}"
    return (
        f"│ <b>{fighter.name}</b>\n"
        f"│ {E_HEART} <b>{fighter.hp}</b>/{fighter.max_hp}  {generate_hp_bar(fighter)}{cd_str}\n"
        f"│ {w['emoji']} {w['name']} · баз. урон {fighter.base_weapon_dmg}\n"
        f"│ {E_SHIELD} {E_ZONE_HEAD}{ad['head']} {E_ZONE_TORSO}{ad['torso']} "
        f"{E_ZONE_ARMS}{ad['arms']} {E_ZONE_LEGS}{ad['legs']}"
    )


@dataclass
class Duel:
    a_id: int; b_id: int; a: Fighter; b: Fighter
    attacker_is_a: bool = True
    round_no: int = 1
    atk_zone: Optional[str] = None
    def_zone: Optional[str] = None
    chosen_variant_idx: Optional[int] = None
    log: List[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    is_boss: bool = False
    boss_key: Optional[str] = None
    reward_mult: int = 1
    finished: bool = False
    bot_last_block_round: int = -10
    bot_block_streak: int = 0
    timer_task: Optional[asyncio.Task] = None
    timer_deadline: float = 0.0
    timer_for: Optional[int] = None
    timer_role: Optional[str] = None

    def get_state_for(self, uid: int) -> str:
        if uid == self.a_id:
            return "attacker" if self.attacker_is_a else "defender"
        if uid == self.b_id:
            return "defender" if self.attacker_is_a else "attacker"
        return "none"

    def get_attacker(self) -> Fighter:
        return self.a if self.attacker_is_a else self.b

    def get_defender(self) -> Fighter:
        return self.b if self.attacker_is_a else self.a

    def get_attacker_id(self) -> int:
        return self.a_id if self.attacker_is_a else self.b_id

    def get_defender_id(self) -> int:
        return self.b_id if self.attacker_is_a else self.a_id

    def get_fighter(self, uid: int) -> Optional[Fighter]:
        if uid == self.a_id:
            return self.a
        if uid == self.b_id:
            return self.b
        return None

    def get_opponent(self, uid: int) -> Optional[Fighter]:
        if uid == self.a_id:
            return self.b
        if uid == self.b_id:
            return self.a
        return None

    def add_log(self, message: str) -> None:
        self.log.append(message)
        if len(self.log) > DUEL_LOG_LIMIT:
            self.log = self.log[-DUEL_LOG_LIMIT:]


ACTIVE_DUELS: Dict[int, Duel] = {}


@dataclass
class PendingDuel:
    challenger_id: int; target_id: int
    challenger_msg_id: int; target_msg_id: int
    chat_id: int; created_at: float
    timeout_task: Optional[asyncio.Task] = None


PENDING_DUELS: Dict[Tuple[int, int], PendingDuel] = {}


@dataclass
class ChatEvent:
    event_id: int; event_type: str; name: str
    hp: int; max_hp: int; started_by: int
    started_at: float; ends_at: float
    active: bool = True
    participants: Set[int] = field(default_factory=set)
    damage_log: List[str] = field(default_factory=list)
    total_damage_dealt: int = 0

    def is_active(self) -> bool:
        return self.active and self.hp > 0 and time.time() < self.ends_at

    def take_damage(self, attacker_id: int, attacker_name: str, damage: int, is_crit: bool = False) -> str:
        self.hp = max(0, self.hp - damage)
        self.participants.add(attacker_id)
        self.total_damage_dealt += damage
        crit_text = " 💥 <b>КРИТ!</b>" if is_crit else ""
        log_entry = f"⚔️ {attacker_name} наносит <b>{damage}</b> урона!{crit_text} (Осталось HP: {self.hp}/{self.max_hp})"
        self.damage_log.append(log_entry)
        return log_entry

    def get_participants_count(self) -> int:
        return len(self.participants)

    def get_time_left(self) -> int:
        return max(0, int(self.ends_at - time.time()))


ACTIVE_CHAT_EVENT: Optional[ChatEvent] = None
NEXT_SCHEDULED_EVENT: Optional[float] = None


# ============================================================================
# МИНЫ
# ============================================================================

def calculate_mines_multiplier(mines_count: int, opened_safe: int) -> float:
    total_cells = Config.MINES_FIELD_SIZE
    if opened_safe == 0:
        return 1.0
    mult = 1.0
    for i in range(opened_safe):
        numerator = total_cells - mines_count - i
        denominator = total_cells - i
        if denominator <= 0 or numerator <= 0:
            return mult
        mult *= total_cells / numerator
    return round(mult, 2)


@dataclass
class MinesGame:
    user_id: int
    bet: int
    mines_count: int
    mine_positions: Set[int]
    opened: Set[int] = field(default_factory=set)
    message_id: int = 0
    chat_id: int = 0
    active: bool = True
    started_at: float = field(default_factory=time.time)

    @property
    def current_multiplier(self) -> float:
        return calculate_mines_multiplier(self.mines_count, len(self.opened))

    @property
    def current_winnings(self) -> int:
        return int(self.bet * self.current_multiplier)

    def is_mine(self, cell: int) -> bool:
        return cell in self.mine_positions

    def open_cell(self, cell: int) -> Tuple[bool, str]:
        if not self.active:
            return False, "Игра уже завершена."
        if cell in self.opened:
            return False, "Эта клетка уже открыта."
        if cell < 0 or cell >= Config.MINES_FIELD_SIZE:
            return False, "Неверная клетка."
        if self.is_mine(cell):
            self.active = False
            return False, f"{E_BOMB} <b>БОМБА!</b> Ты наступил на мину."
        self.opened.add(cell)
        safe_total = Config.MINES_FIELD_SIZE - self.mines_count
        if len(self.opened) >= safe_total:
            self.active = False
            return True, f"{E_TROPHY} <b>ПОБЕДА!</b> Все безопасные клетки открыты!"
        return True, f"{E_GEM} Безопасно! Множитель: ×{self.current_multiplier}"

    def cashout(self) -> Tuple[bool, str]:
        if not self.active:
            return False, "Игра уже завершена."
        if len(self.opened) == 0:
            return False, "Открой хотя бы одну клетку."
        self.active = False
        return True, f"{E_CASHOUT} <b>ТЫ ЗАБРАЛ ВЫИГРЫШ!</b>"


ACTIVE_MINES: Dict[int, MinesGame] = {}


def generate_mines_field(game: MinesGame) -> str:
    lines = []
    for row in range(5):
        cells = []
        for col in range(5):
            idx = row * 5 + col
            if idx in game.opened:
                cells.append(E_GEM)
            elif not game.active and idx in game.mine_positions:
                cells.append(E_MINE)
            else:
                cells.append(E_CLOSED)
        lines.append(" ".join(cells))
    return "\n".join(lines)


def get_mines_keyboard(game: MinesGame) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in range(5):
        row_buttons = []
        for col in range(5):
            idx = row * 5 + col
            if idx in game.opened:
                text = E_GEM
                callback = f"mines:opened:{idx}"
            elif not game.active:
                if idx in game.mine_positions:
                    text = E_MINE
                    callback = f"mines:mine:{idx}"
                else:
                    text = "·"
                    callback = f"mines:safe:{idx}"
            else:
                text = "⬜"
                callback = f"mines:cell:{idx}"
            row_buttons.append(InlineKeyboardButton(text=text, callback_data=callback))
        builder.row(*row_buttons)
    
    if game.active and len(game.opened) > 0:
        builder.row(
            InlineKeyboardButton(text=f"{E_CASHOUT} Забрать {game.current_winnings}💎", callback_data="mines:cashout", style="success"),
            InlineKeyboardButton(text=f"{E_REJECT} Сдаться", callback_data="mines:surrender", style="danger")
        )
    else:
        builder.row(InlineKeyboardButton(text=f"{E_BACK} В казино", callback_data="casino:menu", style="primary"))
    
    return builder.as_markup()


# ============================================================================
# КРАШ
# ============================================================================

def generate_crash_point() -> float:
    r = random.random()
    if r < 0.04:
        return 1.0
    crash = 0.99 / (1.0 - r)
    return min(max(crash, 1.01), Config.CRASH_MAX_MULTIPLIER)


@dataclass
class CrashGame:
    user_id: int
    bet: int
    crash_point: float
    current_multiplier: float = 1.00
    started_at: float = field(default_factory=time.time)
    message_id: int = 0
    chat_id: int = 0
    cashed_out: bool = False
    cashout_multiplier: float = 0.0
    crashed: bool = False
    task: Optional[asyncio.Task] = None


ACTIVE_CRASH: Dict[int, CrashGame] = {}


def generate_crash_display(game: CrashGame) -> str:
    if game.crashed:
        multiplier_str = f"{game.crash_point:.2f}"
        return (
            f"{E_CRASH} <b>КРАХ!</b>\n\n"
            f"📈 Множитель достиг: <b>{multiplier_str}x</b>\n"
            f"💸 Ты проиграл: <b>{game.bet}</b> {E_CRYSTAL}\n\n"
            f"<i>В следующий раз забери раньше!</i>"
        )
    if game.cashed_out:
        winnings = int(game.bet * game.cashout_multiplier)
        return (
            f"{E_CASHOUT} <b>ТЫ ЗАБРАЛ!</b>\n\n"
            f"📈 Множитель: <b>{game.cashout_multiplier:.2f}x</b>\n"
            f"💰 Выигрыш: <b>{winnings}</b> {E_CRYSTAL}\n"
            f"🚀 Краш был на: <b>{game.crash_point:.2f}x</b>"
        )
    multiplier_str = f"{game.current_multiplier:.2f}"
    bar_length = 20
    progress = min((game.current_multiplier - 1.0) / max(game.crash_point - 1.0, 0.01), 1.0)
    filled = int(progress * bar_length)
    bar = "🟩" * filled + "⬜" * (bar_length - filled)
    return (
        f"{E_ROCKET} <b>КРАШ</b>\n\n"
        f"📈 Множитель: <b>{multiplier_str}x</b>\n"
        f"[{bar}]\n\n"
        f"💵 Ставка: <b>{game.bet}</b> {E_CRYSTAL}\n"
        f"💰 potential: <b>{int(game.bet * game.current_multiplier)}</b> {E_CRYSTAL}\n"
        f"💥 Краш будет на: <b>???</b>\n\n"
        f"<i>Успей забрать до краха!</i>"
    )


def get_crash_keyboard(game: CrashGame) -> InlineKeyboardMarkup:
    if game.cashed_out or game.crashed:
        return build_vertical_keyboard_with_styles([
            ("🔁 Играть ещё", "crash:play", "primary"),
            (f"{E_BACK} В казино", "casino:menu", "success"),
        ])
    potential = int(game.bet * game.current_multiplier)
    return build_vertical_keyboard_with_styles([
        (f"{E_CASHOUT} Забрать {potential}💎", "crash:cashout", "success"),
    ])


async def crash_tick_loop(game: CrashGame, bot: Bot) -> None:
    try:
        last_update = 0.0
        while not game.cashed_out and not game.crashed:
            await asyncio.sleep(Config.CRASH_TICK_INTERVAL)
            elapsed = time.time() - game.started_at
            game.current_multiplier = 1.0 + elapsed * 0.5
            game.current_multiplier = round(game.current_multiplier, 2)
            
            if game.current_multiplier >= game.crash_point:
                game.crashed = True
                game.current_multiplier = game.crash_point
                db.execute_transaction([
                    ("UPDATE player_stats SET crash_games=crash_games+1 WHERE user_id=?", (game.user_id,)),
                ])
                db.execute("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (game.user_id,))
                break
            
            now = time.time()
            if now - last_update >= 0.5:
                last_update = now
                try:
                    await bot.edit_message_text(
                        chat_id=game.chat_id,
                        message_id=game.message_id,
                        text=generate_crash_display(game),
                        reply_markup=get_crash_keyboard(game),
                        parse_mode=ParseMode.HTML
                    )
                except TelegramBadRequest:
                    pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Crash tick error: {e}")
    finally:
        try:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.message_id,
                text=generate_crash_display(game),
                reply_markup=get_crash_keyboard(game),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


def start_mines_game(uid: int, bet: int, mines_count: int) -> MinesGame:
    all_positions = set(range(Config.MINES_FIELD_SIZE))
    mine_positions = set(random.sample(list(all_positions), mines_count))
    return MinesGame(user_id=uid, bet=bet, mines_count=mines_count, mine_positions=mine_positions)


def start_crash_game(uid: int, bet: int) -> CrashGame:
    crash_point = generate_crash_point()
    return CrashGame(user_id=uid, bet=bet, crash_point=crash_point)


# ============================================================================
# БОЕВАЯ ЛОГИКА
# ============================================================================

def calculate_damage(attacker: Fighter, defender: Fighter, atk_zone: str, def_zone: Optional[str],
                     variant: AttackVariant) -> Tuple[int, str]:
    if def_zone == atk_zone:
        return 0, f"{E_SHIELD} <b>Блок!</b>"
    weapon_dmg = attacker.get_weapon_dmg_for_zone(atk_zone, variant.damage_mult)
    base_armor = defender.get_armor_def(atk_zone)
    effective_armor = max(0, round(base_armor * (1.0 - variant.armor_penetration)))
    final_dmg = max(1, round(weapon_dmg - effective_armor))
    return final_dmg, ""


def process_dots(fighter: Fighter, log: List[str]) -> None:
    for dot in list(fighter.dots):
        fighter.hp = max(0, fighter.hp - dot["dmg"])
        log.append(f"{dot['name']}: {fighter.name} −{dot['dmg']} HP")
        dot["left"] -= 1
        if dot["left"] <= 0:
            fighter.dots.remove(dot)
        if fighter.hp <= 0:
            log.append(f"☠️ {fighter.name} гибнет от эффектов")
            return


def apply_dot_effect(target: Fighter, name: str, dmg: int, rounds: int) -> None:
    target.dots = [d for d in target.dots if d["name"] != name]
    target.dots.append({"name": name, "dmg": dmg, "left": rounds})


def resolve_special_attack(attacker: Fighter, defender: Fighter, atk_zone: str, def_zone: Optional[str],
                           variant: AttackVariant, log: List[str]) -> bool:
    if def_zone == atk_zone:
        log.append(f"{E_SHIELD} {defender.name} заблокировал <b>{variant.name}</b>")
        return True
    effect = variant.effect
    if effect == "triple":
        hits = [max(1, round(calculate_damage(attacker, defender, atk_zone, def_zone, variant)[0] / 3)) for _ in range(3)]
        total_dmg = sum(hits)
        defender.hp = max(0, defender.hp - total_dmg)
        log.append(f"⚡ <b>{variant.name}</b>: {' + '.join(map(str, hits))} = <b>−{total_dmg}</b>")
        return True
    elif effect == "exec":
        dmg, _ = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
        defender.hp = max(0, defender.hp - dmg)
        log.append(f"{E_SWORD} <b>{variant.name}</b>: {attacker.name} → {defender.name} <b>−{dmg}</b>")
        return True
    elif effect == "bleed":
        dmg, _ = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
        defender.hp = max(0, defender.hp - dmg)
        bleed_dmg = max(1, round(defender.max_hp * 0.04))
        apply_dot_effect(defender, "🩸 Кровотечение", bleed_dmg, 3)
        log.append(f"🪓 <b>{variant.name}</b>: −{dmg}, кровь по <b>{bleed_dmg}</b> ×3")
        return True
    elif effect == "pierce":
        dmg, _ = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
        defender.hp = max(0, defender.hp - dmg)
        log.append(f"🏹 <b>{variant.name}</b>: пробивает броню на <b>−{dmg}</b>")
        return True
    elif effect == "burn":
        dmg, _ = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
        defender.hp = max(0, defender.hp - dmg)
        burn_dmg = max(1, round(dmg * 0.4))
        apply_dot_effect(defender, f"{E_FIRE} Горение", burn_dmg, 3)
        log.append(f"{E_FIRE} <b>{variant.name}</b>: −{dmg}, огонь по <b>{burn_dmg}</b> ×3")
        return True
    elif effect == "stun":
        dmg, _ = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
        defender.hp = max(0, defender.hp - dmg)
        defender.stun = True
        log.append(f"🔨 <b>{variant.name}</b>: оглушает цель на <b>−{dmg}</b>")
        return True
    return False


def execute_attack_phase(attacker: Fighter, defender: Fighter, atk_zone: str, def_zone: Optional[str],
                         variant_idx: int, log: List[str]) -> None:
    if attacker.stun:
        attacker.stun = False
        log.append(f"💫 {attacker.name} оглушён и пропускает ход!")
        return
    weapon_data = WEAPONS[attacker.weapon]
    variant = weapon_data["variants"][variant_idx]
    if variant.cooldown_rounds > 0:
        attacker.attack_cooldowns[variant_idx] = variant.cooldown_rounds
    if variant.effect and random.random() * 100 < attacker.spec_chance:
        if resolve_special_attack(attacker, defender, atk_zone, def_zone, variant, log):
            return
    dmg, note = calculate_damage(attacker, defender, atk_zone, def_zone, variant)
    if note:
        log.append(f"{ZONE_INFO[atk_zone]['emoji']} {attacker.name} бьёт — {note}")
    else:
        defender.hp = max(0, defender.hp - dmg)
        log.append(f"👊 {attacker.name} [{variant.name}] → {defender.name} <b>−{dmg}</b>")


def stop_duel_timer(duel: Duel) -> None:
    if duel.timer_task and not duel.timer_task.done():
        duel.timer_task.cancel()
    duel.timer_task = None
    duel.timer_deadline = 0.0
    duel.timer_for = None
    duel.timer_role = None


def terminate_duel(duel: Duel) -> None:
    duel.finished = True
    stop_duel_timer(duel)
    ACTIVE_DUELS.pop(duel.a_id, None)
    if duel.b_id > 0:
        ACTIVE_DUELS.pop(duel.b_id, None)


def start_duel_timer(duel: Duel, uid: int, role: str, bot: Bot) -> None:
    if uid < 0:
        return
    stop_duel_timer(duel)
    duel.timer_for = uid
    duel.timer_role = role
    duel.timer_deadline = time.time() + Config.TURN_TIMEOUT
    duel.timer_task = asyncio.create_task(_timer_runner_task(duel, uid, role, bot))


async def _timer_runner_task(duel: Duel, uid: int, role: str, bot: Bot) -> None:
    try:
        while True:
            if duel.finished:
                return
            time_left = int(round(duel.timer_deadline - time.time()))
            if time_left <= 0:
                break
            await asyncio.sleep(1)
        if duel.finished or duel.timer_for != uid or duel.get_state_for(uid) != role or uid not in ACTIVE_DUELS:
            return
        await handle_timeout_defeat(duel, uid, bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Timer error for {uid}: {e}")


async def handle_timeout_defeat(duel: Duel, loser_uid: int, bot: Bot) -> None:
    loser = duel.get_fighter(loser_uid)
    loser_name = loser.name if loser else "Неизвестный"
    duel.log.append(f"⏱ <b>{loser_name} не успел за {Config.TURN_TIMEOUT} сек!</b>")
    winner_is_a = not (loser_uid == duel.a_id)
    await finalize_duel(duel, winner_is_a=winner_is_a, bot=bot, reason="timeout")


# ============================================================================
# ИИ БОТА
# ============================================================================

def get_player_armor_slots(player_row: sqlite3.Row) -> Dict[str, str]:
    if not player_row:
        return {s: f"{s}_none" for s in ZONES}
    return {
        "head": player_row["armor_head"] or "head_none",
        "torso": player_row["armor_torso"] or "torso_none",
        "arms": player_row["armor_arms"] or "arms_none",
        "legs": player_row["armor_legs"] or "legs_none",
    }


def create_fighter_from_db(player_row: sqlite3.Row) -> Fighter:
    slots = get_player_armor_slots(player_row)
    total_hp = BASE_STATS["hp"]
    for key in slots.values():
        item = get_armor_item_by_key(key)
        if item:
            total_hp += item.get("hp", 0)
    weapon = player_row["weapon"] if player_row["weapon"] in WEAPONS else "fists"
    return Fighter(name=esc(player_row["name"]), max_hp=total_hp, hp=total_hp, weapon=weapon, armor_slots=slots)


def determine_arena(wins: int) -> str:
    for k in ARENA_ORDER:
        if ARENAS[k]["min_wins"] <= wins <= ARENAS[k]["max_wins"]:
            return k
    return "gold"


HUMAN_NAMES: List[str] = [
    "Максим", "Артём", "Данил", "Кирилл", "Егор", "Иван", "Никита", "Рома",
    "Саня", "Дима", "Влад", "Серёга", "Паша", "Толя", "Женя", "Костя",
    "Лёха", "Миша", "Гриша", "Стас", "Олег", "Ден", "Марк", "Тимур",
    "Алина", "Катя", "Настя", "Даша", "Лера", "Соня", "Вика", "Полина",
    "Крис", "Милана", "Аня", "Юля", "Оля", "Маша", "Ксюша", "Ника",
]

HUMAN_TITLES: List[str] = ["", "", "", "xd", "pro", "god", "real", "top", "_", "007", "boss", "king"]


def ensure_masked_bots_exist(target_count: int = 50) -> None:
    existing_names = {r["name"].lower() for r in db.fetch_all("SELECT name FROM players")}
    bots = db.fetch_all("SELECT user_id, wins FROM players WHERE is_bot=1")
    need = max(0, target_count - len(bots))
    for _ in range(need):
        name = ""
        for _ in range(BOT_NAME_GENERATION_ATTEMPTS):
            base = random.choice(HUMAN_NAMES)
            title = random.choice(HUMAN_TITLES)
            suffix = str(random.randint(1, 99)) if random.random() < 0.35 else ""
            candidate = f"{base}{title}{suffix}"
            if candidate.lower() not in existing_names and MIN_NAME_LENGTH <= len(candidate) <= 16:
                existing_names.add(candidate.lower())
                name = candidate
                break
        if not name:
            name = f"Игрок{random.randint(10000, 99999)}"
        uid = -random.randint(10_000_000, 99_999_999)
        arena_rand = random.random()
        if arena_rand < Config.BOT_WIN_DISTRIBUTION["bronze"]:
            wins = random.randint(0, 9)
        elif arena_rand < Config.BOT_WIN_DISTRIBUTION["bronze"] + Config.BOT_WIN_DISTRIBUTION["silver"]:
            wins = random.randint(10, 29)
        else:
            wins = random.randint(30, 60)
        losses = random.randint(max(0, wins // 2), wins * 2 + 3)
        arena_key = determine_arena(wins)
        if arena_key == "bronze":
            weapon = random.choice(["fists", "dagger", "sword", "whip"])
            tier_max = 2
        elif arena_key == "silver":
            weapon = random.choice(["sword", "axe", "bow", "dagger", "spear", "crossbow"])
            tier_max = 4
        else:
            weapon = random.choice(["bow", "staff", "hammer", "axe", "sword", "scythe", "wand", "crossbow"])
            tier_max = 6
        slots = {}
        for s in ZONES:
            items = ARMOR_DATA[s]
            idx = min(random.randint(0, tier_max), len(items) - 1)
            slots[s] = items[idx]["key"]
        owned_armors = set(list(slots.values()) + START_ARMOR_KEYS)
        db.execute(
            """INSERT OR IGNORE INTO players (user_id, username, name, crystals, wins, losses, weapon,
                armor_head, armor_torso, armor_arms, armor_legs, weapons_owned, armors_owned, is_bot, created, last_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, None, name, random.randint(0, 400), wins, losses, weapon,
             slots["head"], slots["torso"], slots["arms"], slots["legs"],
             weapon, ",".join(owned_armors), 1, time.time(), time.time())
        )


def pick_balanced_opponent(player_uid: int, player_wins: int) -> Optional[int]:
    arena = determine_arena(player_wins)
    limits = ARENAS[arena]
    humans = [r["user_id"] for r in db.fetch_all(
        """SELECT user_id FROM players WHERE user_id != ? AND banned=0 AND is_bot=0
           AND allow_duels=1 AND wins BETWEEN ? AND ? ORDER BY RANDOM() LIMIT 6""",
        (player_uid, limits["min_wins"], limits["max_wins"])
    )]
    bots = [r["user_id"] for r in db.fetch_all(
        """SELECT user_id FROM players WHERE is_bot=1 AND banned=0
           AND wins BETWEEN ? AND ? ORDER BY RANDOM() LIMIT 6""",
        (limits["min_wins"], limits["max_wins"])
    )]
    if humans and bots:
        return random.choice(bots if random.random() < 0.6 else humans)
    if humans:
        return random.choice(humans)
    if bots:
        return random.choice(bots)
    ensure_masked_bots_exist(10)
    rows = db.fetch_all(
        """SELECT user_id FROM players WHERE is_bot=1 AND wins BETWEEN ? AND ?
           ORDER BY RANDOM() LIMIT 1""",
        (limits["min_wins"], limits["max_wins"])
    )
    return rows[0]["user_id"] if rows else None


def bot_decide_attack_zone(attacker: Fighter, defender: Fighter) -> str:
    if random.random() < 0.10:
        return random.choice(ZONES)
    if defender.hp <= defender.max_hp * 0.30:
        return max(ZONES, key=lambda z: attacker.get_weapon_dmg_for_zone(z))
    def score_zone(z: str) -> tuple:
        dmg = attacker.get_weapon_dmg_for_zone(z) - defender.get_armor_def(z)
        return (dmg, ZONE_INFO[z]["mult"])
    return max(ZONES, key=score_zone)


def bot_decide_attack_variant(attacker: Fighter) -> int:
    variants = WEAPONS[attacker.weapon]["variants"]
    available = attacker.get_available_variants()
    if not available:
        return 0
    return max(available, key=lambda i: variants[i].damage_mult)


def bot_decide_to_defend(duel: Duel, bot_is_a: bool) -> bool:
    if duel.bot_block_streak >= 2 or duel.round_no - duel.bot_last_block_round < 3:
        return False
    bot_fighter = duel.a if bot_is_a else duel.b
    hp_ratio = bot_fighter.hp / bot_fighter.max_hp
    if hp_ratio < 0.30:
        base_chance = 0.65
    elif hp_ratio < 0.60:
        base_chance = 0.40
    else:
        base_chance = 0.25
    return random.random() < base_chance


def bot_decide_defend_zone(attacker: Fighter, defender: Fighter) -> str:
    def danger_level(z: str) -> int:
        return attacker.get_weapon_dmg_for_zone(z) - defender.get_armor_def(z)
    sorted_zones = sorted(ZONES, key=danger_level, reverse=True)
    if random.random() < 0.25 and len(sorted_zones) > 1:
        return sorted_zones[1]
    return sorted_zones[0]


# ============================================================================
# КАЗИНО
# ============================================================================

async def play_casino_slots_animated(chat_id: int, bet: int, uid: int, bot: Bot) -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    sent_message = await bot.send_dice(chat_id=chat_id, emoji="🎰")
    dice_value = sent_message.dice.value
    if dice_value == 1:
        mult = 10
        win = bet * mult
        db.execute_transaction([
            ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (win, uid)),
            ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
        ])
        return f"{E_SLOT} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>ДЖЕКПОТ ×{mult}!</b>\n💎 +{win} кристаллов", None, True
    else:
        db.execute_transaction([
            ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
            ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
        ])
        return f"{E_SLOT} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Нет комбинации.</b>\n💎 −{bet} кристаллов", None, False


async def play_casino_dice_game(chat_id: int, bet: int, uid: int, bot: Bot, mode: str, value: Any = None) -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    sent_message = await bot.send_dice(chat_id=chat_id, emoji="🎲")
    dice_value = sent_message.dice.value
    win = False
    mult = 0
    if mode == "even_odd":
        is_even = (dice_value % 2 == 0)
        if (value == "even" and is_even) or (value == "odd" and not is_even):
            mult = 2
            win = True
    elif mode == "high_low":
        if (value == "high" and dice_value >= 4) or (value == "low" and dice_value <= 3):
            mult = 2
            win = True
    elif mode == "number":
        if dice_value == value:
            mult = 6
            win = True
    if win:
        payout = bet * mult
        db.execute_transaction([
            ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
            ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
        ])
        return f"{E_DICE} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>Победа ×{mult}!</b>\n💎 +{payout} кристаллов", None, True
    else:
        db.execute_transaction([
            ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
            ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
        ])
        return f"{E_DICE} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Поражение.</b>\n💎 −{bet} кристаллов", None, False


async def play_casino_darts_animated(chat_id: int, bet: int, uid: int, bot: Bot, bet_on_miss: bool = False) -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    sent_message = await bot.send_dice(chat_id=chat_id, emoji="🎯")
    dice_value = sent_message.dice.value
    is_hit = dice_value >= 4
    if bet_on_miss:
        if not is_hit:
            payout = int(bet * 1.9)
            db.execute_transaction([
                ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
                ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_DARTS} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>Промах! Ты выиграл!</b>\n💎 +{payout} кристаллов", None, True
        else:
            db.execute_transaction([
                ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
                ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_DARTS} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Попадание. Ты проиграл.</b>\n💎 −{bet} кристаллов", None, False
    else:
        if is_hit:
            payout = int(bet * 1.9)
            db.execute_transaction([
                ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
                ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_DARTS} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>Попадание!</b>\n💎 +{payout} кристаллов", None, True
        else:
            db.execute_transaction([
                ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
                ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_DARTS} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Промах.</b>\n💎 −{bet} кристаллов", None, False


async def play_casino_basketball_animated(chat_id: int, bet: int, uid: int, bot: Bot, bet_on_miss: bool = False) -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    sent_message = await bot.send_dice(chat_id=chat_id, emoji="🏀")
    dice_value = sent_message.dice.value
    is_hit = dice_value == 5
    if bet_on_miss:
        if not is_hit:
            payout = int(bet * 1.9)
            db.execute_transaction([
                ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
                ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_BASKET} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>Промах! Ты выиграл!</b>\n💎 +{payout} кристаллов", None, True
        else:
            db.execute_transaction([
                ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
                ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_BASKET} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Слэм-данк. Ты проиграл.</b>\n💎 −{bet} кристаллов", None, False
    else:
        if is_hit:
            payout = int(bet * 1.9)
            db.execute_transaction([
                ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
                ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_BASKET} Выпало: <b>{dice_value}</b>\n\n{E_TROPHY} <b>СЛЭМ-ДАНК!</b>\n💎 +{payout} кристаллов", None, True
        else:
            db.execute_transaction([
                ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
                ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
            ])
            return f"{E_BASKET} Выпало: <b>{dice_value}</b>\n\n{E_SKULL} <b>Промах.</b>\n💎 −{bet} кристаллов", None, False


def play_casino_roulette(uid: int, bet: int, bet_type: str, bet_value: Any = None) -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    reds = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    num = random.randint(0, 36)
    if num == 0:
        res_color = "green"
        color_emoji = E_GREEN
    elif num in reds:
        res_color = "red"
        color_emoji = E_RED
    else:
        res_color = "black"
        color_emoji = E_BLACK
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    win = False
    mult = 0
    if bet_type == "color":
        if bet_value == res_color:
            mult = 14 if res_color == "green" else 2
            win = True
    elif bet_type == "even_odd":
        if num != 0:
            is_even = (num % 2 == 0)
            if (bet_value == "even" and is_even) or (bet_value == "odd" and not is_even):
                mult = 2
                win = True
    elif bet_type == "half":
        if num != 0:
            if (bet_value == "low" and 1 <= num <= 18) or (bet_value == "high" and 19 <= num <= 36):
                mult = 2
                win = True
    elif bet_type == "number":
        if num == bet_value:
            mult = 36
            win = True
    elif bet_type == "dozen":
        if num != 0:
            if (bet_value == 1 and 1 <= num <= 12) or (bet_value == 2 and 13 <= num <= 24) or (bet_value == 3 and 25 <= num <= 36):
                mult = 3
                win = True
    if win:
        payout = bet * mult
        db.execute_transaction([
            ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
            ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
        ])
        return f"🎡 Выпало: {color_emoji} <b>{num}</b>\n\n{E_TROPHY} <b>Победа ×{mult}!</b>\n💎 +{payout} кристаллов", None, True
    else:
        db.execute_transaction([
            ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
            ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
        ])
        return f"🎡 Выпало: {color_emoji} <b>{num}</b>\n\n{E_SKULL} <b>Поражение.</b>\n💎 −{bet} кристаллов", None, False


def play_casino_coin(uid: int, bet: int, choice: str = "heads") -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    result = random.choice(["heads", "tails"])
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    result_text = "Орёл" if result == "heads" else "Решка"
    result_emoji = "🔵" if result == "heads" else "🔴"
    if result == choice:
        db.execute_transaction([
            ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (bet * 2, uid)),
            ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
        ])
        return f"{E_COIN} Выпало: {result_emoji} <b>{result_text}</b>\n\n{E_TROPHY} <b>Победа!</b>\n💎 +{bet * 2} кристаллов", None, True
    db.execute_transaction([
        ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
        ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
    ])
    return f"{E_COIN} Выпало: {result_emoji} <b>{result_text}</b>\n\n{E_SKULL} <b>Поражение.</b>\n💎 −{bet} кристаллов", None, False


def play_casino_highlow(uid: int, bet: int, choice: str = "high") -> Tuple[Optional[str], Optional[str], bool]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p or p["crystals"] < bet:
        return None, "Недостаточно кристаллов.", False
    if bet < Config.CASINO_MIN_BET:
        return None, f"Минимальная ставка: {Config.CASINO_MIN_BET} {E_CRYSTAL}", False
    result_num = random.randint(1, 100)
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, uid))])
    if result_num == 50:
        db.execute_transaction([("UPDATE players SET crystals=crystals+? WHERE user_id=?", (bet, uid))])
        return f"📊 Выпало: <b>{result_num}</b>\n\n🤝 <b>Ровно 50!</b> Ставка возвращена.", None, False
    win = (choice == "high" and result_num > 50) or (choice == "low" and result_num < 50)
    if win:
        payout = int(bet * 1.9)
        db.execute_transaction([
            ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (payout, uid)),
            ("UPDATE player_stats SET casino_wins=casino_wins+1 WHERE user_id=?", (uid,)),
        ])
        return f"📊 Выпало: <b>{result_num}</b>\n\n{E_TROPHY} <b>Победа!</b>\n💎 +{payout} кристаллов", None, True
    db.execute_transaction([
        ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (uid,)),
        ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,)),
    ])
    return f"📊 Выпало: <b>{result_num}</b>\n\n{E_SKULL} <b>Поражение.</b>\n💎 −{bet} кристаллов", None, False


# ============================================================================
# ЧАТОВЫЕ СОБЫТИЯ
# ============================================================================

def is_admin(uid: int) -> bool:
    return uid == Config.ADMIN_ID


def is_user_banned(uid: int) -> bool:
    p = db.fetch_one("SELECT banned FROM players WHERE user_id=?", (uid,))
    return bool(p and p["banned"])


def notify_player(uid: int, text: str) -> None:
    if uid <= 0:
        return
    db.execute("INSERT INTO notifications (user_id, text, ts) VALUES (?,?,?)", (uid, text, time.time()))


def spawn_chat_event(event_type: str, started_by: int, custom_hp: Optional[int] = None,
                     custom_duration: Optional[float] = None) -> Optional[ChatEvent]:
    global ACTIVE_CHAT_EVENT
    if ACTIVE_CHAT_EVENT and ACTIVE_CHAT_EVENT.is_active():
        return None
    template = CHAT_EVENT_TEMPLATES.get(event_type)
    if not template:
        return None
    hp = custom_hp or template["base_hp"]
    duration = custom_duration or template["duration_hours"]
    name = template["name_template"].format(emoji=template["emoji"])
    now = time.time()
    ends_at = now + (duration * 3600)
    event = ChatEvent(event_id=int(now), event_type=event_type, name=name, hp=hp, max_hp=hp,
                      started_by=started_by, started_at=now, ends_at=ends_at)
    ACTIVE_CHAT_EVENT = event
    db.execute(
        """INSERT INTO chat_events (event_type, name, hp, max_hp, started_by, started_at, ends_at, active)
           VALUES (?,?,?,?,?,?,?,1)""",
        (event_type, name, hp, hp, started_by, now, ends_at)
    )
    return event


def attack_chat_event(attacker_id: int, attacker_name: str) -> Optional[str]:
    global ACTIVE_CHAT_EVENT
    if not ACTIVE_CHAT_EVENT or not ACTIVE_CHAT_EVENT.is_active():
        return None
    if is_user_banned(attacker_id):
        return "🚫 Ты забанен и не можешь участвовать в событиях."
    base_dmg = random.randint(Config.EVENT_MIN_DAMAGE, Config.EVENT_MAX_DAMAGE)
    is_crit = random.random() < Config.EVENT_CRIT_CHANCE
    if is_crit:
        base_dmg = int(base_dmg * Config.EVENT_CRIT_MULT)
    log_entry = ACTIVE_CHAT_EVENT.take_damage(attacker_id, attacker_name, base_dmg, is_crit)
    db.execute("UPDATE player_stats SET event_participations=event_participations+1 WHERE user_id=?", (attacker_id,))
    if ACTIVE_CHAT_EVENT.hp <= 0:
        ACTIVE_CHAT_EVENT.active = False
        db.execute("UPDATE chat_events SET active=0 WHERE event_id=?", (ACTIVE_CHAT_EVENT.event_id,))
        template = CHAT_EVENT_TEMPLATES.get(ACTIVE_CHAT_EVENT.event_type, {})
        reward_range = template.get("reward_per_participant", (30, 100))
        total_rewards = 0
        for pid in ACTIVE_CHAT_EVENT.participants:
            reward = random.randint(reward_range[0], reward_range[1])
            db.execute("UPDATE players SET crystals=crystals+? WHERE user_id=?", (reward, pid))
            total_rewards += reward
        log_entry += (
            f"\n\n{E_TROPHY} <b>СОБЫТИЕ ЗАВЕРШЕНО!</b>\n"
            f"👥 Участников: {ACTIVE_CHAT_EVENT.get_participants_count()}\n"
            f"💎 Роздано наград: {total_rewards}"
        )
        ACTIVE_CHAT_EVENT = None
    return log_entry


def get_chat_event_status() -> Optional[str]:
    global ACTIVE_CHAT_EVENT
    if not ACTIVE_CHAT_EVENT or not ACTIVE_CHAT_EVENT.is_active():
        return None
    time_left = ACTIVE_CHAT_EVENT.get_time_left()
    minutes = time_left // 60
    seconds = time_left % 60
    hp_percent = (ACTIVE_CHAT_EVENT.hp / ACTIVE_CHAT_EVENT.max_hp) * 100
    return (
        f"{ACTIVE_CHAT_EVENT.name}\n"
        f"❤️ HP: <b>{ACTIVE_CHAT_EVENT.hp}</b>/{ACTIVE_CHAT_EVENT.max_hp} ({hp_percent:.0f}%)\n"
        f"👥 Участников: <b>{ACTIVE_CHAT_EVENT.get_participants_count()}</b>\n"
        f"⏱ Осталось: <b>{minutes}:{seconds:02d}</b>\n\n"
        f"Используйте команду <code>атака</code> для нанесения урона!"
    )


# ============================================================================
# ПРОМОКОДЫ
# ============================================================================

def create_promo_code(code: str, reward_crystals: int, reward_wins: int, max_uses: int,
                      hours_valid: int, created_by: int) -> Tuple[bool, str]:
    code = code.strip().upper()
    if not code or len(code) < Config.PROMO_MIN_CODE_LENGTH or len(code) > Config.PROMO_MAX_CODE_LENGTH:
        return False, f"Код должен быть от {Config.PROMO_MIN_CODE_LENGTH} до {Config.PROMO_MAX_CODE_LENGTH} символов."
    if not re.match(r'^[A-Z0-9_-]+$', code):
        return False, "Код может содержать только буквы, цифры, _ и -"
    if reward_crystals < 0 or reward_wins < 0:
        return False, "Награды не могут быть отрицательными."
    if max_uses < 1 or max_uses > Config.PROMO_MAX_USES:
        return False, f"Максимум активаций: от 1 до {Config.PROMO_MAX_USES}."
    if hours_valid < 1 or hours_valid > Config.PROMO_MAX_HOURS:
        return False, f"Срок действия: от 1 до {Config.PROMO_MAX_HOURS} часов."
    existing = db.fetch_one("SELECT code FROM promo_codes WHERE code=?", (code,))
    if existing:
        return False, f"Промокод <code>{code}</code> уже существует."
    now = time.time()
    expires_at = now + (hours_valid * 3600)
    db.execute(
        """INSERT INTO promo_codes
           (code, reward_crystals, reward_wins, max_uses, current_uses, expires_at, created_by, created_at, active)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?, 1)""",
        (code, reward_crystals, reward_wins, max_uses, expires_at, created_by, now)
    )
    return True, (
        f"{E_PROMO} Промокод <code>{code}</code> создан!\n\n"
        f"💎 Кристаллы: {reward_crystals}\n🏆 Победы: {reward_wins}\n"
        f"👥 Макс. активаций: {max_uses}\n⏳ Действует: {hours_valid} ч."
    )


def activate_promo_code(user_id: int, code: str) -> Tuple[bool, str]:
    code = code.strip().upper()
    player = db.fetch_one("SELECT * FROM players WHERE user_id=?", (user_id,))
    if not player:
        return False, "Сначала отправь /start в ЛС бота."
    if player["banned"]:
        return False, "🚫 Тебе недоступна активация промокодов."
    promo = db.fetch_one("SELECT * FROM promo_codes WHERE code=?", (code,))
    if not promo:
        return False, f"❌ Промокод <code>{code}</code> не найден."
    if not promo["active"]:
        return False, f"❌ Промокод <code>{code}</code> деактивирован."
    if promo["expires_at"] < time.time():
        return False, f"❌ Промокод <code>{code}</code> истёк."
    if promo["current_uses"] >= promo["max_uses"]:
        return False, f"❌ Промокод <code>{code}</code> исчерпан."
    already = db.fetch_one("SELECT 1 FROM promo_activations WHERE user_id=? AND code=?", (user_id, code))
    if already:
        return False, f"❌ Ты уже активировал промокод <code>{code}</code>."
    now = time.time()
    if not db.execute_transaction([
        ("INSERT INTO promo_activations (user_id, code, activated_at) VALUES (?, ?, ?)", (user_id, code, now)),
        ("UPDATE promo_codes SET current_uses=current_uses+1 WHERE code=?", (code,)),
    ]):
        return False, "❌ Ошибка активации. Попробуй позже."
    rewards = []
    if promo["reward_crystals"] > 0:
        db.execute("UPDATE players SET crystals=crystals+? WHERE user_id=?", (promo["reward_crystals"], user_id))
        rewards.append(f"💎 +{promo['reward_crystals']} кристаллов")
    if promo["reward_wins"] > 0:
        db.execute("UPDATE players SET wins=wins+? WHERE user_id=?", (promo["reward_wins"], user_id))
        rewards.append(f"🏆 +{promo['reward_wins']} побед")
    rewards_text = "\n".join(rewards) if rewards else "🎁 Секретный бонус!"
    remaining = promo["max_uses"] - promo["current_uses"] - 1
    return True, (
        f"{E_GIFT} <b>ПРОМОКОД АКТИВИРОВАН!</b>\n\n"
        f"🎟 Код: <code>{code}</code>\n{rewards_text}\n\n"
        f"📊 Осталось активаций: {remaining}/{promo['max_uses']}"
    )


# ============================================================================
# RP СИСТЕМА
# ============================================================================

RP_ACTIONS: Dict[str, Tuple[str, str]] = {
    "ударить": ("👊", "ударил(а)"),
    "обнять": ("🤗", "обнял(а)"),
    "поцеловать": ("😘", "поцеловал(а)"),
    "пнуть": ("🦵", "пнул(а)"),
    "погладить": ("🤚", "погладил(а)"),
    "укусить": ("😬", "укусил(а)"),
    "пожать": ("🤝", "пожал(а) руку"),
    "толкнуть": ("💥", "толкнул(а)"),
    "кинуть": ("🥊", "кинул(а) в"),
    "лечить": ("💊", "подлечил(а)"),
    "игнорировать": ("💅", "проигнорировал(а)"),
    "смеяться": ("😂", "посмеялся(ась) над"),
    "плакать": ("😭", "заплакал(а) у ног"),
    "танцевать": ("💃", "станцевал(а) для"),
    "шлепнуть": ("👋", "шлепнул(а)"),
    "обозвать": ("🤬", "обозвал(а)"),
    "восхититься": ("😍", "восхитился(ась)"),
    "испугаться": ("😱", "испугался(ась)"),
    "подмигнуть": ("😉", "подмигнул(а)"),
    "пожать_плечами": ("🤷", "пожал(а) плечами при виде"),
    "покормить": ("🍕", "покормил(а)"),
    "напоить": ("🍺", "напоил(а)"),
    "щекотать": ("🤣", "пощекотал(а)"),
    "благословить": ("🙏", "благословил(а)"),
    "проклясть": ("💀", "проклял(а)"),
}

RP_COOLDOWNS: Dict[Tuple[int, int, str], float] = {}


def generate_rp_text(actor_id: int, actor_name: str, target_id: int, target_name: str, action_key: str) -> str:
    emoji, verb = RP_ACTIONS.get(action_key, ("✨", "взаимодействовал(а) с"))
    actor_mention = create_mention(actor_id, actor_name)
    target_mention = create_mention(target_id, target_name)
    return f"{emoji} {actor_mention} {verb} {target_mention}!"


def cleanup_rp_cooldowns() -> None:
    now = time.time()
    old_keys = [k for k, v in RP_COOLDOWNS.items() if now - v > 60]
    for k in old_keys:
        del RP_COOLDOWNS[k]


# ============================================================================
# ПАРСЕР ЦЕЛЕЙ
# ============================================================================

def resolve_command_target(m: Message, command_word: str) -> Tuple[Optional[int], Optional[str]]:
    if m.reply_to_message and m.reply_to_message.from_user and not m.reply_to_message.from_user.is_bot:
        return m.reply_to_message.from_user.id, None
    text = m.text or ""
    if text.lower().startswith(command_word.lower()):
        rest_of_text = text[len(command_word):].strip()
    else:
        rest_of_text = text
    match = re.search(r'@(\w+)|(-?\d+)', rest_of_text)
    if match:
        val = match.group(1) or match.group(2)
        if val.lstrip('-').isdigit():
            row = db.fetch_one("SELECT user_id FROM players WHERE user_id=? AND banned=0", (int(val),))
            if row:
                return row["user_id"], None
        else:
            row = db.fetch_one(
                """SELECT user_id FROM players
                   WHERE (LOWER(username)=LOWER(?) OR LOWER(name)=LOWER(?)) AND banned=0 LIMIT 1""",
                (val, val)
            )
            if row:
                return row["user_id"], None
    if m.chat.type == "private":
        return None, f"Укажи цель: ответь на сообщение или напиши <code>{command_word} @user</code> / <code>{command_word} ID</code>"
    return None, f"⚠️ В группе команда работает <b>ответом</b> или через <code>@username</code> / <code>ID</code>."


# ============================================================================
# МЕНЮ
# ============================================================================

BTN_ARENA = "⚔️ Арена"
BTN_CASINO = "🎰 Казино"
BTN_GEAR = "🎒 Снаряжение"
BTN_TOP = "🏆 Топ"
MENU_TEXTS = {BTN_ARENA, BTN_CASINO, BTN_GEAR, BTN_TOP}

MENU_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_ARENA), KeyboardButton(text=BTN_CASINO)],
        [KeyboardButton(text=BTN_GEAR), KeyboardButton(text=BTN_TOP)],
    ],
    resize_keyboard=True,
)


# ============================================================================
# UI ГЕНЕРАТОРЫ
# ============================================================================

def generate_arena_menu_screen(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    a = ARENAS[determine_arena(p["wins"])]
    text = (
        f"╔══════════════════════════╗\n      ⚔️ <b>АРЕНА ДУЭЛЯНТОВ</b>\n╚══════════════════════════╝\n\n"
        f"{E_TROPHY} Победы: <b>{p['wins']}</b>\n"
        f"{E_SKULL} Поражения: {p['losses']}\n"
        f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>\n"
        f"📍 {a['emoji']} <b>{a['name']}</b>\n\n"
        f"🥉 Бронза — 0–9 побед · <b>{ARENAS['bronze']['prize']} {E_CRYSTAL}</b>\n"
        f"🥈 Серебро — 10–29 побед · <b>{ARENAS['silver']['prize']} {E_CRYSTAL}</b>\n"
        f"🥇 Золото — 30+ побед · <b>{ARENAS['gold']['prize']} {E_CRYSTAL}</b>"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🎲 Найти соперника", "arena:find", "success"),
        ("👹 Боссы", "arena:bosses", "danger"),
        ("📋 Список соперников", "arena:list", "primary"),
        ("🔎 Вызвать по нику", "arena:find_name", "primary"),
        ("🏆 Топ арен", "top:cur", "primary"),
        (f"{E_PROFILE} Мой профиль", "duel:myprofile", "success"),
    ])
    return text, kb


def generate_bosses_menu_screen(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    lines = ["╔══════════════════════════╗\n      👹 <b>БОССЫ АРЕНЫ</b>\n╚══════════════════════════╝\n"]
    buttons = []
    for bkey, b in BOSSES.items():
        locked = p["wins"] < b["min_wins"]
        lock_text = f"🔒 нужен {b['min_wins']} {E_TROPHY}" if locked else f"награда ×{b['reward_mult']}"
        lines.append(f"{b['name']}\n  ❤️ HP {b['hp']} · ⚔️ {WEAPONS[b['weapon']]['name']}\n  {b['desc']}\n  → {lock_text}\n")
        buttons.append((b["name"] if not locked else f"{b['name']} 🔒", f"arena:boss:{bkey}", "danger" if not locked else "primary"))
    buttons.append((f"{E_BACK} Назад", "arena:menu", "success"))
    return "\n".join(lines), build_vertical_keyboard_with_styles(buttons)


def generate_gear_screen(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    w = WEAPONS[p["weapon"]]
    f = create_fighter_from_db(p)
    slots = get_player_armor_slots(p)
    lines = [
        f"🎒 <b>{esc(p['name'])}</b>", "",
        f"{E_TROPHY} Победы: <b>{p['wins']}</b>",
        f"{E_SKULL} Поражения: {p['losses']}",
        f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>",
        f"📍 {ARENAS[determine_arena(p['wins'])]['emoji']} {ARENAS[determine_arena(p['wins'])]['name']}", "",
        f"❤️ HP: <b>{f.max_hp}</b>",
        f"⚔️ Атака: <b>{f.base_weapon_dmg}</b>", "",
        "<b>⚔️ Оружие:</b>",
        f"  {w['emoji']} {w['name']} — <i>{w['description']}</i>",
        f"  Базовый урон: <b>{w['base_dmg']}</b>", "",
        "<b>🛡 Броня по слотам:</b>"
    ]
    for slot in ZONES:
        item = get_armor_item_by_key(slots[slot]) or get_armor_item_by_key(f"{slot}_none")
        lines.append(f"  {ZONE_INFO[slot]['emoji']} {ZONE_INFO[slot]['name']}: {item['emoji']} <b>{item['name']}</b> (защита {item['df']})")
    kb = build_vertical_keyboard_with_styles([
        ("⚔️ Оружие", "gear:w", "primary"),
        ("🛡 Броня", "gear:armor_menu", "primary"),
        (f"{E_PROFILE} Мой профиль", "duel:myprofile", "success"),
        (f"{E_BACK} Назад", "arena:menu", "success"),
    ])
    return "\n".join(lines), kb


def generate_weapon_list(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    equipped = p["weapon"]
    owned = set((p["weapons_owned"] or "").split(","))
    lines = ["⚔️ <b>Оружие</b>", f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>", ""]
    buttons = []
    for key, it in WEAPONS.items():
        lines.append(f"{it['emoji']} <b>{it['name']}</b> — <i>{it['description']}</i>")
        lines.append(f"  Базовый урон: {it['base_dmg']} · Цена: {it['price']}💎")
        lines.append("  Варианты атаки:")
        for i, v in enumerate(it["variants"]):
            effect_text = f" [{v.effect}]" if v.effect else ""
            lines.append(f"    {i+1}. {v.name} ×{v.damage_mult}{effect_text} (КД: {v.cooldown_rounds})")
        lines.append("")
        if key == equipped:
            label = "✅ надето"
            style = "success"
        elif key in owned:
            label = "🎒 надеть"
            style = "primary"
        else:
            label = f"{it['price']}💎"
            style = "danger"
        buttons.append((f"{it['emoji']} {it['name']} · {label}", f"buy_weapon:{key}", style))
    buttons.append((f"{E_BACK} Назад", "gear:menu", "success"))
    return "\n".join(lines), build_vertical_keyboard_with_styles(buttons)


def generate_armor_slot_menu(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    slots = get_player_armor_slots(p)
    lines = ["🛡 <b>Броня — выбери часть тела</b>", f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>", ""]
    for slot in ZONES:
        item = get_armor_item_by_key(slots[slot]) or get_armor_item_by_key(f"{slot}_none")
        lines.append(f"{ZONE_INFO[slot]['emoji']} <b>{ZONE_INFO[slot]['name']}</b> — {item['emoji']} {item['name']} (защита {item['df']})")
    kb = build_vertical_keyboard_with_styles([
        ("🧠 Голова", "gear:head", "primary"),
        ("🫀 Торс", "gear:torso", "primary"),
        ("💪 Руки", "gear:arms", "primary"),
        ("🦵 Ноги", "gear:legs", "primary"),
        (f"{E_BACK} Назад", "gear:menu", "success"),
    ])
    return "\n".join(lines), kb


def generate_armor_slot_list(uid: int, slot: str) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p or slot not in ZONES:
        return "Ошибка.", None
    slots = get_player_armor_slots(p)
    equipped = slots.get(slot, f"{slot}_none")
    owned = set((p["armors_owned"] or "").split(","))
    lines = [f"🛡 <b>Броня на {ZONE_INFO[slot]['name'].lower()}</b>", f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>", ""]
    buttons = []
    for item in ARMOR_DATA[slot]:
        key = item["key"]
        lines.append(f"{item['emoji']} <b>{item['name']}</b> — защита <b>{item['df']}</b>, HP +{item['hp']}")
        lines.append(f"    {item['desc']}")
        if key == equipped:
            label = "✅ надето"
            style = "success"
        elif key in owned:
            label = "🎒 надеть"
            style = "primary"
        else:
            label = f"{item['price']}💎"
            style = "danger"
        buttons.append((f"{item['emoji']} {item['name']} · {label}", f"buy_armor:{slot}:{key}", style))
    buttons.append((f"{E_BACK} К слотам", "gear:armor_menu", "success"))
    return "\n".join(lines), build_vertical_keyboard_with_styles(buttons)


def generate_top_screen_paginated(uid: int, arena_key: str, page: int = 0) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    a = ARENAS[arena_key]
    all_rows = db.fetch_all(
        """SELECT user_id, name, wins, losses FROM players
           WHERE is_bot=0 AND banned=0 AND wins BETWEEN ? AND ?
           ORDER BY wins DESC, losses ASC""",
        (a["min_wins"], a["max_wins"])
    )
    total_count = len(all_rows)
    total_pages = max(1, (total_count + Config.TOP_PAGE_SIZE - 1) // Config.TOP_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * Config.TOP_PAGE_SIZE
    end_idx = min(start_idx + Config.TOP_PAGE_SIZE, total_count)
    page_rows = all_rows[start_idx:end_idx]
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{a['emoji']} <b>{a['name']}</b> — топ по победам", ""]
    lines.append(f"📊 Всего игроков: <b>{total_count}</b>")
    lines.append(f"📄 Страница: <b>{page + 1}</b> / {total_pages}\n")
    if not page_rows:
        lines.append("<i>Пока никого нет на этой арене.</i>")
    else:
        for i, r in enumerate(page_rows):
            global_idx = start_idx + i
            mark = medals[global_idx] if global_idx < 3 else f"{global_idx + 1}."
            you = " ← ты" if r["user_id"] == uid else ""
            lines.append(f"{mark} <b>{esc(r['name'])}</b> — {r['wins']} {E_TROPHY} / {r['losses']} {E_SKULL}{you}")
    me = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if me and a["min_wins"] <= me["wins"] <= a["max_wins"]:
        rank_row = db.fetch_one(
            """SELECT COUNT(*) c FROM players
               WHERE is_bot=0 AND banned=0 AND wins BETWEEN ? AND ? AND wins > ?""",
            (a["min_wins"], a["max_wins"], me["wins"])
        )
        rank = (rank_row["c"] if rank_row else 0) + 1
        my_page = (rank - 1) // Config.TOP_PAGE_SIZE
        if my_page != page:
            lines += ["\n…", f"<b>Ты:</b> #{rank}. <b>{esc(me['name'])}</b> — {me['wins']} {E_TROPHY} / {me['losses']} {E_SKULL}"]
    lines += ["", f"{E_TROPHY} Победа: +1 и деньги. {E_SKULL} Поражение: −1 без награды."]
    base_callback = f"top:{arena_key}"
    kb = build_pagination_keyboard(page, total_pages, base_callback, back_callback="arena:menu")
    return "\n".join(lines), kb


def generate_arena_list_screen_paginated(uid: int, page: int = 0) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    key = determine_arena(p["wins"])
    a = ARENAS[key]
    all_rows = db.fetch_all(
        """SELECT user_id, name, wins, losses FROM players
           WHERE user_id != ? AND banned=0 AND allow_duels=1 AND wins BETWEEN ? AND ?
           ORDER BY RANDOM()""",
        (uid, a["min_wins"], a["max_wins"])
    )
    total_count = len(all_rows)
    if total_count == 0:
        return (
            "Сейчас на твоей арене никого нет — жми «Найти соперника».",
            build_vertical_keyboard_with_styles([
                ("🎲 Найти", "arena:find", "success"),
                (f"{E_BACK} Назад", "arena:menu", "primary"),
            ])
        )
    total_pages = max(1, (total_count + PAGINATION_PAGE_SIZE - 1) // PAGINATION_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * PAGINATION_PAGE_SIZE
    end_idx = min(start_idx + PAGINATION_PAGE_SIZE, total_count)
    page_rows = all_rows[start_idx:end_idx]
    flat_buttons: List[Tuple[str, str, str]] = []
    for r in page_rows:
        flat_buttons.append((f"{r['name'][:16]} · {r['wins']}{E_TROPHY}/{r['losses']}{E_SKULL}", f"duel:pick:{r['user_id']}", "primary"))
    if page > 0:
        flat_buttons.append((f"{E_PREV} Назад", f"arena:list:page:{page - 1}", "primary"))
    if page < total_pages - 1:
        flat_buttons.append((f"Вперёд {E_NEXT}", f"arena:list:page:{page + 1}", "primary"))
    flat_buttons.append((f"{E_BACK} Назад", "arena:menu", "success"))
    text = f"{a['emoji']} <b>{a['name']}</b> — соперники\n📊 Всего: {total_count} · Стр. {page + 1}/{total_pages}"
    return text, build_vertical_keyboard_with_styles(flat_buttons)


def generate_profile_text(row: sqlite3.Row) -> str:
    if not row:
        return "Профиль не найден."
    w = WEAPONS[row["weapon"]] if row["weapon"] in WEAPONS else WEAPONS["fists"]
    f = create_fighter_from_db(row)
    slots = get_player_armor_slots(row)
    arena = ARENAS[determine_arena(row["wins"])]
    allow_duels_val = safe_row_get(row, "allow_duels", 1)
    allow_duels = "✅ ВКЛ" if allow_duels_val else "❌ ВЫКЛ"
    lines = [
        f"👤 <b>{esc(row['name'])}</b>", "",
        f"{E_TROPHY} Победы: {row['wins']}",
        f"{E_SKULL} Поражения: {row['losses']}",
        f"{E_CRYSTAL} Кристаллы: {format_number(row['crystals'])}",
        f"📍 {arena['emoji']} {arena['name']}", "",
        f"❤️ HP: <b>{f.max_hp}</b>",
        f"{w['emoji']} {w['name']} — баз. урон <b>{w['base_dmg']}</b>", "",
        f"⚔️ Принимать вызовы: <b>{allow_duels}</b>", "",
        "<b>🛡 Броня:</b>"
    ]
    for slot in ZONES:
        item = get_armor_item_by_key(slots[slot]) or get_armor_item_by_key(f"{slot}_none")
        lines.append(f"  {ZONE_INFO[slot]['emoji']} {ZONE_INFO[slot]['name']}: {item['emoji']} {item['name']} ({item['df']})")
    return "\n".join(lines)


def generate_profile_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🎒 Снаряжение", "gear:menu", "primary"),
        (f"{E_SETTINGS} Настройки", "profile:settings", "primary"),
        (f"{E_BACK} Назад", "arena:menu", "success"),
    ])


def generate_settings_screen(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    """ИСПРАВЛЕНО v20.1: корректный return при отсутствии игрока."""
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    allow_duels = bool(safe_row_get(p, "allow_duels", 1))
    status = "✅ РАЗРЕШЕНО" if allow_duels else "❌ ЗАПРЕЩЕНО"
    text = (
        f"{E_SETTINGS} <b>НАСТРОЙКИ</b>\n\n"
        f"👤 <b>{esc(p['name'])}</b>\n\n"
        f"⚔️ <b>Принимать вызовы на дуэль:</b>\n"
        f"{status}\n\n"
        f"<i>Если запрещено, другие игроки не смогут вызвать тебя на бой.</i>"
    )
    kb = build_vertical_keyboard_with_styles([
        (f"{'🔴 Запретить' if allow_duels else '🟢 Разрешить'} вызовы", "settings:toggle_allow_duels",
         "danger" if allow_duels else "success"),
        (f"{E_BACK} Назад к профилю", "duel:myprofile", "primary"),
    ])
    return text, kb


def generate_duel_status_text(duel: Duel, for_uid: int, extra: str = "", timer_left: Optional[int] = None) -> str:
    role = duel.get_state_for(for_uid)
    me = duel.get_fighter(for_uid) or duel.a
    opp = duel.get_opponent(for_uid) or duel.b
    if role == "attacker" and duel.chosen_variant_idx is None:
        prompt = "🎯 <b>Твой ход</b> — выбери вариант атаки"
    elif role == "attacker":
        prompt = "🎯 <b>Твой ход</b> — выбери зону удара"
    elif role == "defender":
        prompt = f"{E_SHIELD} <b>{duel.get_attacker().name}</b> атакует — выбери, что защищать"
    else:
        prompt = "⏳ Бой идёт…"
    if timer_left is not None and role in ("attacker", "defender"):
        prompt += f"\n⏱ Осталось: <b>{timer_left} сек</b>"
    body = "\n".join(f"  {ln}" for ln in duel.log[-DUEL_LOG_DISPLAY_LIMIT:]) if duel.log else "  <i>Бой начинается…</i>"
    boss_line = f"{E_BOSS} <b>БОЙ С БОССОМ</b>  ·  награда ×{duel.reward_mult}\n\n" if duel.is_boss else ""
    return (
        f"╔══════════════════════════╗\n      ⚔️ <b>РАУНД {duel.round_no}</b>\n╚══════════════════════════╝\n\n"
        f"{boss_line}┌─ 🔵 <b>ТЫ</b>\n{format_fighter_card(me)}\n└────────────\n\n"
        f"┌─ 🔴 <b>СОПЕРНИК</b>\n{format_fighter_card(opp)}\n└────────────\n\n"
        f"📜 <b>Последние действия:</b>\n{body}\n\n━━━━━━━━━━━━━━━━━━━━\n{prompt}"
        + (f"\n\n{extra}" if extra else "")
    )


def get_attack_variant_kb(uid: int) -> InlineKeyboardMarkup:
    duel = ACTIVE_DUELS.get(uid)
    if not duel:
        return build_vertical_keyboard([])
    weapon = WEAPONS[duel.get_attacker().weapon]
    buttons = []
    for i, v in enumerate(weapon["variants"]):
        cd = duel.get_attacker().attack_cooldowns.get(i, 0)
        if cd > 0:
            text = f"⏳ {i + 1}. {v.name} (КД: {cd}р)"
            buttons.append((text, f"duel:variant_disabled:{i}", "primary"))
        else:
            effect_text = f" [{v.effect}]" if v.effect else ""
            text = f"{i + 1}. {v.name} · x{v.damage_mult}{effect_text}"
            buttons.append((text, f"duel:variant:{i}", "success"))
    return build_vertical_keyboard_with_styles(buttons)


def get_attack_zone_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        (f"{E_ZONE_HEAD} Голова ×1.5", "duel:atk:head", "danger"),
        (f"{E_ZONE_TORSO} Торс ×1.0", "duel:atk:torso", "danger"),
        (f"{E_ZONE_ARMS} Руки ×0.8", "duel:atk:arms", "danger"),
        (f"{E_ZONE_LEGS} Ноги ×0.9", "duel:atk:legs", "danger"),
    ])


def get_defend_zone_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        (f"{E_ZONE_HEAD} Голова", "duel:def:head", "success"),
        (f"{E_ZONE_TORSO} Торс", "duel:def:torso", "success"),
        (f"{E_ZONE_ARMS} Руки", "duel:def:arms", "success"),
        (f"{E_ZONE_LEGS} Ноги", "duel:def:legs", "success"),
    ])


def get_finish_duel_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "duel:again", "primary"),
        ("🏠 В главное меню", "arena:menu", "success"),
    ])


def get_challenge_accept_kb(challenger_id: int, target_id: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        (f"{E_ACCEPT} Принять вызов", f"challenge:accept:{challenger_id}:{target_id}", "success"),
        (f"{E_REJECT} Отклонить", f"challenge:reject:{challenger_id}:{target_id}", "danger"),
    ])


def get_challenge_waiting_kb(challenger_id: int, target_id: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        (f"{E_REFRESH} Обновить статус", f"challenge:refresh:{challenger_id}:{target_id}", "primary"),
        (f"{E_REJECT} Отменить вызов", f"challenge:cancel:{challenger_id}:{target_id}", "danger"),
    ])


def get_bet_kb(game: str) -> InlineKeyboardMarkup:
    buttons = [(f"{b} 💎", f"casino:{game}:bet:{b}", "primary") for b in Config.CASINO_BETS]
    buttons.append((f"✏️ Ввести свою", f"casino:{game}:manual", "success"))
    buttons.append((f"{E_BACK} Назад", "casino:menu", "danger"))
    return build_vertical_keyboard_with_styles(buttons)


def get_dice_mode_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🔢 На число (×6)", "casino:dice:number", "primary"),
        ("⚖️ Чёт / Нечет (×2)", "casino:dice:even_odd", "primary"),
        ("📈 Больше / Меньше (×2)", "casino:dice:high_low", "primary"),
        (f"{E_BACK} Назад", "casino:menu", "success"),
    ])


def get_dice_number_kb(bet: int) -> InlineKeyboardMarkup:
    buttons = [(f"{i} (×6)", f"casino:dice:num:{bet}:{i}", "primary") for i in range(1, 7)]
    buttons.append((f"{E_BACK} Назад", "casino:dice", "success"))
    return build_vertical_keyboard_with_styles(buttons)


def get_dice_even_odd_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🔵 Чёт (×2)", f"casino:dice:even:{bet}", "primary"),
        ("🔴 Нечет (×2)", f"casino:dice:odd:{bet}", "danger"),
        (f"{E_BACK} Назад", "casino:dice", "success"),
    ])


def get_dice_high_low_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("📈 Больше (4-6) (×2)", f"casino:dice:high:{bet}", "success"),
        ("📉 Меньше (1-3) (×2)", f"casino:dice:low:{bet}", "danger"),
        (f"{E_BACK} Назад", "casino:dice", "success"),
    ])


def get_darts_mode_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🎯 На попадание (×1.9)", "casino:darts:hit", "success"),
        ("💨 На промах (×1.9)", "casino:darts:miss", "danger"),
        (f"{E_BACK} Назад", "casino:menu", "success"),
    ])


def get_basket_mode_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🏀 На попадание (×1.9)", "casino:basket:hit", "success"),
        ("💨 На промах (×1.9)", "casino:basket:miss", "danger"),
        (f"{E_BACK} Назад", "casino:menu", "success"),
    ])


def get_roulette_mode_kb() -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🎨 На цвет (×2 / ×14)", "casino:roulette:color", "primary"),
        ("⚖️ Чёт / Нечет (×2)", "casino:roulette:even_odd", "primary"),
        ("📈 Половина (×2)", "casino:roulette:half", "primary"),
        ("🔢 На число (×36)", "casino:roulette:number", "danger"),
        ("🎯 На дюжину (×3)", "casino:roulette:dozen", "primary"),
        (f"{E_BACK} Назад", "casino:menu", "success"),
    ])


def get_roulette_color_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🔴 Красное (×2)", f"casino:roulette:color:red:{bet}", "danger"),
        ("⚫ Чёрное (×2)", f"casino:roulette:color:black:{bet}", "primary"),
        ("🟢 Зеро (×14)", f"casino:roulette:color:green:{bet}", "success"),
        (f"{E_BACK} Назад", "casino:roulette", "success"),
    ])


def get_roulette_even_odd_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("🔵 Чёт (×2)", f"casino:roulette:even_odd:even:{bet}", "primary"),
        ("🔴 Нечет (×2)", f"casino:roulette:even_odd:odd:{bet}", "danger"),
        (f"{E_BACK} Назад", "casino:roulette", "success"),
    ])


def get_roulette_half_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("📉 1-18 (×2)", f"casino:roulette:half:low:{bet}", "primary"),
        ("📈 19-36 (×2)", f"casino:roulette:half:high:{bet}", "success"),
        (f"{E_BACK} Назад", "casino:roulette", "success"),
    ])


def get_roulette_number_kb(bet: int) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(0, 37):
        buttons.append((f"{i} (×36)", f"casino:roulette:num:{bet}:{i}", "danger"))
    buttons.append((f"{E_BACK} Назад", "casino:roulette", "success"))
    return build_horizontal_keyboard([(t, c) for t, c, _ in buttons], 4)


def get_roulette_dozen_kb(bet: int) -> InlineKeyboardMarkup:
    return build_vertical_keyboard_with_styles([
        ("1️⃣ 1-12 (×3)", f"casino:roulette:dozen:1:{bet}", "primary"),
        ("2️⃣ 13-24 (×3)", f"casino:roulette:dozen:2:{bet}", "primary"),
        ("3️⃣ 25-36 (×3)", f"casino:roulette:dozen:3:{bet}", "primary"),
        (f"{E_BACK} Назад", "casino:roulette", "success"),
    ])


def get_mines_setup_kb() -> InlineKeyboardMarkup:
    buttons = []
    for mines in [1, 3, 5, 7, 10, 15, 20, 24]:
        buttons.append((f"{E_MINE} {mines} мин", f"mines:start:{mines}", "primary" if mines < 10 else "danger"))
    buttons.append((f"{E_BACK} Назад", "casino:menu", "success"))
    return build_vertical_keyboard_with_styles(buttons)


def generate_casino_menu(uid: int) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (uid,))
    if not p:
        return "Профиль не найден.", None
    text = (
        f"╔══════════════════════════╗\n      {E_SLOT} <b>КАЗИНО</b>\n╚══════════════════════════╝\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери игру:</b>"
    )
    kb = build_vertical_keyboard_with_styles([
        (f"{E_SLOT} Слоты (×10)", "casino:slots", "primary"),
        (f"{E_DICE} Кости", "casino:dice", "primary"),
        (f"{E_DARTS} Дротик (×1.9)", "casino:darts", "primary"),
        (f"{E_BASKET} Баскетбол (×1.9)", "casino:basket", "primary"),
        ("🎡 Рулетка", "casino:roulette", "primary"),
        (f"{E_COIN} Монетка (×2)", "casino:coin", "primary"),
        ("📊 Больше/Меньше (×1.9)", "casino:highlow", "primary"),
        (f"{E_MINE} Мины", "casino:mines", "danger"),
        (f"{E_ROCKET} Краш", "casino:crash", "danger"),
        (f"{E_BACK} Назад", "arena:menu", "success"),
    ])
    return text, kb


# ============================================================================
# HELP
# ============================================================================

HELP_SECTIONS: Dict[str, Dict[str, Any]] = {
    "duels": {
        "title": f"{E_SWORD} <b>⚔️ ДУЭЛИ</b>",
        "text": (
            "• <code>перчатка</code> или <code>перч</code> — вызов\n"
            "• <code>профиль</code> или <code>/profile</code> — статистика\n"
            "• <code>перевод [сумма]</code> — перевести кристаллы\n"
            "• <code>баланс</code> — проверить баланс\n\n"
            "<i>Команды работают ответом / @username / ID</i>"
        ),
    },
    "casino": {
        "title": f"{E_SLOT} <b>🎰 КАЗИНО</b>",
        "text": (
            "<b>Базовые игры:</b>\n"
            "• <code>сл [сумма]</code> — слоты ×10\n"
            "• <code>кости число [сумма] [1-6]</code> — ×6\n"
            "• <code>кости чет [сумма] [чет/нечет]</code> — ×2\n"
            "• <code>кости больше [сумма] [больше/меньше]</code> — ×2\n"
            "• <code>дротик [сумма]</code> / <code>дротик промах [сумма]</code> — ×1.9\n"
            "• <code>баскет [сумма]</code> / <code>баскет промах [сумма]</code> — ×1.9\n"
            "• <code>рул цвет [сумма] [к/ч/з]</code>\n"
            "• <code>рул чет [сумма] [чет/нечет]</code>\n"
            "• <code>рул половина [сумма] [верх/низ]</code>\n"
            "• <code>рул число [сумма] [0-36]</code> — ×36\n"
            "• <code>рул дюжина [сумма] [1/2/3]</code> — ×3\n"
            "• <code>мон [сумма] [о/р]</code>\n"
            "• <code>больше [сумма]</code> / <code>меньше [сумма]</code>\n\n"
            "<b>Новые игры:</b>\n"
            "• <code>мины [сумма] [кол-во мин]</code> — поле 5×5\n"
            "• <code>краш [сумма]</code> — растущий множитель"
        ),
    },
    "rp": {
        "title": f"{E_MAGIC} <b>🎭 RP ДЕЙСТВИЯ</b>",
        "text": (
            "• <code>ударить</code>, <code>обнять</code>, <code>поцеловать</code>\n"
            "• <code>пнуть</code>, <code>погладить</code>, <code>укусить</code>\n"
            "• <code>пожать</code>, <code>толкнуть</code>, <code>кинуть</code>\n"
            "• <code>лечить</code>, <code>игнор</code>, <code>смеяться</code>\n"
            "• <code>танцевать</code>, <code>шлепнуть</code>, <code>обозвать</code>\n"
            "• <code>покормить</code>, <code>напоить</code>, <code>щекотать</code>\n"
            "• <code>благословить</code>, <code>проклясть</code>, <code>подмигнуть</code>\n\n"
            "<b>👹 События:</b>\n"
            "• <code>атака</code> — ударить босса\n"
            "• <code>событие</code> — статус события\n\n"
            "<b>🎟 Промокоды:</b>\n"
            "• <code>#код [промокод]</code>\n"
            "• <code>активировать [код]</code>"
        ),
    },
    "admin": {
        "title": f"{E_CROWN} <b>👑 АДМИН</b>",
        "text": (
            "• <code>бан</code> / <code>разбан</code>\n"
            "• <code>выдать [сумма]</code>\n"
            "• <code>событие босс/караван/набег/дракон/демон/голем</code>\n"
            "• <code>босс [ключ]</code> — активировать босса\n"
            "• <code>следующее событие</code>\n"
            "• <code>промо создать/удалить/список</code>\n"
            "• <code>рассылка текст</code>\n"
            "• <code>статистика</code>\n"
            "• <code>список игроков</code>\n"
            "• <code>очистить ботов</code>\n"
            "• <code>добавить ботов [число]</code>"
        ),
    },
}


HELP_CHAT_SHORT = (
    f"{E_INFO} <b>КРАТКАЯ СПРАВКА</b>\n\n"
    f"<b>⚔️ Дуэли:</b>\n"
    f"• <code>перчатка</code> — вызвать на бой\n"
    f"• <code>профиль</code> / <code>/profile</code> — статистика\n"
    f"• <code>баланс</code> — проверить баланс\n\n"
    f"<b>💎 Экономика:</b>\n"
    f"• <code>перевод [сумма]</code> — перевести кристаллы\n\n"
    f"<b>🎰 Казино:</b>\n"
    f"• <code>сл 100</code> — слоты\n"
    f"• <code>кости число 100 3</code> — кости\n"
    f"• <code>дротик 100</code> — дротик\n"
    f"• <code>баскет 100</code> — баскетбол\n"
    f"• <code>рул цвет 100 к</code> — рулетка\n"
    f"• <code>мон 100 о</code> — монетка\n"
    f"• <code>мины 100 5</code> — мины\n"
    f"• <code>краш 100</code> — краш\n\n"
    f"<b>🎭 RP:</b>\n"
    f"• <code>ударить</code>, <code>обнять</code>, <code>поцеловать</code> и др.\n\n"
    f"<b>👹 События:</b>\n"
    f"• <code>атака</code> — ударить босса\n"
    f"• <code>событие</code> — статус события\n\n"
    f"<b>🎟 Промокоды:</b>\n"
    f"• <code>#код [код]</code> или <code>активировать [код]</code>\n\n"
    f"{E_INFO} <i>Полная справка в ЛС: напиши <code>help</code></i>"
)


def get_help_keyboard() -> InlineKeyboardMarkup:
    return build_horizontal_keyboard([
        (f"{E_SWORD} Дуэли", "help:section:duels"),
        (f"{E_SLOT} Казино", "help:section:casino"),
        (f"{E_MAGIC} RP", "help:section:rp"),
        (f"{E_CROWN} Админ", "help:section:admin"),
    ], 2)


# ============================================================================
# РОУТЕР И FSM
# ============================================================================

router = Router()


class RegistrationState(StatesGroup):
    waiting_for_name = State()


class DuelFindState(StatesGroup):
    waiting_for_target = State()


class ManualBetState(StatesGroup):
    waiting_for_bet = State()
    waiting_for_mines_bet = State()


# ============================================================================
# СТАРТ
# ============================================================================

@router.message(CommandStart())
async def handle_start_command(m: Message, state: FSMContext) -> None:
    await state.clear()
    ensure_masked_bots_exist(Config.BOT_GENERATION_COUNT)
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if p:
        db.execute("UPDATE players SET username=?, last_active=? WHERE user_id=?",
                   (m.from_user.username, time.time(), m.from_user.id))
        if m.chat.type == "private":
            await m.answer(f"С возвращением, <b>{esc(p['name'])}</b>! Арена ждёт 👇", reply_markup=MENU_KB)
            await flush_notifications(m)
        else:
            await m.answer(f"С возвращением, <b>{esc(p['name'])}</b>! Пиши <code>help</code> для списка команд.")
        return
    await state.set_state(RegistrationState.waiting_for_name)
    await m.answer(
        "⚔️ <b>Добро пожаловать на Арену Дуэлянтов!</b>\n\n"
        "PvP + казино + боссы + чатовые ивенты.\n"
        "12 видов оружия, 32 предмета брони, 8 боссов.\n"
        f"Новые игры: 💣 Мины и 🚀 Краш!\n\n"
        f"Как зовут твоего бойца? ({MIN_NAME_LENGTH}–{MAX_NAME_LENGTH} символов)",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(RegistrationState.waiting_for_name, F.text)
async def handle_registration_name(m: Message, state: FSMContext) -> None:
    name = " ".join(m.text.split())
    if not MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH:
        await m.answer(f"Имя должно быть от {MIN_NAME_LENGTH} до {MAX_NAME_LENGTH} символов.")
        return
    if name.startswith("/"):
        await m.answer("Имя не может начинаться с '/'.")
        return
    if db.fetch_one("SELECT 1 FROM players WHERE LOWER(name)=LOWER(?)", (name,)):
        name = f"{name}{random.randint(1, 99)}"
    now = time.time()
    db.execute(
        """INSERT OR IGNORE INTO players
           (user_id, username, name, crystals, wins, losses, weapon,
            armor_head, armor_torso, armor_arms, armor_legs,
            weapons_owned, armors_owned, created, last_active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (m.from_user.id, m.from_user.username, name, Config.START_CRYSTALS, 0, 0, START_WEAPON,
         "head_none", "torso_none", "arms_none", "legs_none", START_WEAPON,
         ",".join(START_ARMOR_KEYS), now, now)
    )
    db.execute("INSERT OR IGNORE INTO player_stats (user_id) VALUES (?)", (m.from_user.id,))
    ensure_masked_bots_exist(Config.BOT_GENERATION_COUNT)
    await state.clear()
    await m.answer(
        f"Боец <b>{esc(name)}</b> создан! 🎉\n\n"
        f"{E_CRYSTAL} Стартовый баланс: {Config.START_CRYSTALS}\n"
        f"⚔️ Оружие: {WEAPONS[START_WEAPON]['emoji']} {WEAPONS[START_WEAPON]['name']}",
        reply_markup=MENU_KB if m.chat.type == "private" else None
    )


@router.message(Command("profile"))
async def cmd_profile_slash(m: Message) -> None:
    if m.chat.type != "private":
        await m.answer("Команда <code>/profile</code> работает только в ЛС с ботом.")
        return
    row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not row:
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    text = generate_profile_text(row)
    kb = generate_profile_kb()
    await m.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(r"(?i)^(help|помощь|хелп)$"))
async def handle_help_command(m: Message) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    if m.chat.type == "private":
        text = (
            f"╔══════════════════════════╗\n   ⚔️ <b>АРЕНА ДУЭЛЯНТОВ</b>\n╚══════════════════════════╝\n\n"
            f"<b>📋 РАЗДЕЛЫ ПО КНОПКАМ МЕНЮ:</b>\n\n"
            f"{E_SWORD} <b>⚔️ АРЕНА</b> — PvP дуэли и боссы\n"
            f"{E_SLOT} <b>🎰 КАЗИНО</b> — Азартные игры\n"
            f"{E_GIFT} <b>🎒 СНАРЯЖЕНИЕ</b> — Экипировка\n"
            f"{E_TROPHY} <b>🏆 ТОП</b> — Рейтинги\n"
            f"{E_PROFILE} <b>👤 ПРОФИЛЬ</b> — <code>/profile</code>\n\n"
            f"<b>📌 ВЫБЕРИ РАЗДЕЛ КОМАНД:</b>"
        )
        await m.answer(text, reply_markup=get_help_keyboard())
        if is_admin(m.from_user.id):
            await m.answer(
                f"{E_CROWN} <b>КОМАНДЫ АДМИНИСТРАТОРА</b>\n\n"
                f"• <code>бан @user</code> или <code>бан ID</code>\n"
                f"• <code>разбан @user</code>\n"
                f"• <code>выдать 1000 @user</code>\n"
                f"• <code>событие босс/караван/набег/дракон/демон/голем</code>\n"
                f"• <code>босс goblin/skeleton/dragon/orc/lord/lich/titan/demon_king</code>\n"
                f"• <code>следующее событие</code>\n"
                f"• <code>промо создать/удалить/список</code>\n"
                f"• <code>рассылка текст</code>\n"
                f"• <code>статистика</code>\n"
                f"• <code>список игроков</code>\n"
                f"• <code>очистить ботов</code>\n"
                f"• <code>добавить ботов [число]</code>"
            )
    else:
        await m.answer(HELP_CHAT_SHORT)


@router.callback_query(F.data.regexp(r"^help:section:(\w+)$"))
async def cb_help_section(cb: CallbackQuery) -> None:
    section_key = cb.data.split(":")[2]
    section = HELP_SECTIONS.get(section_key)
    if not section:
        await cb.answer("Раздел не найден", show_alert=True)
        return
    text = f"{section['title']}\n\n{section['text']}"
    back_buttons = [(f"{E_BACK} Назад к разделам", "help:main", "primary")]
    other_sections = [(k, v) for k, v in HELP_SECTIONS.items() if k != section_key]
    for key, sec in other_sections:
        title = sec["title"].split(">")[1].split("<")[0] if ">" in sec["title"] else key
        back_buttons.append((title, f"help:section:{key}", "primary"))
    kb = build_vertical_keyboard_with_styles(back_buttons)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "help:main")
async def cb_help_main(cb: CallbackQuery) -> None:
    text = (
        f"╔══════════════════════════╗\n   ⚔️ <b>АРЕНА ДУЭЛЯНТОВ</b>\n╚══════════════════════════╝\n\n"
        f"<b>📋 ВЫБЕРИ РАЗДЕЛ КОМАНД:</b>\n\n"
        f"Нажми на кнопку ниже, чтобы увидеть подробные команды раздела."
    )
    await safe_edit_message(cb, text, get_help_keyboard())
    await cb.answer()


async def flush_notifications(m: Message) -> None:
    rows = db.fetch_all(
        "SELECT id, text FROM notifications WHERE user_id=? AND seen=0 ORDER BY id LIMIT ?",
        (m.from_user.id, MAX_NOTIFICATIONS_PER_USER)
    )
    if not rows:
        return
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        db.execute(f"UPDATE notifications SET seen=1 WHERE id IN ({placeholders})", tuple(ids))
    await m.answer("📬 <b>Пока тебя не было:</b>\n\n" + "\n\n".join(r["text"] for r in rows))


@router.message(F.text.in_(MENU_TEXTS))
async def on_menu_button(m: Message, state: FSMContext) -> None:
    if m.chat.type != "private":
        return
    await state.clear()
    if is_user_banned(m.from_user.id):
        await m.answer("🚫 Доступ закрыт.")
        return
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start.")
        return
    db.execute("UPDATE players SET last_active=? WHERE user_id=?", (time.time(), m.from_user.id))
    await flush_notifications(m)
    if m.text == BTN_ARENA:
        text, kb = generate_arena_menu_screen(m.from_user.id)
        await m.answer(text, reply_markup=kb)
    elif m.text == BTN_CASINO:
        text, kb = generate_casino_menu(m.from_user.id)
        await m.answer(text, reply_markup=kb)
    elif m.text == BTN_GEAR:
        text, kb = generate_gear_screen(m.from_user.id)
        await m.answer(text, reply_markup=kb)
    elif m.text == BTN_TOP:
        p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
        if p:
            text, kb = generate_top_screen_paginated(m.from_user.id, determine_arena(p["wins"]), 0)
            await m.answer(text, reply_markup=kb)


# ============================================================================
# ДУЭЛИ
# ============================================================================

@router.message(F.text.regexp(r"(?i)^(перчатка|перч|glove|вызов)(\s|$)"))
async def cmd_challenge_duel(m: Message, bot: Bot) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    if m.from_user.id in ACTIVE_DUELS:
        await m.answer("У тебя уже идёт бой.")
        return
    tid, err = resolve_command_target(m, m.text.split()[0])
    if err:
        await m.answer(err)
        return
    if tid == m.from_user.id:
        await m.answer("🤨 Нельзя вызвать себя.")
        return
    if tid < 0:
        await initiate_duel_message(m.from_user.id, tid, m, bot)
        return
    target = db.fetch_one("SELECT * FROM players WHERE user_id=?", (tid,))
    if not target or target["banned"]:
        await m.answer("Игрок не найден или забанен.")
        return
    if not safe_row_get(target, "allow_duels", 1):
        await m.answer(f"🚫 Игрок <b>{esc(target['name'])}</b> запретил вызовы на дуэль.", parse_mode=ParseMode.HTML)
        return
    if tid in ACTIVE_DUELS:
        await m.answer("Этот игрок уже в бою.")
        return
    key = (m.from_user.id, tid)
    if key in PENDING_DUELS:
        await m.answer("Ты уже отправил этому игроку вызов.")
        return
    challenger_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (m.from_user.id,))
    challenger_name = challenger_row["name"]
    target_name = target["name"]
    challenger_msg, target_msg = await send_challenge_messages(
        m.from_user.id, tid, challenger_name, target_name, bot
    )
    if not target_msg:
        await m.answer("Не удалось отправить вызов (игрок не начал бота).")
        return
    pending = PendingDuel(
        challenger_id=m.from_user.id,
        target_id=tid,
        challenger_msg_id=challenger_msg.message_id if challenger_msg else 0,
        target_msg_id=target_msg.message_id,
        chat_id=m.from_user.id,
        created_at=time.time(),
    )
    PENDING_DUELS[key] = pending
    pending.timeout_task = asyncio.create_task(challenge_timeout_task(m.from_user.id, tid, bot))


@router.message(F.text.regexp(r"(?i)^(фото|профиль|stat)(\s|$)"))
async def cmd_show_profile(m: Message) -> None:
    row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not row:
        await m.answer("Сначала /start в ЛС бота.")
        return
    command_word = m.text.split()[0]
    tid, err = resolve_command_target(m, command_word)
    if tid:
        target_row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (tid,))
        if target_row:
            await m.answer(generate_profile_text(target_row))
            return
    await m.answer(generate_profile_text(row))


@router.message(F.text.regexp(r"(?i)^перевод(\s|$)"))
async def cmd_transfer(m: Message) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    tid, err = resolve_command_target(m, "перевод")
    if err:
        await m.answer(err)
        return
    if tid == m.from_user.id:
        await m.answer("🤨 Себе переводить нельзя.")
        return
    target = db.fetch_one("SELECT * FROM players WHERE user_id=?", (tid,))
    if not target or target["banned"]:
        await m.answer("Игрок не найден или забанен.")
        return
    amount = next((int(x) for x in (m.text or "").split() if x.lstrip("-").isdigit()), None)
    if not amount or amount <= 0:
        await m.answer("Укажи сумму: <code>перевод 100 @user</code>")
        return
    if amount < Config.MIN_TRANSFER:
        await m.answer(f"Минимальная сумма перевода: {Config.MIN_TRANSFER} {E_CRYSTAL}")
        return
    if amount > Config.MAX_TRANSFER:
        await m.answer(f"Максимальная сумма перевода: {Config.MAX_TRANSFER} {E_CRYSTAL}")
        return
    if p["crystals"] < amount:
        await m.answer(f"Недостаточно кристаллов: у тебя {p['crystals']} {E_CRYSTAL}")
        return
    tax = int(amount * Config.TRANSFER_TAX)
    net_amount = amount - tax
    db.execute("UPDATE players SET crystals=crystals-? WHERE user_id=?", (amount, m.from_user.id))
    db.execute("UPDATE players SET crystals=crystals+? WHERE user_id=?", (net_amount, tid))
    await m.answer(
        f"{E_CRYSTAL} Переведено <b>{net_amount}</b> игроку <b>{esc(target['name'])}</b>.\n"
        f"💰 Налог: {tax} ({Config.TRANSFER_TAX * 100:.0f}%)"
    )
    notify_player(tid, f"{E_CRYSTAL} <b>{esc(p['name'])}</b> перевёл тебе <b>{net_amount}</b> кристаллов!")


@router.message(F.text.regexp(r"(?i)^атака(\s|$)"))
async def cmd_attack_event(m: Message) -> None:
    p = db.fetch_one("SELECT name FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    result = attack_chat_event(m.from_user.id, p["name"])
    if not result:
        await m.answer("Сейчас нет активных чатовых событий.")
        return
    await m.answer(result)


@router.message(F.text.regexp(r"(?i)^(событие|статус события)(\s|$)"))
async def cmd_event_status(m: Message) -> None:
    status = get_chat_event_status()
    if not status:
        await m.answer("Сейчас нет активных чатовых событий.")
        return
    await m.answer(f"📋 <b>Текущее событие:</b>\n\n{status}")


@router.message(F.text.regexp(r"(?i)^(баланс|balance|бал)(\s|$)"))
async def cmd_balance(m: Message) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    await m.answer(
        f"👤 <b>{esc(p['name'])}</b>\n\n"
        f"{E_CRYSTAL} Кристаллы: <b>{format_number(p['crystals'])}</b>\n"
        f"{E_TROPHY} Победы: <b>{p['wins']}</b>\n"
        f"{E_SKULL} Поражения: <b>{p['losses']}</b>"
    )


# ============================================================================
# ПРОМОКОДЫ В ЧАТЕ
# ============================================================================

@router.message(F.text.regexp(r"(?i)^#код\s+(\S+)$"))
async def cmd_promo_hash(m: Message) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    match = re.search(r"(?i)^#код\s+(\S+)$", m.text or "")
    if not match:
        return
    code = match.group(1)
    success, message = activate_promo_code(m.from_user.id, code)
    await m.answer(message, parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(r"(?i)^(активировать|актив|redeem)\s+(\S+)$"))
async def cmd_promo_activate(m: Message) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    match = re.search(r"(?i)^(?:активировать|актив|redeem)\s+(\S+)$", m.text or "")
    if not match:
        return
    code = match.group(1)
    success, message = activate_promo_code(m.from_user.id, code)
    await m.answer(message, parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(r"(?i)^промо$"))
async def cmd_promo_list_player(m: Message) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала отправь /start в ЛС бота.")
        return
    promos = db.fetch_all(
        "SELECT * FROM promo_codes WHERE active=1 AND expires_at > ? AND current_uses < max_uses ORDER BY created_at DESC LIMIT 10",
        (time.time(),)
    )
    if not promos:
        await m.answer(f"{E_PROMO} <b>Активных промокодов сейчас нет.</b>")
        return
    lines = [f"{E_PROMO} <b>АКТИВНЫЕ ПРОМОКОДЫ</b>\n", f"Найдено: <b>{len(promos)}</b>\n"]
    for i, promo in enumerate(promos, 1):
        remaining = promo["max_uses"] - promo["current_uses"]
        lines.append(f"{i}. <code>{promo['code']}</code>")
        rewards = []
        if promo["reward_crystals"] > 0:
            rewards.append(f"💎{promo['reward_crystals']}")
        if promo["reward_wins"] > 0:
            rewards.append(f"🏆{promo['reward_wins']}")
        lines.append(f"   Награда: {' + '.join(rewards) if rewards else '🎁'}")
        lines.append(f"   Осталось: {remaining}/{promo['max_uses']}\n")
    lines.append(f"{E_MAGIC} Активируй: <code>#код [код]</code> или <code>активировать [код]</code>")
    await m.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ============================================================================
# RP КОМАНДЫ
# ============================================================================

async def process_rp_action(m: Message, action_key: str) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        await m.answer("Сначала /start в ЛС бота.")
        return
    tid, err = resolve_command_target(m, m.text.split()[0])
    if err:
        await m.answer(err)
        return
    if tid == m.from_user.id:
        await m.answer("🤨 Себе это делать странно.")
        return
    target = db.fetch_one("SELECT * FROM players WHERE user_id=?", (tid,))
    if not target or target["banned"]:
        await m.answer("Игрок не найден или забанен.")
        return
    cooldown_key = (m.from_user.id, tid, action_key)
    now = time.time()
    if now - RP_COOLDOWNS.get(cooldown_key, 0) < Config.RP_COOLDOWN:
        left = int(Config.RP_COOLDOWN - (now - RP_COOLDOWNS[cooldown_key])) + 1
        await m.answer(f"⏱ Подожди ещё {left} сек.")
        return
    RP_COOLDOWNS[cooldown_key] = now
    actor = db.fetch_one("SELECT name FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(
        generate_rp_text(m.from_user.id, actor["name"], tid, target["name"], action_key),
        parse_mode=ParseMode.HTML
    )
    db.execute("UPDATE player_stats SET rp_actions_used=rp_actions_used+1 WHERE user_id=?", (m.from_user.id,))


RP_MAPPINGS: Dict[str, List[str]] = {
    "ударить": ["ударить", "уд", "hit"],
    "обнять": ["обнять", "обн", "hug"],
    "поцеловать": ["поцеловать", "поц", "kiss"],
    "пнуть": ["пнуть", "пн", "kick"],
    "погладить": ["погладить", "погл", "pet"],
    "укусить": ["укусить", "ук", "bite"],
    "пожать": ["пожать", "пож", "handshake"],
    "толкнуть": ["толкнуть", "толк", "push"],
    "кинуть": ["кинуть", "кин", "throw"],
    "лечить": ["лечить", "леч", "heal"],
    "игнорировать": ["игнор", "игнорировать", "ignore"],
    "смеяться": ["смеяться", "смех", "laugh"],
    "плакать": ["плакать", "плач", "cry"],
    "танцевать": ["танцевать", "танец", "dance"],
    "шлепнуть": ["шлепнуть", "шлеп", "slap"],
    "обозвать": ["обозвать", "обзывать", "insult"],
    "восхититься": ["восхититься", "восхищение", "admire"],
    "испугаться": ["испугаться", "испуг", "fear"],
    "подмигнуть": ["подмигнуть", "подмигивание", "wink"],
    "пожать_плечами": ["пожать_плечами", "плечи", "shrug"],
    "покормить": ["покормить", "кормить", "feed"],
    "напоить": ["напоить", "поить", "drink"],
    "щекотать": ["щекотать", "tickle"],
    "благословить": ["благословить", "bless"],
    "проклясть": ["проклясть", "curse"],
}


def _create_rp_handler(action: str) -> Callable:
    async def handler(m: Message) -> None:
        await process_rp_action(m, action)
    return handler


for action, variants in RP_MAPPINGS.items():
    pattern = r"(?i)^(" + "|".join(re.escape(v) for v in variants) + r")(\s|$)"
    router.message(F.text.regexp(pattern))(_create_rp_handler(action))


# ============================================================================
# КАЗИНО В ЧАТЕ
# ============================================================================

async def _handle_casino_loss(uid: int, bot: Bot, context: str) -> None:
    await offer_donation(bot, uid, context)


@router.message(F.text.regexp(r"(?i)^(слоты|slot|сл)(\s+)(\d+)$"))
async def cmd_chat_slots(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    try:
        bet = safe_int_parse(m.text.split()[-1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    result, err, won = await play_casino_slots_animated(m.chat.id, bet, m.from_user.id, bot)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в слотах.\n\n")


@router.message(F.text.regexp(r"(?i)^кости число(\s+)(\d+)(\s+)([1-6])$"))
async def cmd_dice_number(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
        number = safe_int_parse(parts[3], default=0, min_val=1, max_val=6)
    except Exception:
        await m.answer("Неверные параметры.")
        return
    if bet == 0 or number == 0:
        await m.answer("Неверные параметры.")
        return
    result, err, won = await play_casino_dice_game(m.chat.id, bet, m.from_user.id, bot, "number", number)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.message(F.text.regexp(r"(?i)^кости чет(\s+)(\d+)(\s+)(чет|нечет|четное|нечетное|ч|нч)$"))
async def cmd_dice_even_odd(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    choice_raw = parts[3].lower()
    choice = "even" if choice_raw in ["чет", "четное", "ч"] else "odd"
    result, err, won = await play_casino_dice_game(m.chat.id, bet, m.from_user.id, bot, "even_odd", choice)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.message(F.text.regexp(r"(?i)^кости больше(\s+)(\d+)(\s+)(больше|меньше|б|м)$"))
async def cmd_dice_high_low(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    choice_raw = parts[3].lower()
    choice = "high" if choice_raw in ["больше", "б"] else "low"
    result, err, won = await play_casino_dice_game(m.chat.id, bet, m.from_user.id, bot, "high_low", choice)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.message(F.text.regexp(r"(?i)^(дротик|darts|дрот)(\s+)(попадание|промах)?\s*(\d+)$"))
async def cmd_chat_darts(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    text_lower = m.text.lower()
    bet_on_miss = "промах" in text_lower
    try:
        bet = safe_int_parse(m.text.split()[-1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    result, err, won = await play_casino_darts_animated(m.chat.id, bet, m.from_user.id, bot, bet_on_miss)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в дротике.\n\n")


@router.message(F.text.regexp(r"(?i)^(баскет|basketball|баск)(\s+)(попадание|промах)?\s*(\d+)$"))
async def cmd_chat_basketball(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    text_lower = m.text.lower()
    bet_on_miss = "промах" in text_lower
    try:
        bet = safe_int_parse(m.text.split()[-1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    result, err, won = await play_casino_basketball_animated(m.chat.id, bet, m.from_user.id, bot, bet_on_miss)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в баскетболе.\n\n")


@router.message(F.text.regexp(r"(?i)^(монетка|coin|мон)(\s+)(\d+)(\s+)(орел|решка|о|р)$"))
async def cmd_chat_coin(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    choice = "heads" if parts[2].lower() in ["орел", "о"] else "tails"
    result, err, won = play_casino_coin(m.from_user.id, bet, choice)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в монетке.\n\n")


@router.message(F.text.regexp(r"(?i)^рул цвет(\s+)(\d+)(\s+)(красное|черное|зеленое|к|ч|з)$"))
async def cmd_roulette_color(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    color_raw = parts[3].lower()
    color = "red" if color_raw in ["красное", "к"] else ("black" if color_raw in ["черное", "ч"] else "green")
    result, err, won = play_casino_roulette(m.from_user.id, bet, "color", color)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.message(F.text.regexp(r"(?i)^рул чет(\s+)(\d+)(\s+)(чет|нечет|четное|нечетное|ч|нч)$"))
async def cmd_roulette_even_odd(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    choice_raw = parts[3].lower()
    choice = "even" if choice_raw in ["чет", "четное", "ч"] else "odd"
    result, err, won = play_casino_roulette(m.from_user.id, bet, "even_odd", choice)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.message(F.text.regexp(r"(?i)^рул половина(\s+)(\d+)(\s+)(низ|верх|1\-18|19\-36|н|в)$"))
async def cmd_roulette_half(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    choice_raw = parts[3].lower()
    choice = "low" if choice_raw in ["низ", "1-18", "н"] else "high"
    result, err, won = play_casino_roulette(m.from_user.id, bet, "half", choice)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.message(F.text.regexp(r"(?i)^рул число(\s+)(\d+)(\s+)(\d{1,2})$"))
async def cmd_roulette_number(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
        number = safe_int_parse(parts[3], default=-1, min_val=0, max_val=36)
    except Exception:
        await m.answer("Неверные параметры.")
        return
    if bet == 0 or number < 0 or number > 36:
        await m.answer("Число должно быть от 0 до 36.")
        return
    result, err, won = play_casino_roulette(m.from_user.id, bet, "number", number)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.message(F.text.regexp(r"(?i)^рул дюжина(\s+)(\d+)(\s+)(1|2|3)$"))
async def cmd_roulette_dozen(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
        dozen = safe_int_parse(parts[3], default=0, min_val=1, max_val=3)
    except Exception:
        await m.answer("Неверные параметры.")
        return
    if bet == 0 or dozen == 0:
        await m.answer("Неверные параметры.")
        return
    result, err, won = play_casino_roulette(m.from_user.id, bet, "dozen", dozen)
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.message(F.text.regexp(r"(?i)^(больше|high)(\s+)(\d+)$"))
async def cmd_chat_highlow_high(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    try:
        bet = safe_int_parse(m.text.split()[-1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    result, err, won = play_casino_highlow(m.from_user.id, bet, "high")
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL}.\n\n")


@router.message(F.text.regexp(r"(?i)^(меньше|low)(\s+)(\d+)$"))
async def cmd_chat_highlow_low(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    try:
        bet = safe_int_parse(m.text.split()[-1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    result, err, won = play_casino_highlow(m.from_user.id, bet, "low")
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL}.\n\n")


# ============================================================================
# МИНЫ В ЧАТЕ
# ============================================================================

@router.message(F.text.regexp(r"(?i)^(мины|mines)(\s+)(\d+)(\s+)(\d+)$"))
async def cmd_chat_mines(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
        mines_count = safe_int_parse(parts[2], default=0, min_val=Config.MINES_MIN_COUNT, max_val=Config.MINES_MAX_COUNT)
    except Exception:
        await m.answer("Неверные параметры. Используй: <code>мины 100 5</code>")
        return
    if bet == 0 or mines_count == 0:
        await m.answer("Неверные параметры.")
        return
    if p["crystals"] < bet:
        await m.answer(f"Недостаточно кристаллов. У тебя: {p['crystals']} {E_CRYSTAL}")
        return
    if m.from_user.id in ACTIVE_MINES:
        await m.answer("У тебя уже активна игра в мины. Заверши её.")
        return
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, m.from_user.id))])
    game = start_mines_game(m.from_user.id, bet, mines_count)
    sent = await m.answer(
        f"{E_MINE} <b>МИНЫ</b>\n\n"
        f"💵 Ставка: <b>{bet}</b> {E_CRYSTAL}\n"
        f"{E_BOMB} Мин на поле: <b>{mines_count}</b>\n"
        f"📈 Множитель: <b>×{game.current_multiplier}</b>\n\n"
        f"{generate_mines_field(game)}\n\n"
        f"<i>Нажимай на клетки, чтобы открыть. Избегай мин!</i>",
        reply_markup=get_mines_keyboard(game),
        parse_mode=ParseMode.HTML
    )
    game.message_id = sent.message_id
    game.chat_id = sent.chat.id
    ACTIVE_MINES[m.from_user.id] = game
    db.execute("UPDATE player_stats SET mines_games=mines_games+1 WHERE user_id=?", (m.from_user.id,))


# ============================================================================
# КРАШ В ЧАТЕ
# ============================================================================

@router.message(F.text.regexp(r"(?i)^(краш|crash)(\s+)(\d+)$"))
async def cmd_chat_crash(m: Message, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start в ЛС бота.")
        return
    parts = m.text.split()
    try:
        bet = safe_int_parse(parts[1], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    except Exception:
        await m.answer("Неверная ставка.")
        return
    if bet == 0:
        await m.answer("Неверная ставка.")
        return
    if p["crystals"] < bet:
        await m.answer(f"Недостаточно кристаллов. У тебя: {p['crystals']} {E_CRYSTAL}")
        return
    if m.from_user.id in ACTIVE_CRASH:
        await m.answer("У тебя уже активна игра в краш.")
        return
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, m.from_user.id))])
    game = start_crash_game(m.from_user.id, bet)
    sent = await m.answer(
        generate_crash_display(game),
        reply_markup=get_crash_keyboard(game),
        parse_mode=ParseMode.HTML
    )
    game.message_id = sent.message_id
    game.chat_id = sent.chat.id
    ACTIVE_CRASH[m.from_user.id] = game
    game.task = asyncio.create_task(crash_tick_loop(game, bot))
    db.execute("UPDATE player_stats SET crash_games=crash_games+1 WHERE user_id=?", (m.from_user.id,))


# ============================================================================
# АДМИН КОМАНДЫ
# ============================================================================

@router.message(F.text.regexp(r"(?i)^событие босс$"))
async def adm_spawn_boss(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("boss", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["boss"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^событие караван$"))
async def adm_spawn_caravan(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("caravan", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["caravan"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^событие набег$"))
async def adm_spawn_raid(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("raid", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["raid"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^событие дракон$"))
async def adm_spawn_dragon_raid(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("dragon_raid", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["dragon_raid"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^событие демон$"))
async def adm_spawn_demon_invasion(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("demon_invasion", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["demon_invasion"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^событие голем$"))
async def adm_spawn_golem(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    event = spawn_chat_event("ancient_golem", m.from_user.id)
    if not event:
        await m.answer("Событие уже активно!")
        return
    template = CHAT_EVENT_TEMPLATES["ancient_golem"]
    await m.answer(template["announce_text"].format(emoji=template["emoji"], hp=event.hp))


@router.message(F.text.regexp(r"(?i)^босс(\s+)(\w+)$"))
async def adm_spawn_boss_by_key(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    parts = m.text.split()
    bkey = parts[2].lower()
    if bkey not in BOSSES:
        await m.answer(f"❌ Босс <code>{bkey}</code> не найден.\n\nДоступные: {', '.join(BOSSES.keys())}")
        return
    boss = BOSSES[bkey]
    event = spawn_chat_event("boss", m.from_user.id, custom_hp=boss["hp"])
    if not event:
        await m.answer("Событие уже активно!")
        return
    await m.answer(
        f"🚨 <b>ВНИМАНИЕ!</b>\n\n"
        f"{boss['name']} появился в чате!\n"
        f"❤️ HP: {event.hp}\n\n"
        f"Используйте команду <code>атака</code>!"
    )


@router.message(F.text.regexp(r"(?i)^(следующее событие|когда босс)$"))
async def adm_next_event(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    global NEXT_SCHEDULED_EVENT
    if NEXT_SCHEDULED_EVENT and NEXT_SCHEDULED_EVENT > time.time():
        time_left = int(NEXT_SCHEDULED_EVENT - time.time())
        hours = time_left // 3600
        minutes = (time_left % 3600) // 60
        seconds = time_left % 60
        await m.answer(
            f"⏰ <b>Следующее запланированное событие:</b>\n\n"
            f"Через: <b>{hours}ч {minutes}м {seconds}с</b>\n"
            f"Время: <b>{time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(NEXT_SCHEDULED_EVENT))}</b>"
        )
    else:
        await m.answer("📅 Следующее событие будет через 4 часа (автоматически).")


@router.message(F.text.regexp(r"(?i)^бан(\s|$)"))
async def adm_cmd_ban(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    tid, err = resolve_command_target(m, "бан")
    if err or not tid:
        await m.answer(err or "Не найдено.")
        return
    db.execute("UPDATE players SET banned=1 WHERE user_id=?", (tid,))
    ACTIVE_DUELS.pop(tid, None)
    await m.answer(f"🚫 Игрок <code>{tid}</code> забанен.")


@router.message(F.text.regexp(r"(?i)^разбан(\s|$)"))
async def adm_cmd_unban(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    tid, err = resolve_command_target(m, "разбан")
    if err or not tid:
        await m.answer(err or "Не найдено.")
        return
    db.execute("UPDATE players SET banned=0 WHERE user_id=?", (tid,))
    await m.answer(f"✅ Игрок <code>{tid}</code> разбанен.")


@router.message(F.text.regexp(r"(?i)^выдать(\s|$)"))
async def adm_cmd_give(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    tid, err = resolve_command_target(m, "выдать")
    if err or not tid:
        await m.answer(err or "Не найдено.")
        return
    amount = next((int(x) for x in (m.text or "").split() if x.lstrip("-").isdigit()), None)
    if not amount:
        await m.answer("Укажи сумму: <code>выдать 1000 @user</code>")
        return
    db.execute("UPDATE players SET crystals=crystals+? WHERE user_id=?", (amount, tid))
    await m.answer(f"✅ Выдано {amount} {E_CRYSTAL} игроку <code>{tid}</code>.")
    notify_player(tid, f"🎁 Админ выдал тебе {amount} {E_CRYSTAL}")


@router.message(F.text.regexp(r"(?i)^промо создать(\s+)(\S+)(\s+)(\d+)(\s+)(\d+)(\s+)(\d+)(\s+)(\d+)$"))
async def adm_promo_create(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    parts = m.text.split()
    code = parts[2]
    crystals = safe_int_parse(parts[4], default=0)
    wins = safe_int_parse(parts[6], default=0)
    max_uses = safe_int_parse(parts[8], default=1)
    hours = safe_int_parse(parts[10], default=24)
    success, message = create_promo_code(code, crystals, wins, max_uses, hours, m.from_user.id)
    await m.answer(message)


@router.message(F.text.regexp(r"(?i)^промо удалить(\s+)(\S+)$"))
async def adm_promo_delete(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    code = m.text.split()[2].strip().upper()
    existing = db.fetch_one("SELECT code FROM promo_codes WHERE code=?", (code,))
    if not existing:
        await m.answer(f"❌ Промокод <code>{code}</code> не найден.")
        return
    db.execute("UPDATE promo_codes SET active=0 WHERE code=?", (code,))
    await m.answer(f"✅ Промокод <code>{code}</code> деактивирован.")


@router.message(F.text.regexp(r"(?i)^промо список$"))
async def adm_promo_list(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    promos = db.fetch_all("SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT 20")
    if not promos:
        await m.answer(f"{E_PROMO} Промокодов пока нет.")
        return
    lines = [f"{E_PROMO} <b>ВСЕ ПРОМОКОДЫ ({len(promos)})</b>\n"]
    now = time.time()
    for i, p in enumerate(promos, 1):
        is_expired = p["expires_at"] < now
        is_maxed = p["current_uses"] >= p["max_uses"]
        status = "✅" if (p["active"] and not is_expired and not is_maxed) else ("⏰" if is_expired else ("🚫" if is_maxed else "❌"))
        expires_str = time.strftime("%d.%m %H:%M", time.localtime(p["expires_at"]))
        lines.append(f"{i}. {status} <code>{p['code']}</code>")
        rewards = []
        if p["reward_crystals"] > 0:
            rewards.append(f"💎{p['reward_crystals']}")
        if p["reward_wins"] > 0:
            rewards.append(f"🏆{p['reward_wins']}")
        lines.append(f"   Награда: {' + '.join(rewards) if rewards else '—'}")
        lines.append(f"   Активаций: {p['current_uses']}/{p['max_uses']}")
        lines.append(f"   Истекает: {expires_str}\n")
    await m.answer("\n".join(lines))


@router.message(F.text.regexp(r"(?i)^рассылка\s+"))
async def adm_cmd_broadcast(m: Message, bot: Bot) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    text = (m.text or "").split(" ", 1)[1].strip()
    if not text:
        await m.answer("Использование: <code>рассылка текст</code>")
        return
    rows = db.fetch_all("SELECT user_id FROM players WHERE banned=0 AND is_bot=0")
    ok_count = 0
    for r in rows:
        try:
            await bot.send_message(r["user_id"], f"📢 <b>Сообщение:</b>\n\n{text}")
            ok_count += 1
            await asyncio.sleep(BROADCAST_DELAY)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass
    await m.answer(f"✅ Рассылка завершена. Доставлено: {ok_count} игрокам.")


@router.message(F.text.regexp(r"(?i)^статистика$"))
async def adm_cmd_stats(m: Message) -> None:
    """ИСПРАВЛЕНО v20.1: banned_players вместо bed_players."""
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    total_players = db.fetch_one("SELECT COUNT(*) c FROM players WHERE is_bot=0")["c"]
    total_bots = db.fetch_one("SELECT COUNT(*) c FROM players WHERE is_bot=1")["c"]
    banned_players = db.fetch_one("SELECT COUNT(*) c FROM players WHERE banned=1")["c"]
    active_duels = len(ACTIVE_DUELS)
    active_event = "Да" if ACTIVE_CHAT_EVENT and ACTIVE_CHAT_EVENT.is_active() else "Нет"
    text = (
        f"{E_STATS} <b>СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Всего игроков: <b>{total_players}</b>\n"
        f"🤖 Всего ботов: <b>{total_bots}</b>\n"
        f"🚫 Забанено: <b>{banned_players}</b>\n"
        f"⚔️ Активных дуэлей: <b>{active_duels}</b>\n"
        f"👹 Активное событие: <b>{active_event}</b>"
    )
    await m.answer(text)


@router.message(F.text.regexp(r"(?i)^список игроков$"))
async def adm_cmd_list_players(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    players = db.fetch_all("SELECT user_id, name, wins, crystals FROM players WHERE is_bot=0 ORDER BY wins DESC LIMIT 20")
    if not players:
        await m.answer("Игроков не найдено.")
        return
    lines = [f"{E_USERS} <b>СПИСОК ИГРОКОВ (Топ 20)</b>\n"]
    for i, p in enumerate(players, 1):
        lines.append(f"{i}. <b>{esc(p['name'])}</b> — {p['wins']}🏆 / {p['crystals']}💎")
    await m.answer("\n".join(lines))


@router.message(F.text.regexp(r"(?i)^очистить ботов$"))
async def adm_cmd_clear_bots(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    db.execute("DELETE FROM players WHERE is_bot=1")
    await m.answer("✅ Все боты удалены.")


@router.message(F.text.regexp(r"(?i)^добавить ботов(\s+)(\d+)$"))
async def adm_cmd_add_bots(m: Message) -> None:
    if not is_admin(m.from_user.id):
        await m.answer(f"{E_WARNING} У тебя нет прав администратора.")
        return
    parts = m.text.split()
    count = safe_int_parse(parts[2], default=0, min_val=1, max_val=100)
    if count == 0:
        await m.answer("Количество ботов должно быть от 1 до 100.")
        return
    before = db.fetch_one("SELECT COUNT(*) c FROM players WHERE is_bot=1")["c"]
    ensure_masked_bots_exist(before + count)
    after = db.fetch_one("SELECT COUNT(*) c FROM players WHERE is_bot=1")["c"]
    await m.answer(f"✅ Добавлено {after - before} ботов.")


# ============================================================================
# ВЫЗОВЫ
# ============================================================================

async def send_challenge_messages(
    challenger_id: int, target_id: int, challenger_name: str, target_name: str,
    bot: Bot, direct: bool = False
) -> Tuple[Optional[Message], Optional[Message]]:
    challenger_msg = None
    target_msg = None
    target_text = (
        f"{E_GLOVE} <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
        f"👤 <b>{esc(challenger_name)}</b> кинул тебе перчатку!\n"
        f"⏳ У тебя <b>{Config.CHALLENGE_TIMEOUT}</b> секунд.\n\n"
        f"Выбери действие:"
    )
    challenger_text = (
        f"{E_GLOVE} <b>ВЫЗОВ ОТПРАВЛЕН!</b>\n\n"
        f"👤 Твой запрос доставлен игроку <b>{esc(target_name)}</b>.\n"
        f"⏳ Ожидай ответа <b>{Config.CHALLENGE_TIMEOUT}</b> секунд.\n\n"
        f"Ты можешь обновить статус или отменить вызов:"
    )
    try:
        target_msg = await bot.send_message(
            target_id, target_text,
            reply_markup=get_challenge_accept_kb(challenger_id, target_id),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Failed to send challenge to target {target_id}: {e}")
        return None, None
    try:
        challenger_msg = await bot.send_message(
            challenger_id, challenger_text,
            reply_markup=get_challenge_waiting_kb(challenger_id, target_id),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Failed to send confirmation to challenger {challenger_id}: {e}")
    return challenger_msg, target_msg


async def challenge_timeout_task(challenger_id: int, target_id: int, bot: Bot) -> None:
    await asyncio.sleep(Config.CHALLENGE_TIMEOUT)
    key = (challenger_id, target_id)
    pending = PENDING_DUELS.get(key)
    if not pending:
        return
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.target_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТКЛОНЁН</b>\n\n⏱ Время ожидания истекло.",
        None
    )
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.challenger_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТКЛОНЁН</b>\n\n⏱ Время ожидания истекло.",
        None
    )
    PENDING_DUELS.pop(key, None)


# ============================================================================
# CALLBACK HANDLERS — ВЫЗОВЫ
# ============================================================================

@router.callback_query(F.data.regexp(r"^challenge:accept:(-?\d+):(-?\d+)$"))
async def cb_challenge_accept(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    challenger_id = safe_int_parse(parts[2], default=0)
    target_id = safe_int_parse(parts[3], default=0)
    if cb.from_user.id != target_id:
        await cb.answer("Это не твой вызов!", show_alert=True)
        return
    key = (challenger_id, target_id)
    pending = PENDING_DUELS.get(key)
    if not pending:
        await cb.answer("Вызов уже не действителен.", show_alert=True)
        return
    if pending.timeout_task and not pending.timeout_task.done():
        pending.timeout_task.cancel()
    challenger_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (challenger_id,))
    target_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (target_id,))
    challenger_name = challenger_row["name"] if challenger_row else "Неизвестный"
    target_name = target_row["name"] if target_row else "Неизвестный"
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.target_msg_id,
        f"{E_TROPHY} <b>ВЫЗОВ ПРИНЯТ!</b>\n\n⚔️ Бой начинается...",
        None
    )
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.challenger_msg_id,
        f"{E_TROPHY} <b>ВЫЗОВ ПРИНЯТ!</b>\n\n⚔️ Бой начинается...",
        None
    )
    PENDING_DUELS.pop(key, None)
    await cb.answer()
    await asyncio.sleep(1.5)
    await initiate_duel_message(challenger_id, target_id, cb.message, bot)


@router.callback_query(F.data.regexp(r"^challenge:reject:(-?\d+):(-?\d+)$"))
async def cb_challenge_reject(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    challenger_id = safe_int_parse(parts[2], default=0)
    target_id = safe_int_parse(parts[3], default=0)
    if cb.from_user.id != target_id:
        await cb.answer("Это не твой вызов!", show_alert=True)
        return
    key = (challenger_id, target_id)
    pending = PENDING_DUELS.get(key)
    if not pending:
        await cb.answer("Вызов уже не действителен.", show_alert=True)
        return
    if pending.timeout_task and not pending.timeout_task.done():
        pending.timeout_task.cancel()
    challenger_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (challenger_id,))
    target_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (target_id,))
    challenger_name = challenger_row["name"] if challenger_row else "Неизвестный"
    target_name = target_row["name"] if target_row else "Неизвестный"
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.target_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТКЛОНЁН</b>",
        None
    )
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.challenger_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТКЛОНЁН</b>",
        None
    )
    PENDING_DUELS.pop(key, None)
    await cb.answer("Вызов отклонён.")


@router.callback_query(F.data.regexp(r"^challenge:cancel:(-?\d+):(-?\d+)$"))
async def cb_challenge_cancel(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    challenger_id = safe_int_parse(parts[2], default=0)
    target_id = safe_int_parse(parts[3], default=0)
    if cb.from_user.id != challenger_id:
        await cb.answer("Это не твой вызов!", show_alert=True)
        return
    key = (challenger_id, target_id)
    pending = PENDING_DUELS.get(key)
    if not pending:
        await cb.answer("Вызов уже не действителен.", show_alert=True)
        return
    if pending.timeout_task and not pending.timeout_task.done():
        pending.timeout_task.cancel()
    challenger_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (challenger_id,))
    target_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (target_id,))
    challenger_name = challenger_row["name"] if challenger_row else "Неизвестный"
    target_name = target_row["name"] if target_row else "Неизвестный"
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.target_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТМЕНЁН</b>",
        None
    )
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.challenger_msg_id,
        f"{E_SKULL} <b>ВЫЗОВ ОТМЕНЁН</b>",
        None
    )
    PENDING_DUELS.pop(key, None)
    await cb.answer("Вызов отменён.")


@router.callback_query(F.data.regexp(r"^challenge:refresh:(-?\d+):(-?\d+)$"))
async def cb_challenge_refresh(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    challenger_id = safe_int_parse(parts[2], default=0)
    target_id = safe_int_parse(parts[3], default=0)
    if cb.from_user.id != challenger_id:
        await cb.answer("Это не твой вызов!", show_alert=True)
        return
    key = (challenger_id, target_id)
    pending = PENDING_DUELS.get(key)
    if not pending:
        await cb.answer("Вызов уже не действителен.", show_alert=True)
        return
    target_row = db.fetch_one("SELECT name FROM players WHERE user_id=?", (target_id,))
    target_name = target_row["name"] if target_row else "Неизвестный"
    time_left = max(0, int(Config.CHALLENGE_TIMEOUT - (time.time() - pending.created_at)))
    await safe_edit_message_by_id(
        bot, pending.chat_id, pending.challenger_msg_id,
        f"{E_GLOVE} <b>ВЫЗОВ ОЖИДАЕТ ОТВЕТА</b>\n\n"
        f"👤 Игрок <b>{esc(target_name)}</b> получил твой вызов.\n"
        f"⏳ Осталось времени: <b>{time_left}</b> сек.",
        get_challenge_waiting_kb(challenger_id, target_id)
    )
    await cb.answer(f"Осталось {time_left} сек.")


# ============================================================================
# CALLBACK HANDLERS — ПРОФИЛЬ / НАСТРОЙКИ
# ============================================================================

@router.callback_query(F.data == "profile:settings")
async def cb_profile_settings(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_settings_screen(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "settings:toggle_allow_duels")
async def cb_toggle_allow_duels(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT allow_duels FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p:
        await cb.answer("Сначала /start", show_alert=True)
        return
    current = safe_row_get(p, "allow_duels", 1)
    new_value = 0 if current else 1
    db.execute("UPDATE players SET allow_duels=? WHERE user_id=?", (new_value, cb.from_user.id))
    text, kb = generate_settings_screen(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    status = "разрешены" if new_value else "запрещены"
    await cb.answer(f"✅ Вызовы {status}")


@router.callback_query(F.data == "profile:back")
async def cb_profile_back(cb: CallbackQuery) -> None:
    row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not row:
        await cb.answer("Сначала /start", show_alert=True)
        return
    await safe_edit_message(cb, generate_profile_text(row), generate_profile_kb())
    await cb.answer()


# ============================================================================
# CALLBACK HANDLERS — КАЗИНО
# ============================================================================

@router.callback_query(F.data == "casino:menu")
async def cb_casino_menu(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_casino_menu(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "casino:slots")
async def cb_casino_slots(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_SLOT} <b>СЛОТЫ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Правила:</b>\n"
        f"• Выпадает 1 символ (🎰 анимация)\n"
        f"• <b>1</b> = ДЖЕКПОТ ×10\n"
        f"• Другие значения = проигрыш\n\n"
        f"<b>Выбери ставку или введи свою:</b>"
    )
    await safe_edit_message(cb, text, get_bet_kb("slots"))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:slots:bet:(\d+)$"))
async def cb_casino_slots_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[3], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_slots_animated(cb.message.chat.id, bet, cb.from_user.id, bot)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:slots", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в слотах.\n\n")


@router.callback_query(F.data == "casino:dice")
async def cb_casino_dice(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DICE} <b>КОСТИ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери режим игры:</b>"
    )
    await safe_edit_message(cb, text, get_dice_mode_kb())
    await cb.answer()


@router.callback_query(F.data == "casino:dice:number")
async def cb_casino_dice_number(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DICE} <b>КОСТИ — НА ЧИСЛО (×6)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:dice:number:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:dice:number:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:dice", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:number:bet:(\d+)$"))
async def cb_casino_dice_number_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"{E_DICE} <b>КОСТИ — НА ЧИСЛО</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери число от 1 до 6:"
    )
    await safe_edit_message(cb, text, get_dice_number_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:num:(\d+):(\d+)$"))
async def cb_casino_dice_num(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    bet = safe_int_parse(parts[3], default=0)
    number = safe_int_parse(parts[4], default=0, min_val=1, max_val=6)
    if bet == 0 or number == 0:
        await cb.answer("Неверные параметры.", show_alert=True)
        return
    result, err, won = await play_casino_dice_game(cb.message.chat.id, bet, cb.from_user.id, bot, "number", number)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:dice:number", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.callback_query(F.data == "casino:dice:even_odd")
async def cb_casino_dice_even_odd(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DICE} <b>КОСТИ — ЧЁТ/НЕЧЕТ (×2)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:dice:even_odd:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:dice:even_odd:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:dice", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:even_odd:bet:(\d+)$"))
async def cb_casino_dice_even_odd_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"{E_DICE} <b>КОСТИ — ЧЁТ/НЕЧЕТ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    await safe_edit_message(cb, text, get_dice_even_odd_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:(even|odd):(\d+)$"))
async def cb_casino_dice_even_odd_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_dice_game(cb.message.chat.id, bet, cb.from_user.id, bot, "even_odd", choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:dice:even_odd", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.callback_query(F.data == "casino:dice:high_low")
async def cb_casino_dice_high_low(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DICE} <b>КОСТИ — БОЛЬШЕ/МЕНЬШЕ (×2)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"• Больше: 4, 5, 6\n"
        f"• Меньше: 1, 2, 3\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:dice:high_low:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:dice:high_low:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:dice", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:high_low:bet:(\d+)$"))
async def cb_casino_dice_high_low_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"{E_DICE} <b>КОСТИ — БОЛЬШЕ/МЕНЬШЕ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    await safe_edit_message(cb, text, get_dice_high_low_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:dice:(high|low):(\d+)$"))
async def cb_casino_dice_high_low_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_dice_game(cb.message.chat.id, bet, cb.from_user.id, bot, "high_low", choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:dice:high_low", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в костях.\n\n")


@router.callback_query(F.data == "casino:darts")
async def cb_casino_darts(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DARTS} <b>ДРОТИК</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери режим:</b>"
    )
    await safe_edit_message(cb, text, get_darts_mode_kb())
    await cb.answer()


@router.callback_query(F.data == "casino:darts:hit")
async def cb_casino_darts_hit(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DARTS} <b>ДРОТИК — НА ПОПАДАНИЕ (×1.9)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    await safe_edit_message(cb, text, get_bet_kb("darts:hit"))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:darts:hit:bet:(\d+)$"))
async def cb_casino_darts_hit_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_darts_animated(cb.message.chat.id, bet, cb.from_user.id, bot, False)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:darts:hit", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в дротике.\n\n")


@router.callback_query(F.data == "casino:darts:miss")
async def cb_casino_darts_miss(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_DARTS} <b>ДРОТИК — НА ПРОМАХ (×1.9)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    await safe_edit_message(cb, text, get_bet_kb("darts:miss"))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:darts:miss:bet:(\d+)$"))
async def cb_casino_darts_miss_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_darts_animated(cb.message.chat.id, bet, cb.from_user.id, bot, True)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:darts:miss", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в дротике.\n\n")


@router.callback_query(F.data == "casino:basket")
async def cb_casino_basket(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_BASKET} <b>БАСКЕТБОЛ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери режим:</b>"
    )
    await safe_edit_message(cb, text, get_basket_mode_kb())
    await cb.answer()


@router.callback_query(F.data == "casino:basket:hit")
async def cb_casino_basket_hit(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_BASKET} <b>БАСКЕТБОЛ — НА ПОПАДАНИЕ (×1.9)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    await safe_edit_message(cb, text, get_bet_kb("basket:hit"))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:basket:hit:bet:(\d+)$"))
async def cb_casino_basket_hit_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_basketball_animated(cb.message.chat.id, bet, cb.from_user.id, bot, False)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:basket:hit", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в баскетболе.\n\n")


@router.callback_query(F.data == "casino:basket:miss")
async def cb_casino_basket_miss(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_BASKET} <b>БАСКЕТБОЛ — НА ПРОМАХ (×1.9)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    await safe_edit_message(cb, text, get_bet_kb("basket:miss"))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:basket:miss:bet:(\d+)$"))
async def cb_casino_basket_miss_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = await play_casino_basketball_animated(cb.message.chat.id, bet, cb.from_user.id, bot, True)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:basket:miss", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в баскетболе.\n\n")


@router.callback_query(F.data == "casino:roulette")
async def cb_casino_roulette(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"🎡 <b>РУЛЕТКА</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери режим игры:</b>"
    )
    await safe_edit_message(cb, text, get_roulette_mode_kb())
    await cb.answer()


@router.callback_query(F.data == "casino:roulette:color")
async def cb_roulette_color(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"🎨 <b>РУЛЕТКА — НА ЦВЕТ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"• 🔴 Красное / ⚫ Чёрное = ×2\n"
        f"• 🟢 Зеро = ×14\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:roulette:color:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:roulette:color:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:roulette", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:color:bet:(\d+)$"))
async def cb_roulette_color_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"🎨 <b>РУЛЕТКА — НА ЦВЕТ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери цвет:"
    )
    await safe_edit_message(cb, text, get_roulette_color_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:color:(red|black|green):(\d+)$"))
async def cb_roulette_color_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    color = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = play_casino_roulette(cb.from_user.id, bet, "color", color)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:roulette:color", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.callback_query(F.data == "casino:roulette:even_odd")
async def cb_roulette_even_odd(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"⚖️ <b>РУЛЕТКА — ЧЁТ/НЕЧЕТ (×2)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:roulette:even_odd:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:roulette:even_odd:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:roulette", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:even_odd:bet:(\d+)$"))
async def cb_roulette_even_odd_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"⚖️ <b>РУЛЕТКА — ЧЁТ/НЕЧЕТ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    await safe_edit_message(cb, text, get_roulette_even_odd_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:even_odd:(even|odd):(\d+)$"))
async def cb_roulette_even_odd_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = play_casino_roulette(cb.from_user.id, bet, "even_odd", choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:roulette:even_odd", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.callback_query(F.data == "casino:roulette:half")
async def cb_roulette_half(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"📈 <b>РУЛЕТКА — ПОЛОВИНА (×2)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"• 1-18 (низ)\n"
        f"• 19-36 (верх)\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:roulette:half:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:roulette:half:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:roulette", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:half:bet:(\d+)$"))
async def cb_roulette_half_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"📈 <b>РУЛЕТКА — ПОЛОВИНА</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    await safe_edit_message(cb, text, get_roulette_half_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:half:(low|high):(\d+)$"))
async def cb_roulette_half_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = play_casino_roulette(cb.from_user.id, bet, "half", choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:roulette:half", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.callback_query(F.data == "casino:roulette:number")
async def cb_roulette_number(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"🔢 <b>РУЛЕТКА — НА ЧИСЛО (×36)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:roulette:number:bet:{b}", "danger") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:roulette:number:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:roulette", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:number:bet:(\d+)$"))
async def cb_roulette_number_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"🔢 <b>РУЛЕТКА — НА ЧИСЛО</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери число от 0 до 36:"
    )
    await safe_edit_message(cb, text, get_roulette_number_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:num:(\d+):(\d+)$"))
async def cb_roulette_number_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    bet = safe_int_parse(parts[3], default=0)
    number = safe_int_parse(parts[4], default=-1, min_val=0, max_val=36)
    if bet == 0 or number < 0 or number > 36:
        await cb.answer("Неверные параметры.", show_alert=True)
        return
    result, err, won = play_casino_roulette(cb.from_user.id, bet, "number", number)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:roulette:number", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.callback_query(F.data == "casino:roulette:dozen")
async def cb_roulette_dozen(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"🎯 <b>РУЛЕТКА — НА ДЮЖИНУ (×3)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:roulette:dozen:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:roulette:dozen:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:roulette", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:dozen:bet:(\d+)$"))
async def cb_roulette_dozen_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"🎯 <b>РУЛЕТКА — НА ДЮЖИНУ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери дюжину:"
    )
    await safe_edit_message(cb, text, get_roulette_dozen_kb(bet))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:roulette:dozen:(\d+):(\d+)$"))
async def cb_roulette_dozen_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    dozen = safe_int_parse(parts[3], default=0, min_val=1, max_val=3)
    bet = safe_int_parse(parts[4], default=0)
    if dozen == 0 or bet == 0:
        await cb.answer("Неверные параметры.", show_alert=True)
        return
    result, err, won = play_casino_roulette(cb.from_user.id, bet, "dozen", dozen)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:roulette:dozen", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в рулетке.\n\n")


@router.callback_query(F.data == "casino:coin")
async def cb_casino_coin(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_COIN} <b>МОНЕТКА (×2)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:coin:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:coin:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:menu", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:coin:bet:(\d+)$"))
async def cb_casino_coin_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[3], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"{E_COIN} <b>МОНЕТКА</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔵 Орёл (×2)", f"casino:coin:heads:{bet}", "primary"),
        ("🔴 Решка (×2)", f"casino:coin:tails:{bet}", "danger"),
        (f"{E_BACK} Назад", "casino:coin", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:coin:(heads|tails):(\d+)$"))
async def cb_casino_coin_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = play_casino_coin(cb.from_user.id, bet, choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:coin", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL} в монетке.\n\n")


@router.callback_query(F.data == "casino:highlow")
async def cb_casino_highlow(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"📊 <b>БОЛЬШЕ/МЕНЬШЕ (×1.9)</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"• Число от 1 до 100\n"
        f"• Больше: 51-100\n"
        f"• Меньше: 1-49\n"
        f"• 50 = возврат ставки\n\n"
        f"Выбери ставку:"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"casino:highlow:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "casino:highlow:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:menu", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:highlow:bet:(\d+)$"))
async def cb_casino_highlow_bet(cb: CallbackQuery) -> None:
    bet = safe_int_parse(cb.data.split(":")[3], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    text = (
        f"📊 <b>БОЛЬШЕ/МЕНЬШЕ</b>\n\n"
        f"Ставка: <b>{bet} 💎</b>\n\n"
        f"Выбери:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("📈 Больше (51-100) (×1.9)", f"casino:highlow:high:{bet}", "success"),
        ("📉 Меньше (1-49) (×1.9)", f"casino:highlow:low:{bet}", "danger"),
        (f"{E_BACK} Назад", "casino:highlow", "primary"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^casino:highlow:(high|low):(\d+)$"))
async def cb_casino_highlow_play(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    choice = parts[3]
    bet = safe_int_parse(parts[4], default=0)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    result, err, won = play_casino_highlow(cb.from_user.id, bet, choice)
    if err:
        await cb.answer(err, show_alert=True)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{result}\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>\n\n"
        f"Выбери действие:"
    )
    kb = build_vertical_keyboard_with_styles([
        ("🔁 Ещё раз", "casino:highlow", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ])
    await safe_edit_message(cb, text, kb)
    await cb.answer()
    if not won:
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL}.\n\n")


# ============================================================================
# МИНЫ — CALLBACK HANDLERS
# ============================================================================

@router.callback_query(F.data == "casino:mines")
async def cb_casino_mines(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_MINE} <b>МИНЫ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Правила:</b>\n"
        f"• Поле 5×5 с минами\n"
        f"• Больше мин — выше множитель\n"
        f"• Открывай клетки, избегай мин\n"
        f"• Забери выигрыш в любой момент\n\n"
        f"<b>Выбери количество мин:</b>"
    )
    await safe_edit_message(cb, text, get_mines_setup_kb())
    await cb.answer()


@router.callback_query(F.data.regexp(r"^mines:start:(\d+)$"))
async def cb_mines_start(cb: CallbackQuery) -> None:
    mines_count = safe_int_parse(cb.data.split(":")[2], default=0, min_val=1, max_val=24)
    if mines_count == 0:
        await cb.answer("Неверное количество мин.", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_MINE} <b>МИНЫ</b> · {mines_count} мин\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери ставку:</b>"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"mines:bet:{mines_count}:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", f"mines:manual:{mines_count}", "success")]
        + [(f"{E_BACK} Назад", "casino:mines", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^mines:bet:(\d+):(\d+)$"))
async def cb_mines_bet(cb: CallbackQuery, bot: Bot) -> None:
    parts = cb.data.split(":")
    mines_count = safe_int_parse(parts[2], default=0, min_val=1, max_val=24)
    bet = safe_int_parse(parts[3], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    if mines_count == 0 or bet == 0:
        await cb.answer("Неверные параметры.", show_alert=True)
        return
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or p["crystals"] < bet:
        await cb.answer("Недостаточно кристаллов.", show_alert=True)
        return
    if cb.from_user.id in ACTIVE_MINES:
        await cb.answer("У тебя уже активна игра в мины.", show_alert=True)
        return
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, cb.from_user.id))])
    game = start_mines_game(cb.from_user.id, bet, mines_count)
    text = (
        f"{E_MINE} <b>МИНЫ</b>\n\n"
        f"💵 Ставка: <b>{bet}</b> {E_CRYSTAL}\n"
        f"{E_BOMB} Мин на поле: <b>{mines_count}</b>\n"
        f"📈 Множитель: <b>×{game.current_multiplier}</b>\n\n"
        f"{generate_mines_field(game)}\n\n"
        f"<i>Нажимай на клетки, чтобы открыть. Избегай мин!</i>"
    )
    try:
        await cb.message.edit_text(text, reply_markup=get_mines_keyboard(game), parse_mode=ParseMode.HTML)
        game.message_id = cb.message.message_id
        game.chat_id = cb.message.chat.id
    except TelegramBadRequest:
        sent = await cb.message.answer(text, reply_markup=get_mines_keyboard(game), parse_mode=ParseMode.HTML)
        game.message_id = sent.message_id
        game.chat_id = sent.chat.id
    ACTIVE_MINES[cb.from_user.id] = game
    db.execute("UPDATE player_stats SET mines_games=mines_games+1 WHERE user_id=?", (cb.from_user.id,))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^mines:cell:(\d+)$"))
async def cb_mines_cell(cb: CallbackQuery, bot: Bot) -> None:
    cell = safe_int_parse(cb.data.split(":")[2], default=-1)
    game = ACTIVE_MINES.get(cb.from_user.id)
    if not game:
        await cb.answer("Игра не найдена.", show_alert=True)
        return
    if not game.active:
        await cb.answer("Игра уже завершена.", show_alert=True)
        return
    survived, msg = game.open_cell(cell)
    if not survived:
        db.execute_transaction([
            ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (cb.from_user.id,)),
            ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (cb.from_user.id,)),
        ])
        text = (
            f"{E_BOMB} <b>БОМБА!</b>\n\n"
            f"💵 Ставка: <b>{game.bet}</b> {E_CRYSTAL}\n"
            f"💸 Ты проиграл!\n\n"
            f"{generate_mines_field(game)}\n\n"
            f"<i>В следующий раз будь осторожнее!</i>"
        )
        await safe_edit_message(cb, text, build_vertical_keyboard_with_styles([
            ("🔁 Играть ещё", "casino:mines", "primary"),
            (f"{E_BACK} В казино", "casino:menu", "success"),
        ]))
        await cb.answer(msg, show_alert=True)
        del ACTIVE_MINES[cb.from_user.id]
        await _handle_casino_loss(cb.from_user.id, bot, f"Ты проиграл <b>{game.bet}</b> {E_CRYSTAL} в минах.\n\n")
        return
    text = (
        f"{E_GEM} <b>БЕЗОПАСНО!</b>\n\n"
        f"💵 Ставка: <b>{game.bet}</b> {E_CRYSTAL}\n"
        f"📈 Множитель: <b>×{game.current_multiplier}</b>\n"
        f"💰 potential: <b>{game.current_winnings}</b> {E_CRYSTAL}\n\n"
        f"{generate_mines_field(game)}\n\n"
        f"{msg}"
    )
    await safe_edit_message(cb, text, get_mines_keyboard(game))
    await cb.answer()


@router.callback_query(F.data == "mines:cashout")
async def cb_mines_cashout(cb: CallbackQuery, bot: Bot) -> None:
    game = ACTIVE_MINES.get(cb.from_user.id)
    if not game:
        await cb.answer("Игра не найдена.", show_alert=True)
        return
    success, msg = game.cashout()
    if not success:
        await cb.answer(msg, show_alert=True)
        return
    winnings = game.current_winnings
    db.execute_transaction([
        ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (winnings, cb.from_user.id)),
        ("UPDATE player_stats SET mines_wins=mines_wins+1, casino_wins=casino_wins+1 WHERE user_id=?", (cb.from_user.id,)),
    ])
    text = (
        f"{E_CASHOUT} <b>ТЫ ЗАБРАЛ ВЫИГРЫШ!</b>\n\n"
        f"💵 Ставка: <b>{game.bet}</b> {E_CRYSTAL}\n"
        f"📈 Множитель: <b>×{game.current_multiplier}</b>\n"
        f"💰 Выигрыш: <b>{winnings}</b> {E_CRYSTAL}\n\n"
        f"{generate_mines_field(game)}"
    )
    await safe_edit_message(cb, text, build_vertical_keyboard_with_styles([
        ("🔁 Играть ещё", "casino:mines", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ]))
    await cb.answer(f"Выигрыш: {winnings} 💎")
    del ACTIVE_MINES[cb.from_user.id]


@router.callback_query(F.data == "mines:surrender")
async def cb_mines_surrender(cb: CallbackQuery, bot: Bot) -> None:
    game = ACTIVE_MINES.get(cb.from_user.id)
    if not game or not game.active:
        await cb.answer("Игра не активна.", show_alert=True)
        return
    game.active = False
    db.execute_transaction([
        ("UPDATE player_stats SET casino_losses=casino_losses+1 WHERE user_id=?", (cb.from_user.id,)),
        ("UPDATE players SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (cb.from_user.id,)),
    ])
    text = (
        f"{E_REJECT} <b>ТЫ СДАЛСЯ</b>\n\n"
        f"💵 Ставка: <b>{game.bet}</b> {E_CRYSTAL}\n"
        f"💸 Ты проиграл!\n\n"
        f"{generate_mines_field(game)}"
    )
    await safe_edit_message(cb, text, build_vertical_keyboard_with_styles([
        ("🔁 Играть ещё", "casino:mines", "primary"),
        (f"{E_BACK} В казино", "casino:menu", "success"),
    ]))
    await cb.answer("Ты сдался.")
    del ACTIVE_MINES[cb.from_user.id]
    await _handle_casino_loss(cb.from_user.id, bot, f"Ты сдался в минах и проиграл <b>{game.bet}</b> {E_CRYSTAL}.\n\n")


# ============================================================================
# КРАШ — CALLBACK HANDLERS
# ============================================================================

@router.callback_query(F.data == "casino:crash")
async def cb_casino_crash(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_ROCKET} <b>КРАШ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Правила:</b>\n"
        f"• Множитель растёт с 1.00x\n"
        f"• В любой момент может произойти крах\n"
        f"• Успей забрать выигрыш до краха!\n"
        f"• Если не успел — ставка сгорает\n\n"
        f"<b>Выбери ставку:</b>"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"crash:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "crash:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:menu", "danger")]
    )
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^crash:bet:(\d+)$"))
async def cb_crash_bet(cb: CallbackQuery, bot: Bot) -> None:
    bet = safe_int_parse(cb.data.split(":")[2], default=0, min_val=Config.CASINO_MIN_BET, max_val=Config.CASINO_MAX_BET)
    if bet == 0:
        await cb.answer("Неверная ставка.", show_alert=True)
        return
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or p["crystals"] < bet:
        await cb.answer("Недостаточно кристаллов.", show_alert=True)
        return
    if cb.from_user.id in ACTIVE_CRASH:
        await cb.answer("У тебя уже активна игра в краш.", show_alert=True)
        return
    db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, cb.from_user.id))])
    game = start_crash_game(cb.from_user.id, bet)
    try:
        await cb.message.edit_text(
            generate_crash_display(game),
            reply_markup=get_crash_keyboard(game),
            parse_mode=ParseMode.HTML
        )
        game.message_id = cb.message.message_id
        game.chat_id = cb.message.chat.id
    except TelegramBadRequest:
        sent = await cb.message.answer(
            generate_crash_display(game),
            reply_markup=get_crash_keyboard(game),
            parse_mode=ParseMode.HTML
        )
        game.message_id = sent.message_id
        game.chat_id = sent.chat.id
    ACTIVE_CRASH[cb.from_user.id] = game
    game.task = asyncio.create_task(crash_tick_loop(game, bot))
    db.execute("UPDATE player_stats SET crash_games=crash_games+1 WHERE user_id=?", (cb.from_user.id,))
    await cb.answer()


@router.callback_query(F.data == "crash:cashout")
async def cb_crash_cashout(cb: CallbackQuery, bot: Bot) -> None:
    game = ACTIVE_CRASH.get(cb.from_user.id)
    if not game:
        await cb.answer("Игра не найдена.", show_alert=True)
        return
    if game.cashed_out or game.crashed:
        await cb.answer("Игра уже завершена.", show_alert=True)
        return
    game.cashed_out = True
    game.cashout_multiplier = game.current_multiplier
    winnings = int(game.bet * game.cashout_multiplier)
    db.execute_transaction([
        ("UPDATE players SET crystals=crystals+?, consecutive_losses=0 WHERE user_id=?", (winnings, cb.from_user.id)),
        ("UPDATE player_stats SET crash_wins=crash_wins+1, casino_wins=casino_wins+1 WHERE user_id=?", (cb.from_user.id,)),
    ])
    if game.task and not game.task.done():
        game.task.cancel()
    text = generate_crash_display(game)
    await safe_edit_message(cb, text, get_crash_keyboard(game))
    await cb.answer(f"Забрал {winnings} 💎 на ×{game.cashout_multiplier:.2f}!")
    async def cleanup():
        await asyncio.sleep(5)
        ACTIVE_CRASH.pop(cb.from_user.id, None)
    asyncio.create_task(cleanup())


@router.callback_query(F.data == "crash:play")
async def cb_crash_play_again(cb: CallbackQuery) -> None:
    await cb.answer()
    p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (cb.from_user.id,))
    text = (
        f"{E_ROCKET} <b>КРАШ</b>\n\n"
        f"{E_CRYSTAL} Баланс: <b>{format_number(p['crystals'])}</b>\n\n"
        f"<b>Выбери ставку:</b>"
    )
    kb = build_vertical_keyboard_with_styles(
        [(f"{b} 💎", f"crash:bet:{b}", "primary") for b in Config.CASINO_BETS]
        + [(f"✏️ Ввести свою", "crash:manual", "success")]
        + [(f"{E_BACK} Назад", "casino:menu", "danger")]
    )
    await safe_edit_message(cb, text, kb)


# ============================================================================
# РУЧНОЙ ВВОД СТАВКИ
# ============================================================================

@router.callback_query(F.data.regexp(r"^casino:\w+:manual$"))
async def cb_casino_manual_bet(cb: CallbackQuery, state: FSMContext) -> None:
    game = cb.data.split(":")[1]
    await state.update_data(manual_bet_game=game)
    await state.set_state(ManualBetState.waiting_for_bet)
    await cb.message.answer(
        f"✏️ <b>Введи сумму ставки</b>\n\n"
        f"Минимум: {Config.CASINO_MIN_BET} {E_CRYSTAL}\n"
        f"Максимум: {Config.CASINO_MAX_BET} {E_CRYSTAL}\n\n"
        f"<i>Или отправь <code>отмена</code> чтобы вернуться.</i>",
        parse_mode=ParseMode.HTML
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^mines:manual:(\d+)$"))
async def cb_mines_manual_bet(cb: CallbackQuery, state: FSMContext) -> None:
    mines_count = safe_int_parse(cb.data.split(":")[2], default=0, min_val=1, max_val=24)
    if mines_count == 0:
        await cb.answer("Неверное количество мин.", show_alert=True)
        return
    await state.update_data(manual_bet_game="mines", mines_count=mines_count)
    await state.set_state(ManualBetState.waiting_for_bet)
    await cb.message.answer(
        f"✏️ <b>Введи сумму ставки</b>\n\n"
        f"Минимум: {Config.CASINO_MIN_BET} {E_CRYSTAL}\n"
        f"Максимум: {Config.CASINO_MAX_BET} {E_CRYSTAL}\n\n"
        f"<i>Или отправь <code>отмена</code> чтобы вернуться.</i>",
        parse_mode=ParseMode.HTML
    )
    await cb.answer()


@router.callback_query(F.data == "crash:manual")
async def cb_crash_manual_bet(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(manual_bet_game="crash")
    await state.set_state(ManualBetState.waiting_for_bet)
    await cb.message.answer(
        f"✏️ <b>Введи сумму ставки</b>\n\n"
        f"Минимум: {Config.CASINO_MIN_BET} {E_CRYSTAL}\n"
        f"Максимум: {Config.CASINO_MAX_BET} {E_CRYSTAL}\n\n"
        f"<i>Или отправь <code>отмена</code> чтобы вернуться.</i>",
        parse_mode=ParseMode.HTML
    )
    await cb.answer()


@router.message(ManualBetState.waiting_for_bet, F.text)
async def handle_manual_bet(m: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    game = data.get("manual_bet_game")
    
    if m.text.lower() in ["отмена", "cancel", "назад"]:
        await state.clear()
        text, kb = generate_casino_menu(m.from_user.id)
        await m.answer(text, reply_markup=kb)
        return
    
    try:
        bet = int(m.text.strip())
    except ValueError:
        await m.answer(f"❌ Введи число. Минимум: {Config.CASINO_MIN_BET}")
        return
    
    if bet < Config.CASINO_MIN_BET or bet > Config.CASINO_MAX_BET:
        await m.answer(f"❌ Ставка должна быть от {Config.CASINO_MIN_BET} до {Config.CASINO_MAX_BET}.")
        return
    
    await state.clear()
    
    if game == "slots":
        result, err, won = await play_casino_slots_animated(m.chat.id, bet, m.from_user.id, bot)
    elif game == "darts_hit":
        result, err, won = await play_casino_darts_animated(m.chat.id, bet, m.from_user.id, bot, False)
    elif game == "darts_miss":
        result, err, won = await play_casino_darts_animated(m.chat.id, bet, m.from_user.id, bot, True)
    elif game == "basket_hit":
        result, err, won = await play_casino_basketball_animated(m.chat.id, bet, m.from_user.id, bot, False)
    elif game == "basket_miss":
        result, err, won = await play_casino_basketball_animated(m.chat.id, bet, m.from_user.id, bot, True)
    elif game == "coin":
        result, err, won = play_casino_coin(m.from_user.id, bet)
    elif game == "highlow":
        result, err, won = play_casino_highlow(m.from_user.id, bet, "high")
    elif game == "mines":
        mines_count = data.get("mines_count", 5)
        p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
        if not p or p["crystals"] < bet:
            await m.answer("Недостаточно кристаллов.")
            return
        if m.from_user.id in ACTIVE_MINES:
            await m.answer("У тебя уже активна игра в мины.")
            return
        db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, m.from_user.id))])
        mines_game = start_mines_game(m.from_user.id, bet, mines_count)
        sent = await m.answer(
            f"{E_MINE} <b>МИНЫ</b>\n\n"
            f"💵 Ставка: <b>{bet}</b> {E_CRYSTAL}\n"
            f"{E_BOMB} Мин на поле: <b>{mines_count}</b>\n"
            f"📈 Множитель: <b>×{mines_game.current_multiplier}</b>\n\n"
            f"{generate_mines_field(mines_game)}\n\n"
            f"<i>Нажимай на клетки, чтобы открыть. Избегай мин!</i>",
            reply_markup=get_mines_keyboard(mines_game),
            parse_mode=ParseMode.HTML
        )
        mines_game.message_id = sent.message_id
        mines_game.chat_id = sent.chat.id
        ACTIVE_MINES[m.from_user.id] = mines_game
        db.execute("UPDATE player_stats SET mines_games=mines_games+1 WHERE user_id=?", (m.from_user.id,))
        return
    elif game == "crash":
        p = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
        if not p or p["crystals"] < bet:
            await m.answer("Недостаточно кристаллов.")
            return
        if m.from_user.id in ACTIVE_CRASH:
            await m.answer("У тебя уже активна игра в краш.")
            return
        db.execute_transaction([("UPDATE players SET crystals=crystals-? WHERE user_id=?", (bet, m.from_user.id))])
        crash_game = start_crash_game(m.from_user.id, bet)
        sent = await m.answer(
            generate_crash_display(crash_game),
            reply_markup=get_crash_keyboard(crash_game),
            parse_mode=ParseMode.HTML
        )
        crash_game.message_id = sent.message_id
        crash_game.chat_id = sent.chat.id
        ACTIVE_CRASH[m.from_user.id] = crash_game
        crash_game.task = asyncio.create_task(crash_tick_loop(crash_game, bot))
        db.execute("UPDATE player_stats SET crash_games=crash_games+1 WHERE user_id=?", (m.from_user.id,))
        return
    else:
        await m.answer("❌ Неизвестная игра.")
        return
    
    if err:
        await m.answer(err)
        return
    balance = db.fetch_one("SELECT crystals FROM players WHERE user_id=?", (m.from_user.id,))
    await m.answer(f"{result}\n\n{E_CRYSTAL} Баланс: <b>{format_number(balance['crystals'])}</b>")
    if not won:
        await _handle_casino_loss(m.from_user.id, bot, f"Ты проиграл <b>{bet}</b> {E_CRYSTAL}.\n\n")


# ============================================================================
# ДОНАТ
# ============================================================================

async def send_donation_invoice(bot: Bot, user_id: int, stars: int, title: str) -> bool:
    provider_token = Config.PROVIDER_TOKEN or ""
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"{E_DONATE} {title}",
            description="Спасибо за поддержку проекта! 💎\nТы поможешь развивать бота.",
            payload=f"donation_{user_id}_{int(time.time())}_{stars}",
            provider_token=provider_token,
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars)],
        )
        return True
    except Exception as e:
        logging.error(f"Donation invoice error: {e}")
        return False


async def offer_donation(bot: Bot, user_id: int, context: str = "") -> None:
    p = db.fetch_one("SELECT consecutive_losses FROM players WHERE user_id=?", (user_id,))
    if not p:
        return
    if p["consecutive_losses"] < Config.DONATION_AFTER_LOSSES:
        return
    db.execute("UPDATE players SET consecutive_losses=0 WHERE user_id=?", (user_id,))
    
    buttons = []
    for title, stars in Config.DONATION_PACKAGES:
        buttons.append((f"{title} · {stars}⭐", f"donate:{stars}", "primary"))
    buttons.append(("🚫 Не сейчас", "donate:dismiss", "danger"))
    
    text = (
        f"{E_DONATE} <b>ПОДДЕРЖИ РАЗРАБОТЧИКА!</b>\n\n"
        f"{context}"
        f"Тебе не везёт? Может, удача улыбнётся, если ты поддержишь проект!\n\n"
        f"<b>Выбери пакет:</b>"
    )
    
    try:
        await bot.send_message(
            user_id,
            text,
            reply_markup=build_vertical_keyboard_with_styles(buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Failed to offer donation: {e}")


@router.callback_query(F.data.regexp(r"^donate:(\d+)$"))
async def cb_donate_package(cb: CallbackQuery, bot: Bot) -> None:
    stars = safe_int_parse(cb.data.split(":")[1], default=0)
    if stars <= 0:
        await cb.answer("Неверный пакет.", show_alert=True)
        return
    await cb.answer()
    title = next((t for t, s in Config.DONATION_PACKAGES if s == stars), "Донат")
    success = await send_donation_invoice(bot, cb.from_user.id, stars, title)
    if not success:
        await cb.message.answer(
            f"❌ Не удалось создать инвойс. Попробуй позже или напиши админу."
        )


@router.callback_query(F.data == "donate:dismiss")
async def cb_donate_dismiss(cb: CallbackQuery) -> None:
    await cb.answer("Хорошо, может быть в другой раз!")
    try:
        await cb.message.delete()
    except Exception:
        await safe_edit_message(cb, f"{E_INFO} Спасибо, что играешь с нами! ❤️", None)


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot) -> None:
    try:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logging.error(f"Pre-checkout error: {e}")
        try:
            await bot.answer_pre_checkout_query(
                pre_checkout_query.id, ok=False,
                error_message="Произошла ошибка. Попробуй позже."
            )
        except Exception:
            pass


@router.message(F.successful_payment)
async def process_successful_payment(m: Message, bot: Bot) -> None:
    payment = m.successful_payment
    stars = payment.total_amount
    crystals_bonus = stars * 100
    
    db.execute_transaction([
        ("UPDATE players SET crystals=crystals+?, total_stars_donated=total_stars_donated+?, consecutive_losses=0 WHERE user_id=?",
         (crystals_bonus, stars, m.from_user.id)),
    ])
    
    await m.answer(
        f"{E_GIFT} <b>СПАСИБО ЗА ПОДДЕРЖКУ!</b>\n\n"
        f"⭐ Ты задонатил: <b>{stars}</b>\n"
        f"💎 В благодарность: <b>+{crystals_bonus}</b> кристаллов!\n\n"
        f"❤️ Твоя поддержка помогает развивать бота!"
    )
    logging.info(f"Donation: user {m.from_user.id} donated {stars} stars, got {crystals_bonus} crystals")


# ============================================================================
# ЛОГИКА ДУЭЛЕЙ
# ============================================================================

def initiate_duel(a_id: int, b_id: int, is_boss: bool = False, boss_key: Optional[str] = None, reward_mult: int = 1) -> Optional[Duel]:
    a_row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (a_id,))
    if not a_row:
        return None
    fa = create_fighter_from_db(a_row)
    if is_boss and boss_key and boss_key in BOSSES:
        boss_data = BOSSES[boss_key]
        fb = Fighter(
            name=boss_data["name"], max_hp=boss_data["hp"], hp=boss_data["hp"],
            weapon=boss_data["weapon"], armor_slots=boss_data["armor_keys"],
        )
    else:
        b_row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (b_id,))
        if not b_row:
            return None
        fb = create_fighter_from_db(b_row)
    duel = Duel(
        a_id=a_id, b_id=b_id, a=fa, b=fb,
        attacker_is_a=random.random() < 0.5,
        is_boss=is_boss, boss_key=boss_key, reward_mult=reward_mult,
    )
    first_attacker = fa.name if duel.attacker_is_a else fb.name
    prefix = f"{E_BOSS} <b>БОСС</b> " if is_boss else ""
    duel.add_log(f"{prefix}Бой начался! Первым атакует <b>{first_attacker}</b>.")
    ACTIVE_DUELS[a_id] = duel
    if b_id > 0:
        ACTIVE_DUELS[b_id] = duel
    return duel


async def initiate_duel_message(aid: int, bid: int, m: Message, bot: Bot, is_boss: bool = False,
                                 boss_key: Optional[str] = None, reward_mult: int = 1) -> None:
    if bid == aid:
        await m.answer("🤨 Нельзя драться с самим собой.")
        return
    if aid in ACTIVE_DUELS:
        await m.answer("У тебя уже идёт активный бой.")
        return
    duel = initiate_duel(aid, bid, is_boss, boss_key, reward_mult)
    if not duel:
        await m.answer("Не удалось начать бой.")
        return
    role = duel.get_state_for(aid)
    if role == "attacker":
        await m.answer(
            generate_duel_status_text(duel, aid, timer_left=Config.TURN_TIMEOUT),
            reply_markup=get_attack_variant_kb(aid)
        )
        start_duel_timer(duel, aid, "attacker", bot)
    else:
        atk_id = duel.get_attacker_id()
        if atk_id < 0:
            variant_idx = bot_decide_attack_variant(duel.get_attacker())
            duel.chosen_variant_idx = variant_idx
            duel.atk_zone = bot_decide_attack_zone(duel.get_attacker(), duel.get_defender())
            await m.answer(
                generate_duel_status_text(duel, aid, extra="⚔️ Соперник уже выбрал удар.", timer_left=Config.TURN_TIMEOUT),
                reply_markup=get_defend_zone_kb()
            )
            start_duel_timer(duel, aid, "defender", bot)
        else:
            await m.answer(
                generate_duel_status_text(duel, aid, extra="⏳ Соперник выбирает удар…"),
                reply_markup=build_vertical_keyboard_with_styles([(f"{E_REFRESH} Обновить", "duel:refresh", "primary")])
            )
    if bid > 0 and not is_boss:
        attacker_name = db.fetch_one("SELECT name FROM players WHERE user_id=?", (aid,))["name"]
        notify_player(bid, f"{E_GLOVE} <b>{esc(attacker_name)}</b> кинул тебе перчатку!")


async def process_duel_round(duel: Duel, bot: Bot, cb: Optional[CallbackQuery], atk_zone: str,
                              def_zone: Optional[str]) -> None:
    if duel.finished:
        return
    stop_duel_timer(duel)
    attacker = duel.get_attacker()
    defender = duel.get_defender()
    duel.add_log(f"── Раунд {duel.round_no} ──")
    duel.add_log(f"⚔️ {attacker.name} → {ZONE_INFO[atk_zone]['emoji']} {ZONE_INFO[atk_zone]['name']}")
    if def_zone:
        duel.add_log(f"🛡 {defender.name} → {ZONE_INFO[def_zone]['emoji']} {ZONE_INFO[def_zone]['name']}")
    process_dots(attacker, duel.log)
    if not attacker.is_alive():
        await finalize_duel(duel, winner_is_a=(attacker is duel.b), bot=bot)
        return
    execute_attack_phase(attacker, defender, atk_zone, def_zone, duel.chosen_variant_idx, duel.log)
    if not defender.is_alive():
        await finalize_duel(duel, winner_is_a=(defender is duel.a), bot=bot)
        return
    duel.atk_zone = None
    duel.def_zone = None
    duel.chosen_variant_idx = None
    duel.attacker_is_a = not duel.attacker_is_a
    duel.round_no += 1
    attacker.reduce_cooldowns()
    defender.reduce_cooldowns()
    if duel.round_no - duel.bot_last_block_round > 4:
        duel.bot_block_streak = 0
    await start_next_duel_round(duel, bot)


async def start_next_duel_round(duel: Duel, bot: Bot) -> None:
    if duel.finished:
        return
    atk_id = duel.get_attacker_id()
    def_id = duel.get_defender_id()
    if atk_id > 0:
        await bot.send_message(
            atk_id,
            generate_duel_status_text(duel, atk_id, extra="🎯 Твой ход — выбери вариант атаки.", timer_left=Config.TURN_TIMEOUT),
            reply_markup=get_attack_variant_kb(atk_id)
        )
        start_duel_timer(duel, atk_id, "attacker", bot)
    else:
        variant_idx = bot_decide_attack_variant(duel.get_attacker())
        duel.chosen_variant_idx = variant_idx
        duel.atk_zone = bot_decide_attack_zone(duel.get_attacker(), duel.get_defender())
        weapon_data = WEAPONS[duel.get_attacker().weapon]
        variant_name = weapon_data["variants"][variant_idx].name
        duel.add_log(f"⚔️ {duel.get_attacker().name} использует [{variant_name}]")
        if def_id > 0:
            await bot.send_message(
                def_id,
                generate_duel_status_text(duel, def_id, extra=f"{E_SHIELD} Соперник атакует — выбери зону защиты.",
                                          timer_left=Config.TURN_TIMEOUT),
                reply_markup=get_defend_zone_kb()
            )
            start_duel_timer(duel, def_id, "defender", bot)


async def finalize_duel(duel: Duel, winner_is_a: bool, bot: Bot, reason: str = "ko") -> None:
    if duel.finished:
        return
    aid, bid = duel.a_id, duel.b_id
    a_row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (aid,))
    if not a_row:
        terminate_duel(duel)
        return
    mult = duel.reward_mult if duel.is_boss else 1
    if winner_is_a:
        db.execute("UPDATE players SET wins=wins+1, total_duels=total_duels+1, consecutive_losses=0 WHERE user_id=?", (aid,))
        current_wins = db.fetch_one("SELECT wins FROM players WHERE user_id=?", (aid,))["wins"]
        prize = ARENAS[determine_arena(current_wins)]["prize"] * mult
        db.execute("UPDATE players SET crystals=crystals+?, total_crystals_earned=total_crystals_earned+? WHERE user_id=?",
                   (prize, prize, aid))
        if bid and bid > 0:
            db.execute(
                "UPDATE players SET losses=losses+1, total_duels=total_duels+1, "
                "wins=CASE WHEN wins>0 THEN wins-1 ELSE 0 END, consecutive_losses=consecutive_losses+1 WHERE user_id=?",
                (bid,)
            )
            a_name = a_row["name"]
            notify_player(bid, f"{E_SKULL} <b>{esc(a_name)}</b> одолел тебя. −1 {E_TROPHY}.")
        result_line = f"{E_TROPHY} <b>ТЫ ПОБЕДИЛ!</b>  +1 {E_TROPHY}  ·  +{prize} {E_CRYSTAL}"
        if duel.is_boss:
            db.execute("UPDATE player_stats SET boss_kills=boss_kills+1 WHERE user_id=?", (aid,))
    else:
        if bid and bid > 0:
            db.execute("UPDATE players SET wins=wins+1, total_duels=total_duels+1, consecutive_losses=0 WHERE user_id=?", (bid,))
            current_wins_b = db.fetch_one("SELECT wins FROM players WHERE user_id=?", (bid,))["wins"]
            prize_b = ARENAS[determine_arena(current_wins_b)]["prize"] * mult
            db.execute("UPDATE players SET crystals=crystals+?, total_crystals_earned=total_crystals_earned+? WHERE user_id=?",
                       (prize_b, prize_b, bid))
            a_name = a_row["name"]
            notify_player(bid, f"{E_TROPHY} <b>{esc(a_name)}</b> проиграл тебе! +1 {E_TROPHY}, +{prize_b} {E_CRYSTAL}")
            if duel.is_boss:
                db.execute("UPDATE player_stats SET boss_kills=boss_kills+1 WHERE user_id=?", (bid,))
        db.execute(
            "UPDATE players SET losses=losses+1, total_duels=total_duels+1, "
            "wins=CASE WHEN wins>0 THEN wins-1 ELSE 0 END, consecutive_losses=consecutive_losses+1 WHERE user_id=?",
            (aid,)
        )
        result_line = f"{E_SKULL} <b>ТЫ ПРОИГРАЛ.</b>  −1 {E_TROPHY}  ·  без награды"
    terminate_duel(duel)
    reason_line = f"\n⏱ Соперник не успел за {Config.TURN_TIMEOUT} сек." if reason == "timeout" else ""
    new_a = db.fetch_one("SELECT * FROM players WHERE user_id=?", (aid,))
    a_arena = ARENAS[determine_arena(new_a["wins"])]
    text = (
        f"╔══════════════════════════╗\n        ⚔️ <b>ИТОГ БОЯ</b>\n╚══════════════════════════╝\n\n"
        f"{result_line}\n\n"
        f"{E_TROPHY} Кубки: <b>{new_a['wins']}</b>\n"
        f"{E_SKULL} Поражения: <b>{new_a['losses']}</b>\n"
        f"{E_CRYSTAL} Кристаллы: <b>{format_number(new_a['crystals'])}</b>\n"
        f"📍 {a_arena['emoji']} {a_arena['name']}"
        f"{reason_line}\n\nВыбери действие:"
    )
    try:
        await bot.send_message(aid, text, reply_markup=get_finish_duel_kb())
    except Exception as e:
        logging.error(f"Failed to send duel result to {aid}: {e}")
    if bid and bid > 0:
        new_b = db.fetch_one("SELECT * FROM players WHERE user_id=?", (bid,))
        if new_b:
            b_arena = ARENAS[determine_arena(new_b["wins"])]
            res_b = f"{E_SKULL} <b>ТЫ ПРОИГРАЛ.</b>  −1 {E_TROPHY}" if winner_is_a else f"{E_TROPHY} <b>ТЫ ПОБЕДИЛ!</b>  +1 {E_TROPHY}"
            text_b = (
                f"╔══════════════════════════╗\n        ⚔️ <b>ИТОГ БОЯ</b>\n╚══════════════════════════╝\n\n"
                f"{res_b}\n\n"
                f"{E_TROPHY} Кубки: <b>{new_b['wins']}</b>\n"
                f"{E_SKULL} Поражения: <b>{new_b['losses']}</b>\n"
                f"{E_CRYSTAL} Кристаллы: <b>{format_number(new_b['crystals'])}</b>\n"
                f"📍 {b_arena['emoji']} {b_arena['name']}"
                f"{reason_line}\n\nВыбери действие:"
            )
            try:
                await bot.send_message(bid, text_b, reply_markup=get_finish_duel_kb())
            except Exception as e:
                logging.error(f"Failed to send duel result to {bid}: {e}")


# ============================================================================
# CALLBACK HANDLERS — АРЕНА
# ============================================================================

@router.callback_query(F.data == "arena:menu")
async def cb_arena_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_arena_menu_screen(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "arena:bosses")
async def cb_arena_bosses(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_bosses_menu_screen(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^arena:boss:\w+$"))
async def cb_arena_boss_fight(cb: CallbackQuery, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or cb.from_user.id in ACTIVE_DUELS:
        await cb.answer("Сначала /start или бой уже идёт", show_alert=True)
        return
    bkey = cb.data.split(":")[2]
    if bkey not in BOSSES or p["wins"] < BOSSES[bkey]["min_wins"]:
        await cb.answer(f"Нужно {BOSSES[bkey]['min_wins']} {E_TROPHY} для этого босса.", show_alert=True)
        return
    duel = initiate_duel(cb.from_user.id, -1, is_boss=True, boss_key=bkey, reward_mult=BOSSES[bkey]["reward_mult"])
    if not duel:
        await cb.answer("Ошибка запуска боя.", show_alert=True)
        return
    role = duel.get_state_for(cb.from_user.id)
    if role == "attacker":
        await safe_edit_message(cb, generate_duel_status_text(duel, cb.from_user.id, timer_left=Config.TURN_TIMEOUT),
                                get_attack_variant_kb(cb.from_user.id))
        start_duel_timer(duel, cb.from_user.id, "attacker", bot)
    else:
        variant_idx = bot_decide_attack_variant(duel.get_attacker())
        duel.chosen_variant_idx = variant_idx
        duel.atk_zone = bot_decide_attack_zone(duel.get_attacker(), duel.get_defender())
        await safe_edit_message(
            cb,
            generate_duel_status_text(duel, cb.from_user.id, extra="⚔️ Босс уже выбрал удар.", timer_left=Config.TURN_TIMEOUT),
            get_defend_zone_kb()
        )
        start_duel_timer(duel, cb.from_user.id, "defender", bot)
    await cb.answer(f"Бой с {BOSSES[bkey]['name']} начался!")


@router.callback_query(F.data == "arena:find")
async def cb_arena_find(cb: CallbackQuery, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or cb.from_user.id in ACTIVE_DUELS:
        await cb.answer("Сначала /start или бой уже идёт", show_alert=True)
        return
    oid = pick_balanced_opponent(cb.from_user.id, p["wins"])
    if not oid:
        await cb.answer("Не удалось подобрать соперника.", show_alert=True)
        return
    await initiate_duel_message(cb.from_user.id, oid, cb.message, bot)
    await cb.answer()


@router.callback_query(F.data == "arena:list")
async def cb_arena_list(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_arena_list_screen_paginated(cb.from_user.id, 0)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^arena:list:page:(\d+)$"))
async def cb_arena_list_page(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    page = safe_int_parse(cb.data.split(":")[2], default=0)
    text, kb = generate_arena_list_screen_paginated(cb.from_user.id, page)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "arena:find_name")
async def cb_arena_find_name(cb: CallbackQuery, state: FSMContext) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    await state.set_state(DuelFindState.waiting_for_target)
    await cb.message.answer("🔎 Отправь @username, ID или имя бойца.")
    await cb.answer()


@router.callback_query(F.data.regexp(r"^duel:pick:-?\d+$"))
async def cb_duel_pick(cb: CallbackQuery, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or cb.from_user.id in ACTIVE_DUELS:
        await cb.answer("Сначала /start или бой уже идёт", show_alert=True)
        return
    tid = safe_int_parse(cb.data.split(":")[2], default=0)
    if tid == 0 or tid == cb.from_user.id:
        await cb.answer("Нельзя драться с собой.", show_alert=True)
        return
    target = db.fetch_one("SELECT allow_duels FROM players WHERE user_id=?", (tid,))
    if target and not safe_row_get(target, "allow_duels", 1):
        await cb.answer("Этот игрок запретил вызовы на дуэль.", show_alert=True)
        return
    await initiate_duel_message(cb.from_user.id, tid, cb.message, bot)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^duel:profile:-?\d+$"))
async def cb_duel_profile(cb: CallbackQuery) -> None:
    tid = safe_int_parse(cb.data.split(":")[2], default=0)
    if tid == 0:
        await cb.answer("Неверный ID.", show_alert=True)
        return
    row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (tid,))
    if not row:
        await cb.answer("Игрок не найден.", show_alert=True)
        return
    await safe_edit_message(
        cb,
        generate_profile_text(row),
        build_vertical_keyboard_with_styles([
            (f"{E_BACK} Назад", "arena:list", "primary"),
            (f"⚔️ Вызвать на бой", f"duel:pick:{tid}", "danger"),
        ])
    )
    await cb.answer()


@router.callback_query(F.data == "duel:myprofile")
async def cb_my_profile(cb: CallbackQuery) -> None:
    row = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not row:
        await cb.answer("Сначала /start", show_alert=True)
        return
    await safe_edit_message(cb, generate_profile_text(row), generate_profile_kb())
    await cb.answer()


@router.callback_query(F.data == "duel:again")
async def cb_duel_again(cb: CallbackQuery, bot: Bot) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p or cb.from_user.id in ACTIVE_DUELS:
        await cb.answer("Сначала /start или бой уже идёт", show_alert=True)
        return
    oid = pick_balanced_opponent(cb.from_user.id, p["wins"])
    if not oid:
        await cb.answer("Не удалось подобрать соперника.", show_alert=True)
        return
    await initiate_duel_message(cb.from_user.id, oid, cb.message, bot)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^duel:variant:\d+$"))
async def cb_duel_variant(cb: CallbackQuery, bot: Bot) -> None:
    duel = ACTIVE_DUELS.get(cb.from_user.id)
    if not duel or duel.finished or duel.get_state_for(cb.from_user.id) != "attacker":
        await cb.answer("Неверное состояние боя.", show_alert=True)
        return
    if duel.chosen_variant_idx is not None:
        await cb.answer("Вариант уже выбран.", show_alert=True)
        return
    variant_idx = safe_int_parse(cb.data.split(":")[2], default=-1)
    if variant_idx < 0:
        await cb.answer("Неверный вариант.", show_alert=True)
        return
    if variant_idx in duel.get_attacker().attack_cooldowns:
        await cb.answer("Эта атака на перезарядке!", show_alert=True)
        return
    weapon_data = WEAPONS[duel.get_attacker().weapon]
    if variant_idx >= len(weapon_data["variants"]):
        await cb.answer("Неверный вариант атаки.", show_alert=True)
        return
    duel.chosen_variant_idx = variant_idx
    await safe_edit_message(
        cb,
        generate_duel_status_text(duel, cb.from_user.id, extra="🎯 Теперь выбери зону удара.", timer_left=Config.TURN_TIMEOUT),
        get_attack_zone_kb()
    )
    await cb.answer("Вариант атаки выбран.")


@router.callback_query(F.data.regexp(r"^duel:variant_disabled:\d+$"))
async def cb_duel_variant_disabled(cb: CallbackQuery) -> None:
    await cb.answer("Эта атака на перезарядке!", show_alert=True)


@router.callback_query(F.data.regexp(r"^duel:atk:(head|torso|arms|legs)$"))
async def cb_duel_attack(cb: CallbackQuery, bot: Bot) -> None:
    duel = ACTIVE_DUELS.get(cb.from_user.id)
    if not duel or duel.finished:
        await cb.answer("Бой не найден или завершён.", show_alert=True)
        return
    if duel.get_state_for(cb.from_user.id) != "attacker":
        await cb.answer("Сейчас не твой ход атаковать.", show_alert=True)
        return
    if duel.chosen_variant_idx is None:
        await cb.answer("Сначала выбери вариант атаки.", show_alert=True)
        return
    stop_duel_timer(duel)
    duel.atk_zone = cb.data.split(":")[2]
    def_id = duel.get_defender_id()
    if def_id < 0:
        bot_is_a = (def_id == duel.a_id)
        bot_fighter = duel.a if bot_is_a else duel.b
        if bot_decide_to_defend(duel, bot_is_a):
            duel.def_zone = bot_decide_defend_zone(duel.get_attacker(), bot_fighter)
            duel.bot_last_block_round = duel.round_no
            duel.bot_block_streak += 1
            duel.add_log(f"🛡 {bot_fighter.name} встаёт в защиту")
        else:
            duel.def_zone = None
            duel.bot_block_streak = 0
        await process_duel_round(duel, bot, cb=cb, atk_zone=duel.atk_zone, def_zone=duel.def_zone)
    else:
        await bot.send_message(
            def_id,
            generate_duel_status_text(duel, def_id, extra=f"⚔️ {duel.get_attacker().name} выбрал зону удара!", timer_left=Config.TURN_TIMEOUT),
            reply_markup=get_defend_zone_kb()
        )
        start_duel_timer(duel, def_id, "defender", bot)
        await safe_edit_message(
            cb,
            generate_duel_status_text(duel, cb.from_user.id, extra="⏳ Ждём защиту соперника…"),
            build_vertical_keyboard_with_styles([(f"{E_REFRESH} Обновить", "duel:refresh", "primary")])
        )
    await cb.answer("Зона удара выбрана.")


@router.callback_query(F.data.regexp(r"^duel:def:(head|torso|arms|legs)$"))
async def cb_duel_defend(cb: CallbackQuery, bot: Bot) -> None:
    duel = ACTIVE_DUELS.get(cb.from_user.id)
    if not duel or duel.finished:
        await cb.answer("Бой не найден или завершён.", show_alert=True)
        return
    if duel.get_state_for(cb.from_user.id) != "defender":
        await cb.answer("Сейчас ты не защищаешься.", show_alert=True)
        return
    if not duel.atk_zone:
        await cb.answer("Атакующий ещё не выбрал зону.", show_alert=True)
        return
    stop_duel_timer(duel)
    duel.def_zone = cb.data.split(":")[2]
    await process_duel_round(duel, bot, cb=cb, atk_zone=duel.atk_zone, def_zone=duel.def_zone)


@router.callback_query(F.data == "duel:refresh")
async def cb_duel_refresh(cb: CallbackQuery) -> None:
    duel = ACTIVE_DUELS.get(cb.from_user.id)
    if not duel or duel.finished:
        await cb.answer("Бой не найден или завершён.", show_alert=True)
        return
    role = duel.get_state_for(cb.from_user.id)
    time_left = max(0, int(round(duel.timer_deadline - time.time()))) if duel.timer_for == cb.from_user.id else None
    if role == "attacker":
        if duel.chosen_variant_idx is None:
            await safe_edit_message(
                cb,
                generate_duel_status_text(duel, cb.from_user.id, extra="🎯 Выбери вариант атаки.", timer_left=time_left),
                get_attack_variant_kb(cb.from_user.id)
            )
        else:
            await safe_edit_message(
                cb,
                generate_duel_status_text(duel, cb.from_user.id, extra="🎯 Теперь выбери зону удара.", timer_left=time_left),
                get_attack_zone_kb()
            )
    else:
        if not duel.atk_zone:
            await safe_edit_message(
                cb,
                generate_duel_status_text(duel, cb.from_user.id, extra="⏳ Соперник ещё выбирает удар…"),
                build_vertical_keyboard_with_styles([(f"{E_REFRESH} Обновить", "duel:refresh", "primary")])
            )
        else:
            await safe_edit_message(
                cb,
                generate_duel_status_text(duel, cb.from_user.id, extra=f"{E_SHIELD} Выбери зону защиты.", timer_left=time_left),
                get_defend_zone_kb()
            )
    await cb.answer("Обновлено")


# ============================================================================
# CALLBACK HANDLERS — СНАРЯЖЕНИЕ
# ============================================================================

@router.callback_query(F.data == "gear:menu")
async def cb_gear_menu(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_gear_screen(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "gear:w")
async def cb_gear_weapon(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_weapon_list(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^buy_weapon:(\w+)$"))
async def cb_buy_weapon(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p:
        await cb.answer("Сначала /start", show_alert=True)
        return
    key = cb.data.split(":")[1]
    if key not in WEAPONS:
        await cb.answer()
        return
    item = WEAPONS[key]
    owned = set((p["weapons_owned"] or "").split(","))
    if key in owned:
        db.execute("UPDATE players SET weapon=? WHERE user_id=?", (key, cb.from_user.id))
        toast = f"Надето: {item['name']}"
    elif p["crystals"] >= item["price"]:
        db.execute(
            "UPDATE players SET crystals=crystals-?, weapons_owned=?, weapon=? WHERE user_id=?",
            (item["price"], ",".join(owned | {key}), key, cb.from_user.id)
        )
        toast = f"Куплено: {item['name']}"
        db.execute("UPDATE player_stats SET items_bought=items_bought+1, crystals_spent=crystals_spent+? WHERE user_id=?",
                   (item["price"], cb.from_user.id))
    else:
        await cb.answer(f"Нужно {item['price']}💎", show_alert=True)
        return
    text, kb = generate_weapon_list(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer(toast)


@router.callback_query(F.data == "gear:armor_menu")
async def cb_gear_armor_menu(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    text, kb = generate_armor_slot_menu(cb.from_user.id)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^gear:(head|torso|arms|legs)$"))
async def cb_gear_armor_slot(cb: CallbackQuery) -> None:
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (cb.from_user.id,)):
        await cb.answer("Сначала /start", show_alert=True)
        return
    slot = cb.data.split(":")[1]
    text, kb = generate_armor_slot_list(cb.from_user.id, slot)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^buy_armor:(head|torso|arms|legs):(\w+)$"))
async def cb_buy_armor(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p:
        await cb.answer("Сначала /start", show_alert=True)
        return
    parts = cb.data.split(":")
    if len(parts) != 3:
        await cb.answer("Неверные данные.", show_alert=True)
        return
    slot = parts[1]
    key = parts[2]
    item = get_armor_item_by_key(key)
    if not item or item["slot"] != slot:
        await cb.answer("Предмет не найден.", show_alert=True)
        return
    owned = set((p["armors_owned"] or "").split(","))
    col = f"armor_{slot}"
    if key in owned:
        db.execute(f"UPDATE players SET {col}=? WHERE user_id=?", (key, cb.from_user.id))
        toast = f"Надето: {item['name']}"
    elif p["crystals"] >= item["price"]:
        db.execute(
            f"UPDATE players SET crystals=crystals-?, armors_owned=?, {col}=? WHERE user_id=?",
            (item["price"], ",".join(owned | {key}), key, cb.from_user.id)
        )
        toast = f"Куплено: {item['name']}"
        db.execute("UPDATE player_stats SET items_bought=items_bought+1, crystals_spent=crystals_spent+? WHERE user_id=?",
                   (item["price"], cb.from_user.id))
    else:
        await cb.answer(f"Нужно {item['price']}💎", show_alert=True)
        return
    text, kb = generate_armor_slot_list(cb.from_user.id, slot)
    await safe_edit_message(cb, text, kb)
    await cb.answer(toast)


@router.callback_query(F.data.regexp(r"^top:(cur|bronze|silver|gold)$"))
async def cb_top_leaderboard(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p:
        await cb.answer("Сначала /start", show_alert=True)
        return
    key = cb.data.split(":")[1]
    if key == "cur":
        key = determine_arena(p["wins"])
    text, kb = generate_top_screen_paginated(cb.from_user.id, key, 0)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^top:(bronze|silver|gold):page:(\d+)$"))
async def cb_top_leaderboard_page(cb: CallbackQuery) -> None:
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (cb.from_user.id,))
    if not p:
        await cb.answer("Сначала /start", show_alert=True)
        return
    parts = cb.data.split(":")
    arena_key = parts[1]
    page = safe_int_parse(parts[3], default=0)
    text, kb = generate_top_screen_paginated(cb.from_user.id, arena_key, page)
    await safe_edit_message(cb, text, kb)
    await cb.answer()


# ============================================================================
# FSM — ПОИСК СОПЕРНИКА
# ============================================================================

@router.message(DuelFindState.waiting_for_target, F.text)
async def duel_find_target_handler(m: Message, state: FSMContext, bot: Bot) -> None:
    if m.chat.type != "private":
        await state.clear()
        return
    if m.text in MENU_TEXTS:
        await state.clear()
        return
    await state.clear()
    p = db.fetch_one("SELECT * FROM players WHERE user_id=?", (m.from_user.id,))
    if not p:
        await m.answer("Сначала /start.")
        return
    key = m.text.strip().lstrip("@")
    if key.isdigit():
        row = db.fetch_one("SELECT user_id FROM players WHERE user_id=? AND banned=0", (safe_int_parse(key, default=0),))
    else:
        row = None
    if not row:
        row = db.fetch_one(
            """SELECT user_id FROM players
               WHERE (LOWER(username)=LOWER(?) OR LOWER(name)=LOWER(?)) AND banned=0 LIMIT 1""",
            (key, key)
        )
    target = row["user_id"] if row else pick_balanced_opponent(m.from_user.id, p["wins"])
    if not target:
        await m.answer("Не удалось подобрать соперника.")
        return
    await initiate_duel_message(m.from_user.id, target, m, bot)


# ============================================================================
# FALLBACK
# ============================================================================

@router.message()
async def fallback_handler(m: Message) -> None:
    if not m.from_user:
        return
    if not db.fetch_one("SELECT 1 FROM players WHERE user_id=?", (m.from_user.id,)):
        if m.chat.type == "private":
            await m.answer("Отправь /start, чтобы создать бойца ⚔️")
        return
    if is_user_banned(m.from_user.id):
        await m.answer("🚫 Доступ закрыт.")
        return
    db.execute("UPDATE players SET last_active=? WHERE user_id=?", (time.time(), m.from_user.id))
    if m.chat.type == "private":
        await m.answer("Пиши <code>help</code> или пользуйся меню внизу 👇", reply_markup=MENU_KB)
    else:
        await m.answer(
            "В группе команды работают <b>ответом</b> или через <code>@username</code> / <code>ID</code>. "
            "Пиши <code>help</code> для списка."
        )


# ============================================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================================

async def scheduled_event_spawner(bot: Bot) -> None:
    global NEXT_SCHEDULED_EVENT
    while True:
        try:
            NEXT_SCHEDULED_EVENT = time.time() + 4 * 3600
            await asyncio.sleep(4 * 3600)
            if ACTIVE_CHAT_EVENT and ACTIVE_CHAT_EVENT.is_active():
                continue
            event_types = list(CHAT_EVENT_TEMPLATES.keys())
            event_type = random.choice(event_types)
            event = spawn_chat_event(event_type, 0)
            if event:
                logging.info(f"Scheduled event spawned: {event.name}")
        except Exception as e:
            logging.error(f"Error in scheduled_event_spawner: {e}")
            await asyncio.sleep(60)


async def periodic_cleanup() -> None:
    while True:
        try:
            await asyncio.sleep(300)
            cleanup_rp_cooldowns()
            now = time.time()
            expired_pending = [k for k, v in PENDING_DUELS.items() if now - v.created_at > Config.CHALLENGE_TIMEOUT * 2]
            for k in expired_pending:
                pending = PENDING_DUELS.pop(k, None)
                if pending and pending.timeout_task and not pending.timeout_task.done():
                    pending.timeout_task.cancel()
            finished_duels = [uid for uid, duel in ACTIVE_DUELS.items() if duel.finished]
            for uid in finished_duels:
                ACTIVE_DUELS.pop(uid, None)
            expired_mines = [uid for uid, g in ACTIVE_MINES.items() if not g.active or now - g.started_at > 600]
            for uid in expired_mines:
                ACTIVE_MINES.pop(uid, None)
            expired_crash = [uid for uid, g in ACTIVE_CRASH.items() if (g.cashed_out or g.crashed)]
            for uid in expired_crash:
                game = ACTIVE_CRASH.pop(uid, None)
                if game and game.task and not game.task.done():
                    game.task.cancel()
        except Exception as e:
            logging.error(f"Error in periodic_cleanup: {e}")


async def main() -> None:
    logging.basicConfig(level=Config.LOG_LEVEL, format=Config.LOG_FORMAT)
    if not Config.BOT_TOKEN:
        logging.critical("❌ ОШИБКА: Задай BOT_TOKEN в переменных окружения!")
        raise SystemExit("Missing BOT_TOKEN")
    logging.info("=" * 60)
    logging.info("⚔️ АРЕНА ДУЭЛЯНТОВ — v20.1 Hotfix Edition")
    logging.info("=" * 60)
    logging.info("Initializing database...")
    logging.info("Generating masked bots...")
    ensure_masked_bots_exist(Config.BOT_GENERATION_COUNT)
    logging.info("Creating bot instance...")
    bot = Bot(Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logging.info("Setting up dispatcher...")
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать / вернуться"),
        BotCommand(command="help", description="Правила и команды"),
        BotCommand(command="profile", description="Мой профиль"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("✅ Bot successfully started and polling!")
    logging.info("=" * 60)
    event_task = asyncio.create_task(scheduled_event_spawner(bot))
    cleanup_task = asyncio.create_task(periodic_cleanup())
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logging.info("Received shutdown signal...")
    except Exception as e:
        logging.critical(f"Fatal error: {e}\n{traceback.format_exc()}")
    finally:
        event_task.cancel()
        cleanup_task.cancel()
        db.close()
        await bot.session.close()
        logging.info("Bot shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()
