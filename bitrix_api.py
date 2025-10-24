import aiohttp
from typing import Optional, Dict, List
import config
import logging
import json
import re
import base64

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


def _normalize_stage_id(stage_id: str) -> str:
    """Return stage ID without pipeline prefixes (e.g. C1:, L1:) and in upper-case."""
    if not stage_id:
        return stage_id
    normalized = stage_id
    if ':' in normalized:
        normalized = normalized.split(':', 1)[1]
    return normalized.upper()


class BitrixAPI:
    def __init__(self, webhook_url: str = config.BITRIX_WEBHOOK_URL):
        self.webhook_url = webhook_url.rstrip('/')
        logger.info(f"[BitrixAPI] Инициализация с webhook URL: {self.webhook_url[:50]}...")
        self._lead_status_cache: Optional[Dict[str, str]] = None

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

    async def get_sources(self) -> List[Dict[str, str]]:
        """Return available lead sources from Bitrix24."""
        logger.info("[get_sources] Запрашиваю список источников обращения")
        params = {
            "filter": {"ENTITY_ID": "SOURCE"},
            "select": ["STATUS_ID", "NAME", "SORT", "ID", "XML_ID"]
        }
        result = await self._make_request("crm.status.list", params)

        if not result.get("result"):
            logger.error(f"[get_sources] ❌ Не удалось получить источники: {result}")
            return []

        sources: List[Dict[str, str]] = []
        for raw in result["result"]:
            status_id = (raw.get("STATUS_ID") or "").strip()
            xml_id = (raw.get("XML_ID") or "").strip()
            bitrix_id = str(raw.get("ID") or "").strip()

            if not status_id and not xml_id and not bitrix_id:
                continue

            try:
                sort_value = int(raw.get("SORT", len(sources)))
            except (TypeError, ValueError):
                sort_value = len(sources)
            sources.append({
                "status_id": status_id,
                "xml_id": xml_id,
                "id": bitrix_id,
                "name": (raw.get("NAME") or status_id or xml_id or bitrix_id).strip(),
                "sort": sort_value
            })

        sources.sort(key=lambda item: item["sort"])
        logger.info(f"[get_sources] ✅ Получено источников: {len(sources)}")
        logger.debug(f"[get_sources] Источники: {json.dumps(sources, ensure_ascii=False)}")
        return sources


    async def get_lead_status_map(self, force_refresh: bool = False) -> Dict[str, str]:
        """Return mapping of lead status codes to human-readable names."""
        if self._lead_status_cache is not None and not force_refresh:
            return self._lead_status_cache

        logger.info("[get_lead_status_map] Fetching lead statuses from Bitrix24")
        params = {
            "filter": {"ENTITY_ID": "STATUS"},
            "select": ["STATUS_ID", "NAME", "ID", "SORT"]
        }
        result = await self._make_request("crm.status.list", params)

        status_map: Dict[str, str] = {}
        if result.get("result"):
            for raw in result["result"]:
                status_id = (raw.get("STATUS_ID") or "").strip()
                if not status_id:
                    continue

                name = (raw.get("NAME") or status_id).strip() or status_id
                normalized = _normalize_stage_id(status_id) or status_id

                keys = {
                    status_id,
                    status_id.upper(),
                    normalized,
                    normalized.upper(),
                }

                raw_id = raw.get("ID")
                if raw_id not in (None, "", "null"):
                    raw_id_str = str(raw_id).strip()
                    keys.add(raw_id_str)
                    keys.add(raw_id_str.upper())

                sort_value = raw.get("SORT")
                if sort_value not in (None, "", "null"):
                    sort_str = str(sort_value).strip()
                    keys.add(sort_str)
                    keys.add(sort_str.upper())

                for key in keys:
                    if key:
                        status_map[key] = name

        logger.info(f"[get_lead_status_map] Retrieved statuses: {len(status_map)}")
        logger.debug(f"[get_lead_status_map] Map data: {json.dumps(status_map, ensure_ascii=False)}")
        self._lead_status_cache = status_map
        return status_map
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
        """Create new lead in Bitrix24."""
        logger.info("[create_lead] Creating lead in Bitrix24")
        project_file_bytes = lead_data.get("project_file_bytes")
        payload_for_log = dict(lead_data)
        if "project_file_bytes" in payload_for_log:
            payload_for_log["project_file_bytes"] = f"<bytes:{len(project_file_bytes or b'')}>"
        logger.debug(f"[create_lead] Payload: {json.dumps(payload_for_log, ensure_ascii=False)}")

        name_parts = (lead_data.get("client_full_name") or "").split()
        owner_role = lead_data.get("owner_role") or lead_data.get("designer_role_key") or "designer"
        role_title = lead_data.get("designer_role_title") or config.USER_ROLES.get(owner_role, owner_role.title())
        owner_name = lead_data.get("designer_name") or lead_data.get("owner_name") or "Unknown"
        crm_agent_name = lead_data.get("crm_agent_name")
        project_file_name = lead_data.get("project_file_name")
        normalized_phone = normalize_phone(lead_data.get("client_phone"))
        source_id = lead_data.get("source_id") or config.BITRIX_LEAD_SOURCE_ID
        source_description = lead_data.get("source_description") or lead_data.get("source_name") or config.BITRIX_SOURCE_DESCRIPTION
        status_id = lead_data.get("status_id") or lead_data.get("stage_id") or "NEW"

        fields = {
            "TITLE": f"Lead from {role_title}: {owner_name}",
            "NAME": name_parts[1] if len(name_parts) > 1 else "",
            "LAST_NAME": name_parts[0] if name_parts else "",
            "SECOND_NAME": name_parts[2] if len(name_parts) > 2 else "",
            "POST": role_title,
            "COMMENTS": lead_data.get("comment", ""),
            "STATUS_ID": status_id,
            "ASSIGNED_BY_ID": config.BITRIX_ASSIGNED_BY
        }

        if source_id:
            fields["SOURCE_ID"] = source_id

        if source_description:
            fields["SOURCE_DESCRIPTION"] = source_description

        if normalized_phone:
            fields["PHONE"] = [{"VALUE": normalized_phone, "VALUE_TYPE": "WORK"}]

        if lead_data.get("designer_bitrix_id"):
            fields["UF_CRM_DESIGNER_ID"] = lead_data.get("designer_bitrix_id")

        file_field_code = config.BITRIX_PROJECT_FILE_FIELD
        name_field_code = config.BITRIX_PROJECT_FILE_NAME_FIELD

        if project_file_bytes and file_field_code:
            file_name = project_file_name or "document.pdf"
            encoded_file = base64.b64encode(project_file_bytes).decode()
            fields[file_field_code] = {"fileData": [file_name, encoded_file]}

        if project_file_name and name_field_code:
            fields[name_field_code] = project_file_name

        if crm_agent_name:
            fields[config.BITRIX_CRM_AGENT_FIELD] = crm_agent_name

        if config.BITRIX_RESPONSIBLE_ID:
            fields["ASSIGNED_BY_ID"] = config.BITRIX_RESPONSIBLE_ID

        params = {"fields": fields}
        logger.debug(f"[create_lead] Request params: {json.dumps(params, ensure_ascii=False)}")

        result = await self._make_request("crm.lead.add", params)

        if result.get("result"):
            lead_id = result["result"]
            logger.info(f"[create_lead] Lead created with ID: {lead_id}")
            lead_result = {
                "id": lead_id,
                "number": str(lead_id),
                "status": status_id,
                "entity_type": "lead"
            }
            logger.debug(f"[create_lead] Result: {json.dumps(lead_result, ensure_ascii=False)}")
            return lead_result

        logger.error(f"[create_lead] Failed to create lead: {result}")
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

    async def get_stage_name(self, stage_id: str, role: str = 'designer') -> str:
        """Get human-readable stage name using configured mappings."""
        if not stage_id:
            return stage_id

        normalized = _normalize_stage_id(stage_id)

        try:
            stage_map = await self.get_lead_status_map()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[get_stage_name] Не удалось получить стадии из Bitrix: {exc}")
            stage_map = {}

        for key in (
            stage_id,
            stage_id.upper(),
            normalized,
            normalized.upper(),
        ):
            if key and key in stage_map:
                return stage_map[key]

        normalized = _normalize_stage_id(stage_id)
        mappings = []

        if role == 'partner':
            mappings.append(config.PARTNER_FUNNEL_STAGES)
            mappings.append(config.DESIGNER_FUNNEL_STAGES)
        else:
            mappings.append(config.DESIGNER_FUNNEL_STAGES)
            mappings.append(config.PARTNER_FUNNEL_STAGES)

        for mapping in mappings:
            if stage_id in mapping:
                return mapping[stage_id]
            if normalized in mapping:
                return mapping[normalized]

        return stage_id

