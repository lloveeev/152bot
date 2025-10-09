
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import json

from database import Database
from bitrix_api import BitrixAPI, validate_phone
from states import RegistrationStates
from keyboards import (
    get_privacy_consent_keyboard,
    get_role_selection_keyboard,
    get_phone_request_keyboard,
    get_designer_menu_keyboard,
    get_cancel_keyboard
)
import config

router = Router()
db = Database()
bitrix = BitrixAPI()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command with traffic source tracking"""
    user_id = message.from_user.id

    # deep_link rot ebal ego
    traffic_source = None
    if message.text and len(message.text.split()) > 1:
        start_param = message.text.split()[1]
        if start_param.startswith("start="):
            traffic_source = start_param.replace("start=", "").upper()
        else:
            traffic_source = start_param.upper()

    user = await db.get_user(user_id)

    if user:
        if user.get('privacy_consent') == 1:
            await message.answer(
                f"С возвращением, {user.get('full_name', 'пользователь')}!",
                reply_markup=get_designer_menu_keyboard() if user.get('role') == 'designer' else None
            )
        else:
            await start_privacy_flow(message, state, traffic_source)
    else:
        await db.add_user(user_id, traffic_source)
        await start_privacy_flow(message, state, traffic_source)


async def start_privacy_flow(message: Message, state: FSMContext, traffic_source: str = None):
    """Start privacy consent flow"""
    await message.answer(
        f"👋 Добро пожаловать!\n\n"
        f"Для продолжения работы с ботом необходимо ознакомиться и принять условия "
        f"обработки персональных данных согласно 152-ФЗ.\n\n"
        f"📄 [Политика конфиденциальности]({config.PRIVACY_POLICY_URL})",
        reply_markup=get_privacy_consent_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(RegistrationStates.waiting_for_privacy_consent)


@router.callback_query(F.data == "privacy_accept", RegistrationStates.waiting_for_privacy_consent)
async def privacy_accepted(callback: CallbackQuery, state: FSMContext):
    """Handle privacy policy acceptance"""
    await db.update_user(callback.from_user.id, privacy_consent=1)

    await callback.message.edit_text(
        "✅ Спасибо! Вы приняли условия обработки персональных данных.\n\n"
        "Теперь давайте выберем вашу роль:"
    )
    await callback.message.answer(
        "Пожалуйста, выберите вашу роль:",
        reply_markup=get_role_selection_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_role)
    await callback.answer()


@router.callback_query(F.data == "privacy_decline", RegistrationStates.waiting_for_privacy_consent)
async def privacy_declined(callback: CallbackQuery, state: FSMContext):
    """Handle privacy policy decline"""
    await callback.message.edit_text(
        "❌ К сожалению, без принятия условий обработки персональных данных "
        "вы не можете использовать бота.\n\n"
        "Если передумаете, напишите /start"
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("role_"), RegistrationStates.waiting_for_role)
async def role_selected(callback: CallbackQuery, state: FSMContext):
    """Handle role selection"""
    role = callback.data.replace("role_", "")
    role_name = config.USER_ROLES.get(role, "Неизвестная роль")

    await state.update_data(role=role)

    if role == "designer":
        await callback.message.edit_text(f"✅ Вы выбрали роль: {role_name}")
        await callback.message.answer(
            "Отлично! Теперь введите ваше полное ФИО (Фамилия Имя Отчество):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(RegistrationStates.waiting_for_full_name)
    else:
        await callback.message.edit_text(
            f"🚧 Функционал для роли '{role_name}' находится в разработке.\n\n"
            f"По всем вопросам обращайтесь к менеджеру: @{config.MANAGER_USERNAME}"
        )
        await db.update_user(callback.from_user.id, role=role)
        await state.clear()

    await callback.answer()


@router.message(RegistrationStates.waiting_for_full_name)
async def full_name_entered(message: Message, state: FSMContext):
    """Handle full name input"""
    if message.text == "❌ Отмена":
        await message.answer("Регистрация отменена. Напишите /start для начала.")
        await state.clear()
        return

    full_name = message.text.strip()

    if len(full_name.split()) < 2:
        await message.answer("Пожалуйста, введите полное ФИО (минимум Фамилия и Имя):")
        return

    await state.update_data(full_name=full_name)

    await message.answer(
        "Теперь укажите название вашей компании:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_company)


@router.message(RegistrationStates.waiting_for_company)
async def company_entered(message: Message, state: FSMContext):
    """Handle company name input"""
    if message.text == "❌ Отмена":
        await message.answer("Регистрация отменена. Напишите /start для начала.")
        await state.clear()
        return

    company_name = message.text.strip()
    await state.update_data(company_name=company_name)

    data = await state.get_data()
    full_name = data.get('full_name')

    bitrix_contact = await bitrix.find_contact_by_name(full_name)

    if bitrix_contact:
        await state.update_data(bitrix_id=bitrix_contact.get('ID'))

        phone = ""
        if bitrix_contact.get('PHONE'):
            phone = bitrix_contact['PHONE'][0].get('VALUE', '') if isinstance(bitrix_contact['PHONE'], list) else ""

        email = ""
        if bitrix_contact.get('EMAIL'):
            email = bitrix_contact['EMAIL'][0].get('VALUE', '') if isinstance(bitrix_contact['EMAIL'], list) else ""

        await message.answer(
            f"✅ Вы найдены в системе!\n\n"
            f"Проверьте данные:\n"
            f"ФИО: {full_name}\n"
            f"Компания: {company_name}\n"
            f"Телефон: {phone}\n"
            f"Email: {email}\n\n"
            f"Создаю ваш личный кабинет..."
        )

        await db.update_user(
            message.from_user.id,
            full_name=full_name,
            company_name=company_name,
            phone=phone,
            email=email,
            role='designer',
            bitrix_id=bitrix_contact.get('ID')
        )

        await complete_registration(message, state)
    else:
        await message.answer(
            "Вы не найдены в системе. Пожалуйста, предоставьте ваш номер телефона:",
            reply_markup=get_phone_request_keyboard()
        )
        await state.set_state(RegistrationStates.waiting_for_phone)


@router.message(RegistrationStates.waiting_for_phone, F.contact)
async def phone_shared(message: Message, state: FSMContext):
    """Handle phone number shared via button"""
    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    await message.answer(
        "Спасибо! Теперь введите ваш email:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_email)


@router.message(RegistrationStates.waiting_for_phone)
async def phone_entered(message: Message, state: FSMContext):
    """Handle phone number entered manually"""
    if message.text == "❌ Отмена":
        await message.answer("Регистрация отменена. Напишите /start для начала.")
        await state.clear()
        return

    phone = message.text.strip()

    if not validate_phone(phone):
        await message.answer(
            "❌ Неверный формат номера телефона.\n\n"
            "Пожалуйста, введите номер в правильном формате:\n"
            "• +79161234567\n"
            "• 89161234567\n"
            "• 79161234567\n"
            "• 9161234567\n\n"
            "Или используйте кнопку 'Поделиться номером'",
            reply_markup=get_phone_request_keyboard()
        )
        return

    await state.update_data(phone=phone)

    await message.answer(
        "Спасибо! Теперь введите ваш email:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_email)


@router.message(RegistrationStates.waiting_for_email)
async def email_entered(message: Message, state: FSMContext):
    """Handle email input"""
    if message.text == "❌ Отмена":
        await message.answer("Регистрация отменена. Напишите /start для начала.")
        await state.clear()
        return

    email = message.text.strip()

    if '@' not in email or '.' not in email:
        await message.answer("Пожалуйста, введите корректный email:")
        return

    await state.update_data(email=email)

    data = await state.get_data()
    full_name_parts = data.get('full_name', '').split()

    contact_data = {
        "last_name": full_name_parts[0] if len(full_name_parts) > 0 else "",
        "first_name": full_name_parts[1] if len(full_name_parts) > 1 else "",
        "middle_name": full_name_parts[2] if len(full_name_parts) > 2 else "",
        "phone": data.get('phone'),
        "email": email,
        "company_name": data.get('company_name'),
        "telegram_id": message.from_user.id
    }

    bitrix_id = await bitrix.create_contact(contact_data)

    if bitrix_id:
        await state.update_data(bitrix_id=bitrix_id)

        await db.update_user(
            message.from_user.id,
            full_name=data.get('full_name'),
            company_name=data.get('company_name'),
            phone=data.get('phone'),
            email=email,
            role='designer',
            bitrix_id=bitrix_id
        )

        await complete_registration(message, state)
    else:
        await message.answer(
            "❌ Произошла ошибка при создании профиля в системе. "
            "Пожалуйста, обратитесь к менеджеру: @{config.MANAGER_USERNAME}"
        )
        await state.clear()


async def complete_registration(message: Message, state: FSMContext):
    """Complete registration and show main menu"""
    await message.answer(
        "🎉 Регистрация успешно завершена!\n\n"
        "Теперь вы можете создавать сделки, просматривать их статус и участвовать в реферальной программе.",
        reply_markup=get_designer_menu_keyboard()
    )
    await state.clear()
