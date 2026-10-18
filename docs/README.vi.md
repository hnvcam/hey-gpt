# Hey GPT

[English](../README.md)

Trợ lý chạy trên **Pop!_OS 24.04 / Wayland**, kết hợp nghe từ gọi tiếng Việt
trên máy, ChatGPT Voice trong Chrome và nhập văn bản tiếng Anh bằng giọng nói.
ChatGPT trả lời qua tài khoản đã đăng nhập; không cần khóa OpenAI API và không
phát sinh phí API riêng. Hạn mức Voice của tài khoản vẫn được áp dụng.

## Tính năng

- Nhận từ gọi “Hey GPT” và lệnh dừng tiếng Việt ngay trên máy.
- Tự trở lại nghe từ gọi sau khi kết thúc cuộc trò chuyện Voice bình thường.
- Nhập văn bản tiếng Anh vào ô đang chọn, với bản nháp trực tiếp và nhận dạng trên GPU local.
- Biểu tượng trạng thái, điều khiển mô hình và chẩn đoán trên máy.

Cấu hình hiện tại dùng **NVIDIA RTX 4060**, Python 3.12, Chrome hỗ trợ Native
Messaging và PipeWire/PulseAudio. Khi nghe và nhập giọng nói hằng ngày, âm thanh
và văn bản được giữ trong bộ nhớ; Chrome gửi âm thanh Voice tới ChatGPT trong
phiên Voice. Có thể chủ động thu mẫu để hiệu chỉnh lệnh cá nhân.

## Tài liệu hướng dẫn

Toàn bộ hướng dẫn chi tiết nằm trong [`docs/`](./) và được viết bằng tiếng Anh.

| Hướng dẫn | Nội dung |
| --- | --- |
| [Cài đặt](INSTALLATION.md) | Yêu cầu, mô hình, GPU, dịch vụ và tiện ích Chrome |
| [Sử dụng hằng ngày](USAGE.md) | Voice, từ gọi, lệnh dừng, hoạt động micro và biểu tượng trạng thái |
| [Nhập văn bản tiếng Anh](DICTATION.md) | Cài đặt, bản nháp trực tiếp, nhập văn bản và điều khiển mô hình |
| [Thu mẫu lệnh cá nhân](KEYWORD_RECORDING.md) | Mẫu từ gọi/lệnh dừng tiếng Việt và lệnh nhập văn bản tiếng Anh |
| [Khắc phục sự cố](TROUBLESHOOTING.md) | Kiểm tra dịch vụ, log chẩn đoán, Chrome, micro và bàn phím |
| [Phát triển](DEVELOPMENT.md) | Cấu trúc mã nguồn, kiến trúc và lệnh kiểm thử tự động |
| [Lịch sử kiểm chứng và giới hạn](VALIDATION.md) | Kiểm thử mô phỏng, bản ghi và quan sát Chrome/GPU thật |
| [Quyền riêng tư và giấy phép](PRIVACY.md) | Dữ liệu local, tệp loại khỏi Git, hạn mức tài khoản và giấy phép mô hình |
