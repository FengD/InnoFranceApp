# InnoFranceApp 用户指南（中文）

本指南面向使用前端界面的用户，涵盖所有功能与操作说明，并给出扩展性操作入口。

---

## 1. 产品概览

InnoFranceApp 是一个端到端音频处理管线工具，支持：

- YouTube 链接、音频 URL、或本地音频文件输入
- 自动转写（ASR + 说话人分离）
- 翻译与摘要生成
- 多说话人语音合成
- 结果预览、下载与历史管理

---

## 2. 前端界面结构

前端主界面分为三个区域：

1. **New pipeline（新任务）**
2. **Current pipelines（当前任务）**
3. **History（历史记录）**

右上角有 **Settings**，用于设置并行执行参数。

---

## 3. 新任务（New pipeline）

### 3.1 选择输入来源

支持三种输入：

- **YouTube URL**：输入完整视频链接
- **Audio URL**：输入可直接访问的 `.mp3/.wav` 链接
- **Local audio file**：本地上传 `.mp3/.wav` 文件

### 3.2 必填参数

- **Provider**：翻译/摘要 LLM 提供方
- **Model name**：必填，参考你的 LLM 配置

### 3.3 可选参数

- **Language**：ASR 识别语言
- **Chunk length**：语音切分长度（秒）
- **Speed**：合成语速

### 3.4 手动 Speaker JSON

勾选 “Provide speaker JSON after translation” 后：

- 管线在翻译完成后暂停
- 前端会出现 Speaker JSON 输入框
- 你可以粘贴自定义 `speakers.json` 内容，控制每个说话人的声音
- 不勾选时，系统会自动分配说话人配置

---

## 4. 当前任务（Current pipelines）

### 4.1 运行状态

每个任务显示：

- 状态（Queued / Running / Completed / Failed）
- 进度条（按步骤计数）
- 创建时间

### 4.2 详情查看

点击 **Show details** 展开步骤列表：

- **Audio source**：音频准备（下载/复制）
- **Transcription**：语音识别
- **Translation**：翻译
- **Summary**：摘要生成
- **Speakers**：说话人配置
- **TTS**：语音合成

如果选择了手动 Speaker JSON，这里会出现等待输入的步骤。

---

## 5. 历史记录（History）

历史记录显示已完成/失败的任务。

### 5.1 Summary 操作

- **Preview**：加载摘要文本
- **编辑**：可直接修改并保存
- **Generate summary audio**：用固定 voice prompt 生成摘要音频

### 5.2 Audio 操作

- **Preview**：在线播放对话音频
- **Download**：下载生成文件

### 5.3 Final Audio 合成

点击 **Merge final audio** 后，将以下音频合成：

1. `start_music.wav`
2. `beginning.wav`
3. Summary 音频
4. 对话音频

合成后的音频会作为最终音频展示与下载。

---

## 6. 高级能力与扩展入口

### 6.1 更换说话人风格

在 Speaker JSON 中使用不同的 `ref_audio` 和 `design_instruct` 来控制声音风格。

### 6.2 S3 持久化

当配置 S3 后，生成的音频与文本会同步上传至 S3，并可从前端直接打开。

### 6.3 多语言扩展

前端已扩展多语言选项，后端可继续补充识别与翻译支持。

---

## 7. 常见问题

**Q：为什么上传本地文件失败？**  
A：请确认文件为 `.mp3` 或 `.wav`，并重启后端确认已安装 `python-multipart`。

**Q：任务长时间停在 Speakers？**  
A：可能选择了手动 speaker 配置，请在详情中粘贴 JSON 后提交。

**Q：预览一直为空？**  
A：预览是按需加载，请等待生成完成后再预览。

