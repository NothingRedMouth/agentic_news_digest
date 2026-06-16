import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
from datetime import datetime
from os import getenv

logger = logging.getLogger(__name__)


class GoogleSheetsLogger:
    """Логирует действия агента в Google Sheets."""

    def __init__(self, credentials_file: str = None, sheet_name: str = "AgentLogs"):
        self.credentials_file = credentials_file or getenv("GOOGLE_SHEETS_CREDENTIALS")
        self.sheet_name = sheet_name or getenv("GOOGLE_SHEETS_NAME", "AgentLogs")
        self.client = None
        self.sheet = None
        if self.credentials_file:
            try:
                scope = [
                    "https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive",
                ]
                creds = ServiceAccountCredentials.from_json_keyfile_name(
                    self.credentials_file, scope
                )
                self.client = gspread.authorize(creds)
                try:
                    self.sheet = self.client.open(self.sheet_name).sheet1
                except gspread.SpreadsheetNotFound:
                    self.sheet = self.client.create(self.sheet_name).sheet1
                if not self.sheet.get_all_values():
                    self.sheet.append_row(
                        [
                            "Timestamp",
                            "Step",
                            "Channel",
                            "URL",
                            "Text Snippet",
                            "Relevant",
                            "Summary",
                            "Category",
                            "Significance",
                            "Status",
                        ]
                    )
            except Exception as e:
                logger.error(f"Не удалось инициализировать Google Sheets: {e}")
                self.sheet = None
        else:
            logger.warning(
                "GOOGLE_SHEETS_CREDENTIALS не задан, логирование в Google Sheets отключено"
            )

    def log(
        self,
        step: str,
        channel: str = "",
        url: str = "",
        text_snippet: str = "",
        relevant: bool = None,
        summary: str = "",
        category: str = "",
        significance: str = "",
        status: str = "OK",
    ):
        """Добавляет строку в лог."""
        if not self.sheet:
            return
        try:
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                step,
                channel,
                url,
                text_snippet[:100],
                str(relevant) if relevant is not None else "",
                summary[:100],
                category,
                significance,
                status,
            ]
            self.sheet.append_row(row)
        except Exception as e:
            logger.error(f"Ошибка записи в Google Sheets: {e}")


_global_logger = None


def get_global_logger():
    global _global_logger
    if _global_logger is None:
        _global_logger = GoogleSheetsLogger()
    return _global_logger
