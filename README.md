# Hey GPT

Trợ lý tiếng Việt chạy nền trên **Pop!_OS 24.04 / Wayland**: nghe “Hey GPT” trên máy, mở Voice trong tab ChatGPT của Chrome, rồi trở lại chờ sau khi cuộc gọi kết thúc. Bên trả lời là ChatGPT trên tài khoản đã đăng nhập; ứng dụng không dùng OpenAI API tính phí riêng.

## Cách hoạt động

- **Wav2Vec2 tiếng Việt + Silero VAD trên RTX 4060 CUDA** nhận từ gọi và lệnh dừng. Có thể dùng thêm mẫu âm thanh cá nhân. Cấu hình dịch vụ hiện tại không chạy Vosk, không tự chuyển mô hình sang CPU/GPU khác.
- Khi bật trợ lý, micro local nghe liên tục cả trong phiên Voice. Chrome mở nguồn micro riêng; ứng dụng không chuyển hướng âm thanh hằng ngày.
- Nói riêng “hết”, “kết thúc”, “dừng lại” hoặc “done” sau khoảng nghỉ 1–2 giây để đóng Voice. Những từ này nằm trong một câu dài không được coi là lệnh dừng. Lệnh dừng local chỉ được nhận sau khi âm thanh ChatGPT đã ngừng; bỏ qua từ khóa thu trong lúc ChatGPT phát tiếng để tránh loa tự kích hoạt lệnh dừng. Muốn ngắt ngay khi đang phát, dùng menu GPT → Tắt trợ lý và kết thúc Voice hoặc nút End Voice.
- Hoặc chờ **15 giây sau khi lượt trả lời trên giao diện hoàn tất và kênh âm thanh Voice xác nhận yên lặng**, đồng thời người dùng không nói tiếp. Trong lúc xử lý/truyền câu trả lời, bộ đếm chưa chạy.
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

Trình cài tạo cầu nối Chrome, hai dịch vụ systemd user và khởi động lại chúng. Khi đăng nhập hoặc khởi động lại dịch vụ, bộ nghe local tự bật trong phiên Wayland đang mở khóa. Không tự mở cửa sổ điều khiển hay Chrome. Nếu chuyển vị trí project, chạy lại trình cài và nạp lại đường dẫn tiện ích.

Trong Chrome:

1. Mở `chrome://extensions`, bật **Developer mode**, chọn **Load unpacked** và trỏ tới thư mục **`extension/` của project này**.
2. Đăng nhập `https://chatgpt.com` và cho phép micro theo giao diện thông thường một lần.
3. Nói **“Hey GPT” → đợi âm báo hai nốt đi lên → đặt câu hỏi**. Không cần mở Chrome hay chọn tab trước mỗi lần dùng.

Nếu chưa có Chrome, dịch vụ mở Chrome bằng systemd user, ngoài sandbox của bộ nghe. Tiện ích tự nối lại và dùng tab ChatGPT đang gắn, tab đang hoạt động/gần dùng nhất, hoặc tạo tab mới khi không có. Khi Chrome hoặc tab bị đóng, bộ nghe local vẫn chạy. Khởi động Chrome chỉ diễn ra khi có từ gọi mới; yêu cầu đang chuẩn bị hết hạn sau 90 giây, không xếp hàng gọi Voice.

Âm báo chỉ phát một lần sau khi phiên Voice có kênh dữ liệu mở, server ở trạng thái nghe, micro gửi âm thanh đang hoạt động và giao diện không tắt mic. Chỉ tải xong trang hoặc thấy cửa sổ Voice chưa đủ. Nếu hết thời gian, có lỗi/hạn mức hoặc micro chưa sẵn sàng, không phát âm báo và không tự thử lại Voice.

Trình cài lưu tên profile Chrome gần dùng nhất trong `browser.local.json` (mặc định `Default`); có thể sửa trường `profile` nếu tài khoản ChatGPT/tiện ích nằm ở profile khác. Chỉ đọc tên profile, không đọc cookie/token. Muốn đổi tab ưu tiên, tắt/bật trợ lý từ popup của tab đó.

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

Dùng **Tắt trợ lý và kết thúc Voice** để tắt hẳn. Ẩn biểu tượng không tương đương tắt micro. Đóng Chrome/tab không tắt micro local. Màn hình khóa vẫn tắt nghe; mở khóa rồi bật lại qua menu GPT. Lỗi/hạn mức Voice vẫn cần kiểm tra, không tự gọi lại.

```bash
python3 hey_gpt_ctl.py status
systemctl --user status hey-gpt.service hey-gpt-tray.service
journalctl --user -u hey-gpt.service -n 50
```

`python3 hey_gpt_ctl.py wake` kích hoạt một lần bằng tay để thử luồng mở Chrome/âm báo (chỉ khi trợ lý đang nghe và màn hình mở khóa). `python3 hey_gpt_ctl.py enable` bật bộ nghe local mà không mở Chrome. `python3 hey_gpt_ctl.py disable` tắt local và yêu cầu kết thúc Voice; `disarm` chỉ tắt local. Muốn không chạy lúc đăng nhập: `systemctl --user disable --now hey-gpt.service hey-gpt-tray.service`.

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

**Giữ trên máy, Git bỏ qua:** `browser.local.json`, `.venv/`, `models/`, `data/`, `recordings/`, `gpu.local.json`, `wake.local.json`, `native-host.sh`, cache, log, HAR và các tệp âm thanh. Không xóa các phần đang dùng chỉ để giảm kích thước repository. `native-host.sh` được sinh lại khi cài; các cấu hình và mẫu giọng cá nhân không được phân phối kèm.

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

Các kiểm thử tự động, kể cả khởi động im lặng, tự mở/kết nối Chrome và âm báo sẵn sàng, mô phỏng Chrome/micro; không thay thế kiểm chứng Voice thật. Lượt thử thật ngày 16/10/2026 dùng câu hỏi tiếng Việt tổng hợp qua micro thử của Chrome: trạng thái bận gần một phút, sau đó giao diện hoàn tất mới đếm 15 giây, đóng Voice và trở lại nghe local; micro local vẫn mở xuyên suốt.

Kiểm chứng thật ngày 17/10/2026 với tiện ích **0.7.0**: dùng lệnh local `wake` để mô phỏng từ gọi, Chrome đang chạy nhưng không có tab ChatGPT. Tiện ích tự tạo tab, mở Voice và xác nhận server nghe + micro gửi âm thanh đang hoạt động; `paplay` hoàn tất âm báo sau khoảng 4 giây. Lượt tiếp theo tái dùng cùng tab, phát đúng một âm báo mới sau khoảng 1 giây. Kết thúc Voice trở lại `LISTENING`, micro local giữ nguyên một lần capture và không có lỗi. Đây là kiểm chứng Chrome/micro/âm báo thật với từ gọi mô phỏng bằng tay; chưa thử phát âm từ gọi hoặc khởi động khi toàn bộ Chrome đã thoát trong lượt này.

Kiểm chứng thật bản **0.7.1** ngày 17/10/2026: mở một tab thử riêng và gửi câu hỏi không nhạy cảm qua ô nhập trong Voice để yêu cầu kể chuyện khoảng hai phút. Âm thanh trả lời thật chạy gần hai phút; báo cáo audio giữ `busy`, `idle_remaining=null`, không có yêu cầu đóng trong lúc trả lời. Khi âm thanh kết thúc, trạng thái qua `unknown` rồi `quiet/idle`, sau đủ 15 giây mới có `silence-timeout`; báo cáo lúc đóng xác nhận khoảng 17,2 giây audio quiet (bao gồm thời gian xác minh ban đầu). Website trở lại nút Start Voice, local giữ nguyên một lần capture, không có lỗi. Từ gọi của lượt thử được kích hoạt bằng lệnh local; chưa coi đây là kiểm chứng nhận từ gọi hoặc lệnh dừng bằng micro thật. Tổng kiểm thử tự động mô phỏng: 90 Python và 84 JavaScript.

Adapter quan sát thụ động kênh WebRTC sẵn có và cấu trúc lượt mới nhất trong DOM. `state_update.listening` từ server **không đủ** để kết luận Chrome đã đọc xong. Bản 0.7.1 đọc riêng các bộ đếm audio của kết nối Voice qua WebRTC getStats: năng lượng tích lũy, thời lượng mẫu, gói nhận và độ trễ jitter buffer. Chỉ trạng thái busy/quiet/unknown được chuyển về dịch vụ; không thu, lưu hay định tuyến lại audio GPT, không đo loa/tab audible, không lấy cookie/token/SDP và không gửi/replay request riêng. Thiếu bộ đếm, mạng đứng, peer không rõ hoặc báo cáo cũ đều là unknown và giữ cuộc gọi mở. Dấu DOM có thể đổi khi ChatGPT cập nhật; không có dấu hoàn tất rõ và audio quiet được xác nhận thì chưa đếm. Chữ đã hoàn tất không được phép ghi đè âm thanh đang phát; ngay trước khi đóng, tiện ích yêu cầu một mẫu trạng thái mới và kiểm tra lại đủ 15 giây idle liên tục. Nếu hoạt động quay lại, hủy đóng và giữ nguyên cuộc gọi. `last_voice_stop` trong trạng thái/journal lưu lý do dừng và các cờ hoạt động, không lưu lời nói. Kiểm chứng trên chưa phải phép đo thời điểm phát mẫu âm cuối trong mọi điều kiện mạng.

Sau khi Voice đã đóng, nếu giao diện kẹt quá 15 giây, tiện ích có thể tải lại trang một lần khi không có bản nháp, phiên ghi âm hoặc thông báo lỗi/hạn mức. Việc phục hồi không tự mở cuộc gọi mới. Nhận từ khóa vẫn phụ thuộc micro, tiếng ồn và mẫu giọng; có thể dùng bộ thu local để hiệu chỉnh.
