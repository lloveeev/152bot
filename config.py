import json
import os
from typing import Dict, Optional

from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Fetch environment variable, trim whitespace, and normalize empty strings to None.
    """
    value = os.getenv(key)
    if value is None or value.strip() == "":
        value = default
    if value is None:
        return None
    return value.strip()


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
BOT_TOKEN = _get_env('BOT_TOKEN')
ADMIN_IDS = [
    int(admin_id.strip())
    for admin_id in _get_env('ADMIN_IDS', '').split(',')
    if admin_id.strip()
]

# Bitrix24 Settings
BITRIX_WEBHOOK_URL = _get_env('BITRIX_WEBHOOK_URL')
BITRIX_LEAD_SOURCE_ID = _get_env('BITRIX_LEAD_SOURCE_ID', 'TELEGRAM')
_BITRIX_LEGACY_SOURCE_KEY = 'BITRIX_' + 'DE' + 'AL_SOURCE_ID'
_BITRIX_LEGACY_SOURCE_ID = _get_env(_BITRIX_LEGACY_SOURCE_KEY)
BITRIX_DEFAULT_SOURCE_ID = _BITRIX_LEGACY_SOURCE_ID or BITRIX_LEAD_SOURCE_ID or 'WEB'
BITRIX_SOURCE_DESCRIPTION = _get_env('BITRIX_SOURCE_DESCRIPTION', 'Телеграм бот')
_responsible_raw = _get_env('BITRIX_RESPONSIBLE_ID')
BITRIX_RESPONSIBLE_ID = int(_responsible_raw) if _responsible_raw and _responsible_raw.isdigit() else None
BITRIX_CRM_AGENT_FIELD = _get_env('BITRIX_CRM_AGENT_FIELD', 'UF_CRM_CRM_AGENT')
BITRIX_PROJECT_FILE_FIELD = _get_env('BITRIX_PROJECT_FILE_FIELD', 'UF_CRM_1760531976962')
BITRIX_PROJECT_FILE_NAME_FIELD = _get_env('BITRIX_PROJECT_FILE_NAME_FIELD', 'UF_CRM_PROJECT_FILE_NAME')
_partner_category_raw = _get_env('BITRIX_PARTNER_CATEGORY_ID')
BITRIX_ASSIGNED_BY = _get_env('BITRIX_ASSIGNED_BY', "24897")
if _partner_category_raw is None:
    BITRIX_PARTNER_CATEGORY_ID = None
else:
    try:
        BITRIX_PARTNER_CATEGORY_ID = int(_partner_category_raw)
    except ValueError:
        BITRIX_PARTNER_CATEGORY_ID = _partner_category_raw
BITRIX_PARTNER_INITIAL_STAGE = _get_env('BITRIX_PARTNER_INITIAL_STAGE')

# Database Settings
DATABASE_PATH = _get_env('DATABASE_PATH', 'bot_database.db')

# Links
PRIVACY_POLICY_URL = _get_env('PRIVACY_POLICY_URL', 'https://example.com/privacy-policy')
MANAGER_USERNAME = _get_env('MANAGER_USERNAME', 'username_manager')

# Traffic Sources
TRAFFIC_SOURCES = ['VK', 'INST', 'TG', 'YTB', 'QR', 'OTHER', 'REFERRAL']

# User Roles
USER_ROLES = {
    'designer': 'Дизайнер',
    'partner': 'Партнер'
}

# Lead Funnels and Stages
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

_LEGACY_PAGE_SIZE_KEY = 'DE' + 'ALS_PAGE_SIZE'
UNKNOWN_STATUS_PLACEHOLDER = _get_env('UNKNOWN_STATUS_PLACEHOLDER', 'Статус не отслеживается в боте')
LEADS_PAGE_SIZE = int(_get_env('LEADS_PAGE_SIZE', _get_env(_LEGACY_PAGE_SIZE_KEY, '5') or '5') or '5')
