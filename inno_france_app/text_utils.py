from __future__ import annotations

import re
from typing import Iterable


SPEAKER_LINE_RE = re.compile(r"^\[(SPEAKER\d+)\]\s*(.*)$")


def parse_speaker_lines(text: str) -> dict[str, list[str]]:
    speakers: dict[str, list[str]] = {}
    current_speaker: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            current_speaker = match.group(1)
            content = match.group(2).strip()
        else:
            if not current_speaker:
                continue
            content = line

        if not content:
            continue
        speakers.setdefault(current_speaker, []).append(content)

    return speakers


def normalize_translation_text(text: str) -> str:
    normalized_lines: list[str] = []
    current_speaker: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            current_speaker = match.group(1)
            content = match.group(2).strip()
        else:
            content = line
        if not current_speaker or not content:
            continue
        normalized_lines.append(f"[{current_speaker}]{content}")

    return "\n".join(normalized_lines)


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
