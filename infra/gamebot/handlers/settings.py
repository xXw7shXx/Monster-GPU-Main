from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.db import get_session
from database.models import User, Preferences
from utils.localization import get_string
from utils.language import apply_language_defaults, user_language

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user:
        await update.message.reply_text(get_string("en", "settings_first"))
        session.close()
        return
        
    prefs = user.preferences
    lang = user_language(user)
    keyboard = build_settings_keyboard(prefs, lang)
    session.close()
    
    text = get_string(lang, 'settings_title')
    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

def build_settings_keyboard(prefs, lang):
    daily_str = get_string(lang, 'daily_releases')
    free_str = get_string(lang, 'free_games')
    leaving_str = get_string(lang, 'leaving_games')
    pc_str = get_string(lang, 'pc')
    ps_str = get_string(lang, 'ps')
    xbox_str = get_string(lang, 'xbox')
    switch_str = get_string(lang, 'switch')
    mobile_str = get_string(lang, 'mobile')
    lang_btn_str = get_string(lang, 'language')
    
    kb = [
        [InlineKeyboardButton(f"{daily_str} {'✅' if prefs.notify_daily_releases else '❌'}", callback_data="toggle_daily_releases")],
        [InlineKeyboardButton(f"{free_str} {'✅' if prefs.notify_free_games else '❌'}", callback_data="toggle_free_games")],
        [InlineKeyboardButton(f"{leaving_str} {'✅' if prefs.notify_leaving_games else '❌'}", callback_data="toggle_leaving_games")],
        [InlineKeyboardButton(f"{pc_str} {'✅' if prefs.platform_pc else '❌'}", callback_data="toggle_platform_pc")],
        [InlineKeyboardButton(f"{ps_str} {'✅' if prefs.platform_ps else '❌'}", callback_data="toggle_platform_ps")],
        [InlineKeyboardButton(f"{xbox_str} {'✅' if prefs.platform_xbox else '❌'}", callback_data="toggle_platform_xbox")],
        [InlineKeyboardButton(f"{switch_str} {'✅' if prefs.platform_switch else '❌'}", callback_data="toggle_platform_switch")],
        [InlineKeyboardButton(f"{mobile_str} {'✅' if prefs.platform_mobile else '❌'}", callback_data="toggle_platform_mobile")],
        [InlineKeyboardButton(f"🌐 {lang_btn_str}: {'English 🇬🇧' if prefs.language == 'en' else 'العربية 🇸🇦'}", callback_data="settings_change_language")],
        [InlineKeyboardButton(get_string(lang, 'menu_profile'), callback_data="quick|profile")]
    ]
    return InlineKeyboardMarkup(kb)

def build_language_keyboard(lang):
    kb = [
        [
            InlineKeyboardButton("English 🇬🇧", callback_data="set_lang_en"),
            InlineKeyboardButton("العربية 🇸🇦", callback_data="set_lang_ar")
        ],
        [
            InlineKeyboardButton(get_string(lang, 'back'), callback_data="back_to_settings")
        ]
    ]
    return InlineKeyboardMarkup(kb)

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        session.close()
        return
        
    prefs = user.preferences
    data = query.data
    
    if data.startswith("set_lang_"):
        apply_language_defaults(prefs, data.split("_")[2])
        session.commit()
        lang = prefs.language
        keyboard = build_settings_keyboard(prefs, lang)
        text = get_string(lang, 'settings_title')
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        session.close()
        return

    if data == "settings_change_language":
        lang = prefs.language
        text = get_string(lang, 'change_language')
        keyboard = build_language_keyboard(lang)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        session.close()
        return

    if data == "back_to_settings":
        lang = prefs.language
        keyboard = build_settings_keyboard(prefs, lang)
        text = get_string(lang, 'settings_title')
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        session.close()
        return
    
    if data == "toggle_daily_releases":
        prefs.notify_daily_releases = not prefs.notify_daily_releases
    elif data == "toggle_free_games":
        prefs.notify_free_games = not prefs.notify_free_games
    elif data == "toggle_leaving_games":
        prefs.notify_leaving_games = not prefs.notify_leaving_games
    elif data == "toggle_platform_pc":
        prefs.platform_pc = not prefs.platform_pc
    elif data == "toggle_platform_ps":
        prefs.platform_ps = not prefs.platform_ps
    elif data == "toggle_platform_xbox":
        prefs.platform_xbox = not prefs.platform_xbox
    elif data == "toggle_platform_switch":
        prefs.platform_switch = not prefs.platform_switch
    elif data == "toggle_platform_mobile":
        prefs.platform_mobile = not prefs.platform_mobile
        
    session.commit()
    lang = user_language(user)
    keyboard = build_settings_keyboard(prefs, lang)
    session.close()
    
    await query.edit_message_reply_markup(reply_markup=keyboard)
