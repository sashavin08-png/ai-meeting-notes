"""
Turns a raw meeting transcript into a structured summary using Claude.
"""

import json
import os

from .json_utils import extract_json

SYSTEM_PROMPT = """You are an assistant that turns raw meeting transcripts into
clear, useful notes. The transcript may be messy (spoken language, filler
words, unclear audio in places) — do your best with what's there.

Respond with ONLY a JSON object, no markdown, no extra text:
{
  "summary": "<3-6 sentence summary of what was discussed, in plain language>",
  "action_items": ["<short, specific action item>", "..."]
}

If there are no clear action items, return an empty list for action_items.
Write the summary in the same language as the transcript."""


def summarize_transcript(transcript: str) -> dict:
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before running:\n"
            "  export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": transcript}],
    )

    raw_text = response.content[0].text.strip()
    return extract_json(raw_text)
