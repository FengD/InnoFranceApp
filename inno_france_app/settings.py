from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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
    s3_endpoint: str
    s3_bucket: str
    s3_access_key: str
    s3_secret_key: str
    s3_prefix: str


def load_settings() -> AppSettings:
    project_root = _find_project_root()
    python_cmd = os.getenv("INNOFRANCE_PYTHON_CMD", "python3")

    runs_dir = Path(
        os.getenv("INNOFRANCE_RUNS_DIR", project_root / "InnoFranceApp" / "runs")
    ).expanduser().resolve()
    output_dir = runs_dir

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
        s3_endpoint=os.getenv("INNOFRANCE_S3_ENDPOINT", ""),
        s3_bucket=os.getenv("INNOFRANCE_S3_BUCKET", ""),
        s3_access_key=os.getenv("INNOFRANCE_S3_ACCESS_KEY", ""),
        s3_secret_key=os.getenv("INNOFRANCE_S3_SECRET_KEY", ""),
        s3_prefix=os.getenv("INNOFRANCE_S3_PREFIX", "inno_france"),
    )
