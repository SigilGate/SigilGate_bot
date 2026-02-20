# SigilGate Bot

Telegram-бот для управления сетью **Sigil Gate**.
Предоставляет интерфейс для пользователей и администраторов поверх автоматизированных скриптов.

## Документация

- [Технические требования и деплой](docs/deployment.md) — стек, среда выполнения, деплой, переменные окружения
- [Архитектура и текущее состояние](docs/architecture.md) — структура проекта, реализованный функционал, пробелы
- [Политика ролей и статусов](docs/policy.md) — роли, статусы, каскады, матрица доступа, workflow
- [Справочник скриптов](docs/scripts.md) — все скрипты исполнительного слоя с параметрами

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить переменные
python -m bot
```

## Переменные окружения

| Переменная | Обязательная | Назначение |
|---|---|---|
| `SIGILGATE_BOT_TOKEN` | да | Токен Telegram-бота |
| `SIGIL_STORE_PATH` | да | Путь к локальной копии реестра |
| `SIGIL_SCRIPTS_PATH` | да | Путь к директории скриптов |
| `SIGILGATE_ADMIN_IDS` | нет | Telegram ID администраторов (через запятую) |
| `SIGILGATE_VERBOSE` | нет | Вывод скриптов в чат: `1`/`true`/`yes` |

## Деплой

Push в `main` → GitHub Actions → SSH → `systemctl restart sigilgate-bot`

## Лицензия

Apache License 2.0
