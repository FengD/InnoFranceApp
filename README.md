# InnoFranceApp

End-to-end pipeline that turns a YouTube link into:
- a Chinese summary text (`.txt`)
- a Chinese multi-speaker audio (`.wav`) generated from the translated transcript

The app orchestrates the existing MCP services:
- `InnoFranceYTAudioExtractor` (YouTube audio download)
- `InnoFranceASRService` (ASR + speaker diarization)
- `InnoFranceTranslateAGENT` (translation + summary)
- `InnoFranceVoiceGenerateAgent` (TTS voice clone)

## Workflow

1. Download audio from YouTube (MP3).
2. Transcribe with speaker diarization.
3. Translate to Chinese with speaker tags.
4. Summarize the Chinese transcript.
5. Generate multi-speaker Chinese audio from the translated transcript.

Summary text and final audio are saved into `InnoFrance/` with incremental `sp{n}_` naming.

## Prerequisites

- Python 3.10+
- `ffmpeg` on PATH
- LLM provider credentials for `InnoFranceTranslateAGENT`
- Model paths for ASR and TTS services

Install ffmpeg on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

## Install

Create a venv and install this app:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r InnoFranceApp/requirements.txt
```

Install each service dependency (run once):

```bash
pip install -r InnoFranceYTAudioExtractor/requirements.txt
pip install -r InnoFranceASRService/requirements.txt
pip install -r InnoFranceTranslateAGENT/requirements.txt
pip install -r InnoFranceVoiceGenerateAgent/requirements.txt
```

## Quick Start

```bash
cd InnoFranceApp
python3 -m inno_france_app.cli \
  --youtube-url "https://www.youtube.com/watch?v=WRvWLWfv4Ts" \
  --provider openai \
  --language fr \
  --speed 1.0
```

You can also pass a direct audio URL or local audio path:

```bash
python3 -m inno_france_app.cli \
  --audio-url "https://example.com/audio.mp3" \
  --provider openai
```

```bash
python3 -m inno_france_app.cli \
  --audio-path "/path/to/audio.wav" \
  --provider openai
```

Outputs:
- Summary: `InnoFrance/sp{n}_<video>.txt`
- Audio: `InnoFrance/sp{n}_<video>.wav`
- Speakers: `InnoFrance/sp{n}_<video>.speakers.json`
- Run artifacts: `InnoFranceApp/runs/sp{n}_<video>/`

## Output Artifacts

Each run directory contains:
- `audio.mp3`: downloaded audio
- `transcript.json`: ASR result
- `translated.txt`: translated Chinese transcript with speaker tags
- `speakers.json`: generated speaker profile config for TTS

The final summary `.txt` and audio `.wav` are stored in `InnoFrance/` with the same base name.
The generated speaker config is also saved in `InnoFrance/` with the same base name.

## Speaker Config Generation

The app generates `speakers.json` based on the translated transcript:
- speaker count is inferred from `[SPEAKERx]` tags
- each speaker receives a distinct voice instruction
- a short sample from each speaker is used as the design text

If you want to override voices, edit `speakers.json` inside the run directory and rerun TTS with the MCP tool `clone_voice`.

## Configuration

Environment variables:

- `INNOFRANCE_PROJECT_ROOT`: override repo root detection
- `INNOFRANCE_OUTPUT_DIR`: default output directory (default: `<root>/InnoFrance`)
- `INNOFRANCE_RUNS_DIR`: run artifacts directory (default: `<root>/InnoFranceApp/runs`)
- `INNOFRANCE_PYTHON_CMD`: Python command (default: `python3`)
- `INNOFRANCE_YT_EXTRACTOR_DIR`: path to `InnoFranceYTAudioExtractor`
- `INNOFRANCE_ASR_DIR`: path to `InnoFranceASRService`
- `INNOFRANCE_TRANSLATE_DIR`: path to `InnoFranceTranslateAGENT`
- `INNOFRANCE_TTS_DIR`: path to `InnoFranceVoiceGenerateAgent`

LLM provider variables are read by `InnoFranceTranslateAGENT` (e.g. `OPENAI_API_KEY`).

Model configuration (used by the services):
- `WHISPER_MODEL_PATH`, `DIARIZATION_MODEL_PATH` for ASR
- `VOICE_DESIGN_MODEL_PATH`, `VOICE_CLONE_MODEL_PATH` for TTS

## Config File

The default config file is `InnoFranceApp/config.json`. You can override it:

```bash
python3 -m inno_france_app.cli --config /path/to/config.json --youtube-url "..."
```

Config structure:

```json
{
  "output_dir": "InnoFrance",
  "runs_dir": "InnoFranceApp/runs",
  "services": {
    "youtube_audio": {
      "transport": "stdio",
      "command": "python3",
      "args": ["-m", "app.mcp_server"],
      "cwd": "InnoFranceYTAudioExtractor",
      "env": {
        "YT_COOKIES_FILE": "/path/to/cookies.txt",
        "YT_USER_AGENT": "Mozilla/5.0 ..."
      }
    },
    "asr": {
      "transport": "sse",
      "url": "http://127.0.0.1:8000/sse"
    },
    "translate": {
      "transport": "stdio",
      "command": "python3",
      "args": ["-m", "app.mcp_server"],
      "cwd": "InnoFranceTranslateAGENT",
      "env": {
        "DEEPSEEK_API_KEY": "sk-...",
        "DEEPSEEK_API_BASE": "https://api.deepseek.com"
      }
    }
  }
}
```

SSE usage notes:
- For FastMCP SSE servers, use the exact SSE endpoint URL provided by the service.
- If a service runs in a separate environment, set its `transport` to `sse` and provide `url`.

YouTube 403 troubleshooting:
- Set `YT_COOKIES_FILE` (exported from a logged-in browser) or `YT_USER_AGENT`.
- If needed, set `YT_PROXY` for outbound access.
You can also pass cookies directly via CLI:

```bash
python3 -m inno_france_app.cli \
  --youtube-url "https://www.youtube.com/watch?v=WRvWLWfv4Ts" \
  --yt-cookies-file "~/Downloads/cookies.txt" \
  --provider openai
```

## Troubleshooting

- **`ModuleNotFoundError: mcp`**: install this app's requirements.
- **`ffmpeg not found`**: install ffmpeg and ensure it is on PATH.
- **TTS or ASR model errors**: confirm required model paths and GPU settings.
- **Empty summary**: verify LLM credentials and provider settings.

## Notes

- The pipeline uses MCP stdio transport to run tools locally.
- `speed` defaults to `1.0` as requested.
