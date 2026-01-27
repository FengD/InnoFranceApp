from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import json
import os
import uuid
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="InnoFrance App")

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 设置模板目录
templates = Jinja2Templates(directory="app/templates")

# 创建临时目录用于存储中间文件
TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

# 服务配置（可以根据实际部署情况修改）
YOUTUBE_SERVICE_URL = os.getenv("YOUTUBE_SERVICE_URL", "http://localhost:8001")
ASR_SERVICE_URL = os.getenv("ASR_SERVICE_URL", "http://localhost:8002")
TRANSLATE_SERVICE_URL = os.getenv("TRANSLATE_SERVICE_URL", "http://localhost:8003")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://localhost:8004")

class ProcessingStatus:
    def __init__(self):
        self.statuses = {}

    def create_task(self, task_id):
        self.statuses[task_id] = {
            "step": "started",
            "progress": 0,
            "message": "Task started",
            "result": None
        }

    def update_status(self, task_id, step, progress, message, result=None):
        if task_id in self.statuses:
            self.statuses[task_id].update({
                "step": step,
                "progress": progress,
                "message": message,
                "result": result
            })

    def get_status(self, task_id):
        return self.statuses.get(task_id, {"error": "Task does not exist"})

# 全局状态管理器
status_manager = ProcessingStatus()

def extract_youtube_audio(youtube_url: str, task_id: str) -> str:
    """Extract audio from YouTube"""
    status_manager.update_status(task_id, "youtube_extract", 10, "Extracting audio from YouTube...")
    
    try:
        # Call YouTubeAudioExtractor service using POST JSON
        response = requests.post(
            f"{YOUTUBE_SERVICE_URL}/api/extract",
            json={"url": youtube_url},
            headers={"X-Client-Id": "inno-france-app"}
        )
        
        if response.status_code == 200:
            # Save audio file
            audio_filename = TEMP_DIR / f"{task_id}_audio.mp3"
            with open(audio_filename, "wb") as f:
                f.write(response.content)
            
            status_manager.update_status(task_id, "youtube_extract", 20, "Audio extraction completed")
            return str(audio_filename)
        else:
            raise Exception(f"YouTube extraction failed: {response.text}")
    except Exception as e:
        logger.error(f"YouTube audio extraction error: {str(e)}")
        raise

def transcribe_audio(audio_path: str, task_id: str) -> dict:
    """Transcribe audio using ASR service"""
    status_manager.update_status(task_id, "asr_transcribe", 30, "Performing speech-to-text...")
    
    try:
        # Get access token
        token_response = requests.post(f"{ASR_SERVICE_URL}/auth/token")
        if token_response.status_code != 200:
            raise Exception("Unable to obtain ASR service token")
        
        token = token_response.json().get("token")
        if not token:
            raise Exception("ASR service returned invalid token")
        
        # Check if audio_path is a URL
        if audio_path.startswith(('http://', 'https://')):
            # Pass the URL directly to ASR service
            response = requests.post(
                f"{ASR_SERVICE_URL}/transcribe",
                data={"audio_url": audio_path},
                headers={"Authorization": f"Bearer {token}"}
            )
        else:
            # Upload local audio file for transcription
            with open(audio_path, "rb") as audio_file:
                files = {"file": audio_file}
                response = requests.post(
                    f"{ASR_SERVICE_URL}/transcribe",
                    files=files,
                    headers={"Authorization": f"Bearer {token}"}
                )
        
        if response.status_code == 200:
            transcription_result = response.json()
            status_manager.update_status(task_id, "asr_transcribe", 50, "Speech-to-text completed")
            return transcription_result
        else:
            raise Exception(f"ASR transcription failed: {response.text}")
    except Exception as e:
        logger.error(f"ASR transcription error: {str(e)}")
        raise

def translate_text(transcription_data: dict, task_id: str) -> dict:
    """Translate text using translation agent"""
    status_manager.update_status(task_id, "translate", 60, "Translating text...")
    
    try:
        # Prepare translation data
        translation_input = {
            "segments": transcription_data.get("segments", [])
        }
        
        # Call translation service
        response = requests.post(
            f"{TRANSLATE_SERVICE_URL}/translate",
            files={"file": ("transcription.json", json.dumps(translation_input), "application/json")},
            data={"model_type": "openai"}  # Can change model type as needed
        )
        
        if response.status_code == 200:
            translation_result = response.json()
            status_manager.update_status(task_id, "translate", 80, "Text translation completed")
            return translation_result
        else:
            raise Exception(f"Translation failed: {response.text}")
    except Exception as e:
        logger.error(f"Text translation error: {str(e)}")
        raise
def generate_audio(translation_data: dict, task_id: str) -> str:
    """Generate audio using TTS service"""
    status_manager.update_status(task_id, "tts_generate", 90, "Generating audio...")
    
    try:
        # Construct speaker configurations
        # Simplified handling, assuming only two speakers
        speaker_configs = [
            {
                "speaker_tag": "[SPEAKER0]",
                "design_text": "This is the reference text for the first speaker",
                "design_instruct": "Young female voice, lively tone",
                "language": "Chinese"
            },
            {
                "speaker_tag": "[SPEAKER1]",
                "design_text": "This is the reference text for the second speaker",
                "design_instruct": "Middle-aged male voice, steady tone",
                "language": "Chinese"
            }
        ]
        
        # Construct text (with speaker tags)
        text_segments = []
        for segment in translation_data.get("segments", []):
            # Simplified handling, directly using translated text
            speaker_tag = f"[{segment.get('speaker', 'SPEAKER0')}]"
            text_segments.append(f"{speaker_tag}{segment.get('text', '')}")
        
        text_content = "".join(text_segments)
        
        # Call TTS service
        response = requests.post(
            f"{TTS_SERVICE_URL}/api/voice-clone",
            data={
                "text": text_content,
                "speaker_configs": json.dumps(speaker_configs),
                "speed": "1.0"
            }
        )
        
        if response.status_code == 200:
            # Save generated audio file
            output_filename = TEMP_DIR / f"{task_id}_output.wav"
            with open(output_filename, "wb") as f:
                f.write(response.content)
            
            status_manager.update_status(task_id, "tts_generate", 100, "Audio generation completed", str(output_filename))
            return str(output_filename)
        else:
            raise Exception(f"TTS generation failed: {response.text}")
    except Exception as e:
        logger.error(f"Audio generation error: {str(e)}")
        raise

async def process_youtube_to_audio(input_url: str, task_id: str):
    """Complete processing pipeline"""
    try:
        # Check if input is a direct audio URL (mp3/wav)
        is_direct_audio = input_url.lower().endswith(('.mp3', '.wav')) and input_url.startswith(('http://', 'https://'))
        
        if is_direct_audio:
            # Directly transcribe the audio file
            status_manager.update_status(task_id, "direct_audio", 10, "Processing direct audio file...")
            audio_path = input_url  # Use the URL directly for ASR service
        else:
            # 1. Extract YouTube audio
            audio_path = extract_youtube_audio(input_url, task_id)
        
        # 2. Transcribe audio
        transcription_result = transcribe_audio(audio_path, task_id)
        
        # 3. Translate text
        translation_result = translate_text(transcription_result, task_id)
        
        # 4. Generate audio
        output_audio_path = generate_audio(translation_result, task_id)
        
        # Update final status
        status_manager.update_status(
            task_id,
            "completed",
            100,
            "Processing completed",
            output_audio_path
        )
        
        # Clean up temporary audio file (only if it was downloaded)
        if not is_direct_audio:
            try:
                os.remove(audio_path)
            except:
                pass
                
    except Exception as e:
        error_msg = f"Processing failed: {str(e)}"
        logger.error(error_msg)
        status_manager.update_status(task_id, "error", 0, error_msg)


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
@app.post("/process")
async def process_video(background_tasks: BackgroundTasks, input_url: str = Form(...)):
    # Create task ID
    task_id = str(uuid.uuid4())
    
    # Initialize task status
    status_manager.create_task(task_id)
    
    # Run processing task in background
    background_tasks.add_task(process_youtube_to_audio, input_url, task_id)
    
    return JSONResponse({"task_id": task_id})


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    return JSONResponse(status_manager.get_status(task_id))

@app.get("/download/{task_id}")
async def download_audio(task_id: str):
    status = status_manager.get_status(task_id)
    if status.get("step") == "completed" and status.get("result"):
        audio_path = status["result"]
        if os.path.exists(audio_path):
            return FileResponse(
                audio_path,
                media_type="audio/wav",
                filename=f"translated_audio_{task_id}.wav"
            )
    raise HTTPException(status_code=404, detail="音频文件未找到")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)