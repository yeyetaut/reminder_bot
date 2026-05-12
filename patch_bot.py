import re

with open('bot/telegram_bot.py', 'r') as f:
    content = f.read()

# Add idempotency check
content = content.replace(
    "task_repo.mark_done(task_id)",
    "if task.status == TaskStatus.done:\n            return\n\n        task_repo.mark_done(task_id)"
)

# Update Markdown escaping
content = content.replace(
    'safe_title = task.title.replace("_", "\\\\_").replace("*", "\\\\*").replace("`", "\\\\`")',
    'safe_title = task.title.replace("_", "\\\\_").replace("*", "\\\\*").replace("`", "\\\\`").replace("[", "\\\\[").replace("]", "\\\\]")'
)

with open('bot/telegram_bot.py', 'w') as f:
    f.write(content)
print("patched")
