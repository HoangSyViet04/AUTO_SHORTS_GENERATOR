from __future__ import annotations

import argparse
import hashlib
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
from urllib.parse import quote, quote_plus

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)
INPUT_DIR = BASE_DIR / "input_videos"
OUTPUT_DIR = BASE_DIR / "output_results"
TEMP_DIR = BASE_DIR / "temp" / "translation_pipeline"
LOGO_SOURCE_PATH = BASE_DIR / "logo.png"

VIDEO_EXTENSIONS = {".mp4", ".mkv"}


def split_env_values(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[,;\n]+", (value or "").replace("\\n", "\n")) if item.strip()]


def unique_values(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def load_gemini_api_keys() -> List[str]:
    raw_values = [os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_API_KEYS", "")]
    raw_values.extend(os.getenv(f"GEMINI_API_KEY_{index}", "") for index in range(1, 6))
    return unique_values(key for raw_value in raw_values for key in split_env_values(raw_value))


WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
WHISPER_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("WHISPER_FALLBACK_MODELS", "small,base").split(",")
    if model.strip()
]

GEMINI_API_KEYS = load_gemini_api_keys()
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_MODEL_FALLBACKS = [
    model.strip()
    for model in os.getenv("GEMINI_MODEL_FALLBACKS", "gemini-2.5-flash-lite,gemini-1.5-flash").split(",")
    if model.strip()
]
DEFAULT_GEMINI_REWRITE_PROMPT = """Bạn là biên kịch short video commerce nói tiếng Việt tự nhiên.
Nhiệm vụ: chuyển SRT tiếng Trung thành SRT tiếng Việt để đọc lồng tiếng, không dịch word-by-word.

Yêu cầu bắt buộc:
- Giữ nguyên 100% số thứ tự và timestamp của SRT nguồn.
- Chỉ trả về SRT, không markdown, không giải thích.
- Mỗi caption ngắn, dễ đọc TTS, nói như người thật.
- Câu mở đầu phải có hook gây tò mò trong 2 giây đầu.
- Viết theo mạch: vấn đề → phát hiện → lợi ích → lý do nên xem/mua.
- Ưu tiên tiếng Việt đời thường, review sản phẩm Douyin/TikTok, có nhịp cảm xúc.
- Không bịa công dụng y tế, không hứa quá đà, không dùng từ thô.
- Nếu caption gốc rời rạc, hãy rewrite thành kịch bản liền mạch nhưng vẫn khớp timestamp.
"""
DEFAULT_GEMINI_POST_PROMPT = """Tạo nội dung đăng bài từ SRT tiếng Việt.
Trả về đúng format:
Caption: 1 câu ngắn gọn, tự nhiên, có 1 keyword SEO sản phẩm.
Hashtag: 5-8 hashtag liên quan sản phẩm/video.
Không viết dài, không chia nhiều tiêu đề, không thêm markdown.
"""
DEFAULT_SHOPEE_PRODUCT_PROMPT = """Từ SRT tiếng Việt, nhận diện sản phẩm chính trong video để tìm trên Shopee.
Trả về JSON thuần, không markdown:
{
  "product_name": "tên sản phẩm chính bằng tiếng Việt",
  "keywords": ["keyword mua hàng 1", "keyword mua hàng 2", "keyword mua hàng 3"],
  "buyer_intent": "nhu cầu mua hàng ngắn gọn"
}
Quy tắc:
- Keyword phải là cụm người Việt sẽ gõ trên Shopee.
- Ưu tiên keyword có loại sản phẩm + đặc điểm nổi bật.
- Không bịa thương hiệu nếu video không nói rõ.
- Tối đa 3 keywords.
"""
DEFAULT_TTS_ENHANCE_PROMPT = """Bạn là voice director cho video short tiếng Việt.
Nhiệm vụ: biến subtitle_text thành tts_text để ElevenLabs đọc tự nhiên, có nhịp và cảm xúc hơn.

Quy tắc bắt buộc:
- Giữ nguyên ý nghĩa, tên riêng, con số, thông số sản phẩm.
- Không bịa thêm công dụng hoặc dữ kiện.
- Không đưa audio tag vào subtitle_text.
- tts_text được phép thêm dấu câu, nhịp nghỉ bằng dấu câu và nhấn nhá bằng audio tag vừa phải.
- Không dùng tag XML/SSML như <break time='100ms'/>. Chỉ dùng dấu câu, dấu ba chấm hoặc audio tag dạng [curious], [excited], [warm], [confident], [soft].
- Không lạm dụng audio tag; nhưng không được chỉ thêm ở đoạn đầu. Hãy phân bố cảm xúc ở hook, reveal/proof và CTA.
- Với video ngắn, tối thiểu 3 chunk khác nhau cần có cue cảm xúc rõ. Với video dài hơn, dùng 4-5 chunk.
- tts_text phải ngắn hơn hoặc bằng max_tts_chars của từng chunk. Nếu raw_text quá dài, rút gọn lời đọc nhưng giữ ý chính và dữ kiện quan trọng.
- Mỗi chunk phải là một ý hoàn chỉnh, đọc liền mạch như kể chuyện.

Trả về JSON thuần, không markdown:
{
  "chunks": [
    {
      "chunk_id": 1,
      "segment_indexes": [1, 2],
      "emotion_intent": "hook_tò_mò",
      "tts_text": "..."
    }
  ]
}
"""
def multiline_env(name: str, default: str) -> str:
    return os.getenv(name, default).replace("\\n", "\n").strip()


GEMINI_REWRITE_PROMPT = multiline_env("GEMINI_REWRITE_PROMPT", DEFAULT_GEMINI_REWRITE_PROMPT)
GEMINI_POST_PROMPT = multiline_env("GEMINI_POST_PROMPT", DEFAULT_GEMINI_POST_PROMPT)
TTS_ENHANCE_PROMPT = multiline_env("TTS_ENHANCE_PROMPT", DEFAULT_TTS_ENHANCE_PROMPT)
SHOPEE_PRODUCT_PROMPT = multiline_env("SHOPEE_PRODUCT_PROMPT", DEFAULT_SHOPEE_PRODUCT_PROMPT)
SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "").strip()
SHOPEE_SUB_ID_PREFIX = os.getenv("SHOPEE_SUB_ID_PREFIX", "auto-shorts").strip() or "auto-shorts"
SHOPEE_LINK_LIMIT = int(os.getenv("SHOPEE_LINK_LIMIT", "3"))
GOOGLE_TRANSLATE_FALLBACK = os.getenv("GOOGLE_TRANSLATE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}

TTS_MODE = os.getenv("TTS_MODE", "quality").strip().lower() or "quality"
TTS_ENHANCE_ENABLED = os.getenv("TTS_ENHANCE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_SEMANTIC_CHUNK_ENABLED = os.getenv("TTS_SEMANTIC_CHUNK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_AUDIO_FIRST = os.getenv("TTS_AUDIO_FIRST", "false").strip().lower() in {"1", "true", "yes", "on"}
TTS_QUALITY_MODEL_ID = os.getenv("TTS_QUALITY_MODEL_ID", "eleven_v3").strip() or "eleven_v3"
TTS_FAST_MODEL_ID = os.getenv("TTS_FAST_MODEL_ID", "eleven_flash_v2_5").strip() or "eleven_flash_v2_5"
VOICE_ID = os.getenv("TTS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
API_KEY = (os.getenv("TTS_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or "").strip()
API_URL = (
    os.getenv("TTS_API_URL")
    or f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
).strip()
TTS_MODEL_ID = os.getenv("TTS_MODEL_ID", TTS_QUALITY_MODEL_ID if TTS_MODE == "quality" else TTS_FAST_MODEL_ID).strip()
TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "90"))
TTS_MAX_RETRIES = int(os.getenv("TTS_MAX_RETRIES", "3"))
MAX_AUDIO_SPEEDUP_RATIO = float(os.getenv("MAX_AUDIO_SPEEDUP_RATIO", "1.35"))
TTS_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_FINAL_SPEEDUP_RATIO", "1.60"))
TTS_QUALITY_MAX_SPEEDUP_RATIO = float(os.getenv("TTS_QUALITY_MAX_SPEEDUP_RATIO", "1.08"))
TTS_QUALITY_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_QUALITY_FINAL_SPEEDUP_RATIO", "1.12"))
TTS_MIN_SPEEDUP_RATIO = float(os.getenv("TTS_MIN_SPEEDUP_RATIO", "1.05"))
TTS_STRICT_TIMELINE = os.getenv("TTS_STRICT_TIMELINE", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_SEGMENT_GAP_MS = int(os.getenv("TTS_SEGMENT_GAP_MS", "30"))
TTS_MAX_SILENCE_GAP_MS = int(os.getenv("TTS_MAX_SILENCE_GAP_MS", "350"))
TTS_REUSE_SEGMENTS = os.getenv("TTS_REUSE_SEGMENTS", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "260"))
TTS_CHUNK_MAX_SEGMENTS = int(os.getenv("TTS_CHUNK_MAX_SEGMENTS", "3"))
TTS_TARGET_CHARS_PER_SECOND = float(os.getenv("TTS_TARGET_CHARS_PER_SECOND", "13.5"))
TTS_USE_DURATION_TEXT_BUDGET = os.getenv("TTS_USE_DURATION_TEXT_BUDGET", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_PRESERVE_SCRIPT = os.getenv("TTS_PRESERVE_SCRIPT", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_FIT_AUDIO_TO_VIDEO = os.getenv("TTS_FIT_AUDIO_TO_VIDEO", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_EMERGENCY_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_EMERGENCY_FINAL_SPEEDUP_RATIO", "1.22"))
TTS_LEAD_IN_MS = int(os.getenv("TTS_LEAD_IN_MS", "80"))
TTS_VOICE_STABILITY = float(os.getenv("TTS_VOICE_STABILITY", "0.42" if TTS_MODE == "quality" else "0.50"))
TTS_VOICE_SIMILARITY = float(os.getenv("TTS_VOICE_SIMILARITY", "0.82"))
TTS_VOICE_STYLE = float(os.getenv("TTS_VOICE_STYLE", "0.35" if TTS_MODE == "quality" else "0.0"))


def reload_settings() -> None:
    global WHISPER_MODEL_NAME
    global WHISPER_DEVICE
    global WHISPER_COMPUTE_TYPE
    global WHISPER_FALLBACK_MODELS
    global GEMINI_API_KEYS
    global GEMINI_API_KEY
    global GEMINI_MODEL_NAME
    global GEMINI_MODEL_FALLBACKS
    global GEMINI_REWRITE_PROMPT
    global GEMINI_POST_PROMPT
    global TTS_ENHANCE_PROMPT
    global SHOPEE_PRODUCT_PROMPT
    global SHOPEE_AFFILIATE_ID
    global SHOPEE_SUB_ID_PREFIX
    global SHOPEE_LINK_LIMIT
    global GOOGLE_TRANSLATE_FALLBACK
    global TTS_MODE
    global TTS_ENHANCE_ENABLED
    global TTS_SEMANTIC_CHUNK_ENABLED
    global TTS_AUDIO_FIRST
    global TTS_QUALITY_MODEL_ID
    global TTS_FAST_MODEL_ID
    global VOICE_ID
    global API_KEY
    global API_URL
    global TTS_MODEL_ID
    global TTS_TIMEOUT_SECONDS
    global TTS_MAX_RETRIES
    global MAX_AUDIO_SPEEDUP_RATIO
    global TTS_FINAL_SPEEDUP_RATIO
    global TTS_QUALITY_MAX_SPEEDUP_RATIO
    global TTS_QUALITY_FINAL_SPEEDUP_RATIO
    global TTS_MIN_SPEEDUP_RATIO
    global TTS_STRICT_TIMELINE
    global TTS_SEGMENT_GAP_MS
    global TTS_MAX_SILENCE_GAP_MS
    global TTS_REUSE_SEGMENTS
    global TTS_CHUNK_MAX_CHARS
    global TTS_CHUNK_MAX_SEGMENTS
    global TTS_TARGET_CHARS_PER_SECOND
    global TTS_USE_DURATION_TEXT_BUDGET
    global TTS_PRESERVE_SCRIPT
    global TTS_FIT_AUDIO_TO_VIDEO
    global TTS_EMERGENCY_FINAL_SPEEDUP_RATIO
    global TTS_LEAD_IN_MS
    global TTS_VOICE_STABILITY
    global TTS_VOICE_SIMILARITY
    global TTS_VOICE_STYLE

    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)
    WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    WHISPER_FALLBACK_MODELS = [
        model.strip()
        for model in os.getenv("WHISPER_FALLBACK_MODELS", "small,base").split(",")
        if model.strip()
    ]
    GEMINI_API_KEYS = load_gemini_api_keys()
    GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    GEMINI_MODEL_FALLBACKS = [
        model.strip()
        for model in os.getenv("GEMINI_MODEL_FALLBACKS", "gemini-2.5-flash-lite,gemini-1.5-flash").split(",")
        if model.strip()
    ]
    GEMINI_REWRITE_PROMPT = multiline_env("GEMINI_REWRITE_PROMPT", DEFAULT_GEMINI_REWRITE_PROMPT)
    GEMINI_POST_PROMPT = multiline_env("GEMINI_POST_PROMPT", DEFAULT_GEMINI_POST_PROMPT)
    TTS_ENHANCE_PROMPT = multiline_env("TTS_ENHANCE_PROMPT", DEFAULT_TTS_ENHANCE_PROMPT)
    SHOPEE_PRODUCT_PROMPT = multiline_env("SHOPEE_PRODUCT_PROMPT", DEFAULT_SHOPEE_PRODUCT_PROMPT)
    SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "").strip()
    SHOPEE_SUB_ID_PREFIX = os.getenv("SHOPEE_SUB_ID_PREFIX", "auto-shorts").strip() or "auto-shorts"
    SHOPEE_LINK_LIMIT = int(os.getenv("SHOPEE_LINK_LIMIT", "3"))
    GOOGLE_TRANSLATE_FALLBACK = os.getenv("GOOGLE_TRANSLATE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_MODE = os.getenv("TTS_MODE", "quality").strip().lower() or "quality"
    TTS_ENHANCE_ENABLED = os.getenv("TTS_ENHANCE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_SEMANTIC_CHUNK_ENABLED = os.getenv("TTS_SEMANTIC_CHUNK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_AUDIO_FIRST = os.getenv("TTS_AUDIO_FIRST", "false").strip().lower() in {"1", "true", "yes", "on"}
    TTS_QUALITY_MODEL_ID = os.getenv("TTS_QUALITY_MODEL_ID", "eleven_v3").strip() or "eleven_v3"
    TTS_FAST_MODEL_ID = os.getenv("TTS_FAST_MODEL_ID", "eleven_flash_v2_5").strip() or "eleven_flash_v2_5"
    VOICE_ID = os.getenv("TTS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
    API_KEY = (os.getenv("TTS_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or "").strip()
    API_URL = (
        os.getenv("TTS_API_URL")
        or f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    ).strip()
    TTS_MODEL_ID = os.getenv("TTS_MODEL_ID", TTS_QUALITY_MODEL_ID if TTS_MODE == "quality" else TTS_FAST_MODEL_ID).strip()
    TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "90"))
    TTS_MAX_RETRIES = int(os.getenv("TTS_MAX_RETRIES", "3"))
    MAX_AUDIO_SPEEDUP_RATIO = float(os.getenv("MAX_AUDIO_SPEEDUP_RATIO", "1.35"))
    TTS_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_FINAL_SPEEDUP_RATIO", "1.60"))
    TTS_QUALITY_MAX_SPEEDUP_RATIO = float(os.getenv("TTS_QUALITY_MAX_SPEEDUP_RATIO", "1.08"))
    TTS_QUALITY_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_QUALITY_FINAL_SPEEDUP_RATIO", "1.12"))
    TTS_MIN_SPEEDUP_RATIO = float(os.getenv("TTS_MIN_SPEEDUP_RATIO", "1.05"))
    TTS_STRICT_TIMELINE = os.getenv("TTS_STRICT_TIMELINE", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_SEGMENT_GAP_MS = int(os.getenv("TTS_SEGMENT_GAP_MS", "30"))
    TTS_MAX_SILENCE_GAP_MS = int(os.getenv("TTS_MAX_SILENCE_GAP_MS", "350"))
    TTS_REUSE_SEGMENTS = os.getenv("TTS_REUSE_SEGMENTS", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "260"))
    TTS_CHUNK_MAX_SEGMENTS = int(os.getenv("TTS_CHUNK_MAX_SEGMENTS", "3"))
    TTS_TARGET_CHARS_PER_SECOND = float(os.getenv("TTS_TARGET_CHARS_PER_SECOND", "13.5"))
    TTS_USE_DURATION_TEXT_BUDGET = os.getenv("TTS_USE_DURATION_TEXT_BUDGET", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_PRESERVE_SCRIPT = os.getenv("TTS_PRESERVE_SCRIPT", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_FIT_AUDIO_TO_VIDEO = os.getenv("TTS_FIT_AUDIO_TO_VIDEO", "true").strip().lower() in {"1", "true", "yes", "on"}
    TTS_EMERGENCY_FINAL_SPEEDUP_RATIO = float(os.getenv("TTS_EMERGENCY_FINAL_SPEEDUP_RATIO", "1.22"))
    TTS_LEAD_IN_MS = int(os.getenv("TTS_LEAD_IN_MS", "80"))
    TTS_VOICE_STABILITY = float(os.getenv("TTS_VOICE_STABILITY", "0.42" if TTS_MODE == "quality" else "0.50"))
    TTS_VOICE_SIMILARITY = float(os.getenv("TTS_VOICE_SIMILARITY", "0.82"))
    TTS_VOICE_STYLE = float(os.getenv("TTS_VOICE_STYLE", "0.35" if TTS_MODE == "quality" else "0.0"))


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


@dataclass(frozen=True)
class TtsChunk:
    chunk_id: int
    segment_indexes: List[int]
    start_ms: int
    end_ms: int
    subtitle_text: str
    tts_text: str
    emotion_intent: str
    context_before: str = ""
    context_after: str = ""

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


def build_shopee_search_url(keyword: str) -> str:
    return f"https://shopee.vn/search?keyword={quote_plus(keyword.strip())}"


def build_shopee_share_url(target_url: str, sub_id: str) -> str:
    if not SHOPEE_AFFILIATE_ID:
        return target_url
    safe_sub_id = re.sub(r"[^A-Za-z0-9_-]+", "-", sub_id).strip("-")[:80] or SHOPEE_SUB_ID_PREFIX
    return (
        "https://s.shopee.vn/an_redir?"
        f"origin_link={quote(target_url, safe='')}"
        f"&affiliate_id={quote(SHOPEE_AFFILIATE_ID, safe='')}"
        f"&sub_id={quote(safe_sub_id, safe='')}"
    )


def format_product_comment_suggestions(product_data: dict[str, object], video_name: str = "") -> str:
    product_name = str(product_data.get("product_name") or "San pham trong video").strip()
    buyer_intent = str(product_data.get("buyer_intent") or "").strip()
    raw_keywords = product_data.get("keywords") or []
    if not isinstance(raw_keywords, list):
        raw_keywords = [str(raw_keywords)]
    keywords = []
    for keyword in raw_keywords:
        text = str(keyword).strip()
        if text and text.lower() not in {item.lower() for item in keywords}:
            keywords.append(text)
    keywords = keywords[: max(1, SHOPEE_LINK_LIMIT)]
    if not keywords:
        keywords = [product_name]
    safe_video = sanitize_folder_name(Path(video_name).stem if video_name else product_name)
    affiliate_links = []
    for index, keyword in enumerate(keywords, start=1):
        search_url = build_shopee_search_url(keyword)
        sub_id = f"{SHOPEE_SUB_ID_PREFIX}-{safe_video}-{index}"
        affiliate_links.append((keyword, build_shopee_share_url(search_url, sub_id)))

    lines = [
        "💬 Gợi ý comment sản phẩm",
        f"Sản phẩm: {product_name}",
    ]
    if buyer_intent:
        lines.append(f"Nhu cầu: {buyer_intent}")
    lines.extend(
        [
            "",
            "Link affiliate Shopee để gắn video/comment:",
            *[f"- {keyword}: {url}" for keyword, url in affiliate_links],
            "",
            "Gợi ý comment:",
            f"1. Ai cần món này thì mình ghim link sản phẩm ở bình luận nha: {affiliate_links[0][1]}",
            f"2. Mình thấy keyword dễ tìm là: {keywords[0]}. Bạn nào cần thì bấm link mình ghim nhé.",
            "3. Nếu bạn đang tìm món nhỏ gọn, dễ dùng thì thử xem sản phẩm này, mình để link cho tiện.",
            "4. Mình để link tham khảo bên dưới, ai cần đúng mẫu thì vào xem trước đánh giá rồi quyết định nhé.",
        ]
    )
    return "\n".join(lines)


def format_shopee_links(product_data: dict[str, object], video_name: str) -> str:
    return format_product_comment_suggestions(product_data, video_name)


def plain_text_from_srt(srt_content: str) -> str:
    lines = []
    for line in srt_content.splitlines():
        text = line.strip()
        if not text or text.isdigit() or "-->" in text:
            continue
        lines.append(text)
    return " ".join(lines)


def fallback_post_campaign(vietnamese_srt_content: str) -> str:
    summary = plain_text_from_srt(vietnamese_srt_content)[:120].strip() or "sản phẩm tiện ích"
    keyword = fallback_product_data(vietnamese_srt_content)["keywords"][0]
    return "\n".join(
        [
            f"Caption: Review nhanh {keyword}: {summary}...",
            f"Hashtag: #{keyword.replace(' ', '')} #review #sanpham #douyin #tiktok #shopee",
        ]
    )


def fallback_product_data(vietnamese_srt_content: str) -> dict[str, object]:
    text = plain_text_from_srt(vietnamese_srt_content).lower()
    stop_words = {
        "cai", "nay", "kia", "rat", "qua", "minh", "ban", "nhin", "thay", "khong",
        "duoc", "cho", "voi", "nhung", "video", "san", "pham", "review", "tren",
    }
    words = re.findall(r"[a-zA-ZÀ-ỹ0-9]+", text)
    keywords = []
    for size in (4, 3, 2):
        for index in range(0, max(0, len(words) - size + 1)):
            phrase_words = words[index : index + size]
            if any(word in stop_words for word in phrase_words[:1]):
                continue
            phrase = " ".join(phrase_words).strip()
            if len(phrase) >= 8 and phrase not in keywords:
                keywords.append(phrase)
            if len(keywords) >= SHOPEE_LINK_LIMIT:
                break
        if keywords:
            break
    if not keywords:
        keywords = ["sản phẩm tiện ích"]
    return {
        "product_name": keywords[0],
        "keywords": keywords,
        "buyer_intent": "tìm sản phẩm tương tự trong video",
    }


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


def compact_text(text: str) -> str:
    return " ".join(text.split()).strip()


def max_tts_chars_for_duration(duration_ms: int) -> int:
    duration_seconds = max(0.5, duration_ms / 1000)
    return max(32, min(TTS_CHUNK_MAX_CHARS, round(duration_seconds * TTS_TARGET_CHARS_PER_SECOND)))


def sanitize_tts_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<\s*break\b[^>]*/?>", "... ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?[^>]+>", "", cleaned)
    cleaned = cleaned.replace("...", "…")
    return compact_text(cleaned)


def strip_tts_cues(text: str) -> str:
    return compact_text(re.sub(r"\[[^\]]{1,32}\]", "", text))


def normalized_spoken_words(text: str) -> List[str]:
    plain = strip_tts_cues(sanitize_tts_text(text)).casefold()
    return re.findall(r"[^\W_]+", plain, flags=re.UNICODE)


def preserves_spoken_script(source_text: str, candidate_text: str) -> bool:
    return normalized_spoken_words(source_text) == normalized_spoken_words(candidate_text)


def shorten_tts_text_for_duration(text: str, duration_ms: int) -> str:
    cleaned = sanitize_tts_text(text)
    if TTS_PRESERVE_SCRIPT or not TTS_USE_DURATION_TEXT_BUDGET:
        return cleaned
    max_chars = max_tts_chars_for_duration(duration_ms)
    if len(cleaned) <= max_chars:
        return cleaned

    plain = strip_tts_cues(cleaned)
    plain = re.sub(
        r"\b(nha|nhé|luôn|cơ|á|ơi|đó|đâu|thôi|cực|siêu|rất|khá|kiểu|mà|chứ)\b",
        "",
        plain,
        flags=re.IGNORECASE,
    )
    plain = compact_text(plain)
    if len(plain) <= max_chars:
        return plain

    sentences = [compact_text(part) for part in re.split(r"(?<=[.!?…])\s+", plain) if compact_text(part)]
    selected: list[str] = []
    current_length = 0
    for sentence in sentences:
        extra = len(sentence) + (1 if selected else 0)
        if current_length + extra <= max_chars:
            selected.append(sentence)
            current_length += extra
        elif not selected:
            selected.append(sentence[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…")
            break
    shortened = compact_text(" ".join(selected)) if selected else plain[:max_chars].rstrip(" ,;:") + "…"
    return shortened[: max_chars + 1].rstrip(" ,;:")


def emotion_cue_for_chunk(chunk: TtsChunk, total_chunks: int) -> str:
    if TTS_MODE != "quality":
        return ""
    if chunk.chunk_id == 1:
        return "[curious]"
    if chunk.chunk_id in {max(2, total_chunks // 2), max(3, (total_chunks * 2) // 3)}:
        return "[excited]"
    if chunk.chunk_id == total_chunks:
        return "[confident]"
    if any(keyword in chunk.emotion_intent.lower() for keyword in ("reveal", "bất", "cta", "hook")):
        return "[excited]"
    return ""


def prepare_tts_text_for_chunk(chunk: TtsChunk, total_chunks: int) -> str:
    text = shorten_tts_text_for_duration(chunk.tts_text, chunk.duration_ms)
    if TTS_PRESERVE_SCRIPT and not preserves_spoken_script(chunk.subtitle_text, text):
        logging.warning(
            "TTS chunk %s da bi thay doi/bo chu, fallback ve script SRT day du.",
            chunk.chunk_id,
        )
        text = sanitize_tts_text(chunk.subtitle_text)
    if re.search(r"\[[^\]]+\]", text):
        return text
    cue = emotion_cue_for_chunk(chunk, total_chunks)
    if not cue:
        return text
    with_cue = compact_text(f"{cue} {text}")
    if len(with_cue) <= max_tts_chars_for_duration(chunk.duration_ms) + len(cue) + 1:
        return with_cue
    return text


def build_tts_cache_key(text: str, chunk: TtsChunk) -> str:
    payload = {
        "text": text,
        "chunk_id": chunk.chunk_id,
        "target_duration_ms": chunk.duration_ms,
        "voice_id": VOICE_ID,
        "model_candidates": AdamTtsClient._model_candidates() if "AdamTtsClient" in globals() else [TTS_MODEL_ID],
        "voice_settings": {
            "stability": TTS_VOICE_STABILITY,
            "similarity_boost": TTS_VOICE_SIMILARITY,
            "style": TTS_VOICE_STYLE,
        },
        "preserve_script": TTS_PRESERVE_SCRIPT,
        "context_before": chunk.context_before,
        "context_after": chunk.context_after,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:12]


def infer_emotion_intent(text: str, chunk_id: int) -> str:
    lowered = text.lower()
    if chunk_id == 1:
        return "hook_tò_mò"
    if "?" in text or "sao" in lowered or "vì sao" in lowered:
        return "question_tò_mò"
    if any(keyword in lowered for keyword in ("nhưng", "bất ngờ", "hóa ra", "thật ra")):
        return "reveal_bất_ngờ"
    if any(keyword in lowered for keyword in ("mua", "link", "đặt", "chốt", "thử")):
        return "cta_tự_tin"
    return "review_tự_nhiên"


def build_default_tts_chunks(segments: List[SrtSegment]) -> List[TtsChunk]:
    if not segments:
        return []
    if not TTS_SEMANTIC_CHUNK_ENABLED:
        base_groups = [[segment] for segment in segments]
    else:
        base_groups: List[List[SrtSegment]] = []
        current_group: List[SrtSegment] = []
        current_chars = 0
        for segment in segments:
            text = compact_text(segment.text)
            current_group.append(segment)
            current_chars += len(text) + 1
            has_sentence_end = bool(re.search(r"[.!?…]$", text))
            reached_size = current_chars >= TTS_CHUNK_MAX_CHARS or len(current_group) >= TTS_CHUNK_MAX_SEGMENTS
            if current_group and (reached_size or (has_sentence_end and len(current_group) > 1)):
                base_groups.append(current_group)
                current_group = []
                current_chars = 0
        if current_group:
            base_groups.append(current_group)

    chunks: List[TtsChunk] = []
    for chunk_id, group in enumerate(base_groups, start=1):
        subtitle_text = compact_text(" ".join(segment.text for segment in group))
        chunks.append(
            TtsChunk(
                chunk_id=chunk_id,
                segment_indexes=[segment.index for segment in group],
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                subtitle_text=subtitle_text,
                tts_text=subtitle_text,
                emotion_intent=infer_emotion_intent(subtitle_text, chunk_id),
            )
        )

    enriched_chunks: List[TtsChunk] = []
    for index, chunk in enumerate(chunks):
        before = chunks[index - 1].subtitle_text if index > 0 else ""
        after = chunks[index + 1].subtitle_text if index < len(chunks) - 1 else ""
        enriched_chunks.append(
            TtsChunk(
                chunk_id=chunk.chunk_id,
                segment_indexes=chunk.segment_indexes,
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
                subtitle_text=chunk.subtitle_text,
                tts_text=chunk.tts_text,
                emotion_intent=chunk.emotion_intent,
                context_before=before[:220],
                context_after=after[:220],
            )
        )
    return enriched_chunks


def tts_chunks_to_prompt_payload(chunks: List[TtsChunk]) -> str:
    payload = [
        {
            "chunk_id": chunk.chunk_id,
            "segment_indexes": chunk.segment_indexes,
            "target_duration_ms": chunk.duration_ms,
            "max_tts_chars": max_tts_chars_for_duration(chunk.duration_ms),
            "subtitle_text": chunk.subtitle_text,
            "emotion_intent": chunk.emotion_intent,
            "context_before": chunk.context_before,
            "context_after": chunk.context_after,
        }
        for chunk in chunks
    ]
    return json.dumps({"chunks": payload}, ensure_ascii=False, indent=2)


def parse_enhanced_tts_chunks(text: str, fallback_chunks: List[TtsChunk]) -> List[TtsChunk]:
    json_match = re.search(r"\{.*\}", strip_markdown_fence(text), flags=re.S)
    if not json_match:
        raise PipelineError("Gemini TTS Enhance khong tra ve JSON hop le.")
    payload = json.loads(json_match.group(0))
    raw_chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if not isinstance(raw_chunks, list):
        raise PipelineError("JSON TTS Enhance thieu chunks.")

    fallback_by_id = {chunk.chunk_id: chunk for chunk in fallback_chunks}
    enhanced_chunks: List[TtsChunk] = []
    for raw in raw_chunks:
        if not isinstance(raw, dict):
            continue
        chunk_id = int(raw.get("chunk_id", 0))
        base = fallback_by_id.get(chunk_id)
        if base is None:
            continue
        tts_text = shorten_tts_text_for_duration(str(raw.get("tts_text") or base.tts_text), base.duration_ms)
        if not tts_text:
            tts_text = base.tts_text
        if TTS_PRESERVE_SCRIPT and not preserves_spoken_script(base.subtitle_text, tts_text):
            logging.warning(
                "Gemini TTS Enhance chunk %s bo hoac thay chu; giu nguyen script va chi ap dung emotion cue.",
                chunk_id,
            )
            tts_text = base.subtitle_text
        enhanced_chunks.append(
            TtsChunk(
                chunk_id=base.chunk_id,
                segment_indexes=base.segment_indexes,
                start_ms=base.start_ms,
                end_ms=base.end_ms,
                subtitle_text=base.subtitle_text,
                tts_text=tts_text,
                emotion_intent=compact_text(str(raw.get("emotion_intent") or base.emotion_intent)),
                context_before=base.context_before,
                context_after=base.context_after,
            )
        )

    if len(enhanced_chunks) != len(fallback_chunks):
        raise PipelineError("Gemini TTS Enhance tra ve sai so luong chunk.")
    return enhanced_chunks


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


def voice_budget_instructions(source_content: str) -> str:
    segments = parse_srt(source_content)
    limits = []
    for segment in segments:
        max_chars = max(16, round(max(0.5, segment.duration_ms / 1000) * TTS_TARGET_CHARS_PER_SECOND * 1.25))
        limits.append(f"caption {segment.index}: toi da {max_chars} ky tu")
    total_duration_ms = max(segment.end_ms for segment in segments) - min(segment.start_ms for segment in segments)
    total_limit = max(40, round(total_duration_ms / 1000 * TTS_TARGET_CHARS_PER_SECOND))
    return (
        "Gioi han loi doc bat buoc de voice khong bi cat:\n"
        f"- Tong phan text tieng Viet toi da khoang {total_limit} ky tu.\n"
        "- Uu tien y chinh, hook, loi ich va CTA; bo cau dem/lap y.\n"
        "- Moi caption phai la cau/cum tu tron nghia, khong cat nua tu.\n"
        + "\n".join(f"- {limit}" for limit in limits)
    )


def validate_srt_voice_budget(translated_content: str) -> None:
    segments = parse_srt(translated_content)
    total_duration_ms = max(segment.end_ms for segment in segments) - min(segment.start_ms for segment in segments)
    total_limit = max(40, round(total_duration_ms / 1000 * TTS_TARGET_CHARS_PER_SECOND * 1.08))
    total_chars = sum(len(compact_text(segment.text)) for segment in segments)
    if total_chars > total_limit:
        raise PipelineError(f"Script qua dai cho video: {total_chars}/{total_limit} ky tu.")

    overlong_chunks = []
    for chunk in build_default_tts_chunks(segments):
        chunk_chars = len(compact_text(chunk.subtitle_text))
        chunk_limit = round(max_tts_chars_for_duration(chunk.duration_ms) * 1.3)
        if chunk_chars > chunk_limit:
            overlong_chunks.append(f"chunk {chunk.chunk_id}: {chunk_chars}/{chunk_limit}")
    if overlong_chunks:
        raise PipelineError("Script co doan qua day: " + ", ".join(overlong_chunks[:5]))


def fit_srt_to_voice_budget(content: str) -> str:
    fitted_segments: List[SrtSegment] = []
    for segment in parse_srt(content):
        max_chars = max(16, round(max(0.5, segment.duration_ms / 1000) * TTS_TARGET_CHARS_PER_SECOND * 1.2))
        text = compact_text(segment.text)
        if len(text) > max_chars:
            clipped = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
            text = (clipped or text[:max_chars]).rstrip(" ,;:") + "…"
        fitted_segments.append(
            SrtSegment(
                index=segment.index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=text,
            )
        )
    parts = []
    for segment in fitted_segments:
        parts.append(
            "\n".join(
                [
                    str(segment.index),
                    f"{milliseconds_to_srt_time(segment.start_ms)} --> {milliseconds_to_srt_time(segment.end_ms)}",
                    segment.text,
                ]
            )
        )
    return "\n\n".join(parts) + "\n"


def google_translate_text(text: str, source_lang: str = "auto", target_lang: str = "vi") -> str:
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    translated = "".join(part[0] for part in payload[0] if part and part[0])
    return translated.strip() or text


def translate_srt_with_google_fallback(source_content: str) -> str:
    segments = parse_srt(source_content)
    output_segments = []
    for segment in segments:
        output_segments.append(
            SrtSegment(
                index=segment.index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=google_translate_text(segment.text),
            )
        )
    parts = []
    for segment in output_segments:
        parts.append(
            "\n".join(
                [
                    str(segment.index),
                    f"{milliseconds_to_srt_time(segment.start_ms)} --> {milliseconds_to_srt_time(segment.end_ms)}",
                    segment.text.strip(),
                ]
            )
        )
    return validate_translated_srt(source_content, "\n\n".join(parts) + "\n")


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
    def __init__(self, api_keys: List[str], model_name: str):
        self.api_keys = unique_values(api_keys)
        if not self.api_keys:
            raise PipelineError("Chua cau hinh GEMINI_API_KEY/GEMINI_API_KEYS trong .env.")
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise PipelineError("Chua cai google-generativeai. Hay chay: pip install -r requirements.txt") from exc

        self.genai = genai
        self.model_names = []
        for candidate in [model_name, *GEMINI_MODEL_FALLBACKS]:
            if candidate and candidate not in self.model_names:
                self.model_names.append(candidate)

    def generate_text(self, prompt: str, task_name: str) -> str:
        last_error = None
        for key_index, api_key in enumerate(self.api_keys, start=1):
            self.genai.configure(api_key=api_key)
            for model_name in self.model_names:
                logging.info(
                    "Dang goi Gemini key #%s/%s, model %s cho %s...",
                    key_index,
                    len(self.api_keys),
                    model_name,
                    task_name,
                )
                try:
                    response = self.genai.GenerativeModel(model_name).generate_content(prompt)
                    text = (getattr(response, "text", "") or "").strip()
                    if not text:
                        raise PipelineError(f"Gemini model {model_name} khong tra ve text.")
                    return text
                except Exception as exc:
                    last_error = exc
                    logging.warning("Gemini key #%s model %s loi, thu fallback tiep theo: %s", key_index, model_name, exc)
                    continue
        raise PipelineError(
            "Tat ca Gemini API key/model deu loi hoac bi limit. Hay kiem tra GEMINI_API_KEY(S), Google AI project va GEMINI_MODEL. "
            f"Loi cuoi: {last_error}"
        )

    def translate_srt(self, source_content: str) -> str:
        budget_prompt = voice_budget_instructions(source_content)
        prompt = (
            f"{GEMINI_REWRITE_PROMPT}\n\n"
            f"{budget_prompt}\n\n"
            "SRT nguồn:\n"
            f"{source_content}"
        )

        last_error = None
        for attempt in range(1, 4):
            logging.info("Dang rewrite SRT qua Gemini API (lan %s/3)...", attempt)
            try:
                translated_text = self.generate_text(prompt, "rewrite SRT")
                validated_text = validate_translated_srt(source_content, translated_text)
                validate_srt_voice_budget(validated_text)
                return validated_text
            except Exception as exc:
                last_error = exc
                logging.warning("Gemini tra ve chua dat yeu cau: %s", exc)
                prompt = (
                    f"{GEMINI_REWRITE_PROMPT}\n\n"
                    f"{budget_prompt}\n\n"
                    f"Ket qua truoc chua dat: {exc}. Hay tra lai DUY NHAT file SRT tieng Viet, "
                    "giu nguyen 100% so thu tu/timestamp va rut gon dung gioi han loi doc:\n\n"
                    f"{source_content}"
                )
                time.sleep(2)

        if GOOGLE_TRANSLATE_FALLBACK:
            try:
                logging.warning("Gemini khong dung duoc, fallback sang Google Translate de pipeline khong bi dung.")
                fallback_text = translate_srt_with_google_fallback(source_content)
                try:
                    validate_srt_voice_budget(fallback_text)
                    return fallback_text
                except PipelineError:
                    logging.warning("Fallback dich qua dai, rut gon SRT de voice va subtitle luon khop nhau.")
                    return fit_srt_to_voice_budget(fallback_text)
            except Exception as fallback_error:
                raise PipelineError(
                    f"Gemini loi va Google Translate fallback cung loi. Gemini: {last_error}; fallback: {fallback_error}"
                ) from fallback_error

        raise PipelineError(f"Khong dich duoc SRT dung dinh dang qua Gemini: {last_error}")

    def create_post_campaign(self, vietnamese_srt_content: str) -> str:
        prompt = (
            f"{GEMINI_POST_PROMPT}\n\n"
            "SRT tiếng Việt để phân tích sản phẩm và insight:\n"
            f"{vietnamese_srt_content}"
        )
        logging.info("Dang tao chien dich dang bai qua Gemini API...")
        campaign = self.generate_text(prompt, "caption dang bai")
        if not campaign:
            raise PipelineError("Gemini khong tra ve noi dung chien dich dang bai.")
        return campaign

    def create_tts_chunks(self, vietnamese_srt_content: str) -> List[TtsChunk]:
        segments = parse_srt(vietnamese_srt_content)
        fallback_chunks = build_default_tts_chunks(segments)
        if not TTS_ENHANCE_ENABLED:
            logging.info("TTS Enhance dang tat, dung semantic chunk fallback.")
            return fallback_chunks

        prompt = (
            f"{TTS_ENHANCE_PROMPT}\n\n"
            "Semantic chunks can xu ly:\n"
            f"{tts_chunks_to_prompt_payload(fallback_chunks)}"
        )
        try:
            logging.info("Dang enhance text TTS qua Gemini API (%s chunk)...", len(fallback_chunks))
            text = self.generate_text(prompt, "TTS Enhance")
            return parse_enhanced_tts_chunks(text, fallback_chunks)
        except Exception as exc:
            logging.warning("TTS Enhance loi, fallback ve text subtitle goc: %s", exc)
            return fallback_chunks

    def detect_product(self, vietnamese_srt_content: str) -> dict[str, object]:
        prompt = (
            f"{SHOPEE_PRODUCT_PROMPT}\n\n"
            "SRT tiếng Việt:\n"
            f"{vietnamese_srt_content}"
        )
        logging.info("Dang nhan dien san pham de tao link Shopee...")
        text = self.generate_text(prompt, "goi y comment san pham")
        json_match = re.search(r"\{.*\}", text, flags=re.S)
        if not json_match:
            raise PipelineError("Gemini khong tra ve JSON san pham hop le.")
        data = json.loads(json_match.group(0))
        if not isinstance(data, dict):
            raise PipelineError("JSON san pham khong hop le.")
        return data


class AdamTtsClient:
    def __init__(self, api_key: str, api_url: str):
        if not api_key:
            raise PipelineError("Chua cau hinh TTS_API_KEY hoac ELEVENLABS_API_KEY trong .env.")
        if not api_url:
            raise PipelineError("Chua cau hinh API_URL cho dich vu TTS.")
        self.api_key = api_key
        self.api_url = api_url
        self.session = requests.Session()

    @staticmethod
    def _model_candidates() -> List[str]:
        if TTS_MODE == "quality":
            candidates = [TTS_QUALITY_MODEL_ID, TTS_MODEL_ID, TTS_FAST_MODEL_ID]
        else:
            candidates = [TTS_FAST_MODEL_ID, TTS_MODEL_ID, TTS_QUALITY_MODEL_ID]
        return unique_values(candidate for candidate in candidates if candidate)

    def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        previous_text: str = "",
        next_text: str = "",
    ) -> None:
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        if "elevenlabs.io" in self.api_url:
            headers["xi-api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for model_id in self._model_candidates():
            payload = {
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": TTS_VOICE_STABILITY,
                    "similarity_boost": TTS_VOICE_SIMILARITY,
                    "style": TTS_VOICE_STYLE,
                    "use_speaker_boost": True,
                },
            }
            if "elevenlabs.io" in self.api_url:
                if previous_text:
                    payload["previous_text"] = strip_tts_cues(previous_text)[-1000:]
                if next_text:
                    payload["next_text"] = strip_tts_cues(next_text)[:1000]

            for attempt in range(1, TTS_MAX_RETRIES + 1):
                try:
                    logging.info("Dang goi TTS model %s (%s mode)...", model_id, TTS_MODE)
                    response = self.session.post(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=TTS_TIMEOUT_SECONDS,
                    )
                    response.raise_for_status()
                    output_path.write_bytes(response.content)
                    self.last_model_id = model_id
                    return
                except requests.HTTPError as exc:
                    last_error = exc
                    status_code = exc.response.status_code if exc.response is not None else 0
                    if status_code in {400, 403, 404, 422}:
                        logging.warning("TTS model %s khong dung duoc (%s), thu model fallback.", model_id, status_code)
                        break
                    if attempt == TTS_MAX_RETRIES:
                        break
                    wait_seconds = attempt * 2
                    logging.warning("TTS HTTP loi, thu lai sau %ss: %s", wait_seconds, exc)
                    time.sleep(wait_seconds)
                except requests.RequestException as exc:
                    last_error = exc
                    if attempt == TTS_MAX_RETRIES:
                        break
                    wait_seconds = attempt * 2
                    logging.warning("TTS loi mang/API, thu lai sau %ss: %s", wait_seconds, exc)
                    time.sleep(wait_seconds)

        raise PipelineError(f"Loi TTS sau khi thu cac model fallback: {last_error}")


class TimelineDubber:
    def __init__(self, tts_client: AdamTtsClient):
        self.tts_client = tts_client

    def create_dubbed_audio(
        self,
        srt_path: Path,
        output_audio_path: Path,
        segment_audio_dir: Path,
        video_duration_ms: int,
        tts_chunks: Optional[List[TtsChunk]] = None,
        metadata_path: Optional[Path] = None,
    ) -> None:
        try:
            from pydub import AudioSegment
        except ImportError as exc:
            raise PipelineError("Chua cai pydub. Hay chay: pip install -r requirements.txt") from exc

        segments = parse_srt(srt_path.read_text(encoding="utf-8"))
        chunks = tts_chunks or build_default_tts_chunks(segments)
        segment_audio_dir.mkdir(parents=True, exist_ok=True)

        base_duration_ms = video_duration_ms if TTS_FIT_AUDIO_TO_VIDEO and video_duration_ms > 0 else max(video_duration_ms, segments[-1].end_ms)
        final_audio = AudioSegment.silent(duration=base_duration_ms)
        metadata: list[dict[str, object]] = []
        rendered_chunks: list[dict[str, object]] = []

        for chunk in chunks:
            text = prepare_tts_text_for_chunk(chunk, len(chunks))
            if not text:
                continue
            target_duration_ms = max(1, chunk.duration_ms)

            cache_key = build_tts_cache_key(text, chunk)
            segment_path = segment_audio_dir / f"chunk_{chunk.chunk_id:04d}_{cache_key}.mp3"
            if TTS_REUSE_SEGMENTS and segment_path.exists() and segment_path.stat().st_size > 0:
                logging.info("Tai su dung audio chunk %s/%s...", chunk.chunk_id, len(chunks))
                request_status = "cached"
            else:
                logging.info("Dang tao audio chunk %s/%s (%s)...", chunk.chunk_id, len(chunks), chunk.emotion_intent)
                self.tts_client.synthesize_to_file(
                    text,
                    segment_path,
                    previous_text=chunk.context_before,
                    next_text=chunk.context_after,
                )
                request_status = "generated"

            try:
                segment_audio = AudioSegment.from_file(segment_path, format="mp3")
            except Exception as exc:
                raise PipelineError(f"Khong doc duoc audio TTS tai {segment_path}: {exc}") from exc

            original_duration_ms = len(segment_audio)
            if not TTS_AUDIO_FIRST:
                segment_audio = self._fit_audio_to_caption(segment_audio, target_duration_ms, chunk.chunk_id)
            chunk_metadata = {
                    "chunk_id": chunk.chunk_id,
                    "segment_indexes": chunk.segment_indexes,
                    "raw_text": chunk.subtitle_text,
                    "enhanced_text": text,
                    "emotion_intent": chunk.emotion_intent,
                    "context_before": chunk.context_before,
                    "context_after": chunk.context_after,
                    "model_id": TTS_MODEL_ID,
                    "actual_model_id": getattr(self.tts_client, "last_model_id", TTS_MODEL_ID),
                    "model_candidates": AdamTtsClient._model_candidates(),
                    "voice_id": VOICE_ID,
                    "voice_settings": {
                        "stability": TTS_VOICE_STABILITY,
                        "similarity_boost": TTS_VOICE_SIMILARITY,
                        "style": TTS_VOICE_STYLE,
                    },
                    "target_duration_ms": target_duration_ms,
                    "actual_duration_ms": original_duration_ms,
                    "rendered_duration_ms": len(segment_audio),
                    "speed_adjustment_ratio": round(original_duration_ms / len(segment_audio), 4) if len(segment_audio) else 1,
                    "request_status": request_status,
                    "cache_key": cache_key,
                    "audio_file": segment_path.name,
                }
            metadata.append(chunk_metadata)
            rendered_chunks.append({"chunk": chunk, "audio": segment_audio, "metadata": chunk_metadata})

        positions = self._schedule_chunk_positions(rendered_chunks, video_duration_ms)
        for item, position_ms in zip(rendered_chunks, positions):
            segment_audio = item["audio"]
            item["metadata"]["position_ms"] = position_ms
            end_ms = position_ms + len(segment_audio)
            if end_ms > len(final_audio):
                final_audio += AudioSegment.silent(duration=end_ms - len(final_audio))
            final_audio = final_audio.overlay(segment_audio, position=position_ms)

        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        if TTS_FIT_AUDIO_TO_VIDEO and video_duration_ms > 0:
            final_audio = self._fit_final_audio_to_video(final_audio, video_duration_ms, allow_emergency=True)
        elif TTS_STRICT_TIMELINE and not TTS_AUDIO_FIRST:
            final_audio = self._fit_final_audio_to_video(final_audio, video_duration_ms)
        final_audio.export(output_audio_path, format="mp3")
        logging.info("Da luu audio long tieng: %s (%.2fs / video %.2fs)", output_audio_path, len(final_audio) / 1000, video_duration_ms / 1000)
        if metadata_path:
            metadata_path.write_text(
                json.dumps(
                    {
                        "video_duration_ms": video_duration_ms,
                        "audio_duration_ms": len(final_audio),
                        "tts_mode": TTS_MODE,
                        "tts_enhance_enabled": TTS_ENHANCE_ENABLED,
                        "tts_semantic_chunk_enabled": TTS_SEMANTIC_CHUNK_ENABLED,
                        "tts_audio_first": TTS_AUDIO_FIRST,
                        "tts_fit_audio_to_video": TTS_FIT_AUDIO_TO_VIDEO,
                        "tts_use_duration_text_budget": TTS_USE_DURATION_TEXT_BUDGET,
                        "tts_preserve_script": TTS_PRESERVE_SCRIPT,
                        "tts_target_chars_per_second": TTS_TARGET_CHARS_PER_SECOND,
                        "tts_lead_in_ms": TTS_LEAD_IN_MS,
                        "chunks": metadata,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logging.info("Da luu metadata TTS: %s", metadata_path)

    def _schedule_chunk_positions(self, rendered_chunks: list[dict[str, object]], video_duration_ms: int) -> List[int]:
        if not rendered_chunks:
            return []

        positions: List[int] = []
        cursor_ms = max(0, TTS_LEAD_IN_MS)
        for item in rendered_chunks:
            chunk = item["chunk"]
            if TTS_AUDIO_FIRST:
                position_ms = cursor_ms
            elif TTS_STRICT_TIMELINE:
                desired_ms = max(TTS_LEAD_IN_MS, chunk.start_ms)
                position_ms = min(desired_ms, cursor_ms + TTS_MAX_SILENCE_GAP_MS) if positions else desired_ms
                position_ms = max(position_ms, cursor_ms)
            else:
                position_ms = max(chunk.start_ms, cursor_ms)
            positions.append(position_ms)
            cursor_ms = position_ms + len(item["audio"]) + TTS_SEGMENT_GAP_MS

        if not TTS_FIT_AUDIO_TO_VIDEO or video_duration_ms <= 0:
            return positions

        overflow_ms = positions[-1] + len(rendered_chunks[-1]["audio"]) - video_duration_ms
        if overflow_ms <= 0:
            return positions

        for boundary in range(len(positions) - 1, 0, -1):
            previous_end = positions[boundary - 1] + len(rendered_chunks[boundary - 1]["audio"])
            removable_gap = max(0, positions[boundary] - previous_end)
            reduction = min(removable_gap, overflow_ms)
            if reduction:
                for index in range(boundary, len(positions)):
                    positions[index] -= reduction
                overflow_ms -= reduction
            if overflow_ms <= 0:
                break

        if overflow_ms > 0 and positions[0] > 0:
            reduction = min(positions[0], overflow_ms)
            positions = [max(0, position - reduction) for position in positions]
            overflow_ms -= reduction

        if overflow_ms > 0:
            final_end_ms = positions[-1] + len(rendered_chunks[-1]["audio"])
            required_ratio = final_end_ms / video_duration_ms
            raise PipelineError(
                "Voice day du dai hon video %.2fs (can speedup %.2fx). Pipeline dung de tranh cat mat chu; "
                "hay rut gon script/SRT hoac tang TTS_TARGET_CHARS_PER_SECOND."
                % (overflow_ms / 1000, required_ratio)
            )

        logging.info("Da nen khoang nghi timeline de giu tron ven tat ca cau TTS trong video.")
        return positions

    def _fit_audio_to_caption(self, audio: AudioSegment, target_duration_ms: int, caption_index: int) -> AudioSegment:
        if len(audio) <= target_duration_ms:
            return audio

        ratio = len(audio) / target_duration_ms
        max_speedup_ratio = min(MAX_AUDIO_SPEEDUP_RATIO, TTS_QUALITY_MAX_SPEEDUP_RATIO) if TTS_MODE == "quality" else MAX_AUDIO_SPEEDUP_RATIO
        if 1 < ratio < TTS_MIN_SPEEDUP_RATIO:
            return audio
        if TTS_MIN_SPEEDUP_RATIO <= ratio <= max_speedup_ratio:
            try:
                from pydub.effects import speedup

                audio = speedup(audio, playback_speed=ratio, chunk_size=50, crossfade=25)
            except Exception as exc:
                logging.warning("Khong speedup duoc caption %s: %s", caption_index, exc)

        if len(audio) > target_duration_ms:
            logging.warning(
                "Audio caption %s dai hon slot %.2fs, giu nguyen de fit global thay vi cat chu.",
                caption_index,
                target_duration_ms / 1000,
            )

        return audio

    def _fit_final_audio_to_video(self, audio: AudioSegment, target_duration_ms: int, allow_emergency: bool = False) -> AudioSegment:
        audio_class = audio.__class__
        if target_duration_ms <= 0:
            return audio[:0]
        if len(audio) <= target_duration_ms:
            return audio + audio_class.silent(duration=target_duration_ms - len(audio))

        ratio = len(audio) / target_duration_ms
        final_speedup_ratio = min(TTS_FINAL_SPEEDUP_RATIO, TTS_QUALITY_FINAL_SPEEDUP_RATIO) if TTS_MODE == "quality" else TTS_FINAL_SPEEDUP_RATIO
        if allow_emergency:
            final_speedup_ratio = max(final_speedup_ratio, TTS_EMERGENCY_FINAL_SPEEDUP_RATIO)
        if 1 < ratio < TTS_MIN_SPEEDUP_RATIO:
            return audio[:target_duration_ms] if len(audio) > target_duration_ms else audio
        if TTS_MIN_SPEEDUP_RATIO <= ratio <= final_speedup_ratio:
            try:
                from pydub.effects import speedup

                logging.warning(
                    "Tong voice dai %.2fs so voi video %.2fs, speedup global %.2fx de tranh cat chu.",
                    len(audio) / 1000,
                    target_duration_ms / 1000,
                    ratio,
                )
                chunk_size = 60 if ratio > 1.5 else 80
                crossfade = 15 if ratio > 1.5 else 20
                audio = speedup(audio, playback_speed=ratio, chunk_size=chunk_size, crossfade=crossfade)
            except Exception as exc:
                logging.warning("Khong speedup global duoc audio: %s", exc)

        if len(audio) < target_duration_ms:
            return audio + audio_class.silent(duration=target_duration_ms - len(audio))
        if len(audio) > target_duration_ms:
            logging.warning(
                "Tong voice van dai %.2fs, chi trim phan du cuoi con %.2fs.",
                len(audio) / 1000,
                target_duration_ms / 1000,
            )
            fade_ms = min(80, max(12, target_duration_ms // 80))
            return audio[:target_duration_ms].fade_out(fade_ms)
        return audio

    @staticmethod
    def _trim_audio(audio: AudioSegment, target_duration_ms: int, caption_index: int) -> AudioSegment:
        if target_duration_ms <= 0:
            return audio[:0]
        if len(audio) <= target_duration_ms:
            return audio
        fade_ms = min(80, max(12, target_duration_ms // 8))
        logging.warning(
            "Audio caption %s dai hon slot %.2fs, trim con %.2fs de giu sync video.",
            caption_index,
            len(audio) / 1000,
            target_duration_ms / 1000,
        )
        return audio[:target_duration_ms].fade_out(fade_ms)


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
                api_keys=GEMINI_API_KEYS,
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
        tts_script_path = output_dir / "tts_script.json"
        post_campaign_path = output_dir / "chien_dich_dang_bai.txt"
        shopee_links_path = output_dir / "shopee_links.txt"

        copied_video_path = output_dir / f"video_goc{video_path.suffix.lower()}"
        shutil.copy2(video_path, copied_video_path)
        logging.info("Da copy video goc: %s", copied_video_path)

        if LOGO_SOURCE_PATH.exists():
            logo_output_path = output_dir / "logo.png"
            shutil.copy2(LOGO_SOURCE_PATH, logo_output_path)
            logging.info("Da copy logo mac dinh: %s", logo_output_path)
        else:
            logging.warning("Khong tim thay logo mac dinh tai: %s", LOGO_SOURCE_PATH)

        self.extractor.extract_to_srt(video_path, chinese_srt_path)

        logging.info("Dang dich subtitle sang tieng Viet...")
        translated_content = self.translator.translate_srt(chinese_srt_path.read_text(encoding="utf-8"))
        vietnamese_srt_path.write_text(translated_content, encoding="utf-8")
        logging.info("Da luu sub Viet: %s", vietnamese_srt_path)

        try:
            post_campaign = self.translator.create_post_campaign(translated_content)
        except Exception as exc:
            logging.warning("Khong tao duoc chien dich bang Gemini, dung fallback: %s", exc)
            post_campaign = fallback_post_campaign(translated_content)
        post_campaign_path.write_text(post_campaign, encoding="utf-8")
        logging.info("Da luu chien dich dang bai: %s", post_campaign_path)

        try:
            product_data = self.translator.detect_product(translated_content)
        except Exception as exc:
            logging.warning("Khong nhan dien duoc san pham bang Gemini, dung fallback: %s", exc)
            product_data = fallback_product_data(translated_content)
        shopee_links = format_shopee_links(product_data, video_path.name)
        shopee_links_path.write_text(shopee_links, encoding="utf-8")
        logging.info("Da luu link san pham Shopee: %s", shopee_links_path)

        tts_chunks = self.translator.create_tts_chunks(translated_content)
        video_duration_ms = get_video_duration_ms(video_path)
        self.dubber.create_dubbed_audio(
            srt_path=vietnamese_srt_path,
            output_audio_path=dubbed_audio_path,
            segment_audio_dir=work_dir / "tts_chunks",
            video_duration_ms=video_duration_ms,
            tts_chunks=tts_chunks,
            metadata_path=tts_script_path,
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
