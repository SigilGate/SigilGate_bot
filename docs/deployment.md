# Технические требования и деплой

## Стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.11+ |
| Telegram-фреймворк | aiogram 3.x |
| Управление состоянием (FSM) | aiogram FSM + MemoryStorage |
| Модель выполнения | asyncio (асинхронная) |

### Требование асинхронности

Бот **обязан** быть асинхронным. Причины:
- Каждый вызов скрипта — это системный процесс с файловыми и сетевыми операциями
- Сетевые операции включают SSH-подключения к Entry-нодам (изменение конфига Xray, перезапуск сервиса)
- Несколько пользователей могут взаимодействовать с ботом одновременно
- Синхронная модель заблокировала бы обработку входящих сообщений на время выполнения скрипта

Скрипты запускаются через `asyncio.create_subprocess_exec()` в `bot/runner.py`,
что позволяет боту продолжать обрабатывать другие события во время выполнения операций.

---

## Среда выполнения

Бот развёрнут на **Core-ноде** и работает как systemd-сервис от имени сервисного пользователя `sigil`.

Все операции с Entry-нодами выполняются от имени того же пользователя `sigil` по SSH с использованием ключевой аутентификации. Операции, требующие sudo на Entry-ноде (перезапуск Xray, изменение системных конфигов), выполняются через `sudo -S` с передачей пароля из переменной окружения.

### Расположение файлов на Core-ноде

| Путь | Содержимое |
|---|---|
| `~/SigilGate/SigilGate_bot/` | Код бота (клон репозитория) |
| `~/SigilGate/SigilGate_bot/.venv/` | Виртуальное окружение Python |
| `~/SigilGate/registry/` | Локальная копия реестра (`SIGIL_STORE_PATH`) |
| `~/SigilGate/scripts/` | Скрипты автоматизации (`SIGIL_SCRIPTS_PATH`) |
| `~/.config/sigilgate-bot.env` | Переменные окружения бота (загружается systemd через `EnvironmentFile`) |
| `~/.ssh/id_rsa` | SSH-ключ для подключения к Entry-нодам |

---

## Переменные окружения

Переменные окружения задаются в конфигурационном файле на Core-ноде
(`~/.config/sigilgate-bot/` или `.env` в директории бота) и не хранятся в репозитории.

| Переменная | Обязательная | Описание |
|---|---|---|
| `SIGILGATE_BOT_TOKEN` | да | Токен Telegram-бота (от BotFather) |
| `SIGIL_STORE_PATH` | да | Абсолютный путь к реестру на Core-ноде |
| `SIGIL_SCRIPTS_PATH` | да | Абсолютный путь к директории скриптов |
| `SIGILGATE_ADMIN_IDS` | нет | Telegram ID администраторов через запятую |
| `SIGILGATE_VERBOSE` | нет | Режим отладки: `1`/`true`/`yes` |
| `SIGIL_SSH_KEY` | да* | Путь к SSH-ключу для Entry-нод |
| `SIGIL_SSH_USER` | да* | Пользователь SSH на Entry-нодах (`sigil`) |
| `SIGIL_SSH_PASSWORD` | да* | Пароль sudo на Entry-нодах |

\* Переменные `SIGIL_SSH_*` используются скриптами напрямую, бот передаёт их через унаследованное окружение (`os.environ.copy()` в runner.py).

---

## Деплой

### Автоматический (GitHub Actions)

Деплой запускается автоматически при push в ветку `main`,
если изменились файлы в `bot/**` или `requirements.txt`.

**Workflow:** `.github/workflows/deploy.yml`

**Шаги:**
1. GitHub Actions подключается к Core-ноде по SSH (секреты: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`)
2. `git pull origin main` — получает последние изменения
3. `pip install -r requirements.txt` — обновляет зависимости в виртуальном окружении
4. `sudo systemctl restart sigilgate-bot` — перезапускает сервис

**Секреты GitHub** (настраиваются в репозитории):

| Секрет | Описание |
|---|---|
| `DEPLOY_HOST` | IP Core-ноды |
| `DEPLOY_USER` | SSH-пользователь (`sigil`) |
| `DEPLOY_SSH_KEY` | Приватный SSH-ключ |
| `DEPLOY_SUDO_PASSWORD` | Пароль sudo для перезапуска сервиса |

### Systemd unit-файл

`/etc/systemd/system/sigilgate-bot.service`:

```ini
[Unit]
Description=Sigil Gate Telegram Bot
After=network.target

[Service]
Type=simple
User=sigil
Group=sigil
WorkingDirectory=/home/sigil/SigilGate/SigilGate_bot
EnvironmentFile=/home/sigil/.config/sigilgate-bot.env
ExecStart=/home/sigil/SigilGate/SigilGate_bot/.venv/bin/python -m bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Ручной перезапуск

```bash
ssh sigil@<core-ip>
sudo systemctl restart sigilgate-bot
sudo systemctl status sigilgate-bot
```

### Просмотр логов

```bash
sudo journalctl -u sigilgate-bot -f
```

---

## Первоначальная установка на Core-ноде

```bash
# Клонировать репозиторий
git clone git@github.com:SigilGate/SigilGate_bot.git ~/SigilGate/SigilGate_bot

# Создать виртуальное окружение
cd ~/SigilGate/SigilGate_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Создать конфиг (на основе шаблона)
cp .env.example ~/.config/sigilgate-bot.env
# Заполнить значения переменных

# Создать systemd unit-файл (см. содержимое выше)
sudo nano /etc/systemd/system/sigilgate-bot.service
sudo systemctl daemon-reload
sudo systemctl enable sigilgate-bot
sudo systemctl start sigilgate-bot
```
