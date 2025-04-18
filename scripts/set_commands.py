import requests
import os

# Load the bot token from the environment variable
bot_token = os.getenv("BOT_TOKEN")

# Define the API URL
url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"

# Define the payload
payload = {
    "commands": [
        {
        "command": "/request",
        "description": "Request a message"
        },
    ],
    # "scope": {"type": "default"}
    "scope": {"type": "all_group_chats"}
}

# Send the POST request
response = requests.post(url, json=payload)

# Print the response
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")