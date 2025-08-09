import requests
import os

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"

payload = {
    "commands": [
        {
            "command": "/start",
            "description": "Start the bot."
        },
        {
            "command": "/request",
            "description": "Request a generated message."
        },
        {
            "command": "/settings",
            "description": "View group settings."
        },
        {
            "command": "/set",
            "description": "Set a group setting (admins only)."
        },
        {
            "command": "/feed",
            "description": "Feed a text file to the bot."
        }
    ],
    # "scope": {"type": "default"}
    "scope": {"type": "all_group_chats"}
}

response = requests.post(url, json=payload)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")
