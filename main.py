import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

# ================= Configuration =================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VIKUNJA_API_URL = os.getenv("VIKUNJA_API_URL", "").rstrip("/")
VIKUNJA_API_TOKEN = os.getenv("VIKUNJA_API_TOKEN")

try:
    VIKUNJA_PROJECT_ID = int(os.getenv("VIKUNJA_PROJECT_ID", "0"))
    ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))
except ValueError:
    raise ValueError("VIKUNJA_PROJECT_ID and ALLOWED_CHAT_ID must be valid integers.")

TARGET_THREAD_ID_RAW = os.getenv("TARGET_THREAD_ID")
if TARGET_THREAD_ID_RAW and TARGET_THREAD_ID_RAW.lower() != "none":
    try:
        TARGET_THREAD_ID = int(TARGET_THREAD_ID_RAW)
    except ValueError:
        TARGET_THREAD_ID = 1
else:
    TARGET_THREAD_ID = None

if not all(
    [TELEGRAM_BOT_TOKEN, VIKUNJA_API_TOKEN, VIKUNJA_PROJECT_ID, ALLOWED_CHAT_ID]
):
    raise ValueError("Missing required environment variables.")

PREFIX_REGEX = re.compile(r"^(?:/[tт]|[tт])\s+", re.IGNORECASE)

# ================= HTTP Client =================


class VikunjaClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def create_task(self, project_id: int, title: str) -> bool:
        if not self.session:
            logging.error("VikunjaClient session is not initialized.")
            return False

        url = f"{self.base_url}/projects/{project_id}/tasks"
        payload = {"title": title}
        try:
            async with self.session.put(url, json=payload) as response:
                if response.status in [200, 201]:
                    return True

                response_text = await response.text()
                logging.error(f"Vikunja API error ({response.status}): {response_text}")
                return False
        except Exception as e:
            logging.error(f"Failed to connect to Vikunja API: {e}")
            return False


# ================= Custom Filters =================


class TaskMessageFilter(BaseFilter):
    """
    Validates chat ID, thread ID, and extracts task title using regex matching.
    """

    async def __call__(self, message: Message) -> bool | Dict[str, Any]:
        if message.chat.id != ALLOWED_CHAT_ID:
            return False

        if not message.text:
            return False

        current_thread = message.message_thread_id
        if TARGET_THREAD_ID is None or TARGET_THREAD_ID == 1:
            thread_matches = current_thread is None or current_thread == 1
        else:
            thread_matches = current_thread == TARGET_THREAD_ID

        if not thread_matches:
            return False

        match = PREFIX_REGEX.match(message.text)
        if not match:
            return False

        task_title = message.text[match.end() :].strip()
        if not task_title:
            return False

        return {"task_title": task_title}


# ================= Handlers =================

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
vikunja = VikunjaClient(VIKUNJA_API_URL, VIKUNJA_API_TOKEN)


@dp.message(TaskMessageFilter())
async def handle_task_message(message: Message, task_title: str):
    """
    Handles validated messages and forwards the extracted title to Vikunja.
    """
    success = await vikunja.create_task(VIKUNJA_PROJECT_ID, task_title)

    if success:
        try:
            await message.delete()
        except Exception as e:
            logging.error(f"Failed to delete message {message.message_id}: {e}")
    else:
        if not message.from_user:
            logging.error("Cannot send PM: message.from_user is None")
            return

        try:
            await bot.send_message(
                chat_id=message.from_user.id,
                text=(
                    f"❌ <b>Task creation error!</b>\n\n"
                    f"Failed to save the task to Vikunja.\n"
                    f"Task text: <code>{task_title}</code>"
                ),
            )
        except Exception as e:
            logging.error(
                f"Failed to send private message to user {message.from_user.id}: {e}"
            )


# ================= Lifecycle Management =================


@dp.startup()
async def on_startup():
    await vikunja.start()
    logging.info("Vikunja client session started.")


@dp.shutdown()
async def on_shutdown():
    await vikunja.close()
    logging.info("Vikunja client session closed.")


async def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "edited_message"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
