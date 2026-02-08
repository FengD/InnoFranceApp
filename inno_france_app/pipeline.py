from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .config import AppConfig
from .logging_utils import log_event, setup_logging
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
    input_audio_path: Path
    speaker_audio_paths: list[Path]
    speaker_clip_segments: dict[str, dict[str, Any]] = field(default_factory=dict)
    speaker_clip_candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    speaker_clip_selected: dict[str, int] = field(default_factory=dict)
    speaker_audio_tags: list[str] = field(default_factory=list)


class InnoFrancePipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._logger = setup_logging()

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
        provider_api_key: Optional[str] = None,
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
        speaker_detect_client = MCPToolClient(_require_service(services, "speaker_detect"))

        audio_path_input = audio_path
        audio_path = run_dir / "audio.mp3"
        source_kind = _detect_source_kind(youtube_url, audio_url, audio_path_input)
        yt_result: dict[str, Any] = {}

        _emit("youtube_audio", "running", "Preparing audio source", None)
        if source_kind == "audio_path":
            source_path = Path(audio_path_input or "").expanduser().resolve()
            audio_path = await asyncio.to_thread(_copy_audio_to_run, source_path, run_dir)
            base_name = _sanitize_base_name(source_path.name) or base_name
            _emit(
                "youtube_audio",
                "completed",
                "Copied local audio",
                _relative_to_runs(audio_path, runs_dir),
            )
        elif source_kind == "audio_url":
            audio_path = await asyncio.to_thread(
                _download_audio_to_run,
                audio_url or "",
                run_dir,
                yt_user_agent,
                self._logger,
            )
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
                "api_key": provider_api_key,
            },
        )
        _ensure_success(translation_result, "Translation failed")
        translated_text = str(translation_result.get("result", "")).strip()

        translated_text_path = run_dir / "translated.txt"
        translated_text_path.write_text(translated_text, encoding="utf-8")
        speaker_tags = _extract_speaker_tags(translated_text)
        speaker_count = len(speaker_tags) if speaker_tags else 1
        tag_list = ", ".join(speaker_tags) if speaker_tags else "SPEAKER0"
        detail = f"file: {_relative_to_runs(translated_text_path, runs_dir)}"
        _emit(
            "translate",
            "completed",
            f"Translation saved (speakers: {speaker_count} | {tag_list})",
            detail,
        )

        _emit("summary", "running", "Generating summary", None)
        summary_result = await translate_client.call_tool(
            "translate_text",
            {
                "text": translated_text,
                "provider": provider,
                "model_name": model_name,
                "prompt_type": "summary",
                "api_key": provider_api_key,
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
        speaker_audio_paths: list[Path] = []
        speaker_clip_segments: dict[str, dict[str, Any]] = {}
        speaker_clip_candidates: dict[str, list[dict[str, Any]]] = {}
        speaker_audio_tags: list[str] = []
        if manual_speakers:
            if speaker_future is None:
                raise RuntimeError("Manual speakers enabled but no input channel provided")
            tag_list = ", ".join(_extract_speaker_tags(translated_text)) or "SPEAKER0"
            _emit(
                "speakers",
                "waiting",
                "Awaiting manual speaker JSON",
                f"{speaker_count} speakers detected: {tag_list}",
            )
            speakers_json = await speaker_future
            if translated_text_path.exists():
                translated_text = translated_text_path.read_text(encoding="utf-8").strip()
            speakers = _parse_speaker_configs(speakers_json, self.config.settings.project_root)
            _emit("speakers", "running", "Using provided speaker configs", None)
        else:
            _emit("speakers", "running", "Detecting speaker profiles", None)
            speaker_groups = _group_segments_by_speaker(transcript)
            (
                speakers,
                speaker_audio_paths,
                speaker_clip_segments,
                speaker_clip_candidates,
                speaker_audio_tags,
            ) = await _detect_speaker_configs(
                translated_text=translated_text,
                audio_path=audio_path,
                run_dir=run_dir,
                speaker_groups=speaker_groups,
                speaker_client=speaker_detect_client,
                runs_dir=runs_dir,
                emit=_emit,
            )
            if not speakers:
                _emit("speakers", "running", "Fallback to default speaker configs", None)
                speakers = build_speaker_configs(translated_text)
                speaker_clip_segments = {}
                speaker_clip_candidates = {}
                speaker_audio_tags = _extract_speaker_tags(translated_text)
        speaker_clip_selected = {
            tag: 0 for tag in (speaker_audio_tags or _extract_speaker_tags(translated_text))
        }
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
            input_audio_path=Path(audio_path),
            speaker_audio_paths=speaker_audio_paths,
            speaker_clip_segments=speaker_clip_segments,
            speaker_clip_candidates=speaker_clip_candidates,
            speaker_clip_selected=speaker_clip_selected,
            speaker_audio_tags=speaker_audio_tags,
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
        entry = {
            "text": text,
            "speaker": speaker,
        }
        if segment.get("start") is not None and segment.get("end") is not None:
            entry["start"] = float(segment.get("start"))
            entry["end"] = float(segment.get("end"))
        normalized.append(entry)
    speaker_segments = _normalize_speaker_segments(transcript.get("speaker_segments"))
    return {
        "language": transcript.get("language"),
        "segments": normalized,
        "speaker_segments": speaker_segments,
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


def _download_audio_to_run(
    url: str,
    run_dir: Path,
    user_agent: Optional[str] = None,
    logger: Optional[Any] = None,
) -> Path:
    parsed = urllib.parse.urlparse(url)
    filename = Path(parsed.path).name or "audio.mp3"
    target = run_dir / filename
    headers = {
        "User-Agent": user_agent
        or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "*/*",
    }
    request = urllib.request.Request(url, headers=headers)
    if logger:
        log_event(logger, "audio_url_download_start", url=url, filename=filename)
    try:
        with urllib.request.urlopen(request) as response:
            if logger:
                log_event(
                    logger,
                    "audio_url_download_response",
                    url=url,
                    status=getattr(response, "status", None),
                    content_type=response.headers.get("Content-Type"),
                    content_length=response.headers.get("Content-Length"),
                )
            with open(target, "wb") as f:
                shutil.copyfileobj(response, f)
    except urllib.error.HTTPError as exc:
        if logger:
            log_event(
                logger,
                "audio_url_download_error",
                url=url,
                status=exc.code,
                reason=str(exc.reason),
                headers=dict(exc.headers or {}),
            )
        raise ValueError(f"Audio URL download failed ({exc.code} {exc.reason})") from exc
    except Exception as exc:
        if logger:
            log_event(logger, "audio_url_download_error", url=url, error=str(exc))
        raise
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


def _normalize_speaker_segments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        speaker = item.get("speaker")
        if start is None or end is None or not speaker:
            continue
        normalized.append(
            {
                "start": float(start),
                "end": float(end),
                "speaker": str(speaker),
            }
        )
    return sorted(normalized, key=lambda x: x["start"])


def _extract_speaker_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    segments = transcript.get("speaker_segments")
    normalized = _normalize_speaker_segments(segments)
    if normalized:
        return normalized
    derived = []
    for segment in transcript.get("segments", []):
        if not isinstance(segment, dict):
            continue
        start = segment.get("start")
        end = segment.get("end")
        speaker = segment.get("speaker")
        if start is None or end is None or not speaker:
            continue
        derived.append(
            {
                "start": float(start),
                "end": float(end),
                "speaker": str(speaker),
            }
        )
    return sorted(derived, key=lambda x: x["start"])


def _group_segments_by_speaker(
    transcript: dict[str, Any],
) -> dict[str, list[dict[str, float]]]:
    grouped: dict[str, list[dict[str, float]]] = {}
    segments = transcript.get("segments", [])
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        speaker = segment.get("speaker")
        start = segment.get("start")
        end = segment.get("end")
        if speaker is None or start is None or end is None:
            continue
        grouped.setdefault(str(speaker), []).append(
            {"start": float(start), "end": float(end)}
        )
    if grouped:
        return grouped
    fallback = _extract_speaker_segments(transcript)
    for segment in fallback:
        speaker = segment.get("speaker")
        if not speaker:
            continue
        grouped.setdefault(str(speaker), []).append(
            {"start": float(segment["start"]), "end": float(segment["end"])}
        )
    return grouped


def _speaker_index_from_tag(tag: str) -> Optional[int]:
    match = re.search(r"SPEAKER(\d+)", tag)
    if not match:
        return None
    return int(match.group(1))


def _pick_representative_segments(
    candidates: dict[str, list[dict[str, Any]]],
    min_duration: float = 15.0,
    max_duration: float = 30.0,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    target = (min_duration + max_duration) / 2
    for speaker, segments in candidates.items():
        if not segments:
            continue
        preferred = [
            seg
            for seg in segments
            if min_duration <= float(seg.get("duration", 0)) <= max_duration
        ]
        if preferred:
            preferred.sort(key=lambda d: abs(float(d["duration"]) - target))
            selected[speaker] = preferred[0]
        else:
            segments.sort(key=lambda d: float(d.get("duration", 0)), reverse=True)
            selected[speaker] = segments[0]
    return selected


def _build_speaker_clip_candidates(
    grouped: dict[str, list[dict[str, float]]],
    min_duration: float = 15.0,
    max_duration: float = 30.0,
    max_candidates: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    all_segments: list[dict[str, Any]] = []
    for speaker, segments in grouped.items():
        for seg in segments:
            start = float(seg["start"])
            end = float(seg["end"])
            if end <= start:
                continue
            all_segments.append(
                {
                    "speaker": speaker,
                    "start": start,
                    "end": end,
                    "duration": end - start,
                }
            )
    for speaker, segments in grouped.items():
        items = []
        non_overlap = []
        for seg in segments:
            start = float(seg["start"])
            end = float(seg["end"])
            if end <= start:
                continue
            entry = {
                "speaker": speaker,
                "start": start,
                "end": end,
                "duration": end - start,
            }
            items.append(entry)
            overlap = False
            for other in all_segments:
                if other["speaker"] == speaker:
                    continue
                if _segments_overlap(start, end, other["start"], other["end"]):
                    overlap = True
                    break
            if not overlap:
                non_overlap.append(entry)
        source = non_overlap or items
        if not source:
            continue
        source.sort(key=lambda d: d["duration"], reverse=True)
        chosen = source[:max_candidates]
        target = (min_duration + max_duration) / 2
        closest = min(source, key=lambda d: abs(d["duration"] - target))
        if not any(
            abs(c["start"] - closest["start"]) < 1e-3 and abs(c["end"] - closest["end"]) < 1e-3
            for c in chosen
        ):
            chosen.append(closest)
        chosen = chosen[:max_candidates]
        candidates[speaker] = chosen
    return candidates


def _extract_audio_clip(source: Path, start: float, end: float, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        str(max(start, 0)),
        "-to",
        str(max(end, 0)),
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Speaker clip extraction failed: {result.stderr}")


async def _detect_speaker_configs(
    translated_text: str,
    audio_path: Path,
    run_dir: Path,
    speaker_groups: dict[str, list[dict[str, float]]],
    speaker_client: MCPToolClient,
    runs_dir: Path,
    emit: Callable[[str, str, str, Optional[str]], None],
    exclude_segments: Optional[dict[str, list[dict[str, float]]]] = None,
) -> tuple[
    list[dict[str, Any]],
    list[Path],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[str],
]:
    if not speaker_groups:
        emit("speakers", "running", "No speaker segments available for detection", None)
        return [], [], {}, {}, []

    candidates = _build_speaker_clip_candidates(speaker_groups)
    chosen = _pick_representative_segments(candidates)
    if not chosen:
        emit("speakers", "running", "No valid speaker segments for detection", None)
        return [], [], {}, candidates, []

    speaker_order = sorted(chosen.keys(), key=_speaker_sort_key)
    if not speaker_order:
        return [], [], {}, candidates, []

    speaker_audio_paths: list[Path] = []
    speaker_configs: list[dict[str, Any]] = []

    for fallback_index, speaker_label in enumerate(speaker_order):
        segment = chosen.get(speaker_label)
        if not segment:
            continue
        label_index = _speaker_index_from_tag(speaker_label)
        index = label_index if label_index is not None else fallback_index
        output_path = run_dir / f"speaker{index}.wav"
        try:
            await asyncio.to_thread(
                _extract_audio_clip,
                audio_path,
                segment["start"],
                segment["end"],
                output_path,
            )
        except Exception as exc:
            emit(
                "speakers",
                "running",
                f"Speaker clip extraction failed for {speaker_label}",
                str(exc),
            )
            continue
        speaker_audio_paths.append(output_path)
        emit(
            "speakers",
            "running",
            f"Speaker clip saved for {speaker_label}",
            _relative_to_runs(output_path, runs_dir),
        )

        try:
            result = await speaker_client.call_tool(
                "detect_speaker",
                {"audio_path": str(output_path)},
            )
        except Exception as exc:
            emit(
                "speakers",
                "running",
                f"Speaker detect failed for {speaker_label}",
                str(exc),
            )
            result = {"success": False, "error": str(exc)}
        profile = None
        if result.get("success"):
            profiles = result.get("result", [])
            if isinstance(profiles, list) and profiles:
                profile = profiles[0]
            else:
                emit("speakers", "running", f"No profile returned for {speaker_label}", None)
        else:
            error = result.get("error", "Unknown error")
            emit("speakers", "running", f"Speaker detect failed for {speaker_label}", error)

        speaker_configs.append(
            {
                "speaker_tag": f"[{speaker_label}]",
                "design_text": (profile or {}).get("design_text") or f"说话人 {index}",
                "design_instruct": (profile or {}).get("design_instruct")
                or "性别与年龄未知，语速适中，音色自然清晰。",
                "language": "Chinese",
            }
        )

    return speaker_configs, speaker_audio_paths, chosen, candidates, speaker_order


async def _select_speaker_clips(
    audio_path: Path,
    run_dir: Path,
    speaker_groups: dict[str, list[dict[str, float]]],
    runs_dir: Path,
    emit: Callable[[str, str, str, Optional[str]], None],
    exclude_segments: Optional[dict[str, list[dict[str, float]]]] = None,
) -> tuple[list[tuple[str, Path]], dict[str, dict[str, Any]]]:
    if not speaker_groups:
        emit("speakers", "running", "No speaker segments available for clips", None)
        return [], {}

    chosen = _pick_representative_segments(
        speaker_groups, exclude_segments=exclude_segments
    )
    if not chosen:
        emit("speakers", "running", "No valid speaker segments for clips", None)
        return [], {}

    speaker_order = sorted(chosen.keys(), key=_speaker_sort_key)
    if not speaker_order:
        return [], {}

    clips: list[tuple[str, Path]] = []
    for fallback_index, speaker_label in enumerate(speaker_order):
        segment = chosen.get(speaker_label)
        if not segment:
            continue
        label_index = _speaker_index_from_tag(speaker_label)
        index = label_index if label_index is not None else fallback_index
        output_path = run_dir / f"speaker{index}.wav"
        try:
            await asyncio.to_thread(
                _extract_audio_clip,
                audio_path,
                segment["start"],
                segment["end"],
                output_path,
            )
        except Exception as exc:
            emit(
                "speakers",
                "running",
                f"Speaker clip extraction failed for {speaker_label}",
                str(exc),
            )
            continue
        clips.append((speaker_label, output_path))
        emit(
            "speakers",
            "running",
            f"Speaker clip saved for {speaker_label}",
            _relative_to_runs(output_path, runs_dir),
        )

    return clips, chosen


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


def _segment_excluded(start: float, end: float, excluded: list[dict[str, float]]) -> bool:
    for item in excluded:
        try:
            ex_start = float(item.get("start"))
            ex_end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if abs(ex_start - start) < 1e-3 and abs(ex_end - end) < 1e-3:
            return True
    return False


def _segments_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return not (a_end <= b_start or b_end <= a_start)


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
