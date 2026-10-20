# English and Vietnamese dictation

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Command recording](KEYWORD_RECORDING.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Dictate into a focused field

Keep the destination field focused. Speak one isolated trigger and wait for the
two ascending ready tones before dictating:

| Language | Start | Spoken finish |
| --- | --- | --- |
| English / Parakeet TDT v2 Q8 | “typing this” or “type this” | “stop typing”, “end typing” or “typing end” |
| Vietnamese / Wav2Vec2 + 4-gram | “nhập lệnh” or “gõ câu” | “dừng nhập”, “ngừng nhập”, “hết” or “kết thúc” |

Pause at least 0.35 seconds before a spoken finish and say it as a separate
utterance. Commands inside ordinary sentences do not count. You can also finish
by staying silent (default 5 seconds, configurable from 2–30). Recordings have a
three-minute limit. A final isolated stop phrase is rechecked if live command
detection missed it. The app returns to wake listening afterward.

Both languages **paste once using the clipboard**, preserving Unicode and
Vietnamese accents. On COSMIC, the app checks the active application's ID just
before insertion: Tabby, COSMIC Terminal and other recognized terminal apps use
**Ctrl+Shift+V**; other apps use **Ctrl+V**. If app detection is unavailable, it
keeps Ctrl+V. This identifies the application, not individual fields or embedded
terminals inside editors. Window titles and field contents are not retained.
No alternate shortcut is retried. No Enter or Tab is sent; text remains unsent. Each paste
replaces the clipboard contents, which may remain in clipboard history until
cleared. The app does not read or restore your previous clipboard. Review text,
especially terminal commands, before pressing Enter yourself. The app transcribes
words; it does not interpret Vietnamese dictation as commands to execute.

Linux uinput sends only the paste chord using your existing device ACL; the
agent never runs as root. `/dev/uinput` must be writable by your desktop user.
Do not make it world writable. A field must have focus when insertion begins;
the app cannot inspect another app's cursor on Wayland. Disable, screen lock and
model unload cancel pending dictation and keyboard work.

## Transcript board

The board shows a revisable draft about every five seconds. Each pass rechecks
the bounded recording so later context can correct earlier words. The focused
field is left alone until the final paste. The board does not request keyboard
focus. Enable or hide it in **Cài đặt → Hiện bảng văn bản khi nhập giọng nói**.

On COSMIC, the board follows the output configured for the panel containing the
status area. If unavailable it falls back to the primary monitor. Xwayland puts
the popup below the panel without taking focus; native Wayland placement is
compositor-controlled. Drafts stay in memory and are delivered only to the local
tray, never in status files, broadcasts, browser messages or logs. Finishing,
cancellation, lock and unload clear the draft; pasted text follows the desktop's
normal clipboard behavior.

## Models and setup

English uses the CC-BY-4.0 NVIDIA **parakeet-tdt-0.6b-v2**, converted to Q8_0 GGUF
from [mudler/parakeet-cpp-gguf](https://huggingface.co/mudler/parakeet-cpp-gguf),
revision `741158ae71e64ef5c89385862c18f777d07a97a1`. A persistent
[parakeet.cpp](https://github.com/mudler/parakeet.cpp) C API context reuses the
model across requests without PyTorch or NeMo. Runtime source is pinned to
`5c9b0fbbd8e611d88e47d7e1ebae9bca9b447e8f`. The configured RTX 4060 UUID is
selected before CUDA initializes. Missing CUDA, CPU fallback and another GPU are
rejected. CUDA graph reservations are disabled.

Vietnamese shares the existing **Wav2Vec2 Base Vietnamese 250h** on the same
RTX 4060. There is no second acoustic model copy. The author's **4-gram KenLM**
from [the Vietnamese model repository](https://huggingface.co/nguyenvulebinh/wav2vec2-base-vietnamese-250h),
revision `69e9000591623e5a4fc2f502407860bcdc0de0b2`, runs in CPU/system RAM with
pyctcdecode (beam width 32). Eight-second GPU windows have one-second context on
each side of a six-second core; overlapping frame logits are trimmed and joined
for one language-model decode. The CPU decoder has its own process so beam search
does not block local VAD. Wav2Vec2 and Silero remain on GPU; Vosk English command
detection remains on CPU.

Complete the [local listener installation](INSTALLATION.md) first, then run from
the project root with `hf`, `git` and the CUDA toolkit's `nvcc` on PATH:

```sh
sudo apt install python3-evdev wl-clipboard build-essential cmake
.venv/bin/python -m pip install -r requirements.txt
python3 tools/setup_dictation.py
python3 install.py
```

Setup downloads pinned files with `hf`, verifies SHA-256 checksums, extracts the
4-gram model and its vocabulary, and builds CUDA libraries for compute capability
8.9. The former `.parakeet-venv` / NeMo runtime is unused. Models, libraries and
personal data stay ignored by Git. Runtime performs no downloads and the service
is restricted to local Unix sockets. Rebuild the runtime after moving the project.

## Listening and controls

**Cài đặt → Tự động bắt đầu nghe khi khởi động** is the single startup preference
for listening and all models. On loads Wav2Vec2/Silero, Parakeet Q8, Vosk and the
4-gram decoder before opening the microphone. Off stops listening and unloads
all models. The tray and extension on/off controls affect the current session
without changing that startup preference. Errors unload the models without an
automatic retry. Settings remain in `~/.config/hey-gpt/dictation.json`.

```sh
python3 hey_gpt_ctl.py settings --auto-listen on
python3 hey_gpt_ctl.py settings --auto-listen off
python3 hey_gpt_ctl.py settings --silence 10
python3 hey_gpt_ctl.py enable
python3 hey_gpt_ctl.py disable
python3 hey_gpt_ctl.py typing  # manual English dictation
```

Legacy `model-load` / `model-unload` commands alias enable / disable. A strict
whole-utterance personal match can start English or Vietnamese dictation even
when a general transcriber misspells your command. It requires acoustic distance
at most 0.25 and margin at least 0.10 against ordinary speech, stop commands,
the other language's commands and Voice samples. Broader personal similarity
still needs the complete lexical phrase. Vosk and loaded Parakeet provide
English fallback; Wav2Vec2 and the 4-gram decoder provide Vietnamese fallback.
Vietnamese samples stay in their own bank, separate from English and Voice.
Whole-utterance personal stop matches still require a pause. See
[Vietnamese command recording](KEYWORD_RECORDING.md#vietnamese-dictation-commands).

No model is loaded merely to scan background speech after unload. Status exposes
engine names, language, timings and counters without transcripts. See
[command recording](KEYWORD_RECORDING.md#english-typing-commands) for English
enrollment and [validation history](VALIDATION.md) for verification boundaries.
