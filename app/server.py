from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import os
import shlex
import re
import json
import mimetypes
import requests
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import editor, pipeline

STATIC_DIR = pipeline.BASE_DIR / "app" / "static"
ENV_PATH = pipeline.BASE_DIR / ".env"
PIPELINE_LOG_PATH = pipeline.BASE_DIR / "logs" / "pipeline_latest.log"
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
    "ttsEnhancePrompt": "TTS_ENHANCE_PROMPT",
    "shopeeProductPrompt": "SHOPEE_PRODUCT_PROMPT",
    "shopeeAffiliateId": "SHOPEE_AFFILIATE_ID",
    "shopeeSubIdPrefix": "SHOPEE_SUB_ID_PREFIX",
    "shopeeLinkLimit": "SHOPEE_LINK_LIMIT",
    "ttsApiUrl": "TTS_API_URL",
    "ttsApiKey": "TTS_API_KEY",
    "ttsMode": "TTS_MODE",
    "ttsEnhanceEnabled": "TTS_ENHANCE_ENABLED",
    "ttsSemanticChunkEnabled": "TTS_SEMANTIC_CHUNK_ENABLED",
    "ttsAudioFirst": "TTS_AUDIO_FIRST",
    "ttsQualityModelId": "TTS_QUALITY_MODEL_ID",
    "ttsFastModelId": "TTS_FAST_MODEL_ID",
    "ttsVoiceId": "TTS_VOICE_ID",
    "ttsModelId": "TTS_MODEL_ID",
    "ttsTimeoutSeconds": "TTS_TIMEOUT_SECONDS",
    "ttsMaxRetries": "TTS_MAX_RETRIES",
    "maxAudioSpeedupRatio": "MAX_AUDIO_SPEEDUP_RATIO",
    "ttsFinalSpeedupRatio": "TTS_FINAL_SPEEDUP_RATIO",
    "ttsQualityMaxSpeedupRatio": "TTS_QUALITY_MAX_SPEEDUP_RATIO",
    "ttsQualityFinalSpeedupRatio": "TTS_QUALITY_FINAL_SPEEDUP_RATIO",
    "ttsStrictTimeline": "TTS_STRICT_TIMELINE",
    "ttsSegmentGapMs": "TTS_SEGMENT_GAP_MS",
    "ttsMaxSilenceGapMs": "TTS_MAX_SILENCE_GAP_MS",
    "ttsReuseSegments": "TTS_REUSE_SEGMENTS",
    "ttsChunkMaxChars": "TTS_CHUNK_MAX_CHARS",
    "ttsChunkMaxSegments": "TTS_CHUNK_MAX_SEGMENTS",
    "ttsTargetCharsPerSecond": "TTS_TARGET_CHARS_PER_SECOND",
    "ttsUseDurationTextBudget": "TTS_USE_DURATION_TEXT_BUDGET",
    "ttsFitAudioToVideo": "TTS_FIT_AUDIO_TO_VIDEO",
    "ttsEmergencyFinalSpeedupRatio": "TTS_EMERGENCY_FINAL_SPEEDUP_RATIO",
    "ttsVoiceStability": "TTS_VOICE_STABILITY",
    "ttsVoiceSimilarity": "TTS_VOICE_SIMILARITY",
    "ttsVoiceStyle": "TTS_VOICE_STYLE",
    "ttsPreserveScript": "TTS_PRESERVE_SCRIPT",
    "ttsLeadInMs": "TTS_LEAD_IN_MS",
    "capcutPath": "CAPCUT_PATH",
    "capcutProjectDir": "CAPCUT_PROJECT_DIR",
    "openCutUrl": "OPENCUT_URL",
    "editorAutoRender": "EDITOR_AUTO_RENDER",
    "editorSubtitleTemplate": "EDITOR_SUBTITLE_TEMPLATE",
    "editorSubtitleFontSize": "EDITOR_SUBTITLE_FONT_SIZE",
    "editorSubtitleMarginBottom": "EDITOR_SUBTITLE_MARGIN_BOTTOM",
    "editorSubtitleColor": "EDITOR_SUBTITLE_COLOR",
    "editorSubtitleAccentColor": "EDITOR_SUBTITLE_ACCENT_COLOR",
    "editorSubtitleOutlineColor": "EDITOR_SUBTITLE_OUTLINE_COLOR",
    "editorSubtitleBackground": "EDITOR_SUBTITLE_BACKGROUND",
    "editorSubtitleBackgroundOpacity": "EDITOR_SUBTITLE_BACKGROUND_OPACITY",
    "editorLogoPosition": "EDITOR_LOGO_POSITION",
    "editorLogoWidth": "EDITOR_LOGO_WIDTH",
    "editorLogoOpacity": "EDITOR_LOGO_OPACITY",
    "editorVoiceVolume": "EDITOR_VOICE_VOLUME",
    "editorSourceVolume": "EDITOR_SOURCE_VOLUME",
    "editorRenderPreset": "EDITOR_RENDER_PRESET",
    "facebookPageId": "FACEBOOK_PAGE_ID",
    "facebookPageUrl": "FACEBOOK_PAGE_URL",
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
        "finalVideo": (output_dir / "video_final.mp4").exists(),
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
        if ui_key in {"facebookPageId", "facebookPageUrl"} and not text_value:
            updates[env_key] = ""
        if text_value:
            text_value = text_value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
            if env_key in {
                "EDITOR_SUBTITLE_COLOR",
                "EDITOR_SUBTITLE_ACCENT_COLOR",
                "EDITOR_SUBTITLE_OUTLINE_COLOR",
                "EDITOR_SUBTITLE_BACKGROUND",
            }:
                text_value = f'"{text_value}"'
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

    tts_mode = str(values.get("ttsMode", pipeline.TTS_MODE)).strip().lower()
    if tts_mode not in {"quality", "fast"}:
        raise HTTPException(status_code=400, detail="TTS_MODE chi nhan quality hoac fast")

    for key in ("ttsTimeoutSeconds", "ttsMaxRetries", "ttsChunkMaxChars", "ttsChunkMaxSegments"):
        if key in values and int(values[key]) <= 0:
            raise HTTPException(status_code=400, detail=f"{key} phai lon hon 0")
    if "ttsSegmentGapMs" in values and int(values["ttsSegmentGapMs"]) < 0:
        raise HTTPException(status_code=400, detail="TTS_SEGMENT_GAP_MS phai >= 0")

    if "shopeeLinkLimit" in values and int(values["shopeeLinkLimit"]) <= 0:
        raise HTTPException(status_code=400, detail="SHOPEE_LINK_LIMIT phai lon hon 0")

    for key in (
        "maxAudioSpeedupRatio",
        "ttsFinalSpeedupRatio",
        "ttsQualityMaxSpeedupRatio",
        "ttsQualityFinalSpeedupRatio",
        "ttsTargetCharsPerSecond",
        "ttsEmergencyFinalSpeedupRatio",
    ):
        if key in values and float(values[key]) < 1:
            raise HTTPException(status_code=400, detail=f"{SETTING_ENV_KEYS[key]} phai >= 1")
    for key in ("ttsVoiceStability", "ttsVoiceSimilarity", "ttsVoiceStyle"):
        if key in values and not 0 <= float(values[key]) <= 1:
            raise HTTPException(status_code=400, detail=f"{SETTING_ENV_KEYS[key]} phai trong khoang 0-1")
    if "ttsMaxSilenceGapMs" in values and int(values["ttsMaxSilenceGapMs"]) < 0:
        raise HTTPException(status_code=400, detail="TTS_MAX_SILENCE_GAP_MS phai >= 0")
    if "ttsLeadInMs" in values and int(values["ttsLeadInMs"]) < 0:
        raise HTTPException(status_code=400, detail="TTS_LEAD_IN_MS phai >= 0")

    if "editorSubtitleTemplate" in values and str(values["editorSubtitleTemplate"]) not in editor.SUBTITLE_TEMPLATES:
        raise HTTPException(status_code=400, detail="EDITOR_SUBTITLE_TEMPLATE khong hop le")
    if "editorLogoPosition" in values and str(values["editorLogoPosition"]) not in {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    }:
        raise HTTPException(status_code=400, detail="EDITOR_LOGO_POSITION khong hop le")
    if "editorRenderPreset" in values and str(values["editorRenderPreset"]) not in {
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
    }:
        raise HTTPException(status_code=400, detail="EDITOR_RENDER_PRESET khong hop le")

    editor_ranges = {
        "editorSubtitleFontSize": (24, 84),
        "editorSubtitleMarginBottom": (30, 520),
        "editorSubtitleBackgroundOpacity": (0, 1),
        "editorLogoWidth": (60, 480),
        "editorLogoOpacity": (0.1, 1),
        "editorVoiceVolume": (0, 2),
        "editorSourceVolume": (0, 1),
    }
    for key, (minimum, maximum) in editor_ranges.items():
        if key in values and not minimum <= float(values[key]) <= maximum:
            raise HTTPException(
                status_code=400,
                detail=f"{SETTING_ENV_KEYS[key]} phai trong khoang {minimum}-{maximum}",
            )

    for key in (
        "editorSubtitleColor",
        "editorSubtitleAccentColor",
        "editorSubtitleOutlineColor",
        "editorSubtitleBackground",
    ):
        if key in values and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(values[key]).strip()):
            raise HTTPException(status_code=400, detail=f"{SETTING_ENV_KEYS[key]} khong phai ma mau HEX hop le")

    if "facebookPageId" in values and str(values["facebookPageId"]).strip():
        if not re.fullmatch(r"\d+", str(values["facebookPageId"]).strip()):
            raise HTTPException(status_code=400, detail="FACEBOOK_PAGE_ID phai la day so")
    if "facebookPageUrl" in values and str(values["facebookPageUrl"]).strip():
        page_url = urlparse(str(values["facebookPageUrl"]).strip())
        if (
            page_url.scheme != "https"
            or page_url.netloc not in {"facebook.com", "www.facebook.com", "web.facebook.com", "m.facebook.com"}
            or not page_url.path.strip("/")
        ):
            raise HTTPException(status_code=400, detail="FACEBOOK_PAGE_URL phai la link https://www.facebook.com/...")


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


def reveal_file(path: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer.exe", "/select,", str(path)])
    else:
        open_path(path.parent)


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
        try:
            PIPELINE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with PIPELINE_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
        except OSError:
            pass


def environment_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def run_pipeline_worker(video_names: list[str]) -> None:
    try:
        with job_lock:
            job_state.running = True
            job_state.started_at = datetime.now().isoformat(timespec="seconds")
            job_state.finished_at = None
            job_state.error = None
            job_state.logs.clear()
        PIPELINE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        PIPELINE_LOG_PATH.write_text("", encoding="utf-8")

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
        if environment_flag("EDITOR_AUTO_RENDER", True):
            for video_name in video_names:
                project = Path(video_name).stem
                append_job_log(f"[EDITOR] Auto compose project: {project}")
                manifest = editor.build_editor_manifest(project)
                editor.render_editor_project(project, manifest.get("settings"), append_job_log)
        else:
            append_job_log("[EDITOR] Auto render dang tat; project san sang de chinh trong Video Editor.")
    except Exception as exc:
        append_job_log(f"[ERROR] Pipeline loi: {exc}")
        with job_lock:
            job_state.error = next(
                (line.removeprefix("[ERROR] ") for line in reversed(job_state.logs)
                 if line.startswith("[ERROR]") and "Pipeline loi:" not in line),
                str(exc),
            )
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
    editor_defaults = editor.default_editor_settings()
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
            "facebookPageConfigured": bool(
                os.getenv("FACEBOOK_PAGE_URL", "").strip() or os.getenv("FACEBOOK_PAGE_ID", "").strip()
            ),
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
            "ttsEnhancePrompt": pipeline.TTS_ENHANCE_PROMPT,
            "shopeeProductPrompt": pipeline.SHOPEE_PRODUCT_PROMPT,
            "shopeeAffiliateId": pipeline.SHOPEE_AFFILIATE_ID,
            "shopeeSubIdPrefix": pipeline.SHOPEE_SUB_ID_PREFIX,
            "shopeeLinkLimit": pipeline.SHOPEE_LINK_LIMIT,
            "ttsApiUrl": pipeline.API_URL,
            "ttsMode": pipeline.TTS_MODE,
            "ttsEnhanceEnabled": pipeline.TTS_ENHANCE_ENABLED,
            "ttsSemanticChunkEnabled": pipeline.TTS_SEMANTIC_CHUNK_ENABLED,
            "ttsAudioFirst": pipeline.TTS_AUDIO_FIRST,
            "ttsQualityModelId": pipeline.TTS_QUALITY_MODEL_ID,
            "ttsFastModelId": pipeline.TTS_FAST_MODEL_ID,
            "ttsVoiceId": pipeline.VOICE_ID,
            "ttsModelId": pipeline.TTS_MODEL_ID,
            "ttsTimeoutSeconds": pipeline.TTS_TIMEOUT_SECONDS,
            "ttsMaxRetries": pipeline.TTS_MAX_RETRIES,
            "maxAudioSpeedupRatio": pipeline.MAX_AUDIO_SPEEDUP_RATIO,
            "ttsFinalSpeedupRatio": pipeline.TTS_FINAL_SPEEDUP_RATIO,
            "ttsQualityMaxSpeedupRatio": pipeline.TTS_QUALITY_MAX_SPEEDUP_RATIO,
            "ttsQualityFinalSpeedupRatio": pipeline.TTS_QUALITY_FINAL_SPEEDUP_RATIO,
            "ttsStrictTimeline": pipeline.TTS_STRICT_TIMELINE,
            "ttsSegmentGapMs": pipeline.TTS_SEGMENT_GAP_MS,
            "ttsMaxSilenceGapMs": pipeline.TTS_MAX_SILENCE_GAP_MS,
            "ttsReuseSegments": pipeline.TTS_REUSE_SEGMENTS,
            "ttsChunkMaxChars": pipeline.TTS_CHUNK_MAX_CHARS,
            "ttsChunkMaxSegments": pipeline.TTS_CHUNK_MAX_SEGMENTS,
            "ttsTargetCharsPerSecond": pipeline.TTS_TARGET_CHARS_PER_SECOND,
            "ttsUseDurationTextBudget": pipeline.TTS_USE_DURATION_TEXT_BUDGET,
            "ttsFitAudioToVideo": pipeline.TTS_FIT_AUDIO_TO_VIDEO,
            "ttsEmergencyFinalSpeedupRatio": pipeline.TTS_EMERGENCY_FINAL_SPEEDUP_RATIO,
            "ttsVoiceStability": pipeline.TTS_VOICE_STABILITY,
            "ttsVoiceSimilarity": pipeline.TTS_VOICE_SIMILARITY,
            "ttsVoiceStyle": pipeline.TTS_VOICE_STYLE,
            "ttsPreserveScript": pipeline.TTS_PRESERVE_SCRIPT,
            "ttsLeadInMs": pipeline.TTS_LEAD_IN_MS,
            "capcutPath": os.getenv("CAPCUT_PATH", "").strip(),
            "capcutProjectDir": os.getenv("CAPCUT_PROJECT_DIR", "").strip(),
            "openCutUrl": os.getenv("OPENCUT_URL", "http://localhost:5173").strip() or "http://localhost:5173",
            "editorAutoRender": environment_flag("EDITOR_AUTO_RENDER", True),
            "editorSubtitleTemplate": editor_defaults["subtitle"]["template"],
            "editorSubtitleFontSize": editor_defaults["subtitle"]["fontSize"],
            "editorSubtitleMarginBottom": editor_defaults["subtitle"]["marginBottom"],
            "editorSubtitleColor": editor_defaults["subtitle"]["color"],
            "editorSubtitleAccentColor": editor_defaults["subtitle"]["accentColor"],
            "editorSubtitleOutlineColor": editor_defaults["subtitle"]["outlineColor"],
            "editorSubtitleBackground": editor_defaults["subtitle"]["background"],
            "editorSubtitleBackgroundOpacity": round(editor_defaults["subtitle"]["backgroundOpacity"] * 100),
            "editorLogoPosition": editor_defaults["logo"]["position"],
            "editorLogoWidth": editor_defaults["logo"]["width"],
            "editorLogoOpacity": round(editor_defaults["logo"]["opacity"] * 100),
            "editorVoiceVolume": round(editor_defaults["audio"]["voiceVolume"] * 100),
            "editorSourceVolume": round(editor_defaults["audio"]["sourceVolume"] * 100),
            "editorRenderPreset": editor_defaults["export"]["preset"],
            "facebookPageId": os.getenv("FACEBOOK_PAGE_ID", "").strip(),
            "facebookPageUrl": os.getenv("FACEBOOK_PAGE_URL", "").strip(),
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


@app.get("/api/editor/project/{project}")
def editor_project(project: str) -> dict[str, Any]:
    try:
        return editor.build_editor_manifest(project)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Khong doc duoc media project: {exc}") from exc


@app.get("/api/editor/media/{project}/{filename}")
def editor_media(project: str, filename: str) -> FileResponse:
    output_dir = pipeline.OUTPUT_DIR / pipeline.sanitize_folder_name(project)
    file_path = output_dir / Path(filename).name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Khong tim thay media editor")
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@app.post("/api/editor/render")
def editor_render(payload: dict[str, Any]) -> dict[str, Any]:
    project = str(payload.get("project") or "").strip()
    if not project:
        raise HTTPException(status_code=400, detail="Chua chon project de render")
    try:
        return editor.start_editor_render(project, payload.get("settings") or {})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/editor/render")
def editor_render_status() -> dict[str, Any]:
    return editor.render_snapshot()


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


@app.post("/api/publish/final-video")
async def upload_final_video(project: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".mp4":
        raise HTTPException(status_code=400, detail="Video final de dang bai phai la file .mp4")
    output_dir = pipeline.OUTPUT_DIR / pipeline.sanitize_folder_name(project)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Khong tim thay output cua project")

    target_path = output_dir / "video_final.mp4"
    temporary_path = output_dir / "video_final.uploading.mp4"
    with temporary_path.open("wb") as output_file:
        shutil.copyfileobj(file.file, output_file)
    if temporary_path.stat().st_size <= 0:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File video final rong")
    temporary_path.replace(target_path)
    return {
        "status": "ready",
        "name": target_path.name,
        "size": target_path.stat().st_size,
        "url": f"/api/output/{pipeline.sanitize_folder_name(project)}/{target_path.name}",
    }


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


@app.get("/api/tts/history")
def tts_history() -> dict[str, Any]:
    output_dir = tts_output_dir()
    files = sorted(output_dir.glob("*.mp3"), key=lambda path: path.stat().st_mtime, reverse=True)
    return {
        "items": [
            {
                "filename": file_path.name,
                "url": f"/api/tts-output/{file_path.name}",
                "size": file_path.stat().st_size,
                "createdAt": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for file_path in files[:50]
        ]
    }


@app.get("/api/job")
def job() -> dict[str, Any]:
    return snapshot_state()


@app.post("/api/open-output")
def open_output(payload: dict[str, Any]) -> dict[str, str]:
    if payload.get("file"):
        project = payload.get("project")
        if not isinstance(project, str) or not project or payload["file"] != "video_final.mp4":
            raise HTTPException(status_code=400, detail="Chi co the mo video_final.mp4 cua project da chon")
        target = pipeline.OUTPUT_DIR / pipeline.sanitize_folder_name(project) / "video_final.mp4"
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Chua co video_final.mp4 trong project da chon")
        try:
            reveal_file(target)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Khong hien duoc file video: {exc}") from exc
        return {"status": "opened", "path": str(target)}

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
