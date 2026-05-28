# tg-vikunja

A lightweight Telegram bot that forwards tasks to a specific Vikunja project. It monitors a specific chat (and optionally a specific forum thread), catches messages with defined prefixes (`t `, `т `, `/t `, `/т `), creates a task inside Vikunja via its REST API, and cleans up the chat by deleting the trigger message.
