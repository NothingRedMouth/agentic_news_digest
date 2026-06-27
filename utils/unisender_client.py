import asyncio
import aiohttp
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class UnisenderClient:
    def __init__(self, api_key: str, sender_email: str, sender_name: str, list_id: int):
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.list_id = list_id
        self.base_url = "https://api.unisender.com/ru/api"

    async def _make_request(self, method: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Базовый метод для отправки POST-запросов к API Unisender."""
        url = f"{self.base_url}/{method}"
        data.update({"format": "json", "api_key": self.api_key})
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, data=data) as response:
                    if response.status != 200:
                        return {"success": False, "error": f"HTTP status {response.status}"}
                    res_json = await response.json()
                    if "error" in res_json:
                        return {"success": False, "error": res_json["error"]}
                    return {"success": True, "result": res_json.get("result")}
            except Exception as e:
                logger.error(f"Unisender API Exception during '{method}': {e}")
                return {"success": False, "error": str(e)}

    async def subscribe(self, email: str) -> Dict[str, Any]:
        """Подписка email и добавление в список (метод subscribe)."""
        data = {
            "list_ids": str(self.list_id),
            "fields[email]": email,
            "double_optin": "4",
            "overwrite": "1"
        }
        return await self._make_request("subscribe", data)

    async def unsubscribe(self, email: str) -> Dict[str, Any]:
        """Отписка email (метод unsubscribe)."""
        data = {
            "contact": email,
            "contact_type": "email",
            "list_ids": str(self.list_id)
        }
        return await self._make_request("unsubscribe", data)
    
    async def check_email_in_unisender_list(self, email: str):
        """
        Проверка конкретного email, находится ли он в списке
        """
        data = {
            "email": email,
            "list_ids": str(self.list_id),
            "condition": "and"
        }
        res = await self._make_request("isContactInLists", data)
        if not res["success"]:
            logger.error(f"Не удалось проверить контакт: {res.get('error')}")
            return "error"
        
        if res["result"]:
            return "True"
        return "False"
    
    async def send_mass_digest(self, subject: str, html_body: str) -> Dict[str, Any]:
        """
        Полный цикл массовой рассылки дайджеста по списку (list_id).
        Использует связку методов createEmailMessage + createCampaign.
        """
        message_data = {
            "sender_name": self.sender_name,
            "sender_email": self.sender_email,
            "subject": subject,
            "body": html_body,
            "list_id": str(self.list_id)
        }
        
        logger.info("Создание email-сообщения в Unisender...")
        msg_res = await self._make_request("createEmailMessage", message_data)
        
        if not msg_res["success"]:
            return {"success": False, "error": f"Ошибка на шаге createEmailMessage: {msg_res.get('error')}"}
        
        message_id = msg_res["result"]["message_id"]
        logger.info(f"Сообщение создано успешно, message_id: {message_id}")

        campaign_data = {
            "message_id": str(message_id),
            "track_read": "1",
            "track_links": "1"
        }
        
        logger.info(f"Запуск кампании для message_id {message_id}...")
        campaign_res = await self._make_request("createCampaign", campaign_data)
        
        if not campaign_res["success"]:
            return {"success": False, "error": f"Ошибка на шаге createCampaign: {campaign_res.get('error')}"}
            
        return {
            "success": True, 
            "campaign_id": campaign_res["result"]["campaign_id"], 
            "status": campaign_res["result"]["status"]
        }

    async def get_registered_emails(self) -> List[str]:
        """
        Получение списка ВСЕХ активных email-адресов из конкретного списка рассылки.
        Использует метод API exportContacts.
        """
        data = {
            "list_id": str(self.list_id),
            "field_names[0]": "email",
            "field_names[1]": "email_status"
        }
        
        logger.info("Запуск фоновой задачи экспорта контактов в Unisender...")
        res = await self._make_request("async/exportContacts", data)
        
        if not res["success"]:
            logger.error(f"Не удалось запустить экспорт контактов: {res.get('error')}")
            return []
            
        task_uuid = res["result"].get("task_uuid")
        if not task_uuid:
            logger.error("Unisender не вернул task_uuid для задачи экспорта")
            return []
            
        logger.info(f"Задача экспорта успешно создана. Task UUID: {task_uuid}. Начинаем опрос статуса...")
        
        file_url = None
        max_attempts = 15 
        
        async with aiohttp.ClientSession() as session:
            for attempt in range(max_attempts):
                await asyncio.sleep(2)
                
                status_data = {
                    "format": "json",
                    "api_key": self.api_key,
                    "task_uuid": task_uuid
                }
                status_url = f"{self.base_url}/async/getTaskResult"
                
                try:
                    async with session.post(status_url, data=status_data) as response:
                        if response.status != 200:
                            continue
                        res_json = await response.json()
                        task_result = res_json.get("result", {})
                        status = task_result.get("status")
                        
                        if status == "completed":
                            file_url = task_result.get("file_to_download")
                            break
                        elif status in ["new", "processing"]:
                            logger.info(f"Файл подготавливается Unisender (попытка {attempt + 1})...")
                            continue
                        else:
                            logger.error(f"Ошибка выполнения задачи экспорта. Статус: {status}")
                            return []
                except Exception as e:
                    logger.error(f"Исключение при проверке статуса задачи {task_uuid}: {e}")
                    return []
                    
            if not file_url:
                logger.error("Превышено время ожидания готовности файла экспорта.")
                return []
                
            logger.info("Файл готов. Начинаем скачивание и парсинг данных...")
            try:
                async with session.get(file_url) as response:
                    if response.status != 200:
                        logger.error(f"Не удалось скачать файл экспорта: HTTP {response.status}")
                        return []
                        
                    file_text = await response.text(encoding="utf-8")
                    lines = file_text.strip().splitlines()
                    
                    active_emails = []
                    if not lines or len(lines) < 2:
                        return []
                        
                    header = lines[0]
                    delimiter = ";" if ";" in header else ("," if "," in header else "\t")
                    
                    for line in lines[1:]:
                        row = line.replace('"', '').split(delimiter)
                        if len(row) >= 2:
                            email = row[0].strip()
                            status = row[1].strip()
                            if status == "active":
                                active_emails.append(email)
                                
                    return active_emails
            except Exception as e:
                logger.error(f"Ошибка при обработке файла результатов Unisender: {e}")
                return []
