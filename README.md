# bcut-subtitle — 必剪自动字幕工具

复刻「萤火虫」的核心功能：调用 Bilibili 必剪的免费语音识别接口，把音频/视频
自动转成带时间轴的字幕。**免费、无需登录/API key、纯本地脚本**。

## 快速开始

```bash
# 无参数启动图形界面（GUI）
python3 bcut_subtitle.py

# 音频直接识别（命令行）
python3 bcut_subtitle.py --cli 录音.mp3

# 视频自动提取伴音（需要系统安装 ffmpeg）
python3 bcut_subtitle.py --cli 视频.mp4

# 指定格式 / 批量 / 输出目录
python3 bcut_subtitle.py --cli a.mp4 b.mp3 -f json -o out/
```

输出格式：`srt`（默认，字幕）、`json`（原始结果）、`txt`（纯文本）、`lrc`（歌词）。

**图形界面（GUI）**：双击 exe 或运行 `python3 bcut_subtitle.py` 打开，可「添加文件 → 选格式 → 开始识别」，进度实时显示在窗口里。

## 打包成 Windows exe

> 注意：PyInstaller **不支持跨平台编译**，必须在 Windows 上执行打包。

**方式 A：云端打包（无需 Windows）** —— 推送到 GitHub 仓库后，`.github/workflows/build.yml` 自动在云端 Windows 环境编译，产出两个 exe 到 Releases：

- `bcut_subtitle.exe` —— **图形界面**（双击即用，无控制台窗口）
- `bcut_subtitle_cli.exe` —— **命令行**（带控制台，适合拖拽/脚本批量）

**方式 B：本地打包（在 Windows 机器上）**：

1. 安装 Python 3.8+（勾选 "Add python.exe to PATH"）→ https://www.python.org/downloads/
2. 把本项目文件夹复制到 Windows
3. **双击 `build.bat`**，自动安装 PyInstaller 并打包
4. 完成后两个 exe 位于 `dist\` 目录

exe 用法：

- **双击 `bcut_subtitle.exe`**：打开图形界面
- **拖拽到 `bcut_subtitle_cli.exe` 上**：把媒体文件拖到 CLI 版图标，自动在同目录生成 `.srt`
- **命令行**：`bcut_subtitle_cli.exe 视频.mp4 -f json`

如需识别**视频**文件，把 `ffmpeg.exe` 放到 exe 同目录即可（音频无需）。自定义图标：在 `build.bat` 里给 GUI 版打包命令加 `--icon app.ico`。

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
