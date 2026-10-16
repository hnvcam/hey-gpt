# Hey GPT

Trợ lý tiếng Việt chạy nền trên **Pop!_OS 24.04 / Wayland**: nghe “Hey GPT” trên máy, mở Voice trong tab ChatGPT của Chrome, rồi trở lại chờ sau khi cuộc gọi kết thúc. Bên trả lời là ChatGPT trên tài khoản đã đăng nhập; ứng dụng không dùng OpenAI API tính phí riêng.

## Cách hoạt động

- **Wav2Vec2 tiếng Việt + Silero VAD trên RTX 4060 CUDA** nhận từ gọi và lệnh dừng. Có thể dùng thêm mẫu âm thanh cá nhân. Cấu hình dịch vụ hiện tại không chạy Vosk, không tự chuyển mô hình sang CPU/GPU khác.
- Khi bật trợ lý, micro local nghe liên tục cả trong phiên Voice. Chrome mở nguồn micro riêng; ứng dụng không chuyển hướng âm thanh hằng ngày.
- Nói riêng “hết”, “kết thúc”, “dừng lại” hoặc “done” sau khoảng nghỉ 1–2 giây để đóng Voice. Những từ này nằm trong một câu dài không được coi là lệnh dừng.
- Hoặc chờ **15 giây sau khi lượt trả lời trên giao diện hoàn tất**, đồng thời người dùng không nói tiếp. Trong lúc xử lý/truyền câu trả lời, bộ đếm chưa chạy.
- Đóng Voice bình thường chỉ đưa local về chờ “Hey GPT”. Lỗi, hạn mức hoặc màn hình khóa không tự mở lại cuộc gọi.

## Cài đặt

Dùng Chrome bản Linux có hỗ trợ Native Messaging, Python 3.12, driver NVIDIA/CUDA tương thích và PipeWire/PulseAudio. Biểu tượng hệ thống cần GTK 3 và Ayatana AppIndicator. Thực hiện các lệnh dưới đây từ thư mục gốc project.

```bash
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 pulseaudio-utils pipx
python3 -m venv .venv
.venv/bin/python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -r requirements.txt
```

Tải mô hình một lần. Công cụ Wav2Vec2 cần Hugging Face CLI (`hf`) trong PATH; CLI được cài riêng để không thay các thư viện của ứng dụng:

```bash
pipx install huggingface-hub
pipx ensurepath
# Mở terminal mới nếu lệnh hf chưa có trong PATH.
.venv/bin/python tools/fetch_wav2vec.py
python3 tools/fetch_vad.py
```

Chọn UUID của **RTX 4060**, ghi vào `gpu.local.json` ở gốc project:

```bash
nvidia-smi --query-gpu=name,uuid --format=csv,noheader
```

```json
{"uuid": "GPU-thay-bang-UUID-cua-RTX-4060"}
```

Dịch vụ mặc định dùng nguồn `mic_noise_suppressed` đã thiết lập trên máy hiện tại. Máy khác dùng `pactl list short sources`, sửa `--source` trong `systemd/hey-gpt.service.in` thành nguồn thực tế rồi cài:

```bash
.venv/bin/python install.py
```

Trình cài tạo cầu nối Chrome, hai dịch vụ systemd user và khởi động lại chúng. Dịch vụ khởi động với micro local đóng; chỉ mở sau khi bật trợ lý. Nếu chuyển vị trí project, chạy lại trình cài và nạp lại đường dẫn tiện ích.

Trong Chrome:

1. Mở `chrome://extensions`, bật **Developer mode**, chọn **Load unpacked** và trỏ tới thư mục **`extension/` của project này**.
2. Mở tab `https://chatgpt.com` đã đăng nhập, cho phép micro theo giao diện thông thường.
3. Trong popup Hey GPT ở đúng tab, bấm **Bật trợ lý**. Gọi “Hey GPT”, đợi Voice mở rồi đặt câu hỏi.

Không cần key OpenAI. Gói tài khoản và hạn mức Voice vẫn do ChatGPT áp dụng; ứng dụng không né hạn mức hoặc tự thử lại cuộc gọi sau thông báo lỗi/giới hạn.

## Bật/tắt và trạng thái micro

Biểu tượng **GPT** trong vùng hệ thống và popup Chrome cho biết trạng thái:

| Màu | Trạng thái |
| --- | --- |
| Xanh lá | Chờ “Hey GPT”, micro local đang nghe |
| Xanh dương | Voice đang mở, local nghe lệnh kết thúc |
| Vàng | Đang chuẩn bị hoặc chuyển trạng thái |
| Xám | Trợ lý tắt hoặc chưa kết nối; xem thông báo |
| Đỏ | Có lỗi cần kiểm tra |

Dùng **Tắt trợ lý và kết thúc Voice** để tắt hẳn. Ẩn biểu tượng không tương đương tắt micro. Nếu Chrome mất kết nối, có thể phải kết thúc Voice trực tiếp trên website.

```bash
python3 hey_gpt_ctl.py status
systemctl --user status hey-gpt.service hey-gpt-tray.service
journalctl --user -u hey-gpt.service -n 50
```

`python3 hey_gpt_ctl.py disarm` chỉ tắt bộ nghe local. Muốn không chạy lúc đăng nhập: `systemctl --user disable --now hey-gpt.service hey-gpt-tray.service`.

## Cấu trúc mã nguồn

| Thành phần | Tệp/thư mục |
| --- | --- |
| Dịch vụ, điều phối micro và trạng thái | `daemon.py`, `audio_control.py`, `conversation_idle.py` |
| Nhận giọng và so khớp mẫu | `wav2vec_recognizer.py`, `voice_activity.py`, `wake_words.py`, `acoustic_keywords.py` |
| Điều khiển local và cầu nối Chrome | `hey_gpt_ctl.py`, `native_host.py` |
| Biểu tượng và bảng điều khiển | `tray.py`, `icons/` |
| Tiện ích Chrome | `extension/` |
| Cài đặt và dịch vụ | `install.py`, `identity.json`, `systemd/` |
| Tải mô hình, thu mẫu, thử lại dữ liệu | `tools/`, [hướng dẫn thu từ khóa](docs/KEYWORD_RECORDING.md) |
| Kiểm tra hồi quy | `tests/` |

Các tệp Python ở gốc là các thành phần của cùng bản ứng dụng hiện tại, không phải các bản sao phiên bản cũ. Kiểm thử vẫn giữ để phát hiện lỗi cắt ngang câu trả lời, mất micro hoặc nhận nhầm lệnh dừng.

## Dữ liệu local và phạm vi đưa lên GitHub

**Đưa lên Git:** mã nguồn, kiểm thử, biểu tượng, hướng dẫn, cấu hình mẫu systemd và dependencies. `identity.json` và `manifest.key` là định danh/public key của tiện ích, cần giữ để ID ổn định; chúng không phải khóa bí mật.

**Giữ trên máy, Git bỏ qua:** `.venv/`, `models/`, `data/`, `recordings/`, `gpu.local.json`, `wake.local.json`, `native-host.sh`, cache, log, HAR và các tệp âm thanh. Không xóa các phần đang dùng chỉ để giảm kích thước repository. `native-host.sh` được sinh lại khi cài; các cấu hình và mẫu giọng cá nhân không được phân phối kèm.

Chế độ nghe hằng ngày không lưu âm thanh/transcript xuống đĩa. Công cụ thu từ khóa chỉ ghi khi người dùng chủ động bật; các bản ghi được giữ local để thử lại. Chỉ âm thanh của phiên Voice được Chrome gửi tới ChatGPT theo cài đặt tài khoản.

Trọng số Wav2Vec2 dùng giấy phép **CC BY-NC 4.0** theo thẻ mô hình được tải; Silero VAD dùng **MIT**. Repository không chứa trọng số. Xem giấy phép upstream trước khi phân phối hoặc dùng mô hình thương mại. Project chưa chọn giấy phép phân phối cho phần mã ứng dụng.

## Kiểm thử và giới hạn đã biết

```bash
.venv/bin/python -B -m unittest discover -s tests -v
node tests/page.test.cjs
node tests/background.test.cjs
node tests/voice-events.test.cjs
node tests/native-connection.test.cjs
node tests/popup.test.cjs
```

Các kiểm thử tự động mô phỏng Chrome/micro; không thay thế kiểm chứng Voice thật. Lượt thử thật ngày 16/10/2026 dùng câu hỏi tiếng Việt tổng hợp qua micro thử của Chrome: trạng thái bận gần một phút, sau đó giao diện hoàn tất mới đếm 15 giây, đóng Voice và trở lại nghe local; micro local vẫn mở xuyên suốt.

Adapter quan sát thụ động kênh WebRTC sẵn có và cấu trúc lượt mới nhất trong DOM. `state_update.listening` từ server **không đủ** để kết luận Chrome đã đọc xong. Không đo âm thanh GPT/độ to loa/tab audible, không lấy cookie/token/SDP, không gửi hoặc replay request riêng. Dấu DOM có thể đổi khi ChatGPT cập nhật; không có dấu hoàn tất rõ thì chưa đếm. Kiểm chứng trên chưa phải phép đo thời điểm phát mẫu âm cuối trong mọi điều kiện mạng.

Sau khi Voice đã đóng, nếu giao diện kẹt quá 15 giây, tiện ích có thể tải lại trang một lần khi không có bản nháp, phiên ghi âm hoặc thông báo lỗi/hạn mức. Việc phục hồi không tự mở cuộc gọi mới. Nhận từ khóa vẫn phụ thuộc micro, tiếng ồn và mẫu giọng; có thể dùng bộ thu local để hiệu chỉnh.
