# bcut-subtitle — 必剪自动字幕工具

复刻「萤火虫」的核心功能：调用 Bilibili 必剪的免费语音识别接口，把音频/视频
自动转成带时间轴的字幕。**免费、无需登录/API key、纯本地脚本**。

## 快速开始

```bash
# 音频直接识别
python3 bcut_subtitle.py 录音.mp3

# 视频自动提取伴音（需要系统安装 ffmpeg）
python3 bcut_subtitle.py 视频.mp4

# 指定格式 / 批量 / 输出目录
python3 bcut_subtitle.py a.mp4 b.mp3 -f json -o out/
```

输出格式：`srt`（默认，字幕）、`json`（原始结果）、`txt`（纯文本）、`lrc`（歌词）。

## 打包成 Windows exe

> 注意：PyInstaller **不支持跨平台编译**，必须在 Windows 上执行打包。

在 **Windows** 机器上：

1. 安装 Python 3.8+（勾选 "Add python.exe to PATH"）→ https://www.python.org/downloads/
2. 把本项目文件夹（`bcut_subtitle.py` + `build.bat`）复制到 Windows
3. **双击 `build.bat`**，自动安装 PyInstaller 并打包
4. 完成后 exe 位于 `dist\bcut_subtitle.exe`

exe 用法：

- **双击运行**：交互式输入文件路径（或把文件拖进窗口回车）
- **拖拽到 exe 上**：直接把媒体文件拖到 `bcut_subtitle.exe` 图标，自动在同目录生成 `.srt`
- **命令行**：`bcut_subtitle.exe 视频.mp4 -f json`

如需识别**视频**文件，把 `ffmpeg.exe` 放到 exe 同目录即可（音频无需）。自定义图标：在 `build.bat` 里给打包命令加 `--icon app.ico`。

## 依赖

- **Python 3.8+**（只用标准库，无需 pip 安装）
- 仅当输入是**视频**时才需要 `ffmpeg`：
  - macOS: `brew install ffmpeg`
  - Windows: 下载 ffmpeg 放到 exe 同目录（或加入 PATH）
  - 音频（mp3/wav/m4a/flac/aac）无需 ffmpeg

## 工作原理（必剪 ASR 接口协议）

基地址 `https://member.bilibili.com/x/bcut/rubick-interface`，`model_id = 7`（免费模型）：

| 步骤 | 请求 | 作用 |
|---|---|---|
| 1 | `POST /resource/create` | 申请分片上传，返回 `upload_urls[]`、`upload_id`、`in_boss_key` |
| 2 | `PUT upload_urls[i]` | 逐片上传字节，记录每片响应头 `Etag` |
| 3 | `POST /resource/create/complete` | 提交上传，返回 `download_url` |
| 4 | `POST /task` | 用 `download_url` 创建识别任务，返回 `task_id` |
| 5 | `GET /task/result` | 轮询直到 `state == 4`，返回逐句字幕 |

识别结果结构：

```json
{"utterances": [
  {"start_time": 0, "end_time": 2600, "transcript": "你好世界",
   "words": [{"label": "你", "start_time": 0, "end_time": 600}, ...]}
]}
```

## 免责声明

仅供个人学习、测试使用。接口归 Bilibili 必剪所有，请勿用于商业用途或高频滥用。
