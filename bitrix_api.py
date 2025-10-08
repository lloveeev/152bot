import aiohttp
from typing import Optional, Dict, List
import config


class BitrixAPI:
    def __init__(self, webhook_url: str = config.BITRIX_WEBHOOK_URL):
        self.webhook_url = webhook_url.rstrip('/')

    async def _make_request(self, method: str, params: Dict = None) -> Dict:
        """Make request to Bitrix24 API"""
        url = f"{self.webhook_url}/{method}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params or {}) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        return {"error": f"HTTP {response.status}"}
        except Exception as e:
            return {"error": str(e)}

    async def find_contact_by_name(self, full_name: str) -> Optional[Dict]:
        """Find contact in Bitrix24 by full name"""
        params = {
            "filter": {"NAME": full_name},
            "select": ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "PHONE", "EMAIL", "COMPANY_TITLE"]
        }
        result = await self._make_request("crm.contact.list", params)

        if result.get("result") and len(result["result"]) > 0:
            return result["result"][0]
        return None

    async def find_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """Find contact in Bitrix24 by phone number"""
        params = {
            "filter": {"PHONE": phone},
            "select": ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "PHONE", "EMAIL", "COMPANY_TITLE"]
        }
        result = await self._make_request("crm.contact.list", params)

        if result.get("result") and len(result["result"]) > 0:
            return result["result"][0]
        return None

    async def create_contact(self, contact_data: Dict) -> Optional[int]:
        """Create new contact in Bitrix24"""
        params = {
            "fields": {
                "NAME": contact_data.get("first_name", ""),
                "LAST_NAME": contact_data.get("last_name", ""),
                "SECOND_NAME": contact_data.get("middle_name", ""),
                "PHONE": [{"VALUE": contact_data.get("phone"), "VALUE_TYPE": "WORK"}],
                "EMAIL": [{"VALUE": contact_data.get("email"), "VALUE_TYPE": "WORK"}],
                "COMPANY_TITLE": contact_data.get("company_name", ""),
                "UF_CRM_TELEGRAM_ID": contact_data.get("telegram_id")
            }
        }
        result = await self._make_request("crm.contact.add", params)

        if result.get("result"):
            return result["result"]
        return None

    async def update_contact(self, contact_id: int, contact_data: Dict) -> bool:
        """Update existing contact in Bitrix24"""
        params = {
            "id": contact_id,
            "fields": contact_data
        }
        result = await self._make_request("crm.contact.update", params)
        return result.get("result", False)

    async def create_deal(self, deal_data: Dict) -> Optional[Dict]:
        """Create new deal in Bitrix24"""
        # First, find or create client contact
        client_contact_id = None

        # Try to find existing client by phone
        client = await self.find_contact_by_phone(deal_data.get("client_phone"))
        if client:
            client_contact_id = client.get("ID")
        else:
            # Create new client contact
            name_parts = deal_data.get("client_full_name", "").split()
            client_data = {
                "last_name": name_parts[0] if len(name_parts) > 0 else "",
                "first_name": name_parts[1] if len(name_parts) > 1 else "",
                "middle_name": name_parts[2] if len(name_parts) > 2 else "",
                "phone": deal_data.get("client_phone")
            }
            client_contact_id = await self.create_contact(client_data)

        # Create deal
        params = {
            "fields": {
                "TITLE": f"Заявка от дизайнера: {deal_data.get('designer_name')}",
                "CONTACT_ID": client_contact_id,
                "COMMENTS": deal_data.get("comment", ""),
                "UF_CRM_DESIGNER_ID": deal_data.get("designer_bitrix_id"),
                "UF_CRM_PROJECT_FILE": deal_data.get("project_file_url", "")
            }
        }

        result = await self._make_request("crm.deal.add", params)

        if result.get("result"):
            deal_id = result["result"]
            # Get deal details to retrieve deal number
            deal_info = await self.get_deal(deal_id)
            return {
                "id": deal_id,
                "number": deal_info.get("ID", str(deal_id)),
                "status": deal_info.get("STAGE_ID", "NEW")
            }
        return None

    async def get_deal(self, deal_id: int) -> Optional[Dict]:
        """Get deal information by ID"""
        params = {
            "id": deal_id
        }
        result = await self._make_request("crm.deal.get", params)

        if result.get("result"):
            return result["result"]
        return None

    async def get_deals_by_designer(self, designer_bitrix_id: int) -> List[Dict]:
        """Get all deals for a specific designer"""
        params = {
            "filter": {"UF_CRM_DESIGNER_ID": designer_bitrix_id},
            "select": ["ID", "TITLE", "STAGE_ID", "DATE_CREATE", "OPPORTUNITY", "CURRENCY_ID"]
        }
        result = await self._make_request("crm.deal.list", params)

        if result.get("result"):
            return result["result"]
        return []

    async def get_deal_status(self, deal_id: int) -> Optional[str]:
        """Get current deal status"""
        deal = await self.get_deal(deal_id)
        if deal:
            return deal.get("STAGE_ID")
        return None

    async def get_stage_name(self, stage_id: str) -> str:
        """Get human-readable stage name"""
        # This is a simplified mapping. In production, you should fetch this from Bitrix24
        stage_mapping = {
            "NEW": "Новая заявка",
            "PREPARATION": "Подготовка",
            "PREPAYMENT_INVOICE": "Выставлен счет на предоплату",
            "EXECUTING": "Выполняется",
            "FINAL_INVOICE": "Выставлен финальный счет",
            "WON": "Успешно реализовано",
            "LOSE": "Закрыто и не реализовано"
        }
        return stage_mapping.get(stage_id, stage_id)

