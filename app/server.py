from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import os
import shlex
import re
import requests
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import pipeline

STATIC_DIR = pipeline.BASE_DIR / "app" / "static"
ENV_PATH = pipeline.BASE_DIR / ".env"
SETTING_ENV_KEYS = {
    "whisperModel": "WHISPER_MODEL",
    "whisperDevice": "WHISPER_DEVICE",
    "whisperComputeType": "WHISPER_COMPUTE_TYPE",
    "whisperFallbackModels": "WHISPER_FALLBACK_MODELS",
    "geminiModel": "GEMINI_MODEL",
    "geminiModelFallbacks": "GEMINI_MODEL_FALLBACKS",
    "geminiApiKeys": "GEMINI_API_KEYS",
    "googleTranslateFallback": "GOOGLE_TRANSLATE_FALLBACK",
    "geminiRewritePrompt": "GEMINI_REWRITE_PROMPT",
    "geminiPostPrompt": "GEMINI_POST_PROMPT",
    "shopeeProductPrompt": "SHOPEE_PRODUCT_PROMPT",
    "shopeeAffiliateId": "SHOPEE_AFFILIATE_ID",
    "shopeeSubIdPrefix": "SHOPEE_SUB_ID_PREFIX",
    "shopeeLinkLimit": "SHOPEE_LINK_LIMIT",
    "ttsApiUrl": "TTS_API_URL",
    "ttsVoiceId": "TTS_VOICE_ID",
    "ttsModelId": "TTS_MODEL_ID",
    "ttsTimeoutSeconds": "TTS_TIMEOUT_SECONDS",
    "ttsMaxRetries": "TTS_MAX_RETRIES",
    "maxAudioSpeedupRatio": "MAX_AUDIO_SPEEDUP_RATIO",
    "ttsStrictTimeline": "TTS_STRICT_TIMELINE",
    "ttsSegmentGapMs": "TTS_SEGMENT_GAP_MS",
    "capcutPath": "CAPCUT_PATH",
    "capcutProjectDir": "CAPCUT_PROJECT_DIR",
}


@dataclass
class JobState:
    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    current_video: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)


job_state = JobState()
job_lock = threading.Lock()

app = FastAPI(title="Auto Shorts Workflow")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def video_payload(path: Path) -> dict[str, Any]:
    output_dir = pipeline.OUTPUT_DIR / pipeline.sanitize_folder_name(path.stem)
    output_files = []
    if output_dir.exists():
        for file_path in sorted(output_dir.iterdir()):
            if file_path.is_file():
                output_files.append(
                    {
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "url": f"/api/output/{pipeline.sanitize_folder_name(path.stem)}/{file_path.name}",
                    }
                )

    complete = {
        "video": any(file.name.startswith("video_goc") for file in output_dir.iterdir()) if output_dir.exists() else False,
        "subtitle": (output_dir / "sub_viet.srt").exists(),
        "audio": (output_dir / "giong_doc_viet.mp3").exists(),
        "logo": (output_dir / "logo.png").exists(),
        "campaign": (output_dir / "chien_dich_dang_bai.txt").exists(),
        "shopee": (output_dir / "shopee_links.txt").exists(),
    }

    return {
        "name": path.name,
        "stem": path.stem,
        "size": path.stat().st_size,
        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "outputDir": str(output_dir.relative_to(pipeline.BASE_DIR)),
        "complete": complete,
        "status": "done" if complete["video"] and complete["subtitle"] and complete["audio"] and complete["logo"] else "ready",
        "outputs": output_files,
    }


def snapshot_state() -> dict[str, Any]:
    with job_lock:
        return {
            "running": job_state.running,
            "startedAt": job_state.started_at,
            "finishedAt": job_state.finished_at,
            "currentVideo": job_state.current_video,
            "error": job_state.error,
            "logs": list(job_state.logs),
        }


def write_env_settings(values: dict[str, Any]) -> None:
    updates: dict[str, str] = {}
    for ui_key, env_key in SETTING_ENV_KEYS.items():
        if ui_key not in values:
            continue
        value = values[ui_key]
        if isinstance(value, list):
            text_value = ",".join(str(item).strip() for item in value if str(item).strip())
        else:
            text_value = str(value).strip()
        if text_value:
            text_value = text_value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
            updates[env_key] = text_value

    if not updates:
        return

    lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.exists() else []
    seen_keys: set[str] = set()
    for index, line in enumerate(lines):
        for env_key, text_value in updates.items():
            if re.match(rf"^\s*{re.escape(env_key)}\s*=", line):
                lines[index] = f"{env_key}={text_value}"
                seen_keys.add(env_key)

    if lines and lines[-1].strip():
        lines.append("")
    for env_key, text_value in updates.items():
        if env_key not in seen_keys:
            lines.append(f"{env_key}={text_value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pipeline.reload_settings()


def validate_settings_payload(values: dict[str, Any]) -> None:
    allowed_devices = {"cpu", "cuda", "auto"}
    allowed_compute_types = {"int8", "int8_float16", "float16", "float32"}

    device = str(values.get("whisperDevice", pipeline.WHISPER_DEVICE)).strip()
    if device not in allowed_devices:
        raise HTTPException(status_code=400, detail="WHISPER_DEVICE chi nhan cpu, cuda hoac auto")

    compute_type = str(values.get("whisperComputeType", pipeline.WHISPER_COMPUTE_TYPE)).strip()
    if compute_type not in allowed_compute_types:
        raise HTTPException(status_code=400, detail="WHISPER_COMPUTE_TYPE khong hop le")

    for key in ("ttsTimeoutSeconds", "ttsMaxRetries"):
        if key in values and int(values[key]) <= 0:
            raise HTTPException(status_code=400, detail=f"{key} phai lon hon 0")
    if "ttsSegmentGapMs" in values and int(values["ttsSegmentGapMs"]) < 0:
        raise HTTPException(status_code=400, detail="TTS_SEGMENT_GAP_MS phai >= 0")

    if "shopeeLinkLimit" in values and int(values["shopeeLinkLimit"]) <= 0:
        raise HTTPException(status_code=400, detail="SHOPEE_LINK_LIMIT phai lon hon 0")

    if "maxAudioSpeedupRatio" in values and float(values["maxAudioSpeedupRatio"]) < 1:
        raise HTTPException(status_code=400, detail="MAX_AUDIO_SPEEDUP_RATIO phai >= 1")


def selected_output_dir(project: str | None) -> Path:
    if project:
        output_dir = pipeline.OUTPUT_DIR / pipeline.sanitize_folder_name(project)
        if output_dir.exists():
            return output_dir
    latest_dirs = sorted(
        [path for path in pipeline.OUTPUT_DIR.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return latest_dirs[0] if latest_dirs else pipeline.OUTPUT_DIR


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def split_windows_command(raw_command: str) -> tuple[Path, list[str]]:
    command = raw_command.strip()
    if not command:
        return Path(""), []
    lower_command = command.lower()
    exe_index = lower_command.find(".exe")
    if exe_index >= 0:
        executable = command[: exe_index + 4].strip().strip('"')
        rest = command[exe_index + 4 :].strip()
        return Path(executable), shlex.split(rest, posix=False) if rest else []
    parts = shlex.split(command, posix=False)
    if not parts:
        return Path(""), []
    return Path(parts[0].strip('"')), parts[1:]


def capcut_import_files(output_dir: Path) -> list[Path]:
    files: list[Path] = []
    video_files = sorted(output_dir.glob("video_goc.*"))
    if video_files:
        files.append(video_files[0])
    for filename in ("sub_viet.srt", "giong_doc_viet.mp3", "logo.png"):
        file_path = output_dir / filename
        if file_path.exists():
            files.append(file_path)
    return files


def tts_output_dir() -> Path:
    output_dir = pipeline.OUTPUT_DIR / "_tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def tts_api_url_for_voice(voice_id: str | None) -> str:
    voice = (voice_id or pipeline.VOICE_ID).strip()
    if voice and "elevenlabs.io" in pipeline.API_URL:
        return f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    return pipeline.API_URL


def append_job_log(line: str) -> None:
    with job_lock:
        job_state.logs.append(line)
        job_state.logs = job_state.logs[-600:]
        if "Bat dau xu ly:" in line:
            job_state.current_video = line.rsplit(":", 1)[-1].strip()


def run_pipeline_worker(video_names: list[str]) -> None:
    try:
        with job_lock:
            job_state.running = True
            job_state.started_at = datetime.now().isoformat(timespec="seconds")
            job_state.finished_at = None
            job_state.error = None
            job_state.logs.clear()

        command = [sys.executable, "-m", "app.pipeline", "--videos", *video_names]
        append_job_log("[INFO] Khoi dong subprocess pipeline...")
        process = subprocess.Popen(
            command,
            cwd=pipeline.BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        assert process.stdout is not None
        for line in process.stdout:
            append_job_log(line.rstrip())

        return_code = process.wait()
        if return_code != 0:
            raise pipeline.PipelineError(f"Pipeline subprocess ket thuc voi ma loi {return_code}")
    except Exception as exc:
        append_job_log(f"[ERROR] Pipeline loi: {exc}")
        with job_lock:
            job_state.error = str(exc)
    finally:
        with job_lock:
            job_state.running = False
            job_state.current_video = None
            job_state.finished_at = datetime.now().isoformat(timespec="seconds")


@app.on_event("startup")
def startup() -> None:
    pipeline.ensure_directories()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "paths": {
            "base": str(pipeline.BASE_DIR),
            "input": str(pipeline.INPUT_DIR),
            "output": str(pipeline.OUTPUT_DIR),
            "temp": str(pipeline.TEMP_DIR),
        },
        "api": {
            "gemini": bool(pipeline.GEMINI_API_KEY),
            "geminiKeyCount": len(pipeline.GEMINI_API_KEYS),
            "tts": bool(pipeline.API_KEY),
        },
        "settings": {
            "whisperModel": pipeline.WHISPER_MODEL_NAME,
            "whisperDevice": pipeline.WHISPER_DEVICE,
            "whisperComputeType": pipeline.WHISPER_COMPUTE_TYPE,
            "whisperFallbackModels": pipeline.WHISPER_FALLBACK_MODELS,
            "geminiModel": pipeline.GEMINI_MODEL_NAME,
            "geminiModelFallbacks": pipeline.GEMINI_MODEL_FALLBACKS,
            "googleTranslateFallback": pipeline.GOOGLE_TRANSLATE_FALLBACK,
            "geminiRewritePrompt": pipeline.GEMINI_REWRITE_PROMPT,
            "geminiPostPrompt": pipeline.GEMINI_POST_PROMPT,
            "shopeeProductPrompt": pipeline.SHOPEE_PRODUCT_PROMPT,
            "shopeeAffiliateId": pipeline.SHOPEE_AFFILIATE_ID,
            "shopeeSubIdPrefix": pipeline.SHOPEE_SUB_ID_PREFIX,
            "shopeeLinkLimit": pipeline.SHOPEE_LINK_LIMIT,
            "ttsApiUrl": pipeline.API_URL,
            "ttsVoiceId": pipeline.VOICE_ID,
            "ttsModelId": pipeline.TTS_MODEL_ID,
            "ttsTimeoutSeconds": pipeline.TTS_TIMEOUT_SECONDS,
            "ttsMaxRetries": pipeline.TTS_MAX_RETRIES,
            "maxAudioSpeedupRatio": pipeline.MAX_AUDIO_SPEEDUP_RATIO,
            "ttsStrictTimeline": pipeline.TTS_STRICT_TIMELINE,
            "ttsSegmentGapMs": pipeline.TTS_SEGMENT_GAP_MS,
            "capcutPath": os.getenv("CAPCUT_PATH", "").strip(),
            "capcutProjectDir": os.getenv("CAPCUT_PROJECT_DIR", "").strip(),
        },
    }


@app.post("/api/config")
def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    with job_lock:
        if job_state.running:
            raise HTTPException(status_code=409, detail="Khong doi settings khi pipeline dang chay")
    validate_settings_payload(payload)
    write_env_settings(payload)
    return config()


@app.get("/api/videos")
def videos() -> dict[str, Any]:
    pipeline.ensure_directories()
    return {"videos": [video_payload(path) for path in pipeline.discover_videos()]}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    pipeline.ensure_directories()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in pipeline.VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Chi ho tro file .mp4 hoac .mkv")

    target_path = pipeline.INPUT_DIR / Path(file.filename or f"video{suffix}").name
    if target_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = pipeline.INPUT_DIR / f"{target_path.stem}_{timestamp}{target_path.suffix}"

    with target_path.open("wb") as output_file:
        shutil.copyfileobj(file.file, output_file)

    return {"video": video_payload(target_path)}


@app.post("/api/run")
async def run_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    video_names = payload.get("videos")
    if not isinstance(video_names, list) or not all(isinstance(name, str) for name in video_names):
        raise HTTPException(status_code=400, detail="Payload can co videos: string[]")
    if not video_names:
        raise HTTPException(status_code=400, detail="Chua chon video")

    with job_lock:
        if job_state.running:
            raise HTTPException(status_code=409, detail="Pipeline dang chay")
        job_state.running = True
        job_state.started_at = datetime.now().isoformat(timespec="seconds")
        job_state.finished_at = None
        job_state.error = None
        job_state.logs = ["[INFO] Dang dua job vao hang cho..."]

    worker = threading.Thread(target=run_pipeline_worker, args=(video_names,), daemon=True)
    worker.start()
    return snapshot_state()


@app.get("/api/voices")
def voices() -> dict[str, Any]:
    if not pipeline.API_KEY:
        return {
            "voices": [
                {
                    "id": pipeline.VOICE_ID,
                    "name": "Adam",
                    "description": "Giọng mặc định từ cấu hình TTS hiện tại.",
                    "category": "default",
                    "previewUrl": "",
                }
            ]
        }
    if "elevenlabs.io" not in pipeline.API_URL:
        return {
            "voices": [
                {
                    "id": pipeline.VOICE_ID,
                    "name": "Voice hiện tại",
                    "description": "API TTS custom đang được cấu hình.",
                    "category": "custom",
                    "previewUrl": "",
                }
            ]
        }
    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": pipeline.API_KEY},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Khong tai duoc voice tu TTS API: {exc}") from exc

    voice_items = []
    for item in payload.get("voices", []):
        labels = item.get("labels") or {}
        voice_items.append(
            {
                "id": item.get("voice_id", ""),
                "name": item.get("name", "Unnamed voice"),
                "description": item.get("description") or labels.get("description") or labels.get("accent") or "ElevenLabs voice",
                "category": item.get("category") or "library",
                "labels": labels,
                "previewUrl": item.get("preview_url") or "",
            }
        )
    return {"voices": voice_items}


@app.post("/api/tts/generate")
def generate_tts(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    voice_id = str(payload.get("voiceId") or pipeline.VOICE_ID).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Chua nhap van ban de tao audio")
    if len(text) > 8000:
        raise HTTPException(status_code=400, detail="Van ban toi da 8000 ky tu")
    if not pipeline.API_KEY:
        raise HTTPException(status_code=400, detail="Chua cau hinh TTS_API_KEY/ELEVENLABS_API_KEY")

    output_dir = tts_output_dir()
    filename = f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
    output_path = output_dir / filename
    try:
        client = pipeline.AdamTtsClient(api_key=pipeline.API_KEY, api_url=tts_api_url_for_voice(voice_id))
        client.synthesize_to_file(text, output_path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Khong tao duoc audio TTS: {exc}") from exc
    return {
        "status": "ok",
        "filename": filename,
        "url": f"/api/tts-output/{filename}",
        "size": output_path.stat().st_size,
        "voiceId": voice_id,
    }


@app.get("/api/job")
def job() -> dict[str, Any]:
    return snapshot_state()


@app.post("/api/open-output")
def open_output(payload: dict[str, Any]) -> dict[str, str]:
    output_dir = selected_output_dir(payload.get("project"))
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Khong tim thay thu muc output")
    try:
        open_path(output_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Khong mo duoc output: {exc}") from exc
    return {"status": "opened", "path": str(output_dir)}


@app.post("/api/open-capcut")
def open_capcut(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir = selected_output_dir(payload.get("project"))
    capcut_path = os.getenv("CAPCUT_PATH", "").strip()
    executable_path, capcut_args = split_windows_command(capcut_path)
    if capcut_path and executable_path.exists():
        import_files = capcut_import_files(output_dir)
        if len(import_files) < 4:
            missing_count = 4 - len(import_files)
            raise HTTPException(status_code=409, detail=f"Thieu {missing_count} file output de import vao CapCut")
        try:
            subprocess.Popen([str(executable_path), *capcut_args, *[str(file_path) for file_path in import_files]], cwd=str(output_dir))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Khong mo duoc CapCut: {exc}") from exc
        return {
            "status": "capcut_opened_with_files",
            "path": str(executable_path),
            "files": [str(file_path) for file_path in import_files],
        }

    try:
        open_path(output_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Khong mo duoc thu muc output: {exc}") from exc
    return {
        "status": "output_opened",
        "path": str(output_dir),
        "message": "Chua cau hinh CAPCUT_PATH, da mo thu muc output de import thu cong.",
    }


@app.get("/api/output/{project}/{filename}")
def output_file(project: str, filename: str) -> FileResponse:
    safe_project = pipeline.sanitize_folder_name(project)
    file_path = pipeline.OUTPUT_DIR / safe_project / Path(filename).name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Khong tim thay file output")
    return FileResponse(file_path, filename=file_path.name)


@app.get("/api/tts-output/{filename}")
def tts_output_file(filename: str) -> FileResponse:
    file_path = tts_output_dir() / Path(filename).name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Khong tim thay file audio TTS")
    return FileResponse(file_path, media_type="audio/mpeg", filename=file_path.name)
