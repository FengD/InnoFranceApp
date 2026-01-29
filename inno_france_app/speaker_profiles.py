from __future__ import annotations

import re
from typing import Any

from .text_utils import parse_speaker_lines, trim_text


SPEAKER_TAG_RE = re.compile(r"^SPEAKER(\d+)$")


def build_speaker_configs(translated_text: str) -> list[dict[str, Any]]:
    speaker_lines = parse_speaker_lines(translated_text)
    if not speaker_lines:
        return [
            {
                "speaker_tag": "[SPEAKER0]",
                "design_text": "大家好，欢迎收听本期节目。",
                "design_instruct": "Neutral, clear Mandarin voice, steady pace.",
                "language": "Chinese",
            }
        ]

    configs: list[dict[str, Any]] = []
    ordered_speakers = sorted(speaker_lines.keys(), key=_speaker_sort_key)
    for index, speaker in enumerate(ordered_speakers):
        lines = speaker_lines[speaker]
        sample_text = _build_sample_text(lines)
        avg_len = sum(len(line) for line in lines) / max(1, len(lines))
        question_ratio = _question_ratio(lines)
        instruct = _build_instruct(avg_len, question_ratio, index)
        configs.append(
            {
                "speaker_tag": f"[{speaker}]",
                "design_text": sample_text,
                "design_instruct": instruct,
                "language": "Chinese",
            }
        )

    return configs


def _speaker_sort_key(speaker: str) -> int:
    match = SPEAKER_TAG_RE.match(speaker)
    if match:
        return int(match.group(1))
    return 0


def _build_sample_text(lines: list[str]) -> str:
    if not lines:
        return "大家好，欢迎收听本期节目。"
    combined = " ".join(lines[:2]).strip()
    if not combined:
        combined = lines[0].strip() if lines else ""
    if not combined:
        combined = "大家好，欢迎收听本期节目。"
    return trim_text(combined, 160)


def _question_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0
    question_hits = 0
    for line in lines:
        if "?" in line or "？" in line or "吗" in line:
            question_hits += 1
    return question_hits / max(1, len(lines))


def _build_instruct(avg_len: float, question_ratio: float, index: int) -> str:
    if question_ratio >= 0.35:
        base = "Inquisitive host tone, clear and guiding delivery."
    elif avg_len >= 80:
        base = "Expert tone, steady pace, thoughtful delivery."
    elif avg_len <= 30:
        base = "Lively tone, concise delivery, friendly energy."
    else:
        base = "Natural conversational tone, calm and friendly."

    variations = [
        "Slightly lower pitch, confident.",
        "Brighter tone, attentive.",
        "Warm and composed delivery.",
        "Focused and energetic tone.",
    ]
    variation = variations[index % len(variations)]
    return f"{base} {variation}"
