import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Settings
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv('ADMIN_IDS', '').split(',') if admin_id]

# Bitrix24 Settings
BITRIX_WEBHOOK_URL = os.getenv('BITRIX_WEBHOOK_URL')

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
DESIGNER_FUNNEL_STAGES = {
    'NEW': 'Новая сделка (новый номер)',
    'PROJECT_RECEIVED': 'Получен проект на просчет',
    'ESTIMATE_DONE': 'Просчет сделан',
    'MEASUREMENT': 'Замер',
    'WON': 'Успешно реализовано',
    'LOSE': 'Не реализовано'
}

PARTNER_FUNNEL_STAGES = {
    'PROJECT_RECEIVED': 'Получен проект на просчет',
    'ESTIMATE_DONE': 'Просчет сделан',
    'MEASUREMENT': 'Замер',
    'WON': 'Успешно реализовано',
    'LOSE': 'Не реализовано'
}
