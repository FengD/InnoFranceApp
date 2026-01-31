# InnoFranceApp Installation Guide (English)

This guide explains required repositories, folder layout, environment variables, and how to start the system.

---

## 1. Required repositories

Use these HTTP clone commands:

```
git clone https://github.com/FengD/InnoFranceApp.git
git clone https://github.com/FengD/InnoFranceYTAudioExtractor.git
git clone https://github.com/FengD/InnoFranceASRService.git
git clone https://github.com/FengD/InnoFranceTranslateAGENT.git
git clone https://github.com/FengD/InnoFranceVoiceGenerateAgent.git
```

Clone all projects under the same parent directory:

- `InnoFranceApp` (main app)
- `InnoFranceYTAudioExtractor`
- `InnoFranceASRService`
- `InnoFranceTranslateAGENT`
- `InnoFranceVoiceGenerateAgent`

Recommended layout:

```
InnoFranceProject/
├── InnoFranceApp/
├── InnoFranceYTAudioExtractor/
├── InnoFranceASRService/
├── InnoFranceTranslateAGENT/
└── InnoFranceVoiceGenerateAgent/
```

---

## 2. Install dependencies

### 2.1 Main app (conda)

```
conda create -n inno-france python=3.10 -y
conda activate inno-france
pip install -r requirements.txt
```

### 2.2 Main app (venv)

```
cd InnoFranceApp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.3 MCP services

From the repo root:

```
pip install -r InnoFranceYTAudioExtractor/requirements.txt
pip install -r InnoFranceASRService/requirements.txt
pip install -r InnoFranceTranslateAGENT/requirements.txt
pip install -r InnoFranceVoiceGenerateAgent/requirements.txt
```

---

## 3. Configure environment variables

Copy the template:

```
cp env.example .env
```

Key settings:

- `INNOFRANCE_RUNS_DIR`: output directory for run artifacts
- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`: LLM credentials
- Model paths: `WHISPER_MODEL_PATH`, `VOICE_DESIGN_MODEL_PATH`, etc.
- S3 (optional): `INNOFRANCE_S3_ENDPOINT`, etc.

If you want to override the project root:

```
INNOFRANCE_PROJECT_ROOT=/path/to/InnoFranceProject
```

---

## 4. Start the API server

```
python3 -m inno_france_app.server --host 127.0.0.1 --port 8000
```

---

## 5. Start the frontend

```
cd InnoFranceApp/frontend
npm install
npm run dev
```

Open:

```
http://localhost:5173
```

---

## 6. Troubleshooting

**Q: Local upload fails.**  
A: Install `python-multipart` and restart the API server.

**Q: Model load error.**  
A: Verify model paths and GPU settings.

