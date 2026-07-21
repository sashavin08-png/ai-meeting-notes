"""
Audio transcription.

Two backends:
  - Groq's hosted Whisper API — the default for production. No heavy ML
    dependencies (torch, etc.) need to run on our own server; Groq runs
    the model on their infrastructure. Fast, and free tier is generous.
  - Local Whisper (openai-whisper) — used automatically as a fallback
    when GROQ_API_KEY isn't set, e.g. for local development without
    needing a Groq account at all.

This split exists because self-hosting Whisper needs real RAM (1-2GB+)
that a free-tier cloud instance typically doesn't have — Groq avoids
that entirely for the deployed version of this app.
"""

import logging
import os

logger = logging.getLogger("transcriber")

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        import whisper

        logger.info("Loading local Whisper model (first call only)...")
        _local_model = whisper.load_model("base")
    return _local_model


def _transcribe_with_groq(file_path: str) -> dict:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(file_path), f.read()),
            model="whisper-large-v3-turbo",
            response_format="verbose_json",
        )
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result.segments
    ]
    return {"text": result.text.strip(), "segments": segments}


def _transcribe_with_local_whisper(file_path: str) -> dict:
    model = _get_local_model()
    result = model.transcribe(file_path)
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return {"text": result["text"].strip(), "segments": segments}


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file to plain text. Raises on failure."""
    return transcribe_with_segments(file_path)["text"]


def transcribe_with_segments(file_path: str) -> dict:
    """
    Returns {"text": "<full transcript>", "segments": [{"start", "end", "text"}, ...]}.
    Uses Groq's API if GROQ_API_KEY is set, otherwise falls back to a
    locally-run Whisper model.
    """
    if os.environ.get("GROQ_API_KEY"):
        return _transcribe_with_groq(file_path)
    return _transcribe_with_local_whisper(file_path)
