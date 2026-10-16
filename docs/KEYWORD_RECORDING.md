# Bộ câu thu từ khóa Hey GPT

Mỗi dòng dưới đây là **một lần đọc riêng**. Không đọc số thứ tự. Chờ tín hiệu xanh trên trang thu; đọc tự nhiên một lần rồi nghỉ. Với mục im lặng, không đọc gì.

Tắt trợ lý và đóng Voice trước khi thu. Giữ tiếng ồn phòng như lúc sử dụng. Bộ thu lưu song song micro gốc và micro đã lọc, WAV mono PCM16 16 kHz; không gửi lên mạng.

1. [Im lặng 10 giây — tiếng ồn phòng]
2. Hey GPT
3. Hey GPT
4. Hey GPT
5. Hey GPT
6. Hey GPT
7. hết
8. hết
9. kết thúc
10. kết thúc
11. dừng lại
12. dừng lại
13. done
14. done
15. Tôi vẫn chưa nói hết.
16. Câu này có dấu chấm hết.
17. Đừng dừng lại, tôi đang nói.
18. Kết thúc bài này bằng một ví dụ.
19. Hôm nay trời đẹp, tôi muốn hỏi một câu.
20. [Im lặng 10 giây — có thể gõ bàn phím]

## Mở bộ thu

Thực hiện từ thư mục gốc project (không chạy từ docs/):

```bash
python3 tools/keyword_dataset.py serve
```

Mở địa chỉ local vừa hiện. Chỉ bấm **Bắt đầu thu 20 mục** khi đã sẵn sàng; trước đó micro của bộ thu đóng. Có thể **Dừng thu** hoặc **Thu câu này** để làm lại từng câu. Các WAV cũ vẫn được giữ. Mỗi lượt chạy công cụ tạo một thư mục phiên mới.

Dữ liệu nằm trong `recordings/<ngày-giờ>-<mã>/`: WAV, `manifest.json` chứa nhãn/nguồn/mã kiểm tra, và `report.json` sau khi chạy kiểm tra. Thư mục 0700, tệp 0600; toàn bộ `recordings/` được Git bỏ qua. Giữ bản ghi đến khi chủ động xóa; không có tự động tải lên hoặc tự xóa.

## Thử lại cùng dữ liệu

Bấm **Chạy kiểm tra từ bản ghi**, hoặc:

```bash
.venv/bin/python -B tools/keyword_dataset.py evaluate recordings/<thư-mục-phiên>
```

Bản hiện tại chạy Wav2Vec2 và Silero VAD trên RTX 4060 theo cấu hình GPU có sẵn, dùng thêm mẫu âm thanh nếu đã đăng ký. Công cụ đọc lại WAV qua luật nhận từ khóa hiện tại; không chạy Vosk. Không mở Chrome, không phát lại âm thanh ra loa, không thay cấu hình hoặc tự hạ ngưỡng.

Báo cáo tách âm gốc/âm lọc, tập chỉnh `dev`/tập kiểm chứng `test`, từ gọi/lệnh dừng, bỏ sót/kích hoạt nhầm. Báo cáo giữ bản nhận dạng để phân tích dữ liệu đã được cho phép ghi. Lưu mã kiểm tra của mã nguồn và cấu hình ngưỡng để so sánh lần chạy. Không dùng kết quả tập kiểm chứng để tự động chọn ngưỡng; muốn kết luận tổng quát cần thêm mẫu độc lập.

Đây là thử các đoạn ghi riêng, chưa tái hiện tranh chấp hai luồng nhận dạng, thao tác Voice, độ trễ liên tục hoặc tỷ lệ kích hoạt nhầm theo giờ. Khử ồn không bảo đảm loại bỏ giọng người khác phát qua loa. Hai nguồn được thu song song nhưng không bảo đảm đồng bộ đến từng mẫu.

Công cụ chỉ phục vụ thu mẫu và thử lại; không tự sửa bộ lọc hệ thống hoặc tiện ích Chrome. Server chỉ nghe loopback, có địa chỉ bí mật, kiểm tra Origin/Host, tự đóng sau một giờ. Đóng tab không tương đương Dừng thu; hãy bấm Dừng thu nếu cần dừng ngay, hoặc dừng tiến trình.
