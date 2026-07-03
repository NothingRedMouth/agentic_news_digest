import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
from datetime import datetime
from os import getenv

logger = logging.getLogger(__name__)

EXPECTED_HEADERS = ["Timestamp", "Step", "Status", "Message"]
LINKS_HEADERS = ["Timestamp", "Telegram посты", "Ссылки на источники"]


class GoogleSheetsLogger:
    def __init__(self, credentials_file: str = None, sheet_name: str = "AgentLogs"):
        self.credentials_file = credentials_file or getenv("GOOGLE_SHEETS_CREDENTIALS")
        self.sheet_name = sheet_name or getenv("GOOGLE_SHEETS_NAME", "AgentLogs")
        self.personal_email = getenv("PERSONAL_EMAIL", "your-email@gmail.com")
        self.client = None
        self.sheet = None
        self.links_sheet = None
        self.links_sheet_name = "LinksLog"
        self._initialized = False

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._initialized = True
        if not self.credentials_file:
            logger.warning(
                "GOOGLE_SHEETS_CREDENTIALS не задан, логирование в Google Sheets отключено"
            )
            return
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
                spreadsheet = self.client.create(self.sheet_name)
                if self.personal_email:
                    try:
                        spreadsheet.share(
                            self.personal_email, perm_type="user", role="writer"
                        )
                    except Exception as share_err:
                        logger.warning(f"Не удалось выдать права на файл: {share_err}")
                self.sheet = spreadsheet.sheet1

            existing = self.sheet.get_all_values()
            if not existing:
                self.sheet.insert_row(EXPECTED_HEADERS, index=1)
                logger.info("Заголовки созданы")
            else:
                first_row = [str(cell).strip() for cell in existing[0]]
                clean_expected = [str(h).strip() for h in EXPECTED_HEADERS]
                if first_row != clean_expected:
                    self.sheet.update(range_name="A1", values=[EXPECTED_HEADERS])
                    logger.info("Заголовки обновлены")

            # Инициализация второго листа
            self._ensure_links_sheet()

        except Exception as e:
            logger.error(f"Не удалось инициализировать Google Sheets: {e}")
            self.sheet = None

    def _ensure_links_sheet(self):
        """Создаёт второй лист, если его нет, и устанавливает заголовки."""
        if not self.client:
            return
        try:
            self.links_sheet = self.client.open(self.sheet_name).worksheet(
                self.links_sheet_name
            )
        except gspread.WorksheetNotFound:
            self.links_sheet = self.client.open(self.sheet_name).add_worksheet(
                title=self.links_sheet_name, rows=1000, cols=3
            )
            self.links_sheet.update("A1:C1", [LINKS_HEADERS])
            logger.info(f"Создан второй лист '{self.links_sheet_name}' с заголовками")

    def _ensure_row_for_insert(self, worksheet):
        """Проверяет, что в листе есть хотя бы 2 строки (заголовок + пустая), чтобы вставить на позицию 2."""
        rows = worksheet.get_all_values()
        if len(rows) < 2:
            # Добавляем пустую строку, чтобы увеличить размер
            worksheet.append_row([""] * len(rows[0]) if rows else [""] * 3)
            logger.debug("Добавлена пустая строка для возможности вставки")

    def log(self, step: str, status: str = "OK", message: str = ""):
        self._ensure_initialized()
        if not self.sheet:
            return
        try:
            self._ensure_row_for_insert(self.sheet)
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                step,
                status,
                message[:500].strip() if message else "",
            ]
            self.sheet.insert_row(row, index=2)
            logger.info(f"Logged: step={step}, status={status}, message={message[:50]}")
        except Exception as e:
            logger.error(f"Ошибка записи в Google Sheets: {e}", exc_info=True)

    def log_links(self, tg_links: list, source_links: list):
        """
        Логирует ссылки на второй лист.
        tg_links — список ссылок на посты в Telegram
        source_links — список ссылок на внешние источники
        """
        self._ensure_initialized()
        if not self.links_sheet:
            logger.error("Второй лист не доступен, пропускаем логирование ссылок")
            return

        try:
            self._ensure_row_for_insert(self.links_sheet)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tg_text = "\n".join(tg_links) if tg_links else ""
            src_text = "\n".join(source_links) if source_links else ""

            self.links_sheet.insert_row([timestamp, tg_text, src_text], index=2)
            logger.info(
                f"Записано {len(tg_links)} TG-ссылок и {len(source_links)} ссылок на источники"
            )
        except Exception as e:
            logger.error(f"Ошибка записи ссылок в Google Sheets: {e}", exc_info=True)


_global_logger = None


def get_global_logger():
    global _global_logger
    if _global_logger is None:
        _global_logger = GoogleSheetsLogger()
    return _global_logger
