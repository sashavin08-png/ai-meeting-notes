"""
Speaker diarization: figuring out WHO spoke, not just what was said.

Whisper transcribes speech to text but has no concept of "speakers" —
pyannote.audio handles that separately, producing a timeline of who was
talking during which time ranges. This module runs that pipeline and
merges its output with Whisper's timestamped segments to produce a
speaker-labeled transcript like:

    [Speaker A]: Let's start with the timeline.
    [Speaker B]: Sure, I think we can hit Friday.

Requires a (free) Hugging Face account:
  1. Create an account at huggingface.co
  2. Accept the terms for "pyannote/speaker-diarization-3.1"
     (visit that model's page while logged in, click accept)
  3. Create an access token at huggingface.co/settings/tokens
  4. export HUGGINGFACE_TOKEN='hf_...'

If HUGGINGFACE_TOKEN isn't set, diarization is skipped entirely and the
plain (non-speaker-labeled) transcript is used instead — this feature is
additive, not required for the rest of the app to work.
"""

import logging
import os

logger = logging.getLogger("diarizer")

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline

        token = os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            raise RuntimeError(
                "HUGGINGFACE_TOKEN is not set. Speaker diarization requires a free "
                "Hugging Face account and accepting the model terms — see this "
                "module's docstring for the one-time setup steps."
            )
        logger.info("Loading speaker diarization pipeline (first call only)...")
        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=token
        )
    return _pipeline


def get_speaker_turns(file_path: str) -> list[dict]:
    """
    Returns a list of {"start": float, "end": float, "speaker": str} —
    pyannote's raw diarization output, one entry per continuous speaker turn.
    """
    pipeline = _get_pipeline()
    diarization = pipeline(file_path)

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({"start": turn.start, "end": turn.end, "speaker": speaker})
    return turns


def _speaker_at(turns: list[dict], midpoint: float) -> str:
    """Find which speaker turn covers a given point in time (by max overlap)."""
    best_speaker = "Unknown"
    best_overlap = -1.0
    for t in turns:
        if t["start"] <= midpoint <= t["end"]:
            return t["speaker"]
        # Track the closest turn in case no exact match (gaps between turns happen)
        distance = min(abs(midpoint - t["start"]), abs(midpoint - t["end"]))
        if best_overlap == -1.0 or distance < best_overlap:
            best_overlap = distance
            best_speaker = t["speaker"]
    return best_speaker


def merge_segments_with_speakers(segments: list[dict], turns: list[dict]) -> str:
    """
    Combines Whisper's timestamped text segments with pyannote's speaker
    turns into a readable, speaker-labeled transcript. Consecutive segments
    from the same speaker are grouped into one paragraph rather than
    repeating the label on every line.
    """
    if not turns:
        return "\n".join(s["text"] for s in segments)

    labeled = []
    for seg in segments:
        midpoint = (seg["start"] + seg["end"]) / 2
        speaker = _speaker_at(turns, midpoint)
        labeled.append((speaker, seg["text"]))

    lines = []
    current_speaker = None
    current_text_parts = []

    for speaker, text in labeled:
        if speaker != current_speaker:
            if current_speaker is not None:
                lines.append(f"[{current_speaker}] {' '.join(current_text_parts)}")
            current_speaker = speaker
            current_text_parts = [text]
        else:
            current_text_parts.append(text)

    if current_speaker is not None:
        lines.append(f"[{current_speaker}] {' '.join(current_text_parts)}")

    return "\n\n".join(lines)


def transcribe_with_speakers(file_path: str, segments: list[dict]) -> str:
    """
    Convenience wrapper: runs diarization and merges it with already-computed
    Whisper segments. Returns a speaker-labeled transcript string.
    """
    turns = get_speaker_turns(file_path)
    return merge_segments_with_speakers(segments, turns)
