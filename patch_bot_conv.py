import re

with open("bot/conversations.py", "r") as f:
    content = f.read()

# Add adjust_hours to AWAITING_CONFIRMATION
content = content.replace(
'''            AWAITING_CONFIRMATION: [
                CommandHandler("confirm_estimate", confirm_estimate),
                CommandHandler("skip_estimate", skip_estimate),
            ]''',
'''            AWAITING_CONFIRMATION: [
                CommandHandler("confirm_estimate", confirm_estimate),
                CommandHandler("adjust_hours", adjust_hours),
                CommandHandler("skip_estimate", skip_estimate),
            ]'''
)

with open("bot/conversations.py", "w") as f:
    f.write(content)
