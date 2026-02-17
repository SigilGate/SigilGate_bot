# SigilGate Bot

Telegram-бот для управления сетью **Sigil Gate**.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot
```

## Переменные окружения

| Переменная | Обязательная | Назначение |
|---|---|---|
| `SIGILGATE_BOT_TOKEN` | да | Токен Telegram-бота |
| `SIGIL_STORE_PATH` | нет | Путь к клону registry |
| `SIGILGATE_ADMIN_IDS` | нет | Telegram ID администраторов (через запятую) |

## Лицензия

Apache License 2.0
