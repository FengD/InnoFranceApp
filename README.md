# InnoFrance App

InnoFrance is an integrated application that can convert YouTube videos or direct audio files (MP3/WAV) into Chinese dubbed versions. It completes the entire process through the following steps:

1. Extract audio from YouTube (or skip this step for direct audio URLs)
2. Use ASR service to convert audio to text
3. Use translation agent to translate text to Chinese
4. Use TTS service to generate Chinese dubbing

## Features

- Simple and easy-to-use web interface
- Real-time processing progress display
- Audio playback and download functionality
- Support for multi-speaker recognition and translation
- Support for direct MP3/WAV URL input (skip YouTube extraction)

## System Requirements

- Python 3.8+
- pip package manager
- Dependent services (see below)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd InnoFranceApp
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Starting the Application

```bash
./start.sh
```

Or start manually:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

After starting, visit `http://localhost:8000`

## Dependent Services

This application requires the following services to run properly:

1. **YouTubeAudioExtractor** - Running on port 8001
2. **ASRService** - Running on port 8002
3. **InnoFranceTranslateAGENT** - Running on port 8003
4. **InnoFranceVoiceGenerateAgent** - Running on port 8004

You can customize service addresses through environment variables:
- YOUTUBE_SERVICE_URL
- ASR_SERVICE_URL
- TRANSLATE_SERVICE_URL
- TTS_SERVICE_URL

## Usage

1. Paste a YouTube video link or direct MP3/WAV URL in the input box
2. Click the "Start Processing" button
3. Wait for processing to complete (view real-time status in progress bar)
4. Play or download the generated audio after processing is complete

## Project Structure

```
InnoFranceApp/
├── app/
│   ├── main.py          # Main application file
│   ├── templates/       # HTML templates
│   └── static/          # Static resources (CSS, JS)
├── temp/                # Temporary files directory
├── requirements.txt     # Python dependencies
├── start.sh             # Startup script
└── README.md            # This document
```

## Development Guide

### Adding New Features

1. Modify `app/main.py` to add new processing logic
2. Update `app/templates/index.html` to modify the interface
3. Adjust `app/static/css/style.css` and `app/static/js/script.js` for styling and interaction

### Customizing Service Addresses

You can customize dependent service addresses by setting environment variables:

```bash
export YOUTUBE_SERVICE_URL="http://your-youtube-service:8001"
export ASR_SERVICE_URL="http://your-asr-service:8002"
export TRANSLATE_SERVICE_URL="http://your-translate-service:8003"
export TTS_SERVICE_URL="http://your-tts-service:8004"
```

## Troubleshooting

### Service Connection Issues

Ensure all dependent services are running and accessible from InnoFranceApp.

### Audio Processing Issues

Check the log files of each service for detailed error information.

## License

MIT License