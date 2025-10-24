import logging
import math
from io import BytesIO
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
from states import LeadCreationStates, LeadStatusStates
from keyboards import (
    get_cancel_keyboard,
    get_confirmation_keyboard,
    get_main_menu_keyboard,
)
import config

logger = logging.getLogger(__name__)

router = Router()
db = Database()
bitrix = BitrixAPI()

CANCEL_TEXT = "❌ Отмена"
LEADS_CALLBACK_PREFIX = "leads"
PAGE_SIZE = max(config.LEADS_PAGE_SIZE, 1)


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


def _default_source_id() -> str:
    return config.BITRIX_DEFAULT_SOURCE_ID or config.BITRIX_LEAD_SOURCE_ID or "TELEGRAM"


def _default_source_name() -> str:
    return config.BITRIX_SOURCE_DESCRIPTION or "Telegram"


async def _set_default_source(state: FSMContext):
    source_id = _default_source_id()
    source_name = _default_source_name()
    codes = [source_id] if source_id else []
    await state.update_data(
        source_id=source_id,
        source_name=source_name,
        source_codes=codes,
    )


def _build_confirmation_text(data: Dict) -> str:
    project_file = data.get("project_file_name") or "—"
    comment = data.get("comment") or "—"
    source_id = data.get("source_id") or _default_source_id()
    source_name = data.get("source_name") or _default_source_name()
    source_line = source_name
    if source_id:
        source_line = f"{source_line} ({source_id})"

    return (
        "📋 Проверьте данные сделки:\n\n"
        f"👤 Клиент: {data.get('client_name')}\n"
        f"📱 Телефон: {data.get('client_phone')}\n"
        f"📄 Файл: {project_file}\n"
        f"🏷 Источник обращения: {source_line}\n"
        f"💬 Комментарий: {comment}\n\n"
        "✅ Подтвердить создание сделки?"
    )


async def _send_confirmation(message: Message, state: FSMContext):
    await _set_default_source(state)
    data = await state.get_data()
    confirmation_text = _build_confirmation_text(data)
    await message.answer(confirmation_text, reply_markup=get_confirmation_keyboard())
    await state.set_state(LeadCreationStates.confirming_lead)


def _build_pagination_keyboard(role: str, page: int, total_pages: int) -> Optional[InlineKeyboardMarkup]:
    if total_pages <= 1:
        return None

    buttons: List[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"{LEADS_CALLBACK_PREFIX}:{role}:{page - 1}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=f"{LEADS_CALLBACK_PREFIX}:{role}:noop",
        )
    )

    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                text="➡️ Далее",
                callback_data=f"{LEADS_CALLBACK_PREFIX}:{role}:{page + 1}",
            )
        )

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _format_lead_entry(lead: Dict) -> str:
    status_name = lead.get("status_name") or config.UNKNOWN_STATUS_PLACEHOLDER
    sync_status = lead.get("sync_status", "valid")
    icon_map = {
        "updated": "🆕",
        "unsupported_status": "⚠️",
        "valid": "📊",
    }
    status_icon = icon_map.get(sync_status, "📊")

    lines = [
        f"📌 Сделка #{lead.get('lead_number')}",
        f"👤 Клиент: {lead.get('client_full_name')}",
    ]
    if lead.get("project_file_name"):
        lines.append(f"📄 Файл: {lead.get('project_file_name')}")

    lines.append(f"{status_icon} Статус: {status_name}")

    lines.append(f"📅 Дата: {lead.get('created_date', '')[:10]}")

    return "\n".join(lines)


def _render_leads_page(leads: List[Dict], page: int, role: str) -> (str, Optional[InlineKeyboardMarkup]):
    total_pages = max(math.ceil(len(leads) / PAGE_SIZE), 1)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    entries = leads[start:start + PAGE_SIZE]

    lines = ["📋 Ваши сделки:", ""]
    for lead in entries:
        lines.append(_format_lead_entry(lead))
        lines.append("─" * 30)
        lines.append("")

    text = "\n".join(lines).strip()
    keyboard = _build_pagination_keyboard(role, page, total_pages)
    return text, keyboard


async def _sync_lead_with_bitrix(lead: Dict, fallback_role: str) -> Dict:
    """
    Sync single lead with Bitrix24 and enrich it with status info.
    """
    role = lead.get("owner_role", fallback_role)
    lead_id = lead.get("bitrix_lead_id")
    lead_number = lead.get("lead_number")
    current_status = await bitrix.get_lead_status(lead_id)

    if current_status:
        allowed = _is_status_allowed(current_status, role)
        stage_name = await bitrix.get_stage_name(current_status, role=role)

        if allowed:
            if current_status != lead.get("status"):
                await db.update_lead_status(lead_number, current_status)
                lead["status"] = current_status
                lead["sync_status"] = "updated"
            else:
                lead["sync_status"] = "valid"
        else:
            lead["status"] = current_status
            lead["sync_status"] = "unsupported_status"

        lead["status_name"] = stage_name or config.UNKNOWN_STATUS_PLACEHOLDER
    else:
        lead["sync_status"] = "not_found"

    return lead


async def _sync_leads_for_user(telegram_id: int, role: str, *, drop_missing: bool) -> (List[Dict], List[Dict]):
    leads = await db.get_user_leads(telegram_id)
    synced: List[Dict] = []
    invalid: List[Dict] = []

    for lead in leads:
        synced_lead = await _sync_lead_with_bitrix(lead, role)
        if synced_lead.get("sync_status") == "not_found":
            invalid.append(synced_lead)
        else:
            synced.append(synced_lead)

    if drop_missing and invalid:
        for lead in invalid:
            await db.delete_lead(lead.get("lead_number"))

    return synced, invalid


@router.message(F.text == "📝 Новая сделка")
async def new_lead_start(message: Message, state: FSMContext):
    """Start new lead creation"""
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
    await state.set_state(LeadCreationStates.waiting_for_client_name)


@router.message(LeadCreationStates.waiting_for_client_name)
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
    await state.set_state(LeadCreationStates.waiting_for_client_phone)


@router.message(LeadCreationStates.waiting_for_client_phone)
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
    await state.set_state(LeadCreationStates.waiting_for_project_file)


@router.message(LeadCreationStates.waiting_for_project_file, F.document)
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
    await state.set_state(LeadCreationStates.waiting_for_comment)


@router.message(LeadCreationStates.waiting_for_project_file)
async def project_file_invalid(message: Message, state: FSMContext):
    """Handle invalid project file"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    await message.answer("Пожалуйста, отправьте PDF-файл проекта.")


@router.message(LeadCreationStates.waiting_for_comment)
async def comment_entered(message: Message, state: FSMContext):
    """Handle comment input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Создание сделки отменено.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    comment = message.text.strip()
    await state.update_data(comment=comment)

    await _send_confirmation(message, state)


@router.callback_query(F.data == "confirm_yes", LeadCreationStates.confirming_lead)
async def lead_confirmed(callback: CallbackQuery, state: FSMContext):
    """Handle lead confirmation"""
    data = await state.get_data()
    await _set_default_source(state)
    data = await state.get_data()
    user = await db.get_user(callback.from_user.id)
    role = data.get("owner_role", user.get("role", "designer") if user else "designer")

    project_file_id = data.get("project_file_id")
    project_file_name = data.get("project_file_name")
    project_file_bytes: Optional[bytes] = None

    if project_file_id:
        buffer = BytesIO()
        try:
            await callback.message.bot.download(project_file_id, destination=buffer)
            project_file_bytes = buffer.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Не удалось скачать файл проекта из Telegram, file_id=%s: %s",
                project_file_id,
                exc,
            )
            project_file_bytes = None

    await callback.message.edit_text("⏳ Создаю сделку в системе...")

    lead_data = {
        "designer_name": user.get("full_name"),
        "designer_bitrix_id": user.get("bitrix_id"),
        "designer_role_key": role,
        "designer_role_title": config.USER_ROLES.get(role, role.title()),
        "crm_agent_name": user.get("full_name"),
        "client_full_name": data.get("client_name"),
        "client_phone": data.get("client_phone"),
        "project_file_id": project_file_id,
        "project_file_name": project_file_name,
        "project_file_bytes": project_file_bytes,
        "comment": data.get("comment"),
        "owner_role": role,
        "status_id": config.BITRIX_PARTNER_INITIAL_STAGE if role == "partner" else None,
        "source_id": data.get("source_id"),
        "source_description": data.get("source_name"),
        "source_codes": data.get("source_codes"),
    }

    bitrix_lead = await bitrix.create_lead(lead_data)

    if bitrix_lead:
        await db.add_lead({
            "lead_number": bitrix_lead.get("number"),
            "bitrix_lead_id": bitrix_lead.get("id"),
            "designer_telegram_id": callback.from_user.id,
            "client_full_name": data.get("client_name"),
            "client_phone": data.get("client_phone"),
            "project_file_id": data.get("project_file_id"),
            "project_file_name": data.get("project_file_name"),
            "comment": data.get("comment"),
            "status": bitrix_lead.get("status", ""),
            "entity_type": bitrix_lead.get("entity_type", "lead"),
            "owner_role": role,
        })

        status_name = await bitrix.get_stage_name(bitrix_lead.get("status", ""), role=role)

        await callback.message.answer(
            f"✅ Сделка успешно создана!\n\n"
            f"📋 Номер сделки: {bitrix_lead.get('number')}\n"
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


@router.callback_query(F.data == "confirm_no", LeadCreationStates.confirming_lead)
async def lead_cancelled(callback: CallbackQuery, state: FSMContext):
    """Handle lead cancellation"""
    role = await _get_role_from_state(state)

    await callback.message.edit_text("❌ Создание сделки отменено.")
    await callback.message.answer("Возвращаюсь в главное меню.", reply_markup=_menu_for_role(role))
    await state.clear()
    await callback.answer()


@router.message(F.text == "📋 Мои сделки")
async def my_leads(message: Message):
    """Show user's leads with Bitrix validation"""
    user = await db.get_user(message.from_user.id)
    role = user.get("role") if user else None

    if not user or role not in {"designer", "partner"}:
        await message.answer("❌ Эта функция доступна только для зарегистрированных дизайнеров и партнеров.")
        return

    leads = await db.get_user_leads(message.from_user.id)

    if not leads:
        await message.answer(
            "У вас пока нет активных сделок.\n\nСоздайте новую сделку через меню 'Новая сделка'!",
            reply_markup=_menu_for_role(role),
        )
        return

    loading_msg = await message.answer("⏳ Синхронизирую сделки с Bitrix24...")

    valid_leads, invalid_leads = await _sync_leads_for_user(
        message.from_user.id,
        role,
        drop_missing=True,
    )

    if invalid_leads:
        invalid_text_lines = [
            "⚠️ Некоторые сделки не найдены в Bitrix24 и были удалены из списка:",
            "",
        ]
        for lead in invalid_leads:
            invalid_text_lines.extend([
                f"📌 Сделка #{lead.get('lead_number')}",
                f"👤 Клиент: {lead.get('client_full_name')}",
                f"📅 Дата: {lead.get('created_date', '')[:10]}",
                "─" * 30,
            ])
        invalid_text_lines.append(
            f"Если нужна помощь, свяжитесь с менеджером @{config.MANAGER_USERNAME}."
        )
        await message.answer("\n".join(invalid_text_lines))

    if not valid_leads:
        await loading_msg.delete()
        await message.answer(
            "Список актуальных сделок пуст.\nСоздайте новую сделку через меню 'Новая сделка'!",
            reply_markup=_menu_for_role(role),
        )
        return

    text, keyboard = _render_leads_page(valid_leads, page=0, role=role)
    await loading_msg.delete()
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{LEADS_CALLBACK_PREFIX}:"))
async def paginate_leads(callback: CallbackQuery):
    """Handle leads pagination callbacks"""
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

    valid_leads, _ = await _sync_leads_for_user(
        callback.from_user.id,
        role,
        drop_missing=False,
    )

    if not valid_leads:
        await callback.message.edit_text(
            "Список сделок пуст.",
            reply_markup=None,
        )
        await callback.answer()
        return

    text, keyboard = _render_leads_page(valid_leads, page=page, role=role)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(F.text == "🔍 Узнать статус")
async def check_status_start(message: Message, state: FSMContext):
    """Start lead status check"""
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
    await state.set_state(LeadStatusStates.waiting_for_lead_number)


@router.message(LeadStatusStates.waiting_for_lead_number)
async def lead_number_entered(message: Message, state: FSMContext):
    """Handle lead number input"""
    role = await _get_role_from_state(state)

    if message.text == CANCEL_TEXT:
        await message.answer("Операция отменена.", reply_markup=_menu_for_role(role))
        await state.clear()
        return

    lead_number = message.text.strip()

    lead = await db.get_lead_by_number(lead_number)

    if not lead:
        await message.answer(
            f"❌ Сделка с номером {lead_number} не найдена.\nПроверьте номер и попробуйте снова."
        )
        return

    if lead.get("designer_telegram_id") != message.from_user.id:
        await message.answer("❌ Эта сделка вам не принадлежит.")
        await state.clear()
        return

    lead_role = lead.get("owner_role", role)
    current_status = await bitrix.get_lead_status(lead.get("bitrix_lead_id"))

    if current_status:
        await db.update_lead_status(lead_number, current_status)
        status_name = await bitrix.get_stage_name(current_status, role=lead_role) or config.UNKNOWN_STATUS_PLACEHOLDER
        await message.answer(
            f"📊 Статус сделки #{lead_number}\n\n"
            f"👤 Клиент: {lead.get('client_full_name')}\n"
            f"📱 Телефон: {lead.get('client_phone')}\n"
            f"📊 Текущий статус: {status_name}\n"
            f"📅 Дата создания: {lead.get('created_date', '')[:10]}",
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
