from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _find_project_root() -> Path:
    env_root = os.getenv("INNOFRANCE_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "InnoFranceYTAudioExtractor").exists():
            return parent
    return current.parents[1]


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    output_dir: Path
    runs_dir: Path
    python_cmd: str
    yt_extractor_dir: Path
    asr_dir: Path
    translate_dir: Path
    tts_dir: Path


def load_settings() -> AppSettings:
    project_root = _find_project_root()
    python_cmd = os.getenv("INNOFRANCE_PYTHON_CMD", "python3")

    output_dir = Path(
        os.getenv("INNOFRANCE_OUTPUT_DIR", project_root / "InnoFrance")
    ).expanduser().resolve()
    runs_dir = Path(
        os.getenv("INNOFRANCE_RUNS_DIR", project_root / "InnoFranceApp" / "runs")
    ).expanduser().resolve()

    yt_extractor_dir = Path(
        os.getenv("INNOFRANCE_YT_EXTRACTOR_DIR", project_root / "InnoFranceYTAudioExtractor")
    ).expanduser().resolve()
    asr_dir = Path(
        os.getenv("INNOFRANCE_ASR_DIR", project_root / "InnoFranceASRService")
    ).expanduser().resolve()
    translate_dir = Path(
        os.getenv("INNOFRANCE_TRANSLATE_DIR", project_root / "InnoFranceTranslateAGENT")
    ).expanduser().resolve()
    tts_dir = Path(
        os.getenv("INNOFRANCE_TTS_DIR", project_root / "InnoFranceVoiceGenerateAgent")
    ).expanduser().resolve()

    return AppSettings(
        project_root=project_root,
        output_dir=output_dir,
        runs_dir=runs_dir,
        python_cmd=python_cmd,
        yt_extractor_dir=yt_extractor_dir,
        asr_dir=asr_dir,
        translate_dir=translate_dir,
        tts_dir=tts_dir,
    )
