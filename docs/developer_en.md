# InnoFranceApp Developer Guide (English)

This guide covers extension points and recommended implementation paths.

---

## 1. Add new input sources

Goal: support new resource types (e.g., object storage links, databases, etc.).

Recommended steps:

1. **Frontend**
   - Add a new `Source` option in `PipelineForm`
   - Add corresponding input fields or upload logic
2. **Backend**
   - Extend `PipelineStartRequest` with new fields
   - Update `_detect_source_kind` in `pipeline.py`
   - Add a new processing branch in `run()`

Keep the invariant: **only one input source at a time** and all files under `INNOFRANCE_RUNS_DIR`.

---

## 2. Support more audio formats

Currently only `.mp3/.wav` are supported. To add `.m4a/.flac`, etc.:

1. Update upload validation in `api/app.py` (`_save_upload`)
2. Update `_is_audio_path/_is_audio_url` in `pipeline.py`
3. Convert input to `.mp3` or `.wav` using ffmpeg

Also verify ASR supports the new format.

---

## 3. Add new LLM providers

Translation and summary use `InnoFranceTranslateAGENT`:

1. Add provider in `LLMType` (`core/backend/configs/llm_config.py`)
2. Add provider config and request logic
3. Add provider option in `PipelineForm`

---

## 4. Add new translation languages

The UI list can be extended, but ensure:

1. ASR supports the language
2. Any ASR language mapping is updated if needed
3. Update UI language options

---

## 5. Add new pipeline steps

Recommended flow:

1. Add logic and `_emit` calls in `pipeline.py`
2. Add the step to `PIPELINE_STEPS`
3. Update `STEP_ORDER` and labels in the frontend

---

## 6. S3 archival strategy

Current S3 layout:

```
<prefix>/<run_dir>/*
```

For date-based or custom layouts, modify key prefix rules in `queue.py` upload logic.

---

## 7. Development workflow

1. Keep API and UI changes in sync
2. Implement APIs before UI
3. Keep preview/download lazy-loaded

