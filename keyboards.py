from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import USER_ROLES


def get_privacy_consent_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for privacy policy consent"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="privacy_accept")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="privacy_decline")]
    ])


def get_role_selection_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for role selection"""
    keyboard = []
    for role_key, role_name in USER_ROLES.items():
        keyboard.append([InlineKeyboardButton(text=role_name, callback_data=f"role_{role_key}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_phone_request_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard to request phone number"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_designer_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard for designer"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новая сделка")],
            [KeyboardButton(text="📋 Мои сделки"), KeyboardButton(text="🔍 Узнать статус")],
            [KeyboardButton(text="🎁 Реферальная программа")]
        ],
        resize_keyboard=True
    )


def get_admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Admin menu keyboard"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Выгрузить пользователей")],
            [KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="🔙 Вернуться в основное меню")]
        ],
        resize_keyboard=True
    )


def get_broadcast_role_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting broadcast target role"""
    keyboard = [
        [InlineKeyboardButton(text="Всем пользователям", callback_data="broadcast_all")]
    ]
    for role_key, role_name in USER_ROLES.items():
        keyboard.append([InlineKeyboardButton(text=f"Только: {role_name}", callback_data=f"broadcast_{role_key}")])

    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Cancel operation keyboard"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_no")]
    ])
