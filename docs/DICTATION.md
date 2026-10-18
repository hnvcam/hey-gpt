# English keyboard dictation

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Command recording](KEYWORD_RECORDING.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Setup

Install the [local listener](INSTALLATION.md) first. Run all commands from the
project root.

Transcription uses the official NVIDIA **parakeet-tdt-0.6b-v2**, English only,
on the RTX 4060 UUID from `gpu.local.json`; it refuses CPU or another GPU. The
[NVIDIA model](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) is CC-BY-4.0,
revision `ae9ad07059c7c739ffaf932226a8fe64ae2620b0`. Its NeMo runtime is isolated
from the existing Vietnamese wake environment. The offline English command model
is [Vosk small English US 0.15](https://alphacephei.com/vosk/models) (Apache 2.0).

One-time setup, after the existing wake dependencies:

```sh
# Install the system Python keyboard helper and the setup runtime tool.
sudo apt install python3-evdev
pipx install uv
# Both hf (from listener setup) and uv must be on PATH.
.venv/bin/python -m pip install -r requirements.txt
python3 tools/setup_dictation.py
python3 install.py
```

Setup uses `hf` to download the pinned NVIDIA checkpoint and `uv` to create
`.parakeet-venv`. Models, runtime and local settings stay out of Git. The running
service has no internet address families and only loads local files. Settings
are private in `~/.config/hey-gpt/dictation.json`; the service may write only this
application configuration directory and its private runtime directory.

Typing uses Linux uinput with the desktop user's existing device ACL; the agent
never runs as root. `/dev/uinput` must be writable by the logged-in desktop user.
If the device is missing or access is denied, fix the desktop's uinput access
before using dictation. Do not make the device world writable. Use a **US English
keyboard layout** with Caps Lock off. Smart quotes/dashes are normalized for this
keyboard, and line breaks become spaces. The agent emits no Enter, Tab, Ctrl,
Alt or clipboard shortcuts; review dictated terminal commands and press Enter
yourself. Disable, screen lock and Unload cancel pending dictation. A field must
have focus when insertion begins; the agent cannot inspect another app's cursor
on Wayland, so it types wherever you have placed it.

## Dictate into a focused field

Say **“typing this”**, wait for the two ascending ready tones, then speak English.
Text is inserted into the currently focused field without opening Chrome or
moving focus. Finish by either staying silent (default **5 seconds**, configurable
from 2–30 seconds) or pausing at least **0.35 seconds** and saying **“stop typing”**
as a separate utterance. “End typing” and “typing end” work too. A final isolated
phrase is checked again if live command detection missed it or was busy. A final
command sentence is also removed from the transcript before insertion; mentions
inside ordinary sentences remain dictation. Recordings are limited to 3 minutes;
audio and text are kept in memory and are not logged or saved. The agent returns
to wake listening afterward.

While recording, a **transcript board** shows a revisable draft about every five
seconds. Each pass rechecks all audio collected so far (up to the existing
three-minute limit), so the model has the previous speech as context and can
correct earlier wording. The input field is left alone until the final pass:
the finished text is typed once and remains unsent. The board does not request
keyboard focus; keep the destination field focused throughout dictation.
Enable or hide the board in **Cài đặt → Hiện bảng văn bản khi nhập giọng nói**.
The tray menu contains only assistant on/off, Open ChatGPT and Settings. On COSMIC, the board
follows the output configured for the panel containing the status area, even
when another monitor is marked primary. If that panel/output is unavailable,
it falls back to the primary monitor. Xwayland places the popup below the panel
without taking keyboard focus; native Wayland placement is compositor-controlled.
Drafts stay in memory and are delivered only to the local tray, never in status
broadcasts, status files, browser messages or logs. Finishing, cancellation,
screen lock and Unload clear the draft.

## Model controls

Open **Cài đặt…** from the tray menu. All model controls and preferences live here:
**Nạp bộ nhập tiếng Anh**, **Nạp sẵn bộ nhập tiếng Anh khi khởi động**,
**Hiện bảng văn bản khi nhập giọng nói**, the silence timeout, and
**Giải phóng bộ nhớ GPU**. Transcript visibility defaults to on and is saved
alongside the other dictation preferences. The board appears automatically during
recording; it is not an unavailable menu action while idle.

**Giải phóng bộ nhớ GPU** pauses local listening, requests the end of active Chrome
Voice, cancels dictation and terminates both GPU workers: Parakeet and Vietnamese
Wav2Vec2/Silero. It stays available while the service is connected; repeating it
when the models are already unloaded is harmless. The status says **Đã giải phóng
GPU**. Turn the assistant on to reload wake listening. English Vosk stays loaded
on CPU and can confirm “typing this” to load Parakeet after listening resumes.
Changing the startup preference affects the next service start.

**Chi tiết bộ nhận giọng** lists each active component accurately: Vietnamese
Wav2Vec2 on GPU for wake/stop phrases; English Vosk on CPU for dictation commands;
Parakeet on GPU for English transcription; and Silero on GPU for speech activity.
The obsolete Vietnamese Vosk branch has been removed. English Vosk remains in use.

## Local controls

These controls use the same-user socket and are unavailable to the Chrome extension.

```sh
python3 hey_gpt_ctl.py model-load
python3 hey_gpt_ctl.py model-unload
python3 hey_gpt_ctl.py dictation-settings --autoload on --silence 10
python3 hey_gpt_ctl.py typing  # manual equivalent of the spoken trigger
```

## Command recognition

Personal voice similarity alone cannot start dictation: an English recognizer
must also confirm the complete “typing this”/“type this” command.

When the full-vocabulary English detector misses a
command and Parakeet is already loaded, Parakeet checks the same isolated audio
for the entire trigger or stop phrase. This never loads an unloaded model just
to scan background speech. With Parakeet unloaded, a lower-confidence exact Vosk
phrase requires agreement from a second command-grammar pass; grammar alone
cannot wake the assistant. Punctuation is normalized, and phrases inside longer
sentences still do not trigger. `dictation.command_detection` reports counters,
recognizer and latency only, without keeping audio or recognized words.

For personal English command enrollment, see [Command recording](KEYWORD_RECORDING.md#english-typing-commands).
For diagnostics, see [Troubleshooting](TROUBLESHOOTING.md#local-diagnostic-logs).
Prior automated and GPU results are in [Validation history](VALIDATION.md).
