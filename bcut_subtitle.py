#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bcut_subtitle.py — 必剪(bcut) 自动字幕生成工具（零依赖版）

复刻「萤火虫」的核心功能：把音频/视频文件上传到 Bilibili 必剪的免费语音识别
接口（member.bilibili.com/x/bcut/rubick-interface），自动生成带时间轴的字幕。

用法：
    python3 bcut_subtitle.py 视频.mp4                 # 输出 视频.srt
    python3 bcut_subtitle.py 音频.mp3 -f json         # 输出 音频.json
    python3 bcut_subtitle.py a.mp4 b.mp3 -o out/      # 批量，输出到 out/
    python3 bcut_subtitle.py 视频.mkv -f txt          # 纯文本（无时间轴）
    python3 bcut_subtitle.py 视频.mp4 -f lrc          # 歌词格式

依赖：
    - Python 3.8+（仅标准库，无需 pip 安装任何包）
    - 输入为视频（mp4/mkv/avi/flv...）时才需要系统安装 ffmpeg 命令

接口协议（复刻自公开的必剪 ASR 接口，免费、无需登录）：
    1. POST /resource/create          申请分片上传，拿 upload_urls[] + upload_id
    2. PUT  upload_urls[i]            逐片上传原始字节，记录每个分片的 Etag
    3. POST /resource/create/complete 提交上传，拿 download_url
    4. POST /task                     用 download_url 创建识别任务，拿 task_id
    5. GET  /task/result              轮询结果（state==4 完成）
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE + "/resource/create"
API_COMMIT_UPLOAD = API_BASE + "/resource/create/complete"
API_CREATE_TASK = API_BASE + "/task"
API_QUERY_RESULT = API_BASE + "/task/result"

MODEL_ID = 7  # 必剪免费 ASR 模型
AUDIO_EXTS = {"flac", "aac", "m4a", "mp3", "wav"}
OUTPUT_EXTS = {"srt", "json", "txt", "lrc"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _ssl_context():
    """构建 SSL 上下文。

    macOS 上 python.org 自带的 OpenSSL 常缺 B 站 CDN 的中间证书，导致
    CERTIFICATE_VERIFY_FAILED；优先用 certifi（Mozilla 证书库）解决，否则降级。
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return ssl._create_unverified_context()


_VERIFY_CTX = _ssl_context()
_UNVERIFIED_CTX = ssl._create_unverified_context()


class APIError(Exception):
    """必剪接口返回错误。"""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _request(method, url, form=None, json_body=None, raw=None, timeout=60):
    """发送 HTTP 请求，返回 (headers, bytes)。"""
    headers = {"User-Agent": UA, "Referer": "https://member.bilibili.com/"}
    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif raw is not None:
        body = raw
    # 先正常校验证书；若仅因证书链问题失败，降级为不校验重试一次
    for ctx in (_VERIFY_CTX, _UNVERIFIED_CTX):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise APIError(exc.code, detail[:300]) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError) and ctx is _VERIFY_CTX:
                continue  # 证书校验失败，用不校验上下文重试
            raise APIError(-1, f"网络错误: {exc.reason}") from exc
    raise APIError(-1, "网络错误: SSL 连接失败")


def _find_ffmpeg():
    """定位 ffmpeg：打包成 exe 时优先用 exe 同目录的 ffmpeg.exe，否则用 PATH。"""
    if getattr(sys, "frozen", False):
        local = os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
        if os.path.isfile(local):
            return local
    return "ffmpeg"


def extract_audio(path):
    """用 ffmpeg 提取视频伴音，转码为单声道 aac（ADTS），返回 bytes。"""
    cmd = [_find_ffmpeg(), "-v", "warning", "-i", path, "-ac", "1", "-f", "adts", "pipe:1"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 转码失败：" + proc.stderr.decode("utf-8", "ignore")[-400:])
    return proc.stdout


class BcutASR:
    """必剪语音识别客户端。"""

    def __init__(self):
        self.task_id = None

    # ---- 上传三步：申请 -> 分片 -> 提交 ----
    def upload(self, data, fmt, name):
        self.sound_bin = data
        self.sound_fmt = fmt
        self.sound_name = name

        _, raw = _request("POST", API_REQ_UPLOAD, form={
            "type": 2,
            "name": self.sound_name,
            "size": len(self.sound_bin),
            "resource_file_type": self.sound_fmt,
            "model_id": MODEL_ID,
        })
        resp = json.loads(raw)
        if resp.get("code"):
            raise APIError(resp["code"], resp.get("message", "unknown"))
        d = resp["data"]
        self._in_boss_key = d["in_boss_key"]
        self._resource_id = d["resource_id"]
        self._upload_urls = d["upload_urls"]
        self._upload_id = d["upload_id"]
        self._per_size = d["per_size"]
        log(f"申请上传成功，共 {len(self._upload_urls)} 个分片")

        self._upload_parts()
        self._commit()

    def _upload_parts(self):
        self._etags = []
        for i, url in enumerate(self._upload_urls):
            start = i * self._per_size
            end = start + self._per_size
            headers, _ = _request("PUT", url, raw=self.sound_bin[start:end])
            self._etags.append(headers.get("Etag", ""))
            log(f"分片 {i + 1}/{len(self._upload_urls)} 上传完成")

    def _commit(self):
        _, raw = _request("POST", API_COMMIT_UPLOAD, form={
            "in_boss_key": self._in_boss_key,
            "resource_id": self._resource_id,
            "etags": ",".join(self._etags),
            "upload_id": self._upload_id,
            "model_id": MODEL_ID,
        })
        resp = json.loads(raw)
        if resp.get("code"):
            raise APIError(resp["code"], resp.get("message", "unknown"))
        self._download_url = resp["data"]["download_url"]
        log("提交上传成功")

    # ---- 创建任务 ----
    def create_task(self):
        _, raw = _request("POST", API_CREATE_TASK, json_body={
            "resource": self._download_url,
            "model_id": str(MODEL_ID),
        })
        resp = json.loads(raw)
        if resp.get("code"):
            raise APIError(resp["code"], resp.get("message", "unknown"))
        self.task_id = resp["data"]["task_id"]
        log(f"识别任务已创建: {self.task_id}")
        return self.task_id

    # ---- 轮询结果 ----
    def result(self):
        url = API_QUERY_RESULT + "?" + urllib.parse.urlencode({
            "model_id": MODEL_ID,
            "task_id": self.task_id,
        })
        _, raw = _request("GET", url)
        resp = json.loads(raw)
        if resp.get("code"):
            raise APIError(resp["code"], resp.get("message", "unknown"))
        return resp["data"]


# ---- 输出格式转换 ----
def ms_to_srt(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(utterances):
    out = []
    for i, seg in enumerate(utterances, 1):
        out.append(
            f"{i}\n{ms_to_srt(seg['start_time'])} --> {ms_to_srt(seg['end_time'])}\n"
            f"{seg['transcript']}\n"
        )
    return "\n".join(out)


def to_txt(utterances):
    return "\n".join(seg["transcript"] for seg in utterances)


def to_lrc(utterances):
    out = []
    for seg in utterances:
        ms = seg["start_time"]
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        out.append(f"[{m:02d}:{s:02d}.{ms // 10:02d}]{seg['transcript']}")
    return "\n".join(out)


def log(msg):
    print(msg, flush=True)


def convert_one(inpath, outdir, fmt, interval):
    stem = os.path.splitext(os.path.basename(inpath))[0]
    ext = os.path.splitext(inpath)[1].lstrip(".").lower()

    if ext in AUDIO_EXTS:
        with open(inpath, "rb") as f:
            audio = f.read()
        afmt = ext
        log(f"输入为音频({ext})，直接识别: {inpath}")
    else:
        log(f"输入为视频，调用 ffmpeg 提取伴音: {inpath}")
        audio = extract_audio(inpath)
        afmt = "aac"

    asr = BcutASR()
    asr.upload(audio, afmt, f"{stem}.{afmt}")
    asr.create_task()

    while True:
        r = asr.result()
        state = r["state"]
        if state == 0:
            log("等待识别开始…")
        elif state == 1:
            log(f"识别中… {r.get('remark', '')}")
        elif state == 3:
            raise APIError(-1, f"识别失败: {r.get('remark', '')}")
        elif state == 4:
            log("识别成功")
            result = json.loads(r["result"])
            break
        time.sleep(interval)

    utterances = result.get("utterances", [])
    if not utterances:
        raise APIError(-1, "未识别到语音")

    outpath = os.path.join(outdir, f"{stem}.{fmt}")
    if fmt == "srt":
        content = to_srt(utterances)
    elif fmt == "txt":
        content = to_txt(utterances)
    elif fmt == "lrc":
        content = to_lrc(utterances)
    else:  # json
        content = json.dumps(result, ensure_ascii=False, indent=2)

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"已输出: {outpath}")
    return outpath


def _banner():
    return (
        "==============================================\n"
        "  必剪(bcut) 自动字幕工具  v1.0\n"
        "  免费 · 无需登录 · 音频/视频 → 字幕\n"
        "==============================================\n"
        "  输出格式: srt / json / txt / lrc\n"
        "  音频(mp3/wav/m4a/flac/aac): 直接识别\n"
        "  视频(mp4/mkv/avi/flv): 需同目录放 ffmpeg.exe\n"
    )


def _pause():
    try:
        input("\n按回车键退出...")
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    ap = argparse.ArgumentParser(
        description="必剪(bcut) 自动字幕工具（复刻萤火虫核心功能，免费、无需登录）"
    )
    ap.add_argument("inputs", nargs="*", help="输入媒体文件（可多个；留空进入交互模式）")
    ap.add_argument("-f", "--format", default="srt", choices=sorted(OUTPUT_EXTS),
                    help="输出格式（默认 srt）")
    ap.add_argument("-o", "--outdir", default=None, help="输出目录（默认与输入同目录）")
    ap.add_argument("-i", "--interval", type=float, default=2.0, help="轮询间隔/秒（默认 2）")
    ap.add_argument("--pause", action="store_true", help="结束后暂停（双击 exe 时建议加）")
    args = ap.parse_args()

    # 双击 exe 无参数 → 进入交互模式
    interactive = not args.inputs
    if interactive:
        print(_banner())
        inputs = []
        print("逐个输入媒体文件路径（也可把文件拖进本窗口后回车），空行结束：")
        while True:
            try:
                line = input("> ").strip().strip('"')
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            inputs.append(line)
        args.inputs = inputs
        if not args.inputs:
            print("未输入任何文件。")
            _pause()
            return

    for inpath in args.inputs:
        if not os.path.isfile(inpath):
            log(f"跳过，文件不存在: {inpath}")
            continue
        outdir = args.outdir or os.path.dirname(os.path.abspath(inpath)) or "."
        os.makedirs(outdir, exist_ok=True)
        try:
            convert_one(inpath, outdir, args.format, args.interval)
        except APIError as e:
            print(f"[错误] {inpath}: {e}", file=sys.stderr)
        except RuntimeError as e:
            print(f"[错误] {inpath}: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            sys.exit(130)

    if interactive or args.pause:
        _pause()


if __name__ == "__main__":
    main()
