# Installation

[Project overview](../README.md) · [Everyday use](USAGE.md) · [Troubleshooting](TROUBLESHOOTING.md)

Run all commands from the project root. Keep the application here and load its
Chrome extension directly from `extension/`.

## Requirements

The current setup targets Pop!_OS 24.04 / Wayland with Python 3.12, an NVIDIA
RTX 4060 and compatible NVIDIA/CUDA drivers, Chrome for Linux with Native
Messaging, and PipeWire/PulseAudio. The system indicator needs GTK 3 and Ayatana
AppIndicator. GPU selection is explicit; the recognizers do not silently fall
back to the CPU or another GPU.

## Install the local listener

```bash
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 pulseaudio-utils pipx
python3 -m venv .venv
.venv/bin/python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -r requirements.txt
```

Download the models once. Install the Hugging Face CLI separately so it does not
replace the application's libraries:

```bash
pipx install huggingface-hub
pipx ensurepath
# Open a new terminal if hf is not yet on PATH.
.venv/bin/python tools/fetch_wav2vec.py
python3 tools/fetch_vad.py
```

Find the **RTX 4060** UUID:

```bash
nvidia-smi --query-gpu=name,uuid --format=csv,noheader
```

Create `gpu.local.json` in the project root using that UUID:

```json
{"uuid": "GPU-replace-with-your-RTX-4060-UUID"}
```

## Select the microphone and install services

The service template defaults to `mic_noise_suppressed`, a source configured on
the original machine. On another machine, list the available sources:

```bash
pactl list short sources
```

Set `--source` in [`systemd/hey-gpt.service.in`](../systemd/hey-gpt.service.in)
to the actual source, then run:

```bash
.venv/bin/python install.py
```

The installer registers the Chrome native messaging bridge, creates two systemd
user services, enables them, and restarts them. The local listener starts
automatically at login or service restart in an unlocked Wayland session when
**Tự động bắt đầu nghe khi khởi động** is enabled in Settings (the default).
That one preference controls listening and all model loading together. When it
is off, startup leaves the microphone closed and every model unloaded. The
application does not open the control panel or Chrome at startup.

Installed paths are derived from this project root. After moving the project,
run the installer again and reload the extension from its new `extension/` path.
The generated `native-host.sh` stays local.

## Connect Chrome

1. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**,
   and select this project's **`extension/`** directory.
2. Sign in at [ChatGPT](https://chatgpt.com) and grant microphone permission
   through the normal browser interface once.
3. Say **“Hey GPT”**, wait for the two ascending ready tones, then ask a question.

You do not need to open Chrome or select a tab for every conversation. See
[Everyday use](USAGE.md) for tab selection and readiness behavior.

The installer saves the last-used Chrome profile name in `browser.local.json`,
defaulting to `Default`. Edit its `profile` field if ChatGPT and the extension
are in another profile. It reads only the profile name, without cookies or tokens.

No OpenAI key is required. Your ChatGPT plan and Voice limits still apply;
the application does not bypass limits or automatically retry Voice after errors.

## English and Vietnamese dictation models

Complete [dictation setup](DICTATION.md#models-and-setup) to install English Vosk,
Parakeet v2 Q8 with its CUDA runtime, and Vietnamese KenLM 4-gram decoding, then
restart the listener. Enabling listening loads
all models together; if a model is missing or fails, the assistant stops and
unloads the other models. Unicode paste requires `wl-clipboard` and desktop
keyboard-device access for the Ctrl+V chord. KenLM and Vosk run on CPU; acoustic
recognition runs on the configured RTX 4060.
