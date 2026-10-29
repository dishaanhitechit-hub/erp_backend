import os
import anthropic

_client = None

def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _client


def ask_claude(system_prompt: str, user_message: str, max_tokens: int = 1024) -> str:
    client = get_client()
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return msg.content[0].text
