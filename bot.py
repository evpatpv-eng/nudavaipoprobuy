"""
Телеграм-бот для запису на манікюр.
Адмін-панель, портфоліо, слоти, підтвердження записів.
"""
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import config
import database as db

# Стани для запису клієнта
ASK_NAME, ASK_PHONE, ASK_USERNAME = 1, 2, 3

# Стани адміна
ADMIN_MAIN = 10
ADMIN_SET_PHOTO, ADMIN_SET_NAME, ADMIN_SET_ABOUT = 11, 12, 13
ADMIN_SET_ADDRESS, ADMIN_SET_PHONE = 14, 15
ADMIN_ADD_WORK, ADMIN_SERVICES, ADMIN_ADD_SERVICE_NAME, ADMIN_ADD_SERVICE_PRICE = 16, 17, 18, 19
ADMIN_SLOTS, ADMIN_ADD_SLOT, ADMIN_BLOCKED_DAYS = 20, 21, 22


def is_admin(user_id):
    return user_id == config.ADMIN_ID


async def edit_menu_message(query, text: str, reply_markup=None, parse_mode: str | None = None):
    """Редагує caption якщо повідомлення з фото, інакше text."""
    if query.message and getattr(query.message, "photo", None):
        await query.edit_message_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


async def edit_photo_menu_message(query, photo_file_id: str, caption: str, reply_markup=None, parse_mode: str | None = None):
    """Редагує повідомлення, щоб воно стало фото+caption."""
    media = InputMediaPhoto(media=photo_file_id, caption=caption, parse_mode=parse_mode)
    await query.edit_message_media(media=media, reply_markup=reply_markup)


# --- Головне меню (user) ---
def get_user_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Приклади робіт", callback_data="works")],
        [InlineKeyboardButton("💅 Послуги та ціни", callback_data="services")],
        [InlineKeyboardButton("📅 Записатися", callback_data="book")],
    ])


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
    chat = update.effective_chat
    photo = db.get_setting("photo")
    name = db.get_setting("name") or "Майстер манікюру"
    about = db.get_setting("about") or "Ласкаво просимо!"
    msg = f"*{name}*\n\n{about}" if text is None else text
    kb = get_user_main_keyboard()
    if photo:
        await chat.send_photo(photo=photo, caption=msg, parse_mode="Markdown", reply_markup=kb)
    else:
        await chat.send_message(msg, parse_mode="Markdown", reply_markup=kb)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await update.message.reply_text(
            "👋 Ласкаво просимо в адмін-панель!\n\n"
            "Використовуйте /admin для керування ботом."
        )
    else:
        await send_main_menu(update, context)
    # Якщо команда /start викликана під час діалогу запису,
    # завершуємо діалог і повертаємося в головне меню.
    return ConversationHandler.END


# --- Перегляд робіт ---
async def cb_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    works = db.get_works()
    if not works:
        await query.answer("Приклади робіт ще не додані.", show_alert=True)
        return

    # Не чіпаємо основне повідомлення з текстом «Про себе»,
    # просто надсилаємо окремо приклади робіт + кнопку «Назад».
    if len(works) == 1:
        await query.message.reply_photo(
            photo=works[0],
            caption="Приклад роботи майстра",
        )
    else:
        await query.message.reply_media_group([InputMediaPhoto(media=m) for m in works])

    await query.message.reply_text(
        "Приклади робіт майстра",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="back_main")]]),
    )


# --- Послуги ---
async def cb_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    services = db.get_services()
    if not services:
        text = "Послуги ще не додані."
    else:
        lines = ["*Послуги та ціни:*\n"]
        for _, name, price in services:
            lines.append(f"• {name} — {price} ₴")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="back_main")]])
    await edit_menu_message(query, text, reply_markup=kb, parse_mode="Markdown")


# --- Запис ---
async def cb_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slots = db.get_free_slots()
    if not slots:
        await edit_menu_message(
            query,
            "На жаль, вільних вікон зараз немає. Завітайте пізніше!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="back_main")]]),
        )
        return
    services = db.get_services()
    if not services:
        await edit_menu_message(
            query,
            "Послуги ще не налаштовані. Зверніться до майстра.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="back_main")]]),
        )
        return
    blocked = db.get_blocked_weekdays()
    if blocked:
        slots = [(sid, st) for sid, st in slots if datetime.fromisoformat(st.replace(" ", "T")).weekday() not in blocked]
        if not slots:
            await edit_menu_message(
                query,
                "Немає вільних вікон на доступні дні.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="back_main")]]),
            )
            return
    context.user_data["book_services"] = services
    btns = [[InlineKeyboardButton(f"{n} — {p} ₴", callback_data=f"book_svc_{sid}")] for sid, n, p in services]
    btns.append([InlineKeyboardButton("◀ Назад", callback_data="back_main")])
    await edit_menu_message(query, "Оберіть послугу:", reply_markup=InlineKeyboardMarkup(btns))


async def cb_book_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sid = int(query.data.split("_")[-1])
    services = context.user_data.get("book_services", db.get_services())
    svc_name = next((n for s, n, p in services if s == sid), "")
    context.user_data["book_service_id"] = sid
    context.user_data["book_service_name"] = svc_name
    slots = db.get_free_slots()
    blocked = db.get_blocked_weekdays()
    if blocked:
        slots = [(sid, st) for sid, st in slots if datetime.fromisoformat(st.replace(" ", "T")).weekday() not in blocked]
    btns = []
    for slot_id, slot_time in slots[:15]:
        dt = datetime.fromisoformat(slot_time.replace(" ", "T"))
        btn_text = dt.strftime("%d.%m %H:%M")
        btns.append([InlineKeyboardButton(btn_text, callback_data=f"book_slot_{slot_id}")])
    btns.append([InlineKeyboardButton("◀ Назад", callback_data="book")])
    await edit_menu_message(
        query,
        f"Послуга: *{svc_name}*\n\nОберіть зручний час:",
        reply_markup=InlineKeyboardMarkup(btns),
        parse_mode="Markdown",
    )


async def cb_book_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot_id = int(query.data.split("_")[-1])
    row = db.get_slot(slot_id)
    if not row or row[2] != "free":
        await query.answer("Це вікно вже зайняте. Оберіть інше.", show_alert=True)
        return
    context.user_data["book_slot_id"] = slot_id
    context.user_data["book_slot_time"] = row[1]
    await edit_menu_message(query, "Введіть ваше *ім'я*:", parse_mode="Markdown")
    return ASK_NAME


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Введіть коректне ім'я:")
        return ASK_NAME
    context.user_data["book_name"] = name
    await update.message.reply_text(
        "Введіть ваш *номер телефону* (наприклад +380501234567).\n\n"
        "Щоб скасувати запис і повернутися в головне меню — надішліть /start.",
        parse_mode="Markdown",
    )
    return ASK_PHONE


async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.search(r"^[\d\s\+\-\(\)]{10,}$", phone):
        await update.message.reply_text("Введіть коректний номер телефону:")
        return ASK_PHONE
    context.user_data["book_phone"] = phone
    await update.message.reply_text("Введіть ваш *юзернейм у Telegram* (наприклад @username або без @):", parse_mode="Markdown")
    return ASK_USERNAME


async def finish_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username and not username.startswith("@"):
        username = "@" + username
    ud = context.user_data
    slot_id = ud.get("book_slot_id")
    service_id = ud.get("book_service_id")
    name = ud.get("book_name")
    phone = ud.get("book_phone")
    if not all([slot_id, service_id, name, phone]):
        await update.message.reply_text("Помилка даних. Почніть запис заново: /start")
        return ConversationHandler.END
    row = db.get_slot(slot_id)
    if not row or row[2] != "free":
        await update.message.reply_text("На жаль, це вікно вже зайняте. Оберіть інший час.")
        return ConversationHandler.END
    bid = db.create_booking(
        slot_id, service_id, name, phone,
        username or update.effective_user.username or "",
        user_id=update.effective_user.id
    )
    db.book_slot(slot_id)
    # Уведомление админу
    svc = next((s for s in db.get_services() if s[0] == service_id), (0, "?", 0))
    slot_time = row[1]
    admin_text = (
        "📋 *Новий запис!*\n\n"
        f"Послуга: {svc[1]}\n"
        f"Час: {slot_time}\n"
        f"Ім'я: {name}\n"
        f"Телефон: {phone}\n"
        f"Telegram: {username or update.effective_user.username or '—'}\n\n"
        "Підтвердіть або відхиліть:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити", callback_data=f"adm_confirm_{bid}")],
        [InlineKeyboardButton("❌ Відхилити", callback_data=f"adm_reject_{bid}")],
    ])
    await context.bot.send_message(config.ADMIN_ID, admin_text, parse_mode="Markdown", reply_markup=kb)
    await update.message.reply_text(
        "Ваш запит надіслано майстру. Очікуйте підтвердження."
    )
    for k in ["book_slot_id", "book_service_id", "book_name", "book_phone", "book_services", "book_service_name", "book_slot_time"]:
        ud.pop(k, None)
    return ConversationHandler.END


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    photo = db.get_setting("photo")
    name = db.get_setting("name") or "Майстер манікюру"
    about = db.get_setting("about") or "Ласкаво просимо!"
    msg = f"*{name}*\n\n{about}"
    kb = get_user_main_keyboard()
    try:
        if photo:
            await edit_photo_menu_message(query, photo_file_id=photo, caption=msg, reply_markup=kb, parse_mode="Markdown")
        else:
            await edit_menu_message(query, msg, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await query.message.delete()
        if photo:
            await query.message.reply_photo(photo=photo, caption=msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


# --- Админ: подтверждение/отклонение ---
async def cb_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    bid = int(query.data.split("_")[-1])
    row = db.get_booking(bid)
    if not row or row[7] != "pending":  # status at index 7
        await query.edit_message_text("Запис уже оброблено.")
        return
    db.confirm_booking(bid)
    # row: id, slot_id, service_id, name, phone, username, user_id, status, svc_name, price, slot_time
    client_user_id = row[6]
    svc_name, slot_time = row[8], row[10]
    address = db.get_setting("address") or "Адресу уточнюйте у майстра"
    master_phone = db.get_setting("phone") or ""
    await query.edit_message_text(f"✅ Запис #{bid} підтверджено.")
    if client_user_id:
        client_msg = (
            f"✅ *Ваш запис підтверджено!*\n\n"
            f"Послуга: {svc_name}\n"
            f"Дата і час: {slot_time}\n"
            f"Адреса: {address}\n"
            f"Телефон майстра: {master_phone}"
        )
        try:
            await context.bot.send_message(client_user_id, client_msg, parse_mode="Markdown")
        except Exception:
            pass


async def cb_admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    bid = int(query.data.split("_")[-1])
    row = db.get_booking(bid)
    if not row or row[7] != "pending":
        await query.edit_message_text("Запис уже оброблено.")
        return
    client_user_id = row[6]
    db.reject_booking(bid)
    await query.edit_message_text(f"❌ Запис #{bid} відхилено.")
    if client_user_id:
        try:
            await context.bot.send_message(client_user_id, "На жаль, майстер відхилив ваш запис. Спробуйте обрати інший час.")
        except Exception:
            pass


# --- Админ-панель ---
def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 Фото", callback_data="adm_photo")],
        [InlineKeyboardButton("✏ Ім'я", callback_data="adm_name")],
        [InlineKeyboardButton("📝 Про себе", callback_data="adm_about")],
        [InlineKeyboardButton("📍 Адреса", callback_data="adm_address")],
        [InlineKeyboardButton("📞 Телефон майстра", callback_data="adm_phone")],
        [InlineKeyboardButton("🖼 Приклади робіт", callback_data="adm_works")],
        [InlineKeyboardButton("💅 Послуги", callback_data="adm_services")],
        [InlineKeyboardButton("📅 Слоти", callback_data="adm_slots")],
        [InlineKeyboardButton("🚫 Заборонені дні", callback_data="adm_blocked")],
        [InlineKeyboardButton("📖 Історія записів", callback_data="adm_history")],
    ])


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Адмін-панель:", reply_markup=get_admin_keyboard())


async def cb_admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "photo"
    await query.edit_message_text("Надішліть фото для портфоліо:")


async def cb_admin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "name"
    await query.edit_message_text("Введіть ім'я майстра:")


async def cb_admin_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "about"
    await query.edit_message_text("Введіть текст «Про себе»:")


async def cb_admin_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "address"
    await query.edit_message_text("Введіть адресу:")


async def cb_admin_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "phone"
    await query.edit_message_text("Введіть номер телефону майстра:")


async def cb_admin_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    works = db.get_works()
    text = f"Прикладів робіт: {len(works)}\n\nДодати фото чи очистити?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати", callback_data="adm_work_add")],
        [InlineKeyboardButton("🗑 Очистити", callback_data="adm_work_clear")],
        [InlineKeyboardButton("◀ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, reply_markup=kb)


async def cb_admin_work_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "work_add"
    await query.edit_message_text("Надішліть фото прикладу роботи:")


async def cb_admin_work_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    db.clear_works()
    await query.edit_message_text("Приклади робіт очищено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="adm_works")]]))


async def cb_admin_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    services = db.get_services()
    lines = ["*Послуги:*\n"] if services else ["Послуги ще не додані.\n"]
    buttons = []
    for sid, n, p in (services or []):
        lines.append(f"• {n} — {p} ₴")
        buttons.append([InlineKeyboardButton(f"🗑 {n}", callback_data=f"adm_svc_del_{sid}")])
    
    text = "\n".join(lines) if services else lines[0]
    buttons.append([InlineKeyboardButton("➕ Додати послугу", callback_data="adm_svc_add")])
    buttons.append([InlineKeyboardButton("◀ Назад", callback_data="adm_back")])
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def cb_admin_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всіх підтверджених/відхилених записів."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = db.get_bookings_history()
    if not rows:
        await query.edit_message_text(
            "Історія записів поки порожня.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="adm_back")]]),
        )
        return

    lines = ["*Історія записів:*\n"]
    buttons = []
    for bid, status, client_name, client_username, svc_name, price, slot_time in rows[:30]:
        icon = "✅" if status == "confirmed" else "❌"
        short_name = client_name or client_username or "Без імені"
        lines.append(f"{icon} #{bid} — {slot_time} — {short_name} ({svc_name})")
        buttons.append(
            [InlineKeyboardButton(f"{icon} #{bid} — {slot_time}", callback_data=f"adm_hist_{bid}")]
        )

    buttons.append([InlineKeyboardButton("◀ Назад", callback_data="adm_back")])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_admin_history_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Деталі конкретного запису з історії + кнопка зв'язку з клієнтом."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    bid = int(query.data.split("_")[-1])
    row = db.get_booking(bid)
    if not row:
        await query.edit_message_text(
            "Запис не знайдено.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад", callback_data="adm_history")]]),
        )
        return

    (
        _id,
        slot_id,
        service_id,
        client_name,
        client_phone,
        client_username,
        client_user_id,
        status,
        svc_name,
        price,
        slot_time,
    ) = row

    icon = "✅" if status == "confirmed" else "❌"
    status_ua = "Підтверджено" if status == "confirmed" else "Відхилено"
    uname = client_username or "—"

    text = (
        f"{icon} *Запис #{bid}*\n\n"
        f"Статус: {status_ua}\n"
        f"Послуга: {svc_name} ({price} ₴)\n"
        f"Дата і час: {slot_time}\n\n"
        f"Ім'я: {client_name or '—'}\n"
        f"Телефон: {client_phone or '—'}\n"
        f"Telegram: {uname}\n"
    )

    buttons = [[InlineKeyboardButton("◀ Назад до історії", callback_data="adm_history")]]
    # Кнопка для зв'язку з клієнтом, якщо є юзернейм
    if client_username:
        url = f"https://t.me/{client_username.lstrip('@')}"
        buttons.insert(0, [InlineKeyboardButton("💬 Зв'язатися з клієнтом", url=url)])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_admin_svc_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    sid = int(query.data.split("_")[-1])
    # Получаем название услуги для подтверждения
    services = db.get_services()
    service_name = next((n for s, n, p in services if s == sid), "Невідома послуга")
    
    # Кнопки подтверждения удаления
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Так, видалити", callback_data=f"adm_svc_confirm_del_{sid}")],
        [InlineKeyboardButton("❌ Ні, залишити", callback_data="adm_services")],
    ])
    await query.edit_message_text(
        f"Видалити послугу «*{service_name}*»?\n\nЦю дію неможливо скасувати.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def cb_admin_svc_confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    sid = int(query.data.split("_")[-1])
    
    # Проверяем, есть ли записи с этой услугой
    # В базе данных нет прямых связей, но лучше проверить
    db.delete_service(sid)
    
    await query.edit_message_text(
        "✅ Послугу видалено.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Назад до послуг", callback_data="adm_services")]])
    )


async def cb_admin_svc_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "svc_name"
    await query.edit_message_text("Введіть назву послуги:")


async def cb_admin_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    slots = db.get_slots_admin()
    lines = ["*Слоти (сеанс 2 год):*\n"]
    for slot_id, slot_time, status in (slots or [])[:20]:
        st = "✅" if status == "free" else "📌"
        lines.append(f"{st} {slot_time} (id:{slot_id})")
    text = "\n".join(lines)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати слот", callback_data="adm_slot_add")],
        [InlineKeyboardButton("◀ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, reply_markup=kb)


async def cb_admin_slot_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data["adm_state"] = "slot_add"
    await query.edit_message_text("Введіть дату і час слота у форматі: РРРР-ММ-ДД ГГ:ХХ\nНаприклад: 2026-03-20 14:00")


async def cb_admin_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    blocked = db.get_blocked_weekdays()
    days = "Пн Вт Ср Чт Пт Сб Нд".split()
    sel = ", ".join(days[d] for d in blocked) if blocked else "Немає"
    text = f"Дні без запису: {sel}\n\nВкажіть дні (0=Пн, 6=Нд) через кому:"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, reply_markup=kb)
    context.user_data["adm_state"] = "blocked_days"


async def cb_admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop("adm_state", None)
    await query.edit_message_text("Адмін-панель:", reply_markup=get_admin_keyboard())


# Обработка сообщений админа (текст/фото)
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    state = context.user_data.get("adm_state")
    if not state:
        return
    text = update.message.text and update.message.text.strip()
    photo = update.message.photo
    if state == "photo" and photo:
        fid = photo[-1].file_id
        db.set_setting("photo", fid)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Фото збережено.", reply_markup=get_admin_keyboard())
    elif state == "name" and text:
        db.set_setting("name", text)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Ім'я збережено.", reply_markup=get_admin_keyboard())
    elif state == "about" and text:
        db.set_setting("about", text)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Текст збережено.", reply_markup=get_admin_keyboard())
    elif state == "address" and text:
        db.set_setting("address", text)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Адресу збережено.", reply_markup=get_admin_keyboard())
    elif state == "phone" and text:
        db.set_setting("phone", text)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Телефон збережено.", reply_markup=get_admin_keyboard())
    elif state == "work_add" and photo:
        fid = photo[-1].file_id
        db.add_work(fid)
        context.user_data.pop("adm_state")
        await update.message.reply_text("Фото додано.", reply_markup=get_admin_keyboard())
    elif state == "svc_name" and text:
        context.user_data["adm_svc_name"] = text
        context.user_data["adm_state"] = "svc_price"
        await update.message.reply_text("Введіть ціну (число):")
    elif state == "svc_price" and text and text.isdigit():
        name = context.user_data.pop("adm_svc_name", "")
        db.add_service(name, int(text))
        context.user_data.pop("adm_state")
        await update.message.reply_text("Послугу додано.", reply_markup=get_admin_keyboard())
    elif state == "slot_add" and text:
        import re
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
        if m:
            dt_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}:00"
            try:
                dt = datetime.fromisoformat(dt_str.replace(" ", "T"))
            except ValueError:
                await update.message.reply_text("Некоректна дата/час. Приклад: 2026-03-20 14:00")
                context.user_data.pop("adm_state", None)
                return

            if dt <= datetime.now():
                await update.message.reply_text(
                    "Цей час уже в минулому. Вкажіть слот у майбутньому (наприклад: 2026-03-20 14:00)."
                )
                context.user_data.pop("adm_state", None)
                return

            blocked = db.get_blocked_weekdays()
            if blocked and dt.weekday() in blocked:
                await update.message.reply_text(
                    "Цей день заборонений для запису в налаштуваннях. Оберіть інший день."
                )
                context.user_data.pop("adm_state", None)
                return

            if db.add_slot(dt_str):
                await update.message.reply_text("Слот додано.", reply_markup=get_admin_keyboard())
            else:
                await update.message.reply_text("Такий слот уже існує.")
        else:
            await update.message.reply_text("Невірний формат. Використовуйте: РРРР-ММ-ДД ГГ:ХХ")
        context.user_data.pop("adm_state", None)
    elif state == "blocked_days" and text:
        try:
            days = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
            days = [d for d in days if 0 <= d <= 6]
            db.set_blocked_weekdays(days)
            context.user_data.pop("adm_state")
            await update.message.reply_text("Дні оновлено.", reply_markup=get_admin_keyboard())
        except Exception:
            await update.message.reply_text("Введіть числа 0-6 через кому (0=Пн, 6=Нд).")


def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_book_slot, pattern="^book_slot_"),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)],
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_booking)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cb_works, pattern="^works$"))
    app.add_handler(CallbackQueryHandler(cb_services, pattern="^services$"))
    app.add_handler(CallbackQueryHandler(cb_book, pattern="^book$"))
    app.add_handler(CallbackQueryHandler(cb_book_service, pattern="^book_svc_"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(cb_admin_confirm, pattern="^adm_confirm_"))
    app.add_handler(CallbackQueryHandler(cb_admin_reject, pattern="^adm_reject_"))
    app.add_handler(CallbackQueryHandler(cb_admin_photo, pattern="^adm_photo$"))
    app.add_handler(CallbackQueryHandler(cb_admin_name, pattern="^adm_name$"))
    app.add_handler(CallbackQueryHandler(cb_admin_about, pattern="^adm_about$"))
    app.add_handler(CallbackQueryHandler(cb_admin_address, pattern="^adm_address$"))
    app.add_handler(CallbackQueryHandler(cb_admin_phone, pattern="^adm_phone$"))
    app.add_handler(CallbackQueryHandler(cb_admin_works, pattern="^adm_works$"))
    app.add_handler(CallbackQueryHandler(cb_admin_work_add, pattern="^adm_work_add$"))
    app.add_handler(CallbackQueryHandler(cb_admin_work_clear, pattern="^adm_work_clear$"))
    app.add_handler(CallbackQueryHandler(cb_admin_services, pattern="^adm_services$"))
    app.add_handler(CallbackQueryHandler(cb_admin_svc_del, pattern="^adm_svc_del_"))
    app.add_handler(CallbackQueryHandler(cb_admin_svc_confirm_del, pattern="^adm_svc_confirm_del_"))
    app.add_handler(CallbackQueryHandler(cb_admin_svc_add, pattern="^adm_svc_add$"))
    app.add_handler(CallbackQueryHandler(cb_admin_history, pattern="^adm_history$"))
    app.add_handler(CallbackQueryHandler(cb_admin_history_item, pattern="^adm_hist_"))
    app.add_handler(CallbackQueryHandler(cb_admin_slots, pattern="^adm_slots$"))
    app.add_handler(CallbackQueryHandler(cb_admin_slot_add, pattern="^adm_slot_add$"))
    app.add_handler(CallbackQueryHandler(cb_admin_blocked, pattern="^adm_blocked$"))
    app.add_handler(CallbackQueryHandler(cb_admin_back, pattern="^adm_back$"))
    app.add_handler(MessageHandler(filters.ALL, admin_message))

    app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
