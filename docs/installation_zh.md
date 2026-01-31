# InnoFranceApp 安装与启动指南（中文）

本指南说明如何安装所有相关工程、目录结构要求、环境变量配置，以及启动方式。

---

## 1. 必须的工程（Git clone）

请直接使用以下命令克隆（HTTP）：

```
git clone https://github.com/FengD/InnoFranceApp.git
git clone https://github.com/FengD/InnoFranceYTAudioExtractor.git
git clone https://github.com/FengD/InnoFranceASRService.git
git clone https://github.com/FengD/InnoFranceTranslateAGENT.git
git clone https://github.com/FengD/InnoFranceVoiceGenerateAgent.git
```

请确保以下工程都在同一个父目录下（建议放在同一个 repo 根目录）：

- `InnoFranceApp`（主应用）
- `InnoFranceYTAudioExtractor`
- `InnoFranceASRService`
- `InnoFranceTranslateAGENT`
- `InnoFranceVoiceGenerateAgent`

推荐结构：

```
InnoFranceProject/
├── InnoFranceApp/
├── InnoFranceYTAudioExtractor/
├── InnoFranceASRService/
├── InnoFranceTranslateAGENT/
└── InnoFranceVoiceGenerateAgent/
```

---

## 2. 安装依赖

### 2.1 主应用（conda）

```
conda create -n inno-france python=3.10 -y
conda activate inno-france
pip install -r requirements.txt
```

### 2.2 主应用（venv）

```
cd InnoFranceApp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.3 MCP 服务依赖

从项目根目录执行：

```
pip install -r InnoFranceYTAudioExtractor/requirements.txt
pip install -r InnoFranceASRService/requirements.txt
pip install -r InnoFranceTranslateAGENT/requirements.txt
pip install -r InnoFranceVoiceGenerateAgent/requirements.txt
```

---

## 3. 配置环境变量

复制模板：

```
cp env.example .env
```

重点配置项：

- `INNOFRANCE_RUNS_DIR`：生成文件目录
- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`：翻译/摘要服务
- 模型路径：`WHISPER_MODEL_PATH`、`VOICE_DESIGN_MODEL_PATH` 等
- S3（可选）：`INNOFRANCE_S3_ENDPOINT` 等

如需手动指定根目录，可设置：

```
INNOFRANCE_PROJECT_ROOT=/path/to/InnoFranceProject
```

---

## 4. 启动后端 API

```
python3 -m inno_france_app.server --host 127.0.0.1 --port 8000
```

---

## 5. 启动前端

```
cd InnoFranceApp/frontend
npm install
npm run dev
```

打开浏览器：

```
http://localhost:5173
```

---

## 6. 常见问题

**Q：本地上传失败？**  
A：确认 `python-multipart` 已安装并重启后端。

**Q：模型加载失败？**  
A：检查模型路径和 GPU 环境。

