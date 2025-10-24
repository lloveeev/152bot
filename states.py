from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """States for user registration flow"""
    waiting_for_privacy_consent = State()
    waiting_for_role = State()
    waiting_for_full_name = State()
    waiting_for_phone = State()
    waiting_for_company = State()
    waiting_for_email = State()
    confirming_data = State()


class LeadCreationStates(StatesGroup):
    """States for lead creation flow"""
    waiting_for_client_name = State()
    waiting_for_client_phone = State()
    waiting_for_project_file = State()
    waiting_for_comment = State()
    confirming_lead = State()


class LeadStatusStates(StatesGroup):
    """States for checking lead status"""
    waiting_for_lead_number = State()


class BroadcastStates(StatesGroup):
    """States for admin broadcast"""
    waiting_for_target_selection = State()
    waiting_for_message = State()
    confirming_broadcast = State()
