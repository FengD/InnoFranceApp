# InnoFranceApp User Guide (English)

This guide explains every UI operation, each pipeline step, and available advanced actions.

---

## 1. Overview

InnoFranceApp is an end-to-end audio pipeline that supports:

- YouTube URLs, audio URLs, or local audio uploads
- Automatic transcription (ASR + speaker diarization)
- Translation and summary generation
- Multi-speaker voice synthesis
- Preview, download, and history tracking

---

## 2. UI Layout

The main UI contains:

1. **New pipeline**
2. **Current pipelines**
3. **History**

The **Settings** button in the header controls parallel execution.

---

## 3. New Pipeline

### 3.1 Input sources

Choose one:

- **YouTube URL**: paste a full video link
- **Audio URL**: direct `.mp3/.wav` link
- **Local audio file**: upload `.mp3/.wav`

### 3.2 Required fields

- **Provider**: LLM provider for translation/summary
- **Model name**: required; matches your provider setup

### 3.3 Optional fields

- **Language**: ASR language code
- **Chunk length**: ASR chunk length in seconds
- **Speed**: TTS playback speed

### 3.4 Manual speaker JSON

If you enable “Provide speaker JSON after translation”:

- The pipeline pauses after translation
- A speaker JSON input appears in the job details
- Paste custom `speakers.json` content to control voices
- If unchecked, speakers are generated automatically

---

## 4. Current Pipelines

### 4.1 Status & progress

Each job shows:

- Status (Queued / Running / Completed / Failed)
- Progress bar based on step count
- Created time

### 4.2 Step details

Click **Show details** to view step-by-step progress:

- **Audio source**: download/copy input audio
- **Transcription**: ASR + speaker diarization
- **Translation**: translate transcript
- **Summary**: generate summary text
- **Speakers**: build speaker configs
- **TTS**: multi-speaker voice synthesis

If manual speakers are enabled, this panel shows the waiting input.

---

## 5. History

History lists completed/failed jobs.

### 5.1 Summary actions

- **Preview**: load summary text
- **Edit**: update and save summary
- **Generate summary audio**: synthesize summary audio

### 5.2 Audio actions

- **Preview**: play the dialogue audio
- **Download**: download files

### 5.3 Final audio merge

Click **Merge final audio** to combine:

1. `start_music.wav`
2. `beginning.wav`
3. summary audio
4. dialogue audio

The merged output is available for preview and download.

---

## 6. Advanced Features

### 6.1 Custom voice profiles

Provide `ref_audio` and `design_instruct` in speaker JSON to control voice style.

### 6.2 S3 persistence

When S3 is configured, generated assets are uploaded and can be opened from UI.

### 6.3 Language expansion

The UI exposes multiple languages; backend support can be extended further.

---

## 7. FAQ

**Q: Upload fails for local audio.**  
A: Ensure the file is `.mp3` or `.wav` and `python-multipart` is installed on the API.

**Q: The pipeline is waiting at “Speakers”.**  
A: Manual speaker input is enabled; paste JSON in the details panel.

**Q: Preview is empty.**  
A: Preview is lazy-loaded; wait for generation to finish and click preview.

