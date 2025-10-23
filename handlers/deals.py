import math
from typing import Dict, List, Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import Database
from bitrix_api import BitrixAPI, validate_phone
from states import DealCreationStates, DealStatusStates
from keyboards import (
    get_cancel_keyboard,
    get_confirmation_keyboard,
    get_main_menu_keyboard,
)
import config

router = Router()
db = Database()
bitrix = BitrixAPI()

CANCEL_TEXT = "❌ Отмена"
DEALS_CALLBACK_PREFIX = "deals"
PAGE_SIZE = max(config.DEALS_PAGE_SIZE, 1)


def _normalize_status_code(status: str) -> str:
    if not status:
        return ""
    value = status
    if ":" in value:
        value = value.split(":", 1)[1]
    return value.upper()


DESIGNER_ALLOWED_STATUS_CODES = {
    _normalize_status_code(code) for code in config.DESIGNER_ALLOWED_STATUSES
}
PARTNER_ALLOWED_STATUS_CODES = {
    _normalize_status_code(code) for code in config.PARTNER_ALLOWED_STATUSES
}


def _allowed_status_codes(role: str):
    return PARTNER_ALLOWED_STATUS_CODES if role == "partner" else DESIGNER_ALLOWED_STATUS_CODES


def _is_status_allowed(status: str, role: str) -> bool:
    return _normalize_status_code(status) in _allowed_status_codes(role)


def _menu_for_role(role: str):
    return get_main_menu_keyboard(role)


async def _get_role_from_state(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get("owner_role", "designer")


def _build_pagination_keyboard(role: str, page: int, total_pages: int) -> Optional[InlineKeyboardMarkup]:
    if total_pages <= 1:
        return None

    buttons: List[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"{DEALS_CALLBACK_PREFIX}:{role}:{page - 1}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=f"{DEALS_CALLBACK_PREFIX}:{role}:noop",
        )
    )

    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                text="➡️ Далее",
                callback_data=f"{DEALS_CALLBACK_PREFIX}:{role}:{page + 1}",
            )
        )

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _format_deal_entry(deal: Dict) -> str:
    status_name = deal.get("status_name") or config.UNKNOWN_STATUS_PLACEHOLDER
    sync_status = deal.get("sync_status", "valid")
    icon_map = {
        "updated": "🆕",
        "unsupported_status": "⚠️",
        "valid": "📊",
    }
    status_icon = icon_map.get(sync_status, "📊")

    lines = [
        f"📌 Сделка #{deal.get('deal_number')}",
        f"👤 Клиент: {deal.get('client_full_name')}",
    ]
    if deal.get("project_file_name"):
        lines.append(f"📄 Файл: {deal.get('project_file_name')}")

    lines.append(f"{status_icon} Статус: {status_name}")

    if sync_status == "unsupported_status":
        lines.append(f"ℹ️ {config.UNKNOWN_STATUS_PLACEHOLDER}")

    lines.append(f"📅 Дата: {deal.get('created_date', '')[:10]}")

    return "\n".join(lines)


def _render_deals_page(deals: List[Dict], page: int, role: str) -> (str, Optional[InlineKeyboardMarkup]):
    total_pages = max(math.ceil(len(deals) / PAGE_SIZE), 1)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    entries = deals[start:start + PAGE_SIZE]

    lines = ["📋 Ваши сделки:", ""]
    for deal in entries:
        lines.append(_format_deal_entry(deal))
        lines.append("─" * 30)
        lines.append("")

    text = "\n".join(lines).strip()
    keyboard = _build_pagination_keyboard(role, page, total_pages)
    return text, keyboard


async def _sync_deal_with_bitrix(deal: Dict, fallback_role: str) -> Dict:
    """
    Sync single deal with Bitrix24 and enrich it with status info.
    """
    role = deal.get("owner_role", fallback_role)
    deal_id = deal.get("bitrix_deal_id")
    deal_number = deal.get("deal_number")
    entity_type = deal.get("entity_type", "lead")

    if entity_type == "deal":
        current_status = await bitrix.get_deal_status(deal_id)
    else:
        current_status = await bitrix.get_lead_status(deal_id)

    if current_status:
        allowed = _is_status_allowed(current_status, role)

        if allowed:
            if current_status != deal.get("status"):
                await db.update_deal_status(deal_number, current_status)
                deal["status"] = current_status
                deal["sync_status"] = "updated"
            else:
                deal["sync_status"] = "valid"

            deal["status_name"] = await bitrix.get_stage_name(current_status, role=role)
        else:
            deal["status"] = current_status
            deal["status_name"] = config.UNKNOWN_STATUS_PLACEHOLDER
            deal["sync_status"] = "unsupported_status"
    else:
        deal["sync_status"] = "not_found"

    return deal


async def _sync_deals_for_user(telegram_id: int, role: str, *, drop_missing: bool) -> (List[Dict], List[Dict]):
    deals = await db.get_user_deals(telegram_id)
    synced: List[Dict] = []
    invalid: List[Dict] = []

    for deal in deals:
        synced_deal = await _sync_deal_with_bitrix(deal, role)
        if synced_deal.get("sync_status") == "not_found":
            invalid.append(synced_deal)
        else:
            synced.append(synced_deal)

    if drop_missing and invalid:
        for deal in invalid:
            await db.delete_deal(deal.get("deal_number"))

    return synced, invalid


@router.message(F.text == "📝 Новая сделка")
async def new_deal_start(message: Message, state: FSMContext):
    """Start new deal creation"""
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else None

    if not user or role not in {"designer", "partner"}:
        await message.answer("❌ Эта функция доступна только для зарегистрированных дизайнеров и партнеров.")
        return

    if not user.get("bitrix_id"):
        await message.answer(
            "❌ Не удалось определить ваш Bitrix ID. Пожалуйста, завершите регистрацию или обратитесь к менеджеру.",
            reply_markup=_menu_for_role(role),
        )
        return

    await state.update_data(owner_role=role)

    await message.answer(
        "📝 Создание новой сделки\n\nВведите ФИО клиента:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(DealCreationStates.waiting_for_client_name)


@router.message(DealCreationStates.waiting_for_client_name)
async def client_name_entered(message: Message, state: FSMContext):
    """Handle client name input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    client_name = message.text.strip()

    if len(client_name.split()) < 2:
        await message.answer("Пожалуйста, введите полное ФИО клиента (минимум Фамилия и Имя):")
        return

    await state.update_data(client_name=client_name)

    await message.answer("Введите номер телефона клиента:")
    await state.set_state(DealCreationStates.waiting_for_client_phone)


@router.message(DealCreationStates.waiting_for_client_phone)
async def client_phone_entered(message: Message, state: FSMContext):
    """Handle client phone input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    client_phone = message.text.strip()

    if not validate_phone(client_phone):
        await message.answer(
            "❌ Неверный формат номера телефона.\n\n"
            "Пожалуйста, введите номер в правильном формате:\n"
            "• +79161234567\n"
            "• 89161234567\n"
            "• 79161234567\n"
            "• 9161234567"
        )
        return

    await state.update_data(client_phone=client_phone)

    await message.answer(
        "Прикрепите файл проекта в формате PDF:\n(Отправьте PDF-файл или документ)"
    )
    await state.set_state(DealCreationStates.waiting_for_project_file)


@router.message(DealCreationStates.waiting_for_project_file, F.document)
async def project_file_uploaded(message: Message, state: FSMContext):
    """Handle project file upload"""
    document = message.document

    if document.mime_type != "application/pdf":
        await message.answer(
            "⚠️ Пожалуйста, отправьте файл в формате PDF.\n"
            "Если хотите отменить, нажмите кнопку 'Отмена'."
        )
        return

    await state.update_data(project_file_id=document.file_id, project_file_name=document.file_name)

    await message.answer("Добавьте комментарий к сделке:")
    await state.set_state(DealCreationStates.waiting_for_comment)


@router.message(DealCreationStates.waiting_for_project_file)
async def project_file_invalid(message: Message, state: FSMContext):
    """Handle invalid project file"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    await message.answer("Пожалуйста, отправьте PDF-файл проекта.")


@router.message(DealCreationStates.waiting_for_comment)
async def comment_entered(message: Message, state: FSMContext):
    """Handle comment input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    comment = message.text.strip()
    await state.update_data(comment=comment)

    data = await state.get_data()

    confirmation_text = (
        "📋 Проверьте данные сделки:\n\n"
        f"👤 Клиент: {data.get('client_name')}\n"
        f"📱 Телефон: {data.get('client_phone')}\n"
        f"📄 Файл: {data.get('project_file_name')}\n"
        f"💬 Комментарий: {comment}\n\n"
        "✅ Подтвердить создание сделки?"
    )

    await message.answer(confirmation_text, reply_markup=get_confirmation_keyboard())
    await state.set_state(DealCreationStates.confirming_deal)


@router.callback_query(F.data == "confirm_yes", DealCreationStates.confirming_deal)
async def deal_confirmed(callback: CallbackQuery, state: FSMContext):
    """Handle deal confirmation"""
    data = await state.get_data()
    user = await db.get_user(callback.from_user.id)
    role = data.get("owner_role", user.get("role", "designer") if user else "designer")

    await callback.message.edit_text("⏳ Создаю сделку в системе...")

    deal_data = {
        "designer_name": user.get("full_name"),
        "designer_bitrix_id": user.get("bitrix_id"),
        "designer_role_key": role,
        "designer_role_title": config.USER_ROLES.get(role, role.title()),
        "crm_agent_name": user.get("full_name"),
        "client_full_name": data.get("client_name"),
        "client_phone": data.get("client_phone"),
        "project_file_url": data.get("project_file_id"),  # В проде нужно загружать файл в Bitrix
        "project_file_name": data.get("project_file_name"),
        "comment": data.get("comment"),
        "owner_role": role,
        "stage_id": config.BITRIX_PARTNER_INITIAL_STAGE if role == "partner" else None,
    }

    if role == "partner":
        bitrix_deal = await bitrix.create_partner_deal(deal_data)
    else:
        bitrix_deal = await bitrix.create_lead(deal_data)

    if bitrix_deal:
        await db.add_deal({
            "deal_number": bitrix_deal.get("number"),
            "bitrix_deal_id": bitrix_deal.get("id"),
            "designer_telegram_id": callback.from_user.id,
            "client_full_name": data.get("client_name"),
            "client_phone": data.get("client_phone"),
            "project_file_id": data.get("project_file_id"),
            "project_file_name": data.get("project_file_name"),
            "comment": data.get("comment"),
            "status": bitrix_deal.get("status", ""),
            "entity_type": bitrix_deal.get("entity_type", "lead"),
            "owner_role": role,
        })

        status_name = await bitrix.get_stage_name(bitrix_deal.get("status", ""), role=role)

        await callback.message.answer(
            f"✅ Сделка успешно создана!\n\n"
            f"📋 Номер сделки: {bitrix_deal.get('number')}\n"
            f"📊 Статус: {status_name}\n\n"
            "Вы можете отслеживать статус через меню 'Мои сделки' или 'Узнать статус'.",
            reply_markup=_menu_for_role(role),
        )
    else:
        await callback.message.answer(
            "❌ Произошла ошибка при создании сделки в системе.\n"
            f"Пожалуйста, обратитесь к менеджеру: @{config.MANAGER_USERNAME}",
            reply_markup=_menu_for_role(role),
        )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "confirm_no", DealCreationStates.confirming_deal)
async def deal_cancelled(callback: CallbackQuery, state: FSMContext):
    """Handle deal cancellation"""
    role = await _get_role_from_state(state)

    await callback.message.edit_text("❌ Создание сделки отменено.")
    await callback.message.answer("Возвращаюсь в главное меню.", reply_markup=_menu_for_role(role))
    await state.clear()
    await callback.answer()


@router.message(F.text == "📋 Мои сделки")
async def my_deals(message: Message):
    """Show user's deals with Bitrix validation"""
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else None

    if not user or role not in {"designer", "partner"}:
        await message.answer("❌ Эта функция доступна только для зарегистрированных дизайнеров и партнеров.")
        return

    deals = await db.get_user_deals(message.from_user.id)

    if not deals:
        await message.answer(
            "У вас пока нет активных сделок.\n\nСоздайте новую сделку через меню 'Новая сделка'!",
            reply_markup=_menu_for_role(role),
        )
        return

    loading_msg = await message.answer("⏳ Синхронизирую сделки с Bitrix24...")

    valid_deals, invalid_deals = await _sync_deals_for_user(
        message.from_user.id,
        role,
        drop_missing=True,
    )

    if invalid_deals:
        invalid_text_lines = [
            "⚠️ Некоторые сделки не найдены в Bitrix24 и были удалены из списка:",
            "",
        ]
        for deal in invalid_deals:
            invalid_text_lines.extend([
                f"📌 Сделка #{deal.get('deal_number')}",
                f"👤 Клиент: {deal.get('client_full_name')}",
                f"📅 Дата: {deal.get('created_date', '')[:10]}",
                "─" * 30,
            ])
        invalid_text_lines.append(
            f"Если нужна помощь, свяжитесь с менеджером @{config.MANAGER_USERNAME}."
        )
        await message.answer("\n".join(invalid_text_lines))

    if not valid_deals:
        await loading_msg.delete()
        await message.answer(
            "Список актуальных сделок пуст.\nСоздайте новую сделку через меню 'Новая сделка'!",
            reply_markup=_menu_for_role(role),
        )
        return

    text, keyboard = _render_deals_page(valid_deals, page=0, role=role)
    await loading_msg.delete()
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{DEALS_CALLBACK_PREFIX}:"))
async def paginate_deals(callback: CallbackQuery):
    """Handle deals pagination callbacks"""
    parts = callback.data.split(":")

    if len(parts) != 3:
        await callback.answer()
        return

    _, role, target = parts

    if target == "noop":
        await callback.answer()
        return

    try:
        page = int(target)
    except ValueError:
        await callback.answer()
        return

    valid_deals, _ = await _sync_deals_for_user(
        callback.from_user.id,
        role,
        drop_missing=False,
    )

    if not valid_deals:
        await callback.message.edit_text(
            "Список сделок пуст.",
            reply_markup=None,
        )
        await callback.answer()
        return

    text, keyboard = _render_deals_page(valid_deals, page=page, role=role)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(F.text == "🔍 Узнать статус")
async def check_status_start(message: Message, state: FSMContext):
    """Start deal status check"""
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else None

    if not user or role not in {"designer", "partner"}:
        await message.answer("❌ Эта функция доступна только для зарегистрированных дизайнеров и партнеров.")
        return

    await state.update_data(owner_role=role)

    await message.answer(
        "🔍 Проверка статуса сделки\n\nВведите номер сделки:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(DealStatusStates.waiting_for_deal_number)


@router.message(DealStatusStates.waiting_for_deal_number)
async def deal_number_entered(message: Message, state: FSMContext):
    """Handle deal number input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Операция отменена.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    deal_number = message.text.strip()

    deal = await db.get_deal_by_number(deal_number)

    if not deal:
        await message.answer(
            f"❌ Сделка с номером {deal_number} не найдена.\nПроверьте номер и попробуйте снова."
        )
        return

    if deal.get("designer_telegram_id") != message.from_user.id:
        await message.answer("❌ Эта сделка вам не принадлежит.")
        await state.clear()
        return

    deal_role = deal.get("owner_role", role)
    entity_type = deal.get("entity_type", "lead")

    if entity_type == "deal":
        current_status = await bitrix.get_deal_status(deal.get("bitrix_deal_id"))
    else:
        current_status = await bitrix.get_lead_status(deal.get("bitrix_deal_id"))

    if current_status:
        await db.update_deal_status(deal_number, current_status)

        if _is_status_allowed(current_status, deal_role):
            status_name = await bitrix.get_stage_name(current_status, role=deal_role)
        else:
            status_name = config.UNKNOWN_STATUS_PLACEHOLDER

        await message.answer(
            f"📊 Статус сделки #{deal_number}\n\n"
            f"👤 Клиент: {deal.get('client_full_name')}\n"
            f"📱 Телефон: {deal.get('client_phone')}\n"
            f"📊 Текущий статус: {status_name}\n"
            f"📅 Дата создания: {deal.get('created_date', '')[:10]}",
            reply_markup=_menu_for_role(role),
        )
    else:
        await message.answer(
            "❌ Не удалось получить актуальный статус из системы.\n"
            f"Обратитесь к менеджеру: @{config.MANAGER_USERNAME}",
            reply_markup=_menu_for_role(role),
        )

    await state.clear()


@router.message(F.text.in_({"🎁 Реферальная программа", "🤝 Партнерская программа"}))
async def program_info(message: Message):
    """Show program info for designers and partners"""
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else "designer"

    if message.text == "🎁 Реферальная программа":
        text = (
            "🎁 Реферальная программа\n\n"
            "🚧 Данный раздел находится в разработке.\n\n"
            f"Для подробностей свяжитесь с менеджером: @{config.MANAGER_USERNAME}"
        )
    else:
        text = (
            "🤝 Партнерская программа\n\n"
            "🚧 Информация появится здесь позже.\n\n"
            f"По всем вопросам обращайтесь к менеджеру: @{config.MANAGER_USERNAME}"
        )

    await message.answer(text, reply_markup=_menu_for_role(role))
