from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from openpyxl import Workbook
import os

from database import Database
from states import BroadcastStates
from keyboards import get_admin_menu_keyboard, get_broadcast_role_keyboard, get_cancel_keyboard, get_designer_menu_keyboard
import config

router = Router()
db = Database()


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in config.ADMIN_IDS


@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Show admin panel"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к административной панели.")
        return

    await message.answer(
        "👨‍💼 Административная панель\n\n"
        "Выберите действие:",
        reply_markup=get_admin_menu_keyboard()
    )


@router.message(F.text == "🔙 Вернуться в основное меню")
async def back_to_main_menu(message: Message):
    """Return to main menu"""
    if not is_admin(message.from_user.id):
        return

    user = await db.get_user(message.from_user.id)

    if user and user.get('role') == 'designer':
        await message.answer(
            "Возвращаюсь в основное меню.",
            reply_markup=get_designer_menu_keyboard()
        )
    else:
        await message.answer(
            "Возвращаюсь в основное меню."
        )


@router.message(F.text == "👥 Выгрузить пользователей")
async def export_users(message: Message):
    """Export all users to Excel file"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return

    await message.answer("⏳ Формирую выгрузку пользователей...")

    users = await db.get_all_users()

    if not users:
        await message.answer("📭 В базе данных пока нет пользователей.")
        return

    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Пользователи"

    # Headers
    headers = [
        "Telegram ID",
        "ФИО",
        "Телефон",
        "Email",
        "Компания",
        "Роль",
        "Bitrix ID",
        "Источник трафика",
        "Реферальный код",
        "Заблокирован",
        "Согласие 152-ФЗ",
        "Дата регистрации",
        "Последняя активность"
    ]
    ws.append(headers)

    # Data rows
    for user in users:
        row = [
            user.get('telegram_id'),
            user.get('full_name', ''),
            user.get('phone', ''),
            user.get('email', ''),
            user.get('company_name', ''),
            config.USER_ROLES.get(user.get('role', ''), user.get('role', '')),
            user.get('bitrix_id', ''),
            user.get('traffic_source', ''),
            user.get('referral_code', ''),
            "Да" if user.get('is_blocked') == 1 else "Нет",
            "Да" if user.get('privacy_consent') == 1 else "Нет",
            user.get('registration_date', ''),
            user.get('last_activity', '')
        ]
        ws.append(row)

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Save file
    filename = "users_export.xlsx"
    wb.save(filename)

    # Send file
    document = FSInputFile(filename)
    await message.answer_document(
        document,
        caption=f"📊 Выгрузка пользователей\n\nВсего пользователей: {len(users)}"
    )

    # Delete temporary file
    try:
        os.remove(filename)
    except:
        pass

    await message.answer("✅ Выгрузка завершена!", reply_markup=get_admin_menu_keyboard())


@router.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message, state: FSMContext):
    """Start broadcast flow"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return

    await message.answer(
        "📢 Рассылка сообщений\n\n"
        "Выберите целевую аудиторию:",
        reply_markup=get_broadcast_role_keyboard()
    )
    await state.set_state(BroadcastStates.waiting_for_target_selection)


@router.callback_query(F.data.startswith("broadcast_"), BroadcastStates.waiting_for_target_selection)
async def broadcast_target_selected(callback: CallbackQuery, state: FSMContext):
    """Handle broadcast target selection"""
    if callback.data == "broadcast_cancel":
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.message.answer("Возвращаюсь в меню.", reply_markup=get_admin_menu_keyboard())
        await state.clear()
        await callback.answer()
        return

    target = callback.data.replace("broadcast_", "")
    await state.update_data(target=target)

    # Get target users count
    if target == "all":
        users = await db.get_all_users()
        target_name = "всем пользователям"
    else:
        users = await db.get_users_by_role(target)
        target_name = f"пользователям с ролью '{config.USER_ROLES.get(target, target)}'"

    # Filter out blocked users
    active_users = [u for u in users if u.get('is_blocked') == 0 and u.get('privacy_consent') == 1]

    await state.update_data(target_users=active_users)

    await callback.message.edit_text(
        f"✅ Выбрана аудитория: {target_name}\n"
        f"👥 Количество получателей: {len(active_users)}\n\n"
        f"Теперь введите текст сообщения для рассылки:"
    )

    await callback.message.answer(
        "💬 Введите сообщение:",
        reply_markup=get_cancel_keyboard()
    )

    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()


@router.message(BroadcastStates.waiting_for_message)
async def broadcast_message_received(message: Message, state: FSMContext):
    """Handle broadcast message input"""
    if message.text == "❌ Отмена":
        await message.answer("Рассылка отменена.", reply_markup=get_admin_menu_keyboard())
        await state.clear()
        return

    await state.update_data(message_text=message.text)
    data = await state.get_data()

    target_users = data.get('target_users', [])

    await message.answer(
        f"📢 Подтверждение рассылки\n\n"
        f"👥 Получателей: {len(target_users)}\n"
        f"💬 Сообщение:\n{message.text}\n\n"
        f"Начать рассылку?",
        reply_markup=get_broadcast_role_keyboard()
    )

    # Create simple confirmation keyboard
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel_final")]
    ])

    await message.answer(
        "Подтвердите отправку:",
        reply_markup=confirm_kb
    )

    await state.set_state(BroadcastStates.confirming_broadcast)


@router.callback_query(F.data == "broadcast_confirm", BroadcastStates.confirming_broadcast)
async def broadcast_confirmed(callback: CallbackQuery, state: FSMContext):
    """Execute broadcast"""
    data = await state.get_data()
    target_users = data.get('target_users', [])
    message_text = data.get('message_text')

    await callback.message.edit_text("⏳ Выполняю рассылку...")

    success_count = 0
    fail_count = 0

    for user in target_users:
        try:
            await callback.bot.send_message(
                chat_id=user.get('telegram_id'),
                text=message_text
            )
            success_count += 1
        except Exception as e:
            fail_count += 1
            # Mark user as blocked if they blocked the bot
            if "bot was blocked by the user" in str(e).lower():
                await db.set_user_blocked(user.get('telegram_id'), True)

    await callback.message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"✅ Успешно отправлено: {success_count}\n"
        f"❌ Ошибок: {fail_count}",
        reply_markup=get_admin_menu_keyboard()
    )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "broadcast_cancel_final", BroadcastStates.confirming_broadcast)
async def broadcast_cancelled_final(callback: CallbackQuery, state: FSMContext):
    """Cancel broadcast"""
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.message.answer("Возвращаюсь в меню.", reply_markup=get_admin_menu_keyboard())
    await state.clear()
    await callback.answer()
