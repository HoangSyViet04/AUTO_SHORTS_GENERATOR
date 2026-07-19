# Auto Shorts Generator

Tool xử lý video tiếng Trung sang subtitle và giọng đọc tiếng Việt.

## Cấu trúc

```text
app/
  pipeline.py          # Pipeline CLI/STT/Gemini/TTS
  server.py            # FastAPI backend cho giao diện
  static/              # Frontend HTML/CSS/JS
input_videos/          # Video .mp4/.mkv đầu vào
output_results/        # Kết quả từng video
temp/                  # File tạm
logs/                  # Log server
main.py                # Wrapper chạy CLI
```

## Cài đặt

```powershell
pip install -r requirements.txt
```

Cần có `ffmpeg` và `ffprobe` trong PATH.

## Cấu hình `.env`

```env
GEMINI_API_KEY=your_gemini_key
ELEVENLABS_API_KEY=your_tts_key

WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_FALLBACK_MODELS=small,base
GEMINI_MODEL=gemini-3.5-flash
TTS_API_URL=https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB
TTS_VOICE_ID=pNInz6obpgDQGcFmaJgB
TTS_MODEL_ID=eleven_flash_v2_5
TTS_TIMEOUT_SECONDS=90
TTS_MAX_RETRIES=3
MAX_AUDIO_SPEEDUP_RATIO=1.35
```

Các option pipeline có thể chỉnh trực tiếp trong tab `Options` của giao diện web; app sẽ lưu lại vào `.env`.

## Chạy giao diện

```powershell
python -m uvicorn app.server:app --host 127.0.0.1 --port 8501
```

Mở:

```text
http://127.0.0.1:8501
```

## Chạy CLI

```powershell
python main.py --limit 1
```

Kết quả nằm trong:

```text
output_results/[ten_video]/
```

Gồm `video_goc.mp4`, `sub_viet.srt`, `giong_doc_viet.mp3`.
