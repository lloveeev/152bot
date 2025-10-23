import json
import os
from typing import Dict

from dotenv import load_dotenv

load_dotenv()


def _load_stage_mapping(env_key: str, default: Dict[str, str]) -> Dict[str, str]:
    """
    Load stage mapping from environment if provided in JSON form.
    Falls back to the supplied default if parsing fails.
    """
    raw_value = os.getenv(env_key)
    if not raw_value:
        return default

    try:
        loaded = json.loads(raw_value)
        if isinstance(loaded, dict):
            # Convert keys to strings to avoid surprises after json parsing
            return {str(k): str(v) for k, v in loaded.items()}
    except json.JSONDecodeError:
        pass

    return default


# Telegram Bot Settings
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv('ADMIN_IDS', '').split(',') if admin_id]

# Bitrix24 Settings
BITRIX_WEBHOOK_URL = os.getenv('BITRIX_WEBHOOK_URL')
BITRIX_LEAD_SOURCE_ID = os.getenv('BITRIX_LEAD_SOURCE_ID', 'TELEGRAM')
BITRIX_SOURCE_DESCRIPTION = os.getenv('BITRIX_SOURCE_DESCRIPTION', 'Телеграм бот')
BITRIX_RESPONSIBLE_ID = int(os.getenv('BITRIX_RESPONSIBLE_ID', '0')) or None
BITRIX_CRM_AGENT_FIELD = os.getenv('BITRIX_CRM_AGENT_FIELD', 'UF_CRM_CRM_AGENT')
BITRIX_PROJECT_FILE_FIELD = os.getenv('BITRIX_PROJECT_FILE_FIELD', 'UF_CRM_PROJECT_FILE')
BITRIX_PROJECT_FILE_NAME_FIELD = os.getenv('BITRIX_PROJECT_FILE_NAME_FIELD', 'UF_CRM_PROJECT_FILE_NAME')
_partner_category_raw = os.getenv('BITRIX_PARTNER_CATEGORY_ID')
if _partner_category_raw is None:
    BITRIX_PARTNER_CATEGORY_ID = None
else:
    try:
        BITRIX_PARTNER_CATEGORY_ID = int(_partner_category_raw)
    except ValueError:
        BITRIX_PARTNER_CATEGORY_ID = _partner_category_raw
BITRIX_PARTNER_INITIAL_STAGE = os.getenv('BITRIX_PARTNER_INITIAL_STAGE')

# Database Settings
DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot_database.db')

# Links
PRIVACY_POLICY_URL = os.getenv('PRIVACY_POLICY_URL', 'https://example.com/privacy-policy')
MANAGER_USERNAME = os.getenv('MANAGER_USERNAME', 'username_manager')

# Traffic Sources
TRAFFIC_SOURCES = ['VK', 'INST', 'TG', 'YTB', 'QR', 'OTHER', 'REFERRAL']

# User Roles
USER_ROLES = {
    'designer': 'Дизайнер',
    'partner': 'Партнер'
}

# Deal Funnels and Stages
DESIGNER_FUNNEL_STAGES = _load_stage_mapping(
    'DESIGNER_FUNNEL_STAGES',
    {
        'NEW': 'Новая сделка (новый номер)',
        'PROJECT_RECEIVED': 'Получен проект на просчет',
        'ESTIMATE_DONE': 'Просчет сделан',
        'MEASUREMENT': 'Замер',
        'WON': 'Сделка успех',
        'LOSE': 'Сделка провал'
    }
)

PARTNER_FUNNEL_STAGES = _load_stage_mapping(
    'PARTNER_FUNNEL_STAGES',
    {
        'PROJECT_RECEIVED': 'Получен проект на просчет',
        'ESTIMATE_DONE': 'Просчет сделан',
        'MEASUREMENT': 'Замер',
        'WON': 'Сделка успех',
        'LOSE': 'Сделка провал'
    }
)

DESIGNER_ALLOWED_STATUSES = list(DESIGNER_FUNNEL_STAGES.keys())
PARTNER_ALLOWED_STATUSES = list(PARTNER_FUNNEL_STAGES.keys())

UNKNOWN_STATUS_PLACEHOLDER = os.getenv('UNKNOWN_STATUS_PLACEHOLDER', 'Статус не отслеживается в боте')
DEALS_PAGE_SIZE = int(os.getenv('DEALS_PAGE_SIZE', '5'))
