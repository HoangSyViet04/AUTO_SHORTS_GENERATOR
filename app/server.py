from __future__ import annotations

import shutil
import subprocess
import sys
import threading
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
    "ttsApiUrl": "TTS_API_URL",
    "ttsVoiceId": "TTS_VOICE_ID",
    "ttsModelId": "TTS_MODEL_ID",
    "ttsTimeoutSeconds": "TTS_TIMEOUT_SECONDS",
    "ttsMaxRetries": "TTS_MAX_RETRIES",
    "maxAudioSpeedupRatio": "MAX_AUDIO_SPEEDUP_RATIO",
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
    }

    return {
        "name": path.name,
        "stem": path.stem,
        "size": path.stat().st_size,
        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "outputDir": str(output_dir.relative_to(pipeline.BASE_DIR)),
        "complete": complete,
        "status": "done" if all(complete.values()) else "ready",
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
            updates[env_key] = text_value

    if not updates:
        return

    lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.exists() else []
    seen_keys: set[str] = set()
    for index, line in enumerate(lines):
        for env_key, text_value in updates.items():
            if line.strip().startswith(f"{env_key}="):
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

    if "maxAudioSpeedupRatio" in values and float(values["maxAudioSpeedupRatio"]) < 1:
        raise HTTPException(status_code=400, detail="MAX_AUDIO_SPEEDUP_RATIO phai >= 1")


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
            "tts": bool(pipeline.API_KEY),
        },
        "settings": {
            "whisperModel": pipeline.WHISPER_MODEL_NAME,
            "whisperDevice": pipeline.WHISPER_DEVICE,
            "whisperComputeType": pipeline.WHISPER_COMPUTE_TYPE,
            "whisperFallbackModels": pipeline.WHISPER_FALLBACK_MODELS,
            "geminiModel": pipeline.GEMINI_MODEL_NAME,
            "ttsApiUrl": pipeline.API_URL,
            "ttsVoiceId": pipeline.VOICE_ID,
            "ttsModelId": pipeline.TTS_MODEL_ID,
            "ttsTimeoutSeconds": pipeline.TTS_TIMEOUT_SECONDS,
            "ttsMaxRetries": pipeline.TTS_MAX_RETRIES,
            "maxAudioSpeedupRatio": pipeline.MAX_AUDIO_SPEEDUP_RATIO,
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


@app.get("/api/job")
def job() -> dict[str, Any]:
    return snapshot_state()


@app.get("/api/output/{project}/{filename}")
def output_file(project: str, filename: str) -> FileResponse:
    safe_project = pipeline.sanitize_folder_name(project)
    file_path = pipeline.OUTPUT_DIR / safe_project / Path(filename).name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Khong tim thay file output")
    return FileResponse(file_path, filename=file_path.name)
