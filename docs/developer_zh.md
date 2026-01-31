# InnoFranceApp 开发者指南（中文）

本指南面向需要扩展能力的开发者，包含常见扩展点与建议实现路径。

---

## 1. 扩展资源类型（新增输入来源）

目标：支持新的资源类型（例如 OSS、网盘、数据库文件等）。

建议步骤：

1. **前端**
   - 在 `PipelineForm` 增加新的 `Source` 选项
   - 增加对应输入字段或上传逻辑
2. **后端**
   - 扩展 `PipelineStartRequest` 新字段
   - 在 `pipeline.py` 的 `_detect_source_kind` 中新增识别逻辑
   - 在 `run()` 中新增分支处理

扩展时需要保持：

- 仅允许一种输入来源
- 文件必须落在 `INNOFRANCE_RUNS_DIR` 下

---

## 2. 扩展音频格式（mp3/wav 以外）

当前仅支持 `.mp3/.wav`。要支持 `.m4a/.flac` 等：

1. **上传校验**
   - 修改 `api/app.py` 的 `_save_upload` 校验后缀
2. **路径校验**
   - 修改 `pipeline.py` 的 `_is_audio_path/_is_audio_url`
3. **音频转换**
   - 统一转换成 `.mp3` 或 `.wav`（建议使用 ffmpeg）

注意：ASR 服务是否支持新格式也需要确认。

---

## 3. 扩展 LLM Provider

翻译/摘要使用 `InnoFranceTranslateAGENT`：

1. 在 `InnoFranceTranslateAGENT/core/backend/configs/llm_config.py` 中加入新的 `LLMType`
2. 增加对应 provider 的配置读取与请求逻辑
3. 在前端 `PipelineForm` Provider 列表中增加选项

---

## 4. 扩展翻译语言

前端语言下拉已支持扩展，但你需要：

1. 确认 ASR 服务支持新语言
2. 可能需要改 ASR 语言映射（若外部服务需要特殊 code）
3. 更新前端语言列表

---

## 5. 扩展管线步骤

新增步骤建议：

1. 在 `pipeline.py` 中加入步骤逻辑与 `_emit`
2. 在 `PIPELINE_STEPS` 中加入步骤顺序
3. 前端 `JobCard` 的步骤映射新增展示文案
4. 在 `STEP_ORDER` 中加入新步骤

---

## 6. S3 归档策略

当前所有输出都会上传到：

```
<prefix>/<run_dir>/*
```

如需更复杂的目录结构（如按日期分层），可在 `queue.py` 的上传逻辑中调整 key 前缀规则。

---

## 7. 建议的开发流程

1. 保持后端与前端接口同步
2. 新功能先写 API，再写 UI
3. 预览和下载建议保持“按需加载”

