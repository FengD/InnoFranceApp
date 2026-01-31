from __future__ import annotations

import asyncio
import json
import re
import shutil
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .config import AppConfig
from .mcp_clients import MCPToolClient
from .speaker_profiles import build_speaker_configs
from .text_utils import normalize_translation_text, parse_speaker_lines


PIPELINE_STEPS = (
    "youtube_audio",
    "asr",
    "translate",
    "summary",
    "speakers",
    "tts",
)


@dataclass(frozen=True)
class PipelineResult:
    summary_path: Path
    audio_path: Path
    run_dir: Path
    translated_text_path: Path
    transcript_path: Path
    speakers_path: Path


class InnoFrancePipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def run(
        self,
        youtube_url: Optional[str],
        audio_url: Optional[str],
        audio_path: Optional[str],
        provider: str,
        model_name: str,
        language: str,
        chunk_length: int,
        speed: float,
        yt_cookies_file: Optional[str] = None,
        yt_cookies_from_browser: Optional[str] = None,
        yt_user_agent: Optional[str] = None,
        yt_proxy: Optional[str] = None,
        on_progress: Optional[Callable[[str, str, str, Optional[str]], None]] = None,
        manual_speakers: bool = False,
        speaker_future: Optional[asyncio.Future[str]] = None,
    ) -> PipelineResult:
        def _emit(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
            if on_progress:
                on_progress(step, status, message, detail)

        runs_dir = self.config.runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)

        sp_index = _next_sp_index(runs_dir)
        base_name = "youtube_audio"
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        run_name = f"sp{sp_index}_{base_name}_{stamp}"
        run_dir = runs_dir / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        if audio_path and not _is_audio_path(audio_path):
            raise ValueError("audio-path must be an existing .mp3 or .wav file")
        if audio_url and not _is_audio_url(audio_url):
            raise ValueError("audio-url must be an http(s) URL ending with .mp3 or .wav")

        services = self.config.services
        yt_client = MCPToolClient(_require_service(services, "youtube_audio"))
        asr_client = MCPToolClient(_require_service(services, "asr"))
        translate_client = MCPToolClient(_require_service(services, "translate"))
        tts_client = MCPToolClient(_require_service(services, "tts"))

        audio_path_input = audio_path
        audio_path = run_dir / "audio.mp3"
        source_kind = _detect_source_kind(youtube_url, audio_url, audio_path_input)
        yt_result: dict[str, Any] = {}

        _emit("youtube_audio", "running", "Preparing audio source", None)
        if source_kind == "audio_path":
            source_path = Path(audio_path_input or "").expanduser().resolve()
            audio_path = _copy_audio_to_run(source_path, run_dir)
            base_name = _sanitize_base_name(source_path.name) or base_name
            _emit(
                "youtube_audio",
                "completed",
                "Copied local audio",
                _relative_to_runs(audio_path, runs_dir),
            )
        elif source_kind == "audio_url":
            audio_path = _download_audio_to_run(audio_url or "", run_dir)
            base_name = _sanitize_base_name(Path(audio_path).name) or base_name
            _emit(
                "youtube_audio",
                "completed",
                "Downloaded audio from URL",
                _relative_to_runs(audio_path, runs_dir),
            )
        else:
            yt_args = {
                "url": youtube_url,
                "output_path": str(audio_path),
                "format": "mp3",
                "cookies_file": yt_cookies_file,
                "cookies_from_browser": yt_cookies_from_browser,
                "user_agent": yt_user_agent,
                "proxy": yt_proxy,
            }
            yt_result = await yt_client.call_tool("extract_audio_to_file", yt_args)
            _ensure_success(yt_result, "YouTube audio extraction failed")

            filename = yt_result.get("filename") or yt_result.get("file_path") or ""
            base_name = _sanitize_base_name(filename) or base_name
            run_name = f"sp{sp_index}_{base_name}_{stamp}"
            if run_name != run_dir.name:
                run_dir = _rename_run_dir(run_dir, runs_dir, run_name)
                audio_path = run_dir / "audio.mp3"
            audio_path = _resolve_audio_path(audio_path, run_dir, yt_result)
            _emit(
                "youtube_audio",
                "completed",
                "YouTube audio extracted",
                _relative_to_runs(audio_path, runs_dir),
            )

        run_name = f"sp{sp_index}_{base_name}_{stamp}"
        if run_name != run_dir.name:
            run_dir = _rename_run_dir(run_dir, runs_dir, run_name)
            audio_path = run_dir / Path(audio_path).name

        transcript_path = run_dir / "transcript.json"
        _emit("asr", "running", "Transcribing audio with speaker diarization", None)
        asr_result = await asr_client.call_tool(
            "transcribe_audio",
            {
                "audio_path": str(audio_path),
                "language": language,
                "chunk_length": chunk_length,
                "output_format": "json",
            },
        )
        _ensure_success(asr_result, "ASR transcription failed")

        transcript = _normalize_transcript(asr_result.get("result", {}))
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _emit(
            "asr",
            "completed",
            "Transcription saved",
            _relative_to_runs(transcript_path, runs_dir),
        )

        _emit("translate", "running", "Translating transcript to Chinese", None)
        translation_result = await translate_client.call_tool(
            "translate_json",
            {
                "input_json": json.dumps(transcript, ensure_ascii=False),
                "provider": provider,
                "model_name": model_name,
                "prompt_type": "translate",
            },
        )
        _ensure_success(translation_result, "Translation failed")
        translated_text = str(translation_result.get("result", "")).strip()

        translated_text_path = run_dir / "translated.txt"
        translated_text_path.write_text(translated_text, encoding="utf-8")
        speaker_tags = _extract_speaker_tags(translated_text)
        speaker_count = len(speaker_tags) if speaker_tags else 1
        tag_list = ", ".join(speaker_tags) if speaker_tags else "SPEAKER0"
        detail = "\n".join(
            [
                f"speakers: {speaker_count} ({tag_list})",
                f"file: {_relative_to_runs(translated_text_path, runs_dir)}",
            ]
        )
        _emit("translate", "completed", "Translation saved", detail)

        _emit("summary", "running", "Generating summary", None)
        summary_result = await translate_client.call_tool(
            "translate_text",
            {
                "text": translated_text,
                "provider": provider,
                "model_name": model_name,
                "prompt_type": "summary",
            },
        )
        _ensure_success(summary_result, "Summary generation failed")
        summary_text = str(summary_result.get("result", "")).strip()

        summary_path = run_dir / "summary.txt"
        summary_path.write_text(summary_text, encoding="utf-8")
        _emit(
            "summary",
            "completed",
            "Summary saved",
            _relative_to_runs(summary_path, runs_dir),
        )

        speaker_count = _count_speakers(translated_text)
        speakers: list[dict[str, Any]]
        if manual_speakers:
            if speaker_future is None:
                raise RuntimeError("Manual speakers enabled but no input channel provided")
            _emit(
                "speakers",
                "waiting",
                "Awaiting manual speaker JSON",
                f"{speaker_count} speakers detected",
            )
            speakers_json = await speaker_future
            speakers = _parse_speaker_configs(speakers_json, self.config.settings.project_root)
            _emit("speakers", "running", "Using provided speaker configs", None)
        else:
            _emit("speakers", "running", "Building speaker configs", None)
            speakers = build_speaker_configs(translated_text)
        speakers_path = run_dir / "speakers.json"
        speakers_path.write_text(
            json.dumps(speakers, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _emit(
            "speakers",
            "completed",
            "Speaker configs saved",
            _relative_to_runs(speakers_path, runs_dir),
        )

        _emit("tts", "running", "Generating multi-speaker audio", None)
        tts_text = normalize_translation_text(translated_text)
        audio_output_path = run_dir / "audio.wav"
        tts_result = await tts_client.call_tool(
            "clone_voice",
            {
                "text": tts_text,
                "speaker_configs_json": json.dumps(speakers, ensure_ascii=False),
                "speed": speed,
                "output_path": str(audio_output_path),
            },
        )
        _ensure_success(tts_result, "Voice generation failed")
        _emit(
            "tts",
            "completed",
            "Audio generated",
            _relative_to_runs(audio_output_path, runs_dir),
        )

        return PipelineResult(
            summary_path=summary_path,
            audio_path=audio_output_path,
            run_dir=run_dir,
            translated_text_path=translated_text_path,
            transcript_path=transcript_path,
            speakers_path=speakers_path,
        )


def _ensure_success(result: dict[str, Any], message: str) -> None:
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        raise RuntimeError(f"{message}: {error}")


def _next_sp_index(output_dir: Path) -> int:
    pattern = re.compile(r"^sp(\d+)_")
    max_index = 0
    for path in output_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            try:
                max_index = max(max_index, int(match.group(1)))
            except ValueError:
                continue
    return max_index + 1


def _sanitize_base_name(filename: str) -> str:
    raw = Path(filename).stem if filename else ""
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return ascii_text


def _rename_run_dir(run_dir: Path, runs_dir: Path, run_name: str) -> Path:
    target = runs_dir / run_name
    if run_dir == target:
        return run_dir
    if target.exists():
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        target = runs_dir / f"{run_name}_{stamp}"
    return run_dir.rename(target)


def _require_service(
    services: dict[str, Any],
    key: str,
):
    if key not in services:
        raise KeyError(f"Missing service config: {key}")
    return services[key]


def _resolve_audio_path(audio_path: Path, run_dir: Path, yt_result: dict[str, Any]) -> Path:
    if audio_path.exists():
        return audio_path

    file_path = yt_result.get("file_path")
    if isinstance(file_path, str):
        candidate = Path(file_path)
        if candidate.exists():
            return candidate

    filename = yt_result.get("filename")
    if isinstance(filename, str) and filename:
        candidate = run_dir / Path(filename).name
        if candidate.exists():
            return candidate

    for ext in ("mp3", "wav"):
        matches = list(run_dir.glob(f"*.{ext}"))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"Audio file not found in {run_dir}")


def _normalize_transcript(transcript: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(transcript, dict):
        return {"segments": []}
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        return {"segments": []}
    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        speaker = segment.get("speaker") or "SPEAKER0"
        normalized.append(
            {
                "text": text,
                "speaker": speaker,
            }
        )
    return {
        "language": transcript.get("language"),
        "segments": normalized,
    }


def _detect_source_kind(
    youtube_url: Optional[str],
    audio_url: Optional[str],
    audio_path: Optional[str],
) -> str:
    if audio_path and _is_audio_path(audio_path):
        return "audio_path"
    if audio_url and _is_audio_url(audio_url):
        return "audio_url"
    if youtube_url:
        return "youtube"
    return "youtube"


def _is_audio_path(value: str) -> bool:
    path = Path(value).expanduser()
    return path.exists() and path.suffix.lower() in {".mp3", ".wav"}


def _is_audio_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.path.lower().endswith((".mp3", ".wav"))


def _copy_audio_to_run(source_path: Path, run_dir: Path) -> Path:
    target = run_dir / source_path.name
    if source_path.resolve() == target.resolve():
        return target
    shutil.copy2(source_path, target)
    return target


def _download_audio_to_run(url: str, run_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    filename = Path(parsed.path).name or "audio.mp3"
    target = run_dir / filename
    with urllib.request.urlopen(url) as response:
        with open(target, "wb") as f:
            shutil.copyfileobj(response, f)
    return target


def _relative_to_runs(path: Path, runs_dir: Path) -> str:
    try:
        resolved = path.resolve()
        base = runs_dir.resolve()
        if resolved.is_relative_to(base):
            return str(resolved.relative_to(base))
    except ValueError:
        pass
    return path.name


def _count_speakers(translated_text: str) -> int:
    speakers = parse_speaker_lines(translated_text)
    if not speakers:
        return 1
    return len(speakers)


def _extract_speaker_tags(translated_text: str) -> list[str]:
    speakers = parse_speaker_lines(translated_text)
    tags = list(speakers.keys())
    tags.sort(key=_speaker_sort_key)
    return tags


def _speaker_sort_key(tag: str) -> int:
    match = re.search(r"SPEAKER(\d+)", tag)
    if match:
        return int(match.group(1))
    return 0


def _parse_speaker_configs(payload: str, project_root: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON for speaker configs") from exc
    if not isinstance(data, list) or not data:
        raise ValueError("Speaker configs must be a non-empty list")
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each speaker config must be an object")
        ref_audio = item.get("ref_audio")
        if isinstance(ref_audio, str) and ref_audio:
            item["ref_audio"] = _resolve_media_path(ref_audio, project_root)
        ref_text_file = item.get("ref_text_file")
        if isinstance(ref_text_file, str) and ref_text_file:
            item["ref_text_file"] = _resolve_media_path(ref_text_file, project_root)
    return data


def _resolve_media_path(value: str, project_root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        if not path.exists():
            raise ValueError(f"File not found: {value}")
        return str(path)
    candidate = (project_root / path).resolve()
    if candidate.exists():
        return str(candidate)
    # fallback: look under voice prompts
    prompt_dir = project_root / "InnoFranceVoiceGenerateAgent" / "examples" / "voice_prompts"
    fallback = (prompt_dir / path.name).resolve()
    if fallback.exists():
        return str(fallback)
    raise ValueError(f"File not found: {value}")
