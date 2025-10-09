from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import Database
from bitrix_api import BitrixAPI, validate_phone
from states import DealCreationStates, DealStatusStates
from keyboards import get_designer_menu_keyboard, get_cancel_keyboard, get_confirmation_keyboard
import config

router = Router()
db = Database()
bitrix = BitrixAPI()


@router.message(F.text == "📝 Новая сделка")
async def new_deal_start(message: Message, state: FSMContext):
    """Start new deal creation"""
    user = await db.get_user(message.from_user.id)

    if not user or user.get('role') != 'designer':
        await message.answer("❌ Эта функция доступна только для дизайнеров.")
        return

    await message.answer(
        "📝 Создание новой сделки\n\n"
        "Введите ФИО клиента:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(DealCreationStates.waiting_for_client_name)


@router.message(DealCreationStates.waiting_for_client_name)
async def client_name_entered(message: Message, state: FSMContext):
    """Handle client name input"""
    if message.text == "❌ Отмена":
        await message.answer("Создание сделки отменено.", reply_markup=get_designer_menu_keyboard())
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
    if message.text == "❌ Отмена":
        await message.answer("Создание сделки отменено.", reply_markup=get_designer_menu_keyboard())
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
        "Прикрепите файл проекта в формате PDF:\n"
        "(Отправьте PDF-файл или документ)"
    )
    await state.set_state(DealCreationStates.waiting_for_project_file)


@router.message(DealCreationStates.waiting_for_project_file, F.document)
async def project_file_uploaded(message: Message, state: FSMContext):
    """Handle project file upload"""
    document = message.document

    if document.mime_type != 'application/pdf':
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
    if message.text == "❌ Отмена":
        await message.answer("Создание сделки отменено.", reply_markup=get_designer_menu_keyboard())
        await state.clear()
        return

    await message.answer("Пожалуйста, отправьте PDF-файл проекта.")


@router.message(DealCreationStates.waiting_for_comment)
async def comment_entered(message: Message, state: FSMContext):
    """Handle comment input"""
    if message.text == "❌ Отмена":
        await message.answer("Создание сделки отменено.", reply_markup=get_designer_menu_keyboard())
        await state.clear()
        return

    comment = message.text.strip()
    await state.update_data(comment=comment)

    data = await state.get_data()
    user = await db.get_user(message.from_user.id)

    confirmation_text = (
        "📋 Проверьте данные сделки:\n\n"
        f"👤 Клиент: {data.get('client_name')}\n"
        f"📱 Телефон: {data.get('client_phone')}\n"
        f"📄 Файл: {data.get('project_file_name')}\n"
        f"💬 Комментарий: {comment}\n\n"
        f"✅ Подтвердить создание сделки?"
    )

    await message.answer(confirmation_text, reply_markup=get_confirmation_keyboard())
    await state.set_state(DealCreationStates.confirming_deal)


@router.callback_query(F.data == "confirm_yes", DealCreationStates.confirming_deal)
async def deal_confirmed(callback: CallbackQuery, state: FSMContext):
    """Handle deal confirmation"""
    data = await state.get_data()
    user = await db.get_user(callback.from_user.id)

    await callback.message.edit_text("⏳ Создаю сделку в системе...")

    deal_data = {
        "designer_name": user.get('full_name'),
        "designer_bitrix_id": user.get('bitrix_id'),
        "client_full_name": data.get('client_name'),
        "client_phone": data.get('client_phone'),
        "project_file_url": data.get('project_file_id'),  # In real scenario, upload to Bitrix
        "comment": data.get('comment')
    }

    bitrix_deal = await bitrix.create_lead(deal_data)

    if bitrix_deal:
        await db.add_deal({
            "deal_number": bitrix_deal.get('number'),
            "bitrix_deal_id": bitrix_deal.get('id'),
            "designer_telegram_id": callback.from_user.id,
            "client_full_name": data.get('client_name'),
            "client_phone": data.get('client_phone'),
            "project_file_id": data.get('project_file_id'),
            "comment": data.get('comment'),
            "status": bitrix_deal.get('status', 'NEW')
        })

        await callback.message.answer(
            f"✅ Сделка успешно создана!\n\n"
            f"📋 Номер сделки: {bitrix_deal.get('number')}\n"
            f"📊 Статус: {await bitrix.get_stage_name(bitrix_deal.get('status', 'NEW'))}\n\n"
            f"Вы можете отслеживать статус через меню 'Мои сделки' или 'Узнать статус'",
            reply_markup=get_designer_menu_keyboard()
        )
    else:
        await callback.message.answer(
            "❌ Произошла ошибка при создании сделки в системе.\n"
            f"Пожалуйста, обратитесь к менеджеру: @{config.MANAGER_USERNAME}",
            reply_markup=get_designer_menu_keyboard()
        )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "confirm_no", DealCreationStates.confirming_deal)
async def deal_cancelled(callback: CallbackQuery, state: FSMContext):
    """Handle deal cancellation"""
    await callback.message.edit_text("❌ Создание сделки отменено.")
    await callback.message.answer("Возвращаюсь в главное меню.", reply_markup=get_designer_menu_keyboard())
    await state.clear()
    await callback.answer()


@router.message(F.text == "📋 Мои сделки")
async def my_deals(message: Message):
    """Show user's deals"""
    user = await db.get_user(message.from_user.id)

    if not user or user.get('role') != 'designer':
        await message.answer("❌ Эта функция доступна только для дизайнеров.")
        return

    deals = await db.get_user_deals(message.from_user.id)

    if not deals:
        await message.answer(
            "У вас пока нет созданных сделок.\n\n"
            "Создайте первую сделку через меню 'Новая сделка'!",
            reply_markup=get_designer_menu_keyboard()
        )
        return

    deals_text = "📋 Ваши сделки:\n\n"

    for deal in deals:
        status_name = await bitrix.get_stage_name(deal.get('status', 'NEW'))
        deals_text += (
            f"📌 Сделка #{deal.get('deal_number')}\n"
            f"👤 Клиент: {deal.get('client_full_name')}\n"
            f"📊 Статус: {status_name}\n"
            f"📅 Дата: {deal.get('created_date', '')[:10]}\n"
            f"{'─' * 30}\n\n"
        )

    await message.answer(deals_text, reply_markup=get_designer_menu_keyboard())


@router.message(F.text == "🔍 Узнать статус")
async def check_status_start(message: Message, state: FSMContext):
    """Start deal status check"""
    user = await db.get_user(message.from_user.id)

    if not user or user.get('role') != 'designer':
        await message.answer("❌ Эта функция доступна только для дизайнеров.")
        return

    await message.answer(
        "🔍 Проверка статуса сделки\n\n"
        "Введите номер сделки:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(DealStatusStates.waiting_for_deal_number)


@router.message(DealStatusStates.waiting_for_deal_number)
async def deal_number_entered(message: Message, state: FSMContext):
    """Handle deal number input"""
    if message.text == "❌ Отмена":
        await message.answer("Операция отменена.", reply_markup=get_designer_menu_keyboard())
        await state.clear()
        return

    deal_number = message.text.strip()

    deal = await db.get_deal_by_number(deal_number)

    if not deal:
        await message.answer(
            f"❌ Сделка с номером {deal_number} не найдена.\n"
            "Проверьте номер и попробуйте снова."
        )
        return

    if deal.get('designer_telegram_id') != message.from_user.id:
        await message.answer(
            "❌ Эта сделка вам не принадлежит."
        )
        await state.clear()
        return

    current_status = await bitrix.get_lead_status(deal.get('bitrix_deal_id'))

    if current_status:
        # Update local database
        await db.update_deal_status(deal_number, current_status)
        status_name = await bitrix.get_stage_name(current_status)

        await message.answer(
            f"📊 Статус сделки #{deal_number}\n\n"
            f"👤 Клиент: {deal.get('client_full_name')}\n"
            f"📱 Телефон: {deal.get('client_phone')}\n"
            f"📊 Текущий статус: {status_name}\n"
            f"📅 Дата создания: {deal.get('created_date', '')[:10]}",
            reply_markup=get_designer_menu_keyboard()
        )
    else:
        await message.answer(
            "❌ Не удалось получить актуальный статус из системы.\n"
            f"Обратитесь к менеджеру: @{config.MANAGER_USERNAME}",
            reply_markup=get_designer_menu_keyboard()
        )

    await state.clear()


@router.message(F.text == "🎁 Реферальная программа")
async def referral_program(message: Message):
    """Show referral program info"""
    await message.answer(
        "🎁 Реферальная программа\n\n"
        "🚧 Данный раздел находится в разработке.\n\n"
        f"Для получения подробной информации обратитесь к менеджеру: @{config.MANAGER_USERNAME}",
        reply_markup=get_designer_menu_keyboard()
    )
