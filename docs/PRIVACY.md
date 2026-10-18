# Privacy and licensing

[Project overview](../README.md) · [Development](DEVELOPMENT.md) · [Command recording](KEYWORD_RECORDING.md)

## Audio, text, and diagnostics

Everyday local listening does not save audio or transcripts to disk. English
dictation keeps audio and text in memory, with a three-minute recording limit.
Drafts are delivered only to the local tray, never in status broadcasts, status
files, browser messages, or logs. Finishing, cancellation, screen lock, and model
unloading clear the draft.

The keyword recorder saves audio only when the user explicitly starts recording.
These files remain local for replay until deliberately deleted. Closing the
recorder tab does not stop recording; use its Stop control or stop the process.
See [Command recording](KEYWORD_RECORDING.md) for storage and server details.

Chrome sends Voice audio to ChatGPT during a Voice session according to your
account settings. The application does not extract cookies or tokens, use private
ChatGPT endpoints, bypass quotas, or automatically retry Voice after errors or
limits. No OpenAI API key or separate API billing is required; your account's
plan and Voice limits still apply.

Local diagnostics use the systemd user journal and contain timing, state, and
sanitized error locations, without audio, transcripts, clipboard contents,
credentials, or exception messages. Nothing is uploaded by diagnostics.
See [Troubleshooting](TROUBLESHOOTING.md#local-diagnostic-logs).

The running listener service is restricted to local Unix sockets and loads
local models. Explicit setup tools download models. Dictation settings are
private in `~/.config/hey-gpt/dictation.json`; the service can write only its
application configuration directory and private runtime directory.

## What belongs in Git

Commit source, tests, icons, documentation, systemd templates, and dependency
lists. `identity.json` and the extension's public manifest key preserve its stable
ID; they are public identifiers, not secret credentials.

Keep these local and ignored:

- `.venv/`, `.parakeet-venv/`, downloaded `models/`, caches, and generated files.
- `data/`, `recordings/`, and personal voice templates.
- `browser.local.json`, `gpu.local.json`, `wake.local.json`, and other local settings.
- Generated `native-host.sh`, logs, HAR files, credentials, and personal audio files.

Do not delete active local data just to shrink the repository. The installer
regenerates `native-host.sh`; personal settings and voice samples are not distributed.

## Model and application licenses

The repository does not contain model weights. The existing setup records these
upstream licenses:

| Model | License recorded by the project |
| --- | --- |
| Vietnamese Wav2Vec2 weights | CC BY-NC 4.0, according to the downloaded model card |
| Silero VAD | MIT |
| NVIDIA `parakeet-tdt-0.6b-v2` | CC BY 4.0 |
| Vosk small English US 0.15 | Apache 2.0 |

Parakeet is pinned to revision `ae9ad07059c7c739ffaf932226a8fe64ae2620b0`.
Model references: [NVIDIA Parakeet](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2)
and [Vosk models](https://alphacephei.com/vosk/models).

Check the upstream license terms before redistributing models or using them
commercially. This project has not selected a distribution license for its
application code.
