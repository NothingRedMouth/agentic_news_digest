# NewsDigest AI Agent

### Система автоматического сбора новостей из Telegram-каналов, генерации дайджеста через LLM и публикации в Telegram, Telegra.ph и email-рассылке (Unisender).
#### Быстрый запуск
1. Подготовка окружения

    Установите Python 3.12+ и Docker Compose.

    Скопируйте .env.example → .env и заполните обязательные переменные (Telegram API, Unisender, Google Sheets, LLM).


2. Получение ключей
```
    Telegram: зарегистрируйте приложение на my.telegram.org, получите api_id и api_hash. Для обхода блокировок добавьте в /etc/hosts:

    149.154.167.220 my.telegram.org

    Unisender: получите API-ключ, укажите ID списка рассылки.

    Google Sheets: создайте сервисный аккаунт, включите Google Sheets API и Drive API, скачайте JSON-ключ в credentials/service_account.json.
```

3. Создание сессии Telethon
Установите python-dotenv и другие зависимости для работы с telegram(pip подскажет какие)
Выполните скрипт для авторизации userbot (потребуется номер телефона и код):
``` dotenv run python create_session.py ```


4. Настройка параметров

  - Список каналов, глубина парсинга, лимиты – в configs/digest_config.py
  - Промпты для LLM – в configs/prompts.yaml.


5. Запуск через Docker Compose

   Сборка может требовать VPN для корректной работы Telethon (этап COPY . .).

    ``` sudo docker compose up --build ```


6. Проверка

    Бот отвечает на команды в Telegram (только для пользователей из ALLOWED_USERS).

    Команда /digest_now ставит задачу в RabbitMQ, в логах виден прогресс.

    Результат публикуется в Telegram-канал, на Telegra.ph и отправляется по email (если настроено).

## Основные команды бота

    /digest_now – ручной запуск генерации.

    /status – статус последнего запуска.

    /subscribe_email <email> – подписка на рассылку.

    /unsubscribe_email <email> – отписка.

    /get_emails – список подписчиков.

    /check_email <email> – проверить статус email.

## Конфигурация (ключевые переменные .env)

    TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, ALLOWED_USERS

    TELEGRAM_API_ID, TELEGRAM_API_HASH

    UNISENDER_API_KEY, UNISENDER_SENDER_EMAIL, UNISENDER_SENDER_NAME, UNISENDER_LIST_ID

    GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEETS_NAME

    LLM_PREFERENCE (external / external_only / local)

    EXTERNAL_API_KEY, EXTERNAL_MODEL, EXTERNAL_API_BASE_URL (для внешнего LLM)

    LOCAL_LLM_SERVER_URL, LOCAL_LLM_TIMEOUT и др. (для локального llama.cpp)

    DIGEST_INTERVAL_DAYS – авто-запуск через N дней, 0 – только вручную.

## Структура

    agent/ – LLM и парсинг контента

    bot/ – Telegram бот

    rabbitmq/ – очереди задач

    scheduler/ – планировщик

    utils/ – логирование и Unisender

    configs/ – настройки каналов и промптов

    credentials/ – JSON-ключи Google

    models/ – локальные LLM-модели

## Схематичное представление основных компонентов:

<img width="4179" height="5245" alt="flowchart" src="https://github.com/user-attachments/assets/256a141b-e275-47a3-9b30-8fd7f404a9e9" />


## Запуск без Docker (для разработки)

### Установите зависимости:

``` pip install -r requirements.txt ```

### Запустите RabbitMQ и локальный LLM (если нужен) отдельно, затем выполните:

``` python main.py ```

## Примечания
  Для локальной LLM в Docker используется образ llama.cpp с GPU (CUDA). Модель (например, Gemma-4-31B) помещается в models/.

  Все сервисы используют network_mode: host для упрощения сетевых настроек и корректной работы c VPN.

  Логирование в Google Sheets опционально – если не настроено, система работает с предупреждениями.

  Файл bot_status.json обновляется после каждого запуска и используется командой /status.
