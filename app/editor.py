from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app import pipeline


EDITOR_SCHEMA_VERSION = 3
EDITOR_OUTPUT_NAME = "video_final.mp4"
SUBTITLE_TEMPLATES = {"classic", "reveal", "karaoke", "pop", "neon"}
WORD_EFFECT_TEMPLATES = {"pop", "neon"}
WORD_EFFECT_PACE_RATIO = 0.92
WORD_EFFECT_LEAD_MS = 90


@dataclass
class EditorRenderState:
    running: bool = False
    project: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    output: str | None = None
    logs: list[str] = field(default_factory=list)


render_state = EditorRenderState()
render_lock = threading.Lock()
composition_lock = threading.Lock()


def _output_dir(project: str) -> Path:
    safe_project = pipeline.sanitize_folder_name(project)
    output_dir = pipeline.OUTPUT_DIR / safe_project
    if not output_dir.exists() or not output_dir.is_dir():
        raise FileNotFoundError(f"Khong tim thay output project: {safe_project}")
    return output_dir


def _source_video(output_dir: Path) -> Path:
    candidates = sorted(output_dir.glob("video_goc.*"))
    if not candidates:
        raise FileNotFoundError("Project chua co video_goc")
    return candidates[0]


def _probe_media(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    return {
        "duration": round(float((payload.get("format") or {}).get("duration") or 0), 3),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "hasAudio": any(item.get("codec_type") == "audio" for item in streams),
    }


def _asset_payload(output_dir: Path, file_path: Path | None, kind: str) -> dict[str, Any] | None:
    if not file_path or not file_path.exists():
        return None
    project = output_dir.name
    return {
        "kind": kind,
        "name": file_path.name,
        "path": str(file_path.relative_to(pipeline.BASE_DIR)).replace("\\", "/"),
        "url": f"/api/editor/media/{project}/{file_path.name}",
        "size": file_path.stat().st_size,
    }


def _subtitle_cues(subtitle_path: Path) -> list[dict[str, Any]]:
    if not subtitle_path.exists():
        return []
    try:
        segments = pipeline.parse_srt(subtitle_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    return [
        {
            "id": segment.index,
            "startMs": segment.start_ms,
            "endMs": segment.end_ms,
            "text": segment.text.strip(),
        }
        for segment in segments
    ]


def _clean_spoken_text(text: Any) -> str:
    cleaned = re.sub(r"\[[^\]\n]{1,60}\]\s*", "", str(text or ""))
    cleaned = re.sub(r"\s+([,.!?;:…])", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _voice_subtitle_cues(metadata_path: Path) -> list[dict[str, Any]]:
    if not metadata_path.exists():
        return []
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return []

    audio_duration_ms = max(0, int(payload.get("audio_duration_ms") or 0))
    cues: list[dict[str, Any]] = []
    for position, chunk in enumerate(payload.get("chunks") or [], start=1):
        try:
            start_ms = max(0, int(chunk["position_ms"]))
            duration_ms = max(10, int(chunk["rendered_duration_ms"]))
        except (KeyError, TypeError, ValueError):
            continue
        text = _clean_spoken_text(chunk.get("enhanced_text") or chunk.get("raw_text"))
        if not text:
            continue
        end_ms = start_ms + duration_ms
        if audio_duration_ms:
            end_ms = min(end_ms, audio_duration_ms)
        if end_ms <= start_ms:
            continue
        cues.append(
            {
                "id": f"voice-{chunk.get('chunk_id') or position}",
                "startMs": start_ms,
                "endMs": end_ms,
                "text": text,
            }
        )
    return cues


def _env_number(name: str, fallback: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(os.getenv(name, str(fallback)))))
    except (TypeError, ValueError):
        return fallback


def _env_color(name: str, fallback: str) -> str:
    value = os.getenv(name, fallback).strip().upper()
    if len(value) == 7 and value.startswith("#") and all(char in "0123456789ABCDEF" for char in value[1:]):
        return value
    return fallback


def default_editor_settings() -> dict[str, Any]:
    template = os.getenv("EDITOR_SUBTITLE_TEMPLATE", "classic").strip().lower()
    if template not in SUBTITLE_TEMPLATES:
        template = "classic"
    logo_position = os.getenv("EDITOR_LOGO_POSITION", "top-right").strip().lower()
    if logo_position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        logo_position = "top-right"
    render_preset = os.getenv("EDITOR_RENDER_PRESET", "medium").strip().lower()
    if render_preset not in {"veryfast", "faster", "fast", "medium", "slow"}:
        render_preset = "medium"
    return {
        "canvas": {"width": 1080, "height": 1920, "fit": "cover"},
        "subtitle": {
            "enabled": True,
            "font": "Arial",
            "fontSize": round(_env_number("EDITOR_SUBTITLE_FONT_SIZE", 48, 24, 84)),
            "template": template,
            "color": _env_color("EDITOR_SUBTITLE_COLOR", "#FFFFFF"),
            "accentColor": _env_color("EDITOR_SUBTITLE_ACCENT_COLOR", "#FACC15"),
            "outlineColor": _env_color("EDITOR_SUBTITLE_OUTLINE_COLOR", "#050816"),
            "background": _env_color("EDITOR_SUBTITLE_BACKGROUND", "#000000"),
            "backgroundOpacity": _env_number("EDITOR_SUBTITLE_BACKGROUND_OPACITY", 0.58, 0, 1),
            "marginBottom": round(_env_number("EDITOR_SUBTITLE_MARGIN_BOTTOM", 140, 30, 520)),
        },
        "logo": {
            "enabled": True,
            "width": round(_env_number("EDITOR_LOGO_WIDTH", 180, 60, 480)),
            "opacity": _env_number("EDITOR_LOGO_OPACITY", 0.95, 0.1, 1),
            "position": logo_position,
            "margin": 48,
        },
        "audio": {
            "voiceVolume": _env_number("EDITOR_VOICE_VOLUME", 1.0, 0, 2),
            "sourceVolume": _env_number("EDITOR_SOURCE_VOLUME", 0.0, 0, 1),
        },
        "export": {"preset": render_preset, "crf": 20, "audioBitrate": "192k"},
    }


def build_editor_manifest(project: str, persist: bool = True) -> dict[str, Any]:
    output_dir = _output_dir(project)
    video_path = _source_video(output_dir)
    subtitle_path = output_dir / "sub_viet.srt"
    voice_path = output_dir / "giong_doc_viet.mp3"
    logo_path = output_dir / "logo.png"
    final_path = output_dir / EDITOR_OUTPUT_NAME
    media = _probe_media(video_path)
    manifest_path = output_dir / "editor_project.json"
    settings = default_editor_settings()
    if manifest_path.exists():
        try:
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            settings = normalize_editor_options(saved_manifest.get("settings"))
            if int(saved_manifest.get("schemaVersion") or 1) < 2 and abs(settings["audio"]["sourceVolume"] - 0.12) < 0.001:
                settings["audio"]["sourceVolume"] = default_editor_settings()["audio"]["sourceVolume"]
            settings["canvas"] = default_editor_settings()["canvas"]
        except (OSError, ValueError, TypeError):
            settings = default_editor_settings()
    cues = _subtitle_cues(subtitle_path)
    voice_cues = _voice_subtitle_cues(output_dir / "tts_script.json")

    manifest = {
        "schema": "auto-shorts.opencut-bridge",
        "schemaVersion": EDITOR_SCHEMA_VERSION,
        "project": output_dir.name,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "duration": media["duration"],
        "source": {**media, **(_asset_payload(output_dir, video_path, "video") or {})},
        "assets": {
            "voice": _asset_payload(output_dir, voice_path, "audio"),
            "subtitle": _asset_payload(output_dir, subtitle_path, "subtitle"),
            "logo": _asset_payload(output_dir, logo_path, "image"),
            "finalVideo": _asset_payload(output_dir, final_path, "video"),
        },
        "tracks": [
            {"id": "video", "type": "video", "label": "Video nguồn", "start": 0, "duration": media["duration"]},
            {"id": "voice", "type": "audio", "label": "Giọng lồng tiếng", "start": 0, "duration": media["duration"]},
            {
                "id": "subtitle",
                "type": "subtitle",
                "label": "Phụ đề Việt",
                "start": 0,
                "duration": media["duration"],
                "clips": cues,
                "voiceClips": voice_cues,
            },
            {"id": "logo", "type": "overlay", "label": "Logo kênh", "start": 0, "duration": media["duration"]},
        ],
        "settings": settings,
        "bridge": {
            "target": "OpenCut",
            "mode": "adapter-preview",
            "note": "Manifest on dinh de map sang Editor API/headless cua OpenCut khi API chinh thuc san sang.",
        },
    }
    if persist:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return manifest


def save_editor_settings(project: str, options: dict[str, Any] | None) -> dict[str, Any]:
    manifest = build_editor_manifest(project, persist=False)
    settings = normalize_editor_options(options)
    settings["canvas"] = default_editor_settings()["canvas"]
    manifest["settings"] = settings
    output_dir = _output_dir(project)
    (output_dir / "editor_project.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def render_snapshot() -> dict[str, Any]:
    with render_lock:
        return {
            "running": render_state.running,
            "project": render_state.project,
            "startedAt": render_state.started_at,
            "finishedAt": render_state.finished_at,
            "error": render_state.error,
            "output": render_state.output,
            "logs": list(render_state.logs),
        }


def _log(message: str) -> None:
    with render_lock:
        render_state.logs.append(message)
        render_state.logs = render_state.logs[-100:]


def _clamp_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _hex_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip().upper()
    if len(text) == 7 and text.startswith("#") and all(char in "0123456789ABCDEF" for char in text[1:]):
        return text
    return fallback


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    red, green, blue = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{alpha:02X}{blue}{green}{red}"


def _ffmpeg_filter_path(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")


def _ass_inline_color(hex_color: str) -> str:
    red, green, blue = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{blue}{green}{red}&"


def _ass_timestamp(milliseconds: int) -> str:
    total_centiseconds = max(0, round(milliseconds / 10))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _word_weight(word: str) -> float:
    clean_word = word.strip(".,!?;:…")
    length_bonus = min(0.35, max(0, len(clean_word) - 2) * 0.05)
    pause_bonus = 0.16 if word.rstrip().endswith((",", ".", "!", "?", ";", ":", "…")) else 0
    return 1 + length_bonus + pause_bonus


def _word_intervals(
    words: list[str],
    start_ms: int,
    end_ms: int,
    *,
    pace_ratio: float = 1,
    lead_ms: int = 0,
) -> list[tuple[int, int]]:
    if not words:
        return []
    duration = max(10, end_ms - start_ms)
    paced_duration = max(10, round(duration * max(0.5, min(1, pace_ratio))))
    weights = [_word_weight(word) for word in words]
    total_weight = sum(weights)
    intervals: list[tuple[int, int]] = []
    elapsed_weight = 0
    for index, weight in enumerate(weights):
        interval_start = start_ms + max(0, round(paced_duration * elapsed_weight / total_weight) - lead_ms)
        elapsed_weight += weight
        interval_end = (
            end_ms
            if index == len(words) - 1
            else start_ms + max(10, round(paced_duration * elapsed_weight / total_weight) - lead_ms)
        )
        safe_start = min(interval_start, max(start_ms, end_ms - 10))
        intervals.append((safe_start, max(safe_start + 10, min(interval_end, end_ms))))
    return intervals


def _styled_words(words: list[str], active_index: int, subtitle: dict[str, Any], template: str) -> str:
    base_color = _ass_inline_color(subtitle["color"])
    accent_color = _ass_inline_color(subtitle["accentColor"])
    chunks: list[str] = []
    for index, word in enumerate(words):
        escaped = _ass_escape(word)
        if index == active_index:
            if template == "pop":
                chunks.append(
                    rf"{{\1c{accent_color}\fscx128\fscy128\t(0,70,\fscx100\fscy100)}}{escaped}{{\1c{base_color}}}"
                )
            elif template == "neon":
                chunks.append(rf"{{\1c{accent_color}\blur2}}{escaped}{{\1c{base_color}\blur0}}")
            else:
                chunks.append(rf"{{\1c{accent_color}}}{escaped}{{\1c{base_color}}}")
        elif template in {"karaoke", "neon"} and index > active_index:
            chunks.append(rf"{{\alpha&H88&}}{escaped}{{\alpha&H00&}}")
        else:
            chunks.append(escaped)
    return " ".join(chunks)


def _build_styled_subtitle_file(
    subtitle_path: Path,
    output_path: Path,
    subtitle: dict[str, Any],
    voice_timing_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segments = pipeline.parse_srt(subtitle_path.read_text(encoding="utf-8-sig"))
    template = subtitle["template"]
    if template in WORD_EFFECT_TEMPLATES and voice_timing_path:
        voice_cues = _voice_subtitle_cues(voice_timing_path)
        if voice_cues:
            segments = [
                pipeline.SrtSegment(
                    index=index,
                    start_ms=int(cue["startMs"]),
                    end_ms=int(cue["endMs"]),
                    text=str(cue["text"]),
                )
                for index, cue in enumerate(voice_cues, start=1)
            ]
    border_style = 3 if template == "classic" else 1
    outline_width = 2 if template == "classic" else 4 if template in {"pop", "neon"} else 3
    shadow = 0 if template != "neon" else 2
    font_size = subtitle["fontSize"] + (12 if template == "pop" else 4 if template == "neon" else 0)
    background_alpha = round((1 - subtitle["backgroundOpacity"]) * 255)
    back_color = _ass_color(subtitle["background"], background_alpha if template == "classic" else 255)
    style = ",".join(
        [
            "Default",
            subtitle["font"],
            str(font_size),
            _ass_color(subtitle["color"]),
            _ass_color(subtitle["color"]),
            _ass_color(subtitle["outlineColor"]),
            back_color,
            "-1",
            "0",
            "0",
            "0",
            "100",
            "100",
            "0",
            "0",
            str(border_style),
            str(outline_width),
            str(shadow),
            "2",
            "72",
            "72",
            str(subtitle["marginBottom"]),
            "1",
        ]
    )
    events: list[str] = []
    for segment in segments:
        words = segment.text.replace("\n", " ").split()
        if not words:
            continue
        if template == "classic":
            events.append(
                f"Dialogue: 0,{_ass_timestamp(segment.start_ms)},{_ass_timestamp(segment.end_ms)},Default,,0,0,0,,{_ass_escape(segment.text)}"
            )
            continue
        intervals = _word_intervals(
            words,
            segment.start_ms,
            segment.end_ms,
            pace_ratio=WORD_EFFECT_PACE_RATIO if template in WORD_EFFECT_TEMPLATES else 1,
            lead_ms=WORD_EFFECT_LEAD_MS if template in WORD_EFFECT_TEMPLATES else 0,
        )
        for index, (interval_start, interval_end) in enumerate(intervals):
            if template == "reveal":
                visible_words = words[: index + 1]
                text = _styled_words(visible_words, len(visible_words) - 1, subtitle, template)
            elif template == "pop":
                text = _styled_words([words[index]], 0, subtitle, template)
            else:
                text = _styled_words(words, index, subtitle, template)
            events.append(
                f"Dialogue: 0,{_ass_timestamp(interval_start)},{_ass_timestamp(interval_end)},Default,,0,0,0,,{text}"
            )
    content = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: {style}",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
    output_path.write_text(content, encoding="utf-8-sig")
    return output_path


def normalize_editor_options(payload: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_editor_settings()
    payload = payload or {}
    subtitle = payload.get("subtitle") or {}
    logo = payload.get("logo") or {}
    audio = payload.get("audio") or {}
    export = payload.get("export") or {}
    return {
        "subtitle": {
            "enabled": bool(subtitle.get("enabled", True)),
            "font": str(subtitle.get("font") or "Arial")[:80],
            "fontSize": round(_clamp_number(subtitle.get("fontSize"), 24, 84, defaults["subtitle"]["fontSize"])),
            "template": str(subtitle.get("template") or defaults["subtitle"]["template"])
            if str(subtitle.get("template") or defaults["subtitle"]["template"]) in SUBTITLE_TEMPLATES
            else defaults["subtitle"]["template"],
            "color": _hex_color(subtitle.get("color"), defaults["subtitle"]["color"]),
            "accentColor": _hex_color(subtitle.get("accentColor"), defaults["subtitle"]["accentColor"]),
            "outlineColor": _hex_color(subtitle.get("outlineColor"), defaults["subtitle"]["outlineColor"]),
            "background": _hex_color(subtitle.get("background"), defaults["subtitle"]["background"]),
            "backgroundOpacity": _clamp_number(subtitle.get("backgroundOpacity"), 0, 1, defaults["subtitle"]["backgroundOpacity"]),
            "marginBottom": round(_clamp_number(subtitle.get("marginBottom"), 30, 520, defaults["subtitle"]["marginBottom"])),
        },
        "logo": {
            "enabled": bool(logo.get("enabled", True)),
            "width": round(_clamp_number(logo.get("width"), 60, 480, defaults["logo"]["width"])),
            "opacity": _clamp_number(logo.get("opacity"), 0.1, 1, defaults["logo"]["opacity"]),
            "position": str(logo.get("position") or defaults["logo"]["position"]),
            "margin": round(_clamp_number(logo.get("margin"), 0, 180, defaults["logo"]["margin"])),
        },
        "audio": {
            "voiceVolume": _clamp_number(audio.get("voiceVolume"), 0, 2, defaults["audio"]["voiceVolume"]),
            "sourceVolume": _clamp_number(audio.get("sourceVolume"), 0, 1, defaults["audio"]["sourceVolume"]),
        },
        "export": {
            "preset": str(export.get("preset") or defaults["export"]["preset"])
            if str(export.get("preset") or defaults["export"]["preset"]) in {"veryfast", "faster", "fast", "medium", "slow"}
            else defaults["export"]["preset"],
            "crf": round(_clamp_number(export.get("crf"), 16, 30, defaults["export"]["crf"])),
            "audioBitrate": defaults["export"]["audioBitrate"],
        },
    }


def _logo_position(position: str, margin: int) -> tuple[str, str]:
    positions = {
        "top-left": (str(margin), str(margin)),
        "top-right": (f"W-w-{margin}", str(margin)),
        "bottom-left": (str(margin), f"H-h-{margin}"),
        "bottom-right": (f"W-w-{margin}", f"H-h-{margin}"),
    }
    return positions.get(position, positions["top-right"])


def missing_composition_assets(output_dir: Path) -> list[str]:
    return [
        name for name in ("sub_viet.srt", "giong_doc_viet.mp3")
        if not (output_dir / name).is_file() or (output_dir / name).stat().st_size == 0
    ]


def build_ffmpeg_command(project: str, options: dict[str, Any] | None = None) -> tuple[list[str], Path, Path]:
    output_dir = _output_dir(project)
    video_path = _source_video(output_dir)
    subtitle_path = output_dir / "sub_viet.srt"
    voice_path = output_dir / "giong_doc_viet.mp3"
    missing_assets = missing_composition_assets(output_dir)
    if missing_assets:
        raise RuntimeError(f"Pipeline chua hoan tat: thieu {', '.join(missing_assets)}. Hay kiem tra tab Logs va chay lai pipeline.")
    logo_path = output_dir / "logo.png"
    output_path = output_dir / EDITOR_OUTPUT_NAME
    temporary_path = output_dir / "video_final.rendering.mp4"
    media = _probe_media(video_path)
    settings = normalize_editor_options(options)

    command = ["ffmpeg", "-y", "-i", str(video_path)]
    input_index = 1
    logo_index: int | None = None
    voice_index: int | None = None
    if settings["logo"]["enabled"] and logo_path.exists():
        logo_index = input_index
        command.extend(["-loop", "1", "-i", str(logo_path)])
        input_index += 1
    if voice_path.exists():
        voice_index = input_index
        command.extend(["-i", str(voice_path)])

    filters = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[canvas]"]
    video_label = "canvas"
    if logo_index is not None:
        logo = settings["logo"]
        x_value, y_value = _logo_position(logo["position"], logo["margin"])
        filters.append(
            f"[{logo_index}:v]scale={logo['width']}:-1,format=rgba,colorchannelmixer=aa={logo['opacity']:.3f}[logo]"
        )
        filters.append(f"[{video_label}][logo]overlay=x={x_value}:y={y_value}:format=auto[branded]")
        video_label = "branded"

    subtitle = settings["subtitle"]
    if subtitle["enabled"] and subtitle_path.exists():
        styled_subtitle_path = _build_styled_subtitle_file(
            subtitle_path,
            pipeline.TEMP_DIR / "editor" / output_dir.name / "subtitle_editor.ass",
            subtitle,
            output_dir / "tts_script.json",
        )
        filters.append(f"[{video_label}]subtitles=filename='{_ffmpeg_filter_path(styled_subtitle_path)}'[vout]")
        video_label = "vout"

    audio_label: str | None = None
    source_volume = settings["audio"]["sourceVolume"]
    voice_volume = settings["audio"]["voiceVolume"]
    duration = float(media["duration"] or 0)
    if voice_index is not None and media["hasAudio"] and source_volume > 0:
        filters.extend(
            [
                f"[0:a]volume={source_volume:.3f}[source_audio]",
                f"[{voice_index}:a]volume={voice_volume:.3f}[voice_audio]",
                "[source_audio][voice_audio]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixed_audio]",
            ]
        )
        audio_label = "mixed_audio"
    elif voice_index is not None:
        filters.append(f"[{voice_index}:a]volume={voice_volume:.3f},apad[voice_audio]")
        audio_label = "voice_audio"
    elif media["hasAudio"]:
        filters.append(f"[0:a]volume={max(source_volume, 0.001):.3f}[source_audio]")
        audio_label = "source_audio"

    command.extend(["-filter_complex", ";".join(filters), "-map", f"[{video_label}]"])
    if audio_label:
        command.extend(["-map", f"[{audio_label}]"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            settings["export"]["preset"],
            "-crf",
            str(settings["export"]["crf"]),
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if audio_label:
        command.extend(["-c:a", "aac", "-b:a", settings["export"]["audioBitrate"]])
    if duration > 0:
        command.extend(["-t", f"{duration:.3f}"])
    command.extend(["-movflags", "+faststart", str(temporary_path)])
    return command, temporary_path, output_path


def render_editor_project(
    project: str,
    options: dict[str, Any] | None = None,
    log_callback: Any | None = None,
) -> Path:
    def emit(message: str) -> None:
        if log_callback:
            log_callback(message)

    temporary_path: Path | None = None
    with composition_lock:
        try:
            emit("[EDITOR] Dang tao FFmpeg composition...")
            command, temporary_path, output_path = build_ffmpeg_command(project, options)
            emit("[EDITOR] Dang render video 9:16, subtitle, logo va voice...")
            process = subprocess.run(
                command,
                cwd=pipeline.BASE_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process.returncode != 0:
                error_tail = "\n".join((process.stderr or "").splitlines()[-18:])
                raise RuntimeError(error_tail or f"FFmpeg ket thuc voi ma {process.returncode}")
            if not temporary_path.exists() or temporary_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg khong tao duoc file video")
            shutil.move(str(temporary_path), str(output_path))
            build_editor_manifest(project, persist=True)
            emit(f"[EDITOR] Da xuat {output_path.name}")
            return output_path
        except Exception:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
            raise


def _render_worker(project: str, options: dict[str, Any] | None) -> None:
    try:
        output_path = render_editor_project(project, options, _log)
        with render_lock:
            render_state.output = str(output_path.relative_to(pipeline.BASE_DIR)).replace("\\", "/")
    except Exception as exc:
        _log(f"[EDITOR][ERROR] {exc}")
        with render_lock:
            render_state.error = str(exc)
    finally:
        with render_lock:
            render_state.running = False
            render_state.finished_at = datetime.now().isoformat(timespec="seconds")


def start_editor_render(project: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    output_dir = _output_dir(project)
    missing_assets = missing_composition_assets(output_dir)
    if missing_assets:
        raise RuntimeError(f"Pipeline chua hoan tat: thieu {', '.join(missing_assets)}. Hay kiem tra tab Logs va chay lai pipeline.")
    with render_lock:
        if render_state.running:
            raise RuntimeError(f"Editor dang render project {render_state.project}")
        save_editor_settings(project, options)
        render_state.running = True
        render_state.project = pipeline.sanitize_folder_name(project)
        render_state.started_at = datetime.now().isoformat(timespec="seconds")
        render_state.finished_at = None
        render_state.error = None
        render_state.output = None
        render_state.logs = []
    thread = threading.Thread(target=_render_worker, args=(project, options), daemon=True)
    thread.start()
    return render_snapshot()
