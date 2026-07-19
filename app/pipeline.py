from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)
INPUT_DIR = BASE_DIR / "input_videos"
OUTPUT_DIR = BASE_DIR / "output_results"
TEMP_DIR = BASE_DIR / "temp" / "translation_pipeline"

VIDEO_EXTENSIONS = {".mp4", ".mkv"}
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
WHISPER_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("WHISPER_FALLBACK_MODELS", "small,base").split(",")
    if model.strip()
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"

VOICE_ID = os.getenv("TTS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
API_KEY = (os.getenv("TTS_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or "").strip()
API_URL = (
    os.getenv("TTS_API_URL")
    or f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
).strip()
TTS_MODEL_ID = os.getenv("TTS_MODEL_ID", "eleven_flash_v2_5").strip() or "eleven_flash_v2_5"
TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "90"))
TTS_MAX_RETRIES = int(os.getenv("TTS_MAX_RETRIES", "3"))
MAX_AUDIO_SPEEDUP_RATIO = float(os.getenv("MAX_AUDIO_SPEEDUP_RATIO", "1.35"))


def reload_settings() -> None:
    global WHISPER_MODEL_NAME
    global WHISPER_DEVICE
    global WHISPER_COMPUTE_TYPE
    global WHISPER_FALLBACK_MODELS
    global GEMINI_API_KEY
    global GEMINI_MODEL_NAME
    global VOICE_ID
    global API_KEY
    global API_URL
    global TTS_MODEL_ID
    global TTS_TIMEOUT_SECONDS
    global TTS_MAX_RETRIES
    global MAX_AUDIO_SPEEDUP_RATIO

    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)
    WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    WHISPER_FALLBACK_MODELS = [
        model.strip()
        for model in os.getenv("WHISPER_FALLBACK_MODELS", "small,base").split(",")
        if model.strip()
    ]
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
    VOICE_ID = os.getenv("TTS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
    API_KEY = (os.getenv("TTS_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or "").strip()
    API_URL = (
        os.getenv("TTS_API_URL")
        or f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    ).strip()
    TTS_MODEL_ID = os.getenv("TTS_MODEL_ID", "eleven_flash_v2_5").strip() or "eleven_flash_v2_5"
    TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "90"))
    TTS_MAX_RETRIES = int(os.getenv("TTS_MAX_RETRIES", "3"))
    MAX_AUDIO_SPEEDUP_RATIO = float(os.getenv("MAX_AUDIO_SPEEDUP_RATIO", "1.35"))


class PipelineError(Exception):
    """Raised when a video cannot complete the translation pipeline."""


@dataclass(frozen=True)
class SrtSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def ensure_directories() -> None:
    for directory in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def discover_videos() -> List[Path]:
    return sorted(
        path
        for path in INPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def sanitize_folder_name(name: str) -> str:
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return safe_name or "video"


def milliseconds_to_srt_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def seconds_to_srt_time(seconds: float) -> str:
    return milliseconds_to_srt_time(round(seconds * 1000))


def srt_time_to_milliseconds(value: str) -> int:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise PipelineError(f"Timestamp SRT khong hop le: {value}")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def parse_srt(content: str) -> List[SrtSegment]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise PipelineError("File SRT rong.")

    blocks = re.split(r"\n{2,}", normalized)
    segments: List[SrtSegment] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            raise PipelineError(f"Khoi SRT thieu du lieu: {block!r}")

        try:
            index = int(lines[0])
        except ValueError as exc:
            raise PipelineError(f"So thu tu SRT khong hop le: {lines[0]!r}") from exc

        if " --> " not in lines[1]:
            raise PipelineError(f"Dong timestamp SRT khong hop le: {lines[1]!r}")

        start_text, end_text = lines[1].split(" --> ", 1)
        start_ms = srt_time_to_milliseconds(start_text)
        end_ms = srt_time_to_milliseconds(end_text)
        if end_ms <= start_ms:
            raise PipelineError(f"Timeline SRT khong hop le tai doan {index}.")

        segments.append(SrtSegment(index=index, start_ms=start_ms, end_ms=end_ms, text="\n".join(lines[2:])))

    expected_indexes = list(range(1, len(segments) + 1))
    actual_indexes = [segment.index for segment in segments]
    if actual_indexes != expected_indexes:
        raise PipelineError("So thu tu SRT khong lien tuc tu 1.")

    return segments


def write_srt(segments: Iterable[SrtSegment], output_path: Path) -> None:
    parts = []
    for segment in segments:
        parts.append(
            "\n".join(
                [
                    str(segment.index),
                    f"{milliseconds_to_srt_time(segment.start_ms)} --> {milliseconds_to_srt_time(segment.end_ms)}",
                    segment.text.strip(),
                ]
            )
        )
    output_path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:srt)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def validate_translated_srt(source_content: str, translated_content: str) -> str:
    source_segments = parse_srt(source_content)
    translated_segments = parse_srt(strip_markdown_fence(translated_content))

    if len(source_segments) != len(translated_segments):
        raise PipelineError("Gemini tra ve SRT sai so luong caption.")

    for source, translated in zip(source_segments, translated_segments):
        if source.index != translated.index:
            raise PipelineError(f"Gemini tra ve sai so thu tu tai caption {source.index}.")
        if source.start_ms != translated.start_ms or source.end_ms != translated.end_ms:
            raise PipelineError(f"Gemini tra ve sai timestamp tai caption {source.index}.")

    return strip_markdown_fence(translated_content) + "\n"


def get_video_duration_ms(video_path: Path) -> int:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        duration_seconds = float(json.loads(result.stdout)["format"]["duration"])
        return round(duration_seconds * 1000)
    except Exception as exc:
        logging.warning("Khong doc duoc duration video, dung timestamp cuoi SRT: %s", exc)
        return 0


class ChineseSubtitleExtractor:
    def __init__(self, model_name: str, device: str, compute_type: str):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _model_candidates(self) -> List[str]:
        candidates = [self.model_name, *WHISPER_FALLBACK_MODELS]
        unique_candidates = []
        for candidate in candidates:
            if candidate not in unique_candidates:
                unique_candidates.append(candidate)
        return unique_candidates

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise PipelineError("Chua cai faster-whisper. Hay chay: pip install -r requirements.txt") from exc

            last_error = None
            for candidate in self._model_candidates():
                try:
                    logging.info("Dang tai faster-whisper model '%s' (%s/%s)...", candidate, self.device, self.compute_type)
                    self._model = WhisperModel(candidate, device=self.device, compute_type=self.compute_type)
                    self.model_name = candidate
                    return self._model
                except RuntimeError as exc:
                    last_error = exc
                    logging.warning("Khong load duoc model Whisper '%s': %s", candidate, exc)

            raise PipelineError(f"Khong load duoc faster-whisper model nao: {last_error}")
        return self._model

    def extract_to_srt(self, video_path: Path, output_srt_path: Path) -> None:
        logging.info("Dang trich xuat subtitle tieng Trung: %s", video_path.name)
        srt_segments = self._transcribe_video(video_path, vad_filter=True)
        if not srt_segments:
            logging.warning("VAD khong tim thay caption, thu lai khong dung VAD.")
            srt_segments = self._transcribe_video(video_path, vad_filter=False)

        if not srt_segments:
            raise PipelineError(f"Khong trich xuat duoc subtitle tu {video_path.name}.")

        write_srt(srt_segments, output_srt_path)
        logging.info("Da luu sub Trung: %s", output_srt_path)

    def _transcribe_video(self, video_path: Path, vad_filter: bool) -> List[SrtSegment]:
        try:
            model = self._load_model()
            segments, info = model.transcribe(
                str(video_path),
                language="zh",
                beam_size=5,
                vad_filter=vad_filter,
            )
            logging.info("Whisper nhan dien ngon ngu: %s (xac suat %.2f)", info.language, info.language_probability)

            srt_segments = [
                SrtSegment(
                    index=index,
                    start_ms=round(segment.start * 1000),
                    end_ms=round(segment.end * 1000),
                    text=segment.text.strip(),
                )
                for index, segment in enumerate(segments, start=1)
                if segment.text.strip()
            ]
            logging.info("Whisper tao duoc %s caption.", len(srt_segments))
            return srt_segments
        except RuntimeError as exc:
            if self.device != "cpu" and "cublas" in str(exc).lower():
                logging.warning("GPU/CUDA thieu thu vien cublas, tu dong chuyen Whisper sang CPU.")
                self.device = "cpu"
                self._model = None
                return self._transcribe_video(video_path, vad_filter=vad_filter)
            raise PipelineError(f"Loi khi chay faster-whisper cho {video_path.name}: {exc}") from exc
        except Exception as exc:
            raise PipelineError(f"Loi khi chay faster-whisper cho {video_path.name}: {exc}") from exc


class GeminiSrtTranslator:
    def __init__(self, api_key: str, model_name: str):
        if not api_key:
            raise PipelineError("Chua cau hinh GEMINI_API_KEY trong .env.")
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise PipelineError("Chua cai google-generativeai. Hay chay: pip install -r requirements.txt") from exc

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def translate_srt(self, source_content: str) -> str:
        prompt = (
            "Ban la dich thuat vien chuyen nghiep cho video TikTok. "
            "Hay dich noi dung file SRT nay tu tieng Trung sang tieng Viet chuan van phong ban dia, tu nhien. "
            "BAT BUOC giu nguyen dinh dang file SRT, so thu tu cac doan va toan bo cac moc thoi gian (timestamps). "
            "Chi tra ve noi dung file SRT sau khi dich, tuyet doi khong them loi giai thich hay boc trong markdown ```srt.\n\n"
            f"{source_content}"
        )

        last_error = None
        for attempt in range(1, 3):
            logging.info("Dang dich SRT qua Gemini API (lan %s/2)...", attempt)
            try:
                response = self.model.generate_content(prompt)
                translated_text = getattr(response, "text", "") or ""
                return validate_translated_srt(source_content, translated_text)
            except Exception as exc:
                last_error = exc
                logging.warning("Gemini tra ve chua dat yeu cau: %s", exc)
                prompt = (
                    "Ket qua truoc sai dinh dang SRT. Hay tra lai DUY NHAT file SRT tieng Viet, "
                    "giu nguyen 100% so thu tu va timestamp nhu nguon sau:\n\n"
                    f"{source_content}"
                )
                time.sleep(2)

        raise PipelineError(f"Khong dich duoc SRT dung dinh dang qua Gemini: {last_error}")


class AdamTtsClient:
    def __init__(self, api_key: str, api_url: str):
        if not api_key:
            raise PipelineError("Chua cau hinh TTS_API_KEY hoac ELEVENLABS_API_KEY trong .env.")
        if not api_url:
            raise PipelineError("Chua cau hinh API_URL cho dich vu TTS.")
        self.api_key = api_key
        self.api_url = api_url
        self.session = requests.Session()

    def synthesize_to_file(self, text: str, output_path: Path) -> None:
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        if "elevenlabs.io" in self.api_url:
            headers["xi-api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "text": text,
            "model_id": TTS_MODEL_ID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
            },
        }

        for attempt in range(1, TTS_MAX_RETRIES + 1):
            try:
                response = self.session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=TTS_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                output_path.write_bytes(response.content)
                return
            except requests.RequestException as exc:
                if attempt == TTS_MAX_RETRIES:
                    raise PipelineError(f"Loi TTS sau {TTS_MAX_RETRIES} lan thu: {exc}") from exc
                wait_seconds = attempt * 2
                logging.warning("TTS loi mang/API, thu lai sau %ss: %s", wait_seconds, exc)
                time.sleep(wait_seconds)


class TimelineDubber:
    def __init__(self, tts_client: AdamTtsClient):
        self.tts_client = tts_client

    def create_dubbed_audio(self, srt_path: Path, output_audio_path: Path, segment_audio_dir: Path, video_duration_ms: int) -> None:
        try:
            from pydub import AudioSegment
        except ImportError as exc:
            raise PipelineError("Chua cai pydub. Hay chay: pip install -r requirements.txt") from exc

        segments = parse_srt(srt_path.read_text(encoding="utf-8"))
        segment_audio_dir.mkdir(parents=True, exist_ok=True)

        base_duration_ms = max(video_duration_ms, segments[-1].end_ms)
        final_audio = AudioSegment.silent(duration=base_duration_ms)

        for segment in segments:
            text = " ".join(segment.text.split())
            if not text:
                continue

            segment_path = segment_audio_dir / f"{segment.index:04d}.mp3"
            logging.info("Dang tao audio caption %s/%s...", segment.index, len(segments))
            self.tts_client.synthesize_to_file(text, segment_path)

            try:
                segment_audio = AudioSegment.from_file(segment_path, format="mp3")
            except Exception as exc:
                raise PipelineError(f"Khong doc duoc audio TTS tai {segment_path}: {exc}") from exc

            segment_audio = self._fit_audio_to_caption(segment_audio, segment.duration_ms, segment.index)
            final_audio = final_audio.overlay(segment_audio, position=segment.start_ms)

        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        final_audio.export(output_audio_path, format="mp3")
        logging.info("Da luu audio long tieng: %s", output_audio_path)

    def _fit_audio_to_caption(self, audio: AudioSegment, target_duration_ms: int, caption_index: int) -> AudioSegment:
        if len(audio) <= target_duration_ms:
            return audio

        ratio = len(audio) / target_duration_ms
        if 1 < ratio <= MAX_AUDIO_SPEEDUP_RATIO:
            try:
                from pydub.effects import speedup

                audio = speedup(audio, playback_speed=ratio, chunk_size=50, crossfade=25)
            except Exception as exc:
                logging.warning("Khong speedup duoc caption %s: %s", caption_index, exc)

        if len(audio) > target_duration_ms:
            logging.warning(
                "Audio caption %s dai hon slot %.2fs, cat bot de giu timeline.",
                caption_index,
                target_duration_ms / 1000,
            )
            audio = audio[:target_duration_ms]

        return audio


class VideoTranslationPipeline:
    def __init__(self):
        self._extractor: Optional[ChineseSubtitleExtractor] = None
        self._translator: Optional[GeminiSrtTranslator] = None
        self._dubber: Optional[TimelineDubber] = None

    @property
    def extractor(self) -> ChineseSubtitleExtractor:
        if self._extractor is None:
            self._extractor = ChineseSubtitleExtractor(
                model_name=WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        return self._extractor

    @property
    def translator(self) -> GeminiSrtTranslator:
        if self._translator is None:
            self._translator = GeminiSrtTranslator(
                api_key=GEMINI_API_KEY,
                model_name=GEMINI_MODEL_NAME,
            )
        return self._translator

    @property
    def dubber(self) -> TimelineDubber:
        if self._dubber is None:
            self._dubber = TimelineDubber(AdamTtsClient(api_key=API_KEY, api_url=API_URL))
        return self._dubber

    def process_video(self, video_path: Path) -> None:
        video_name = sanitize_folder_name(video_path.stem)
        work_dir = TEMP_DIR / video_name
        output_dir = OUTPUT_DIR / video_name
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        chinese_srt_path = work_dir / "sub_trung.srt"
        vietnamese_srt_path = output_dir / "sub_viet.srt"
        dubbed_audio_path = output_dir / "giong_doc_viet.mp3"

        copied_video_path = output_dir / f"video_goc{video_path.suffix.lower()}"
        shutil.copy2(video_path, copied_video_path)
        logging.info("Da copy video goc: %s", copied_video_path)

        self.extractor.extract_to_srt(video_path, chinese_srt_path)

        logging.info("Dang dich subtitle sang tieng Viet...")
        translated_content = self.translator.translate_srt(chinese_srt_path.read_text(encoding="utf-8"))
        vietnamese_srt_path.write_text(translated_content, encoding="utf-8")
        logging.info("Da luu sub Viet: %s", vietnamese_srt_path)

        video_duration_ms = get_video_duration_ms(video_path)
        self.dubber.create_dubbed_audio(
            srt_path=vietnamese_srt_path,
            output_audio_path=dubbed_audio_path,
            segment_audio_dir=work_dir / "tts_segments",
            video_duration_ms=video_duration_ms,
        )

    def run(self, limit: Optional[int] = None, video_names: Optional[List[str]] = None) -> None:
        ensure_directories()
        videos = discover_videos()

        if video_names:
            video_map = {video.name: video for video in videos}
            missing = [name for name in video_names if name not in video_map]
            if missing:
                raise PipelineError(f"Khong tim thay video: {', '.join(missing)}")
            videos = [video_map[name] for name in video_names]

        if limit is not None:
            videos = videos[:limit]

        if not videos:
            logging.info("Chua co video .mp4/.mkv trong thu muc: %s", INPUT_DIR)
            return

        logging.info("Tim thay %s video can xu ly.", len(videos))
        failures = []
        for video_path in videos:
            logging.info("Bat dau xu ly: %s", video_path.name)
            try:
                self.process_video(video_path)
                logging.info("Hoan tat: %s", video_path.name)
            except Exception as exc:
                logging.exception("Xu ly that bai: %s", video_path.name)
                failures.append((video_path.name, exc))

        if failures:
            details = "; ".join(f"{name}: {error}" for name, error in failures)
            raise PipelineError(f"Co {len(failures)} video xu ly that bai: {details}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tu dong trich sub Trung, dich sang tieng Viet va tao file long tieng theo timeline.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Gioi han so video xu ly trong input_videos.")
    parser.add_argument("--videos", nargs="*", default=None, help="Ten video cu the trong input_videos can xu ly.")
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()

    try:
        VideoTranslationPipeline().run(limit=args.limit, video_names=args.videos)
        return 0
    except PipelineError as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logging.error("Da dung chuong trinh theo yeu cau nguoi dung.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
