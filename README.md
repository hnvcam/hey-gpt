# Hey GPT

[Tiếng Việt](docs/README.vi.md)

A local desktop assistant for **Pop!_OS 24.04 / Wayland** that brings together
Vietnamese wake listening, ChatGPT Voice in Chrome, and English/Vietnamese dictation.
ChatGPT replies through your signed-in account; no OpenAI API key or separate API
billing is required. Your account's Voice limits still apply.

## Features

- Local “Hey GPT” wake detection and Vietnamese stop commands.
- ChatGPT Voice that returns to wake listening after a normal conversation ends.
- English Parakeet v2 Q8 and Vietnamese Wav2Vec2 + 4-gram dictation, with live drafts and Unicode clipboard paste into the focused field.
- A desktop status indicator, model controls, and local diagnostics.

The current setup uses an **NVIDIA RTX 4060**, Python 3.12, Chrome with Native
Messaging, and PipeWire/PulseAudio. Everyday local listening and dictation keep
audio and text in memory; Chrome sends Voice audio to ChatGPT during a Voice session.
Explicit sample recording is available for personal command tuning.

## Documentation

All detailed guides are in English in [`docs/`](docs/).

| Guide | Contents |
| --- | --- |
| [Installation](docs/INSTALLATION.md) | Requirements, models, GPU, services, and Chrome extension setup |
| [Everyday use](docs/USAGE.md) | Voice, wake and stop commands, microphone behavior, and status indicators |
| [English and Vietnamese dictation](docs/DICTATION.md) | Setup, live drafts, clipboard paste, and model controls |
| [Personal command recording](docs/KEYWORD_RECORDING.md) | Vietnamese wake/stop samples and English typing commands |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Service checks, diagnostic logs, Chrome, microphone, and keyboard issues |
| [Development](docs/DEVELOPMENT.md) | Source layout, architecture, and automated test commands |
| [Validation history and limitations](docs/VALIDATION.md) | Simulated tests, recorded-audio checks, and real Chrome/GPU observations |
| [Privacy and licensing](docs/PRIVACY.md) | Local data, Git exclusions, account limits, and model licenses |
