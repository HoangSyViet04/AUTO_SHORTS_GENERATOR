Bạn là một Senior Python Developer chuyên về Automation và Media Processing. Hãy viết một script Python hoàn chỉnh, chạy cấu trúc rõ ràng (Production-ready) để tự động hóa pipeline xử lý video ngắn từ tiếng Trung sang tiếng Việt. 

hiện tại thì project của t vẫn khá cùi  , hãy update cho t nha :

Yêu cầu hệ thống phải thực hiện mượt mà các bước sau:

1. CẤU TRÚC THƯ MỤC & ĐẦU VÀO:
- Tự động tạo thư mục `input_videos/` và `output_results/` nếu chưa có.
- Script sẽ quét thư mục `input_videos/` để tìm file video (.mp4, .mkv).

2. BƯỚC 1: TRÍCH XUẤT AUDIO VÀ SUBTITLE TIẾNG TRUNG (STT)
- Sử dụng thư viện `faster-whisper` (mô hình 'base' hoặc 'small' để chạy nhanh, hỗ trợ cả CPU/GPU).
- Nhận đầu vào là video -> Tiến hành trích xuất tiếng Trung và xuất ra file `sub_trung.srt` lưu trong thư mục tạm.

3. BƯỚC 2: DỊCH SRT SANG TIẾNG VIỆT QUA GEMINI API
- Sử dụng thư viện chính thức `google-generativeai`.
- Viết một hàm nhận vào nội dung file `sub_trung.srt` và gửi prompt đến model `gemini-2.5-flash` (hoặc bản mới nhất).
- Prompt gửi cho Gemini cần ép ràng buộc nghiêm ngặt: "Bạn là dịch thuật viên chuyên nghiệp cho video TikTok. Hãy dịch nội dung file SRT này từ tiếng Trung sang tiếng Việt chuẩn văn phong bản địa, tự nhiên. BẮT BUỘC giữ nguyên định dạng file SRT, số thứ tự các đoạn và toàn bộ các mốc thời gian (timestamps). Chỉ trả về nội dung file SRT sau khi dịch, tuyệt đối không thêm lời giải thích hay bọc trong markdown ```srt."
- Lưu kết quả thành file `sub_viet.srt`.

4. BƯỚC 3: XỬ LÝ LỒNG TIẾNG TỰ ĐỘNG (TTS) KHỚP TIMELINE
- Thiết kế một hàm xử lý Text-to-Speech (TTS). Vì tôi đang dùng giọng đọc Adam (hãy để hàm này ở dạng mẫu/vỏ bọc Clean Architecture, sử dụng thư viện `requests` để gọi API, có biến `API_KEY` và `API_URL` ở đầu file để tôi dễ dàng cấu hình endpoint của bên cấp giọng đọc sau).
- Logic xử lý âm thanh quan trọng: Đọc file `sub_viet.srt`. Với mỗi dòng sub, lấy text gửi lên API để tải về file audio nhỏ (.mp3). Sau đó, sử dụng thư viện `pydub` để nối các đoạn audio này lại thành một file duy nhất là `giong_doc_viet.mp3`. 
- ĐẶC BIỆT: Phải tính toán khoảng lặng (silence padding) dựa trên timestamp của file SRT để đảm bảo câu thoại tiếng Việt phát ra khớp chuẩn từng giây với mốc thời gian trong video gốc.

5. ĐẦU RA (OUTPUT):
Sau khi chạy xong, trong thư mục `output_results/[Tên_Video_Gốc]/` phải chứa đủ 3 file:
- File `video_goc.mp4` (Hoặc file video gốc được copy sang).
- File `sub_viet.srt` (Subtitle tiếng Việt chuẩn timeline).
- File `giong_doc_viet.mp3` (File audio lồng tiếng Việt hoàn chỉnh chạy suốt video).

YÊU CẦU KỸ THUẬT:
- Code viết bằng Python 3, cấu trúc hướng đối tượng (OOP) hoặc chia hàm (Modular) rõ ràng, sạch sẽ.
- Có hệ thống logging rõ ràng tại từng bước để dễ theo dõi tiến độ (Ví dụ: [INFO] Đang trích xuất sub Trung..., [INFO] Đang dịch qua Gemini API...).
- Bắt lỗi ngoại lệ (try-except) chặt chẽ, đặc biệt là lỗi nghẽn mạng khi gọi API hoặc file SRT lỗi định dạng.
- Viết code HOÀN CHỈNH, KHÔNG viết tắt, KHÔNG để lại các đoạn comment kiểu `# Code xử lý tiếp theo ở đây...` hoặc `# TODO`.
- Tạo kèm một đoạn text hướng dẫn các thư viện cần cài đặt (requirements.txt).