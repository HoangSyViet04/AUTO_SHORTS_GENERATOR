# Auto Shorts Generator

Tool xử lý video tiếng Trung sang subtitle và giọng đọc tiếng Việt.

## Cấu trúc

```text
app/
  pipeline.py          # Pipeline CLI/STT/Gemini/TTS
  editor.py            # Composition manifest + FFmpeg video renderer
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
TTS_PRESERVE_SCRIPT=true
TTS_LEAD_IN_MS=80

# Video Editor local-first
EDITOR_AUTO_RENDER=true
OPENCUT_URL=http://localhost:5173

# Facebook Fanpage (đăng thủ công)
FACEBOOK_PAGE_ID=
FACEBOOK_PAGE_URL=
```

Các option pipeline có thể chỉnh trong `Cài đặt & API`; app sẽ lưu lại vào `.env`.

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

Gồm `video_goc.mp4`, `sub_viet.srt`, `giong_doc_viet.mp3`, `logo.png` và `video_final.mp4`.

## Composition Studio / OpenCut bridge

Khi `EDITOR_AUTO_RENDER=true`, pipeline tự ghép video dọc 1080×1920, voice, phụ đề và logo thành `video_final.mp4`. `Workspace` là một studio duy nhất: cột trái chọn video và theo dõi pipeline, giữa xem trước và chỉnh timeline, cột phải chuyển giữa Nội dung, Phụ đề, Âm thanh và Xuất bản. Có thể chỉnh phụ đề/logo/âm lượng rồi render lại ngay tại đây.

Editor có Focus Mode để phóng lớn preview và 5 template phụ đề: Classic, Reveal từng từ, Karaoke highlight, Pop Punch và Neon. Màu chữ chính, màu từ nổi bật, màu viền và màu nền đều có thể chỉnh riêng; hiệu ứng được render trực tiếp vào MP4 bằng ASS/FFmpeg.

Mỗi project có `editor_project.json` làm manifest local-first. Nút `OpenCut Labs` mở URL trong `OPENCUT_URL`; manifest này là lớp adapter để chuyển sang Editor API/headless của OpenCut khi upstream ổn định.

## Đăng Facebook

1. Chọn video trong `Workspace`, chạy pipeline để tạo `video_final.mp4`, hoặc tinh chỉnh và render lại tại preview.
2. Mở `Xuất bản` ở cột phải; vẫn có thể tải MP4 từ CapCut nếu cần fallback.
3. `video_final.mp4` nằm trong `output_results/<tên-project>/`. Tab Xuất bản hiển thị đường dẫn và có nút `Hiện file trong Explorer`.
4. Copy caption rồi bấm `Mở Fanpage`: app mở Facebook và chọn sẵn file MP4 trong Explorer để bạn kéo vào Reels và đăng thủ công.

App luôn dùng `video_final.mp4`, không tự đăng `video_goc.mp4`. Có thể cấu hình link Fanpage trong Cài đặt; nếu để trống, app dùng `FACEBOOK_PAGE_ID` hiện có. Không cần Page Access Token và app không gửi video tới Graph API. TikTok vẫn đăng thủ công.
