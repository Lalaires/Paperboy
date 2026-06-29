import os
import httpx
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAX_CHARS = 1900  # Leave buffer below Discord's 2000 limit

def split_message(text: str) -> list[str]:
    """Split briefing into chunks that fit Discord's limit."""
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_CHARS:
            chunks.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks

def deliver(briefing: str):
    """Send briefing to Discord webhook in chunks."""
    if not DISCORD_WEBHOOK_URL:
        print("No DISCORD_WEBHOOK_URL set — printing to terminal only.")
        print(briefing)
        return

    chunks = split_message(briefing)
    total = len(chunks)

    for i, chunk in enumerate(chunks, 1):
        label = f"-# Part {i}/{total}\n" if total > 1 else ""
        payload = {"content": label + chunk}
        response = httpx.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code not in (200, 204):
            print(f"Discord error on chunk {i}: {response.status_code} {response.text}")
        else:
            print(f"Delivered chunk {i}/{total}")

if __name__ == "__main__":
    # Test with a sample message
    deliver("✅ deliver.py is working correctly.")
