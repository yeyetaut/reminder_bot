import os
import anthropic
import dotenv

dotenv.load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

try:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "Hi"}]
    )
    print("Success:", response.content[0].text)
except Exception as e:
    print("Error:", e)
