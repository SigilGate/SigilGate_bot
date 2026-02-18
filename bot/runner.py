import asyncio
import logging
import os
from typing import Callable, Coroutine, Any

logger = logging.getLogger(__name__)

# Тип функции отправки сообщения в чат (например, message.answer или bot.send_message)
SendFunc = Callable[[str], Coroutine[Any, Any, Any]]


async def run_script(
    cmd: list[str],
    send: SendFunc | None = None,
    verbose: bool = False,
) -> tuple[int, str, str]:
    """
    Асинхронно запускает скрипт и возвращает (returncode, stdout, stderr).

    Если verbose=True и передана функция send — отправляет сырой вывод
    скрипта в чат отдельным сообщением перед тем, как управление
    вернётся в хендлер.
    """
    env = os.environ.copy()

    logger.debug("Running: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    stdout = stdout_bytes.decode().strip()
    stderr = stderr_bytes.decode().strip()
    returncode = proc.returncode

    logger.debug("Exit code: %d", returncode)
    if stdout:
        logger.debug("stdout: %s", stdout)
    if stderr:
        logger.debug("stderr: %s", stderr)

    if verbose and send is not None:
        combined = "\n".join(filter(None, [stdout, stderr]))
        if combined:
            await send(f"<pre>{combined}</pre>")

    return returncode, stdout, stderr
