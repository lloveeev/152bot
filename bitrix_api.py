import aiohttp
from typing import Optional, Dict, List
import config
import logging
import json
import re

logger = logging.getLogger(__name__)


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format
    Accepts Russian phone numbers in various formats:
    - +79161234567 (11 digits with +7)
    - 89161234567 (11 digits with 8)
    - 79161234567 (11 digits with 7)
    - 9161234567 (10 digits)
    Returns True if valid, False otherwise
    """
    if not phone:
        return False

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)

    # Valid phone should have 10-11 digits
    if len(digits) < 10 or len(digits) > 11:
        return False

    # If 11 digits, first digit should be 7 or 8
    if len(digits) == 11 and digits[0] not in ['7', '8']:
        return False

    # If 10 digits, first digit should be 9 (mobile) or 3-9 (landline)
    if len(digits) == 10 and not digits[0].isdigit():
        return False

    return True


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number to last 10 digits (without +7/8)
    Example: +79161234567 -> 9161234567
    """
    if not phone:
        return ""

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)

    # Take last 10 digits
    normalized = digits[-10:] if len(digits) >= 10 else digits

    logger.debug(f"[normalize_phone] {phone} -> {normalized}")
    return normalized


class BitrixAPI:
    def __init__(self, webhook_url: str = config.BITRIX_WEBHOOK_URL):
        self.webhook_url = webhook_url.rstrip('/')
        logger.info(f"[BitrixAPI] Инициализация с webhook URL: {self.webhook_url[:50]}...")

    async def _make_request(self, method: str, params: Dict = None) -> Dict:
        """Make request to Bitrix24 API"""
        url = f"{self.webhook_url}/{method}"
        logger.info(f"[BitrixAPI] Запрос к Bitrix24: {method}")
        logger.debug(f"[BitrixAPI] URL: {url}")
        logger.debug(f"[BitrixAPI] Параметры: {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params or {}) as response:
                    response_text = await response.text()
                    logger.info(f"[BitrixAPI] Статус ответа: {response.status}")
                    logger.debug(f"[BitrixAPI] Тело ответа: {response_text}")

                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"[BitrixAPI] ✅ Запрос {method} успешен")
                        return result
                    else:
                        logger.error(f"[BitrixAPI] ❌ Ошибка HTTP {response.status}: {response_text}")
                        return {"error": f"HTTP {response.status}", "details": response_text}
        except Exception as e:
            logger.exception(f"[BitrixAPI] ❌ Исключение при запросе {method}: {str(e)}")
            return {"error": str(e)}

    async def find_contact_by_name(self, full_name: str) -> Optional[Dict]:
        """Find contact in Bitrix24 by full name"""
        logger.info(f"[find_contact_by_name] Поиск контакта по имени: {full_name}")
        params = {
            "filter": {"NAME": full_name},
            "select": ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "PHONE", "EMAIL", "COMPANY_TITLE"]
        }
        result = await self._make_request("crm.contact.list", params)

        if result.get("result") and len(result["result"]) > 0:
            logger.info(f"[find_contact_by_name] ✅ Найден контакт ID: {result['result'][0].get('ID')}")
            logger.debug(f"[find_contact_by_name] Данные: {json.dumps(result['result'][0], ensure_ascii=False)}")
            return result["result"][0]
        logger.warning(f"[find_contact_by_name] ⚠️ Контакт не найден")
        return None

    async def find_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """Find contact in Bitrix24 by phone number (normalized to 10 digits)"""
        normalized_phone = normalize_phone(phone)
        logger.info(f"[find_contact_by_phone] Поиск контакта по телефону: {phone} (нормализован: {normalized_phone})")
        params = {
            "filter": {"PHONE": normalized_phone},
            "select": ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "PHONE", "EMAIL", "COMPANY_TITLE"]
        }
        result = await self._make_request("crm.contact.list", params)

        if result.get("result") and len(result["result"]) > 0:
            logger.info(f"[find_contact_by_phone] ✅ Найден контакт ID: {result['result'][0].get('ID')}")
            logger.debug(f"[find_contact_by_phone] Данные: {json.dumps(result['result'][0], ensure_ascii=False)}")
            return result["result"][0]
        logger.warning(f"[find_contact_by_phone] ⚠️ Контакт не найден")
        return None

    async def create_contact(self, contact_data: Dict) -> Optional[int]:
        """Create new contact in Bitrix24"""
        logger.info(f"[create_contact] Создание нового контакта")
        logger.debug(f"[create_contact] Данные контакта: {json.dumps(contact_data, ensure_ascii=False)}")

        params = {
            "fields": {
                "NAME": contact_data.get("first_name", ""),
                "LAST_NAME": contact_data.get("last_name", ""),
                "SECOND_NAME": contact_data.get("middle_name", ""),
                "POST": contact_data.get("position", "Дизайнер"),
                "PHONE": [{"VALUE": contact_data.get("phone"), "VALUE_TYPE": "WORK"}] if contact_data.get("phone") else [],
                "EMAIL": [{"VALUE": contact_data.get("email"), "VALUE_TYPE": "WORK"}] if contact_data.get("email") else [],
                "COMPANY_TITLE": contact_data.get("company_name", ""),
                "UF_CRM_TELEGRAM_ID": contact_data.get("telegram_id")
            }
        }
        result = await self._make_request("crm.contact.add", params)

        if result.get("result"):
            logger.info(f"[create_contact] ✅ Контакт создан с ID: {result['result']}")
            return result["result"]
        logger.error(f"[create_contact] ❌ Не удалось создать контакт: {result}")
        return None

    async def update_contact(self, contact_id: int, contact_data: Dict) -> bool:
        """Update existing contact in Bitrix24"""
        logger.info(f"[update_contact] Обновление контакта ID: {contact_id}")
        logger.debug(f"[update_contact] Новые данные: {json.dumps(contact_data, ensure_ascii=False)}")

        params = {
            "id": contact_id,
            "fields": contact_data
        }
        result = await self._make_request("crm.contact.update", params)

        if result.get("result"):
            logger.info(f"[update_contact] ✅ Контакт {contact_id} обновлен")
        else:
            logger.error(f"[update_contact] ❌ Не удалось обновить контакт: {result}")
        return result.get("result", False)

    async def create_lead(self, lead_data: Dict) -> Optional[Dict]:
        """Create new lead in Bitrix24 (will be converted to deal by manager)"""
        logger.info(f"[create_lead] Создание нового лида")
        logger.debug(f"[create_lead] Входные данные: {json.dumps(lead_data, ensure_ascii=False)}")

        # Parse client name
        name_parts = lead_data.get("client_full_name", "").split()

        # Create lead
        params = {
            "fields": {
                "TITLE": f"Заявка от {lead_data.get('designer_role', 'дизайнера')}: {lead_data.get('designer_name')}",
                "NAME": name_parts[1] if len(name_parts) > 1 else "",
                "LAST_NAME": name_parts[0] if len(name_parts) > 0 else "",
                "SECOND_NAME": name_parts[2] if len(name_parts) > 2 else "",
                "PHONE": [{"VALUE": normalize_phone(lead_data.get("client_phone")), "VALUE_TYPE": "WORK"}],
                "COMMENTS": lead_data.get("comment", ""),
                "SOURCE_ID": "TELEGRAM",
                "UF_CRM_DESIGNER_ID": lead_data.get("designer_bitrix_id"),
                "UF_CRM_PROJECT_FILE": lead_data.get("project_file_url", "")
            }
        }
        logger.debug(f"[create_lead] Параметры лида: {json.dumps(params, ensure_ascii=False)}")

        result = await self._make_request("crm.lead.add", params)

        if result.get("result"):
            lead_id = result["result"]
            logger.info(f"[create_lead] ✅ Лид создан с ID: {lead_id}")
            lead_result = {
                "id": lead_id,
                "number": str(lead_id),
                "status": "NEW"  # Default status for new leads
            }
            logger.info(f"[create_lead] Результат: {json.dumps(lead_result, ensure_ascii=False)}")
            return lead_result
        logger.error(f"[create_lead] ❌ Не удалось создать лид: {result}")
        return None

    async def get_lead(self, lead_id: int) -> Optional[Dict]:
        """Get lead information by ID"""
        logger.info(f"[get_lead] Получение информации о лиде ID: {lead_id}")
        params = {
            "id": lead_id
        }
        result = await self._make_request("crm.lead.get", params)

        if result.get("result"):
            logger.info(f"[get_lead] ✅ Информация о лиде получена")
            logger.debug(f"[get_lead] Данные лида: {json.dumps(result['result'], ensure_ascii=False)}")
            return result["result"]
        logger.error(f"[get_lead] ❌ Не удалось получить лид: {result}")
        return None

    async def get_deal(self, deal_id: int) -> Optional[Dict]:
        """Get deal information by ID"""
        logger.info(f"[get_deal] Получение информации о сделке ID: {deal_id}")
        params = {
            "id": deal_id
        }
        result = await self._make_request("crm.deal.get", params)

        if result.get("result"):
            logger.info(f"[get_deal] ✅ Информация о сделке получена")
            logger.debug(f"[get_deal] Данные сделки: {json.dumps(result['result'], ensure_ascii=False)}")
            return result["result"]
        logger.error(f"[get_deal] ❌ Не удалось получить сделку: {result}")
        return None

    async def get_deals_by_designer(self, designer_bitrix_id: int) -> List[Dict]:
        """Get all deals for a specific designer"""
        logger.info(f"[get_deals_by_designer] Получение сделок дизайнера ID: {designer_bitrix_id}")
        params = {
            "filter": {"UF_CRM_DESIGNER_ID": designer_bitrix_id},
            "select": ["ID", "TITLE", "STAGE_ID", "DATE_CREATE", "OPPORTUNITY", "CURRENCY_ID"]
        }
        result = await self._make_request("crm.deal.list", params)

        if result.get("result"):
            logger.info(f"[get_deals_by_designer] ✅ Найдено сделок: {len(result['result'])}")
            logger.debug(f"[get_deals_by_designer] Сделки: {json.dumps(result['result'], ensure_ascii=False)}")
            return result["result"]
        logger.warning(f"[get_deals_by_designer] ⚠️ Сделки не найдены")
        return []

    async def get_lead_status(self, lead_id: int) -> Optional[str]:
        """Get current lead status"""
        logger.info(f"[get_lead_status] Получение статуса лида ID: {lead_id}")
        lead = await self.get_lead(lead_id)
        if lead:
            status = lead.get("STATUS_ID")
            logger.info(f"[get_lead_status] ✅ Статус лида: {status}")
            return status
        logger.warning(f"[get_lead_status] ⚠️ Не удалось получить статус лида")
        return None

    async def get_deal_status(self, deal_id: int) -> Optional[str]:
        """Get current deal status"""
        logger.info(f"[get_deal_status] Получение статуса сделки ID: {deal_id}")
        deal = await self.get_deal(deal_id)
        if deal:
            status = deal.get("STAGE_ID")
            logger.info(f"[get_deal_status] ✅ Статус сделки: {status}")
            return status
        logger.warning(f"[get_deal_status] ⚠️ Не удалось получить статус сделки")
        return None

    async def get_stage_name(self, stage_id: str) -> str:
        """Get human-readable stage name for both leads and deals"""
        # This is a simplified mapping. In production, you should fetch this from Bitrix24

        # Lead statuses (STATUS_ID)
        lead_mapping = {
            "NEW": "Новый лид",
            "IN_PROCESS": "В обработке",
            "PROCESSED": "Обработан",
            "JUNK": "Некачественный лид",
            "CONVERTED": "Конвертирован в сделку"
        }

        # Deal stages (STAGE_ID)
        deal_mapping = {
            "NEW": "Новая заявка",
            "PREPARATION": "Подготовка",
            "PREPAYMENT_INVOICE": "Выставлен счет на предоплату",
            "EXECUTING": "Выполняется",
            "FINAL_INVOICE": "Выставлен финальный счет",
            "WON": "Успешно реализовано",
            "LOSE": "Закрыто и не реализовано"
        }

        # Try lead mapping first, then deal mapping
        return lead_mapping.get(stage_id) or deal_mapping.get(stage_id, stage_id)

