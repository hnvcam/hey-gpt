# Development

[Project overview](../README.md) · [Validation history](VALIDATION.md) · [Privacy and licensing](PRIVACY.md)

## Source layout

This project directory is the canonical application source. The Python service,
status indicator, Chrome native messaging host, and extension form one local
application. Root-level Python modules are components of the current application,
not copies of earlier versions. Keep the extension in `extension/` and install it
from there. Rerun `install.py` after relocating the project.

| Component | Files/directories |
| --- | --- |
| Service, microphone coordination, conversation state | `daemon.py`, `audio_control.py`, `conversation_idle.py` |
| Vietnamese recognition and acoustic matching | `wake_worker.py`, `wav2vec_recognizer.py`, `voice_activity.py`, `wake_words.py`, `acoustic_keywords.py` |
| English dictation and keyboard insertion | `dictation.py`, `parakeet_worker.py`, `keyboard_input.py` |
| Local controls and Chrome bridge | `hey_gpt_ctl.py`, `native_host.py` |
| Desktop indicator, draft board, and diagnostics | `tray.py`, `tray_status.py`, `tray_position.py`, `diagnostics.py`, `icons/` |
| Chrome extension | `extension/` |
| Installer and services | `install.py`, `identity.json`, `systemd/` |
| Model downloads, recording, and replay | `tools/`, [command recording guide](KEYWORD_RECORDING.md) |
| Regression checks | `tests/` |

## Voice activity and recovery

The extension passively observes the existing WebRTC channel and the latest
turn's DOM structure. The server's `state_update.listening` alone does **not**
prove Chrome has finished speaking. The 0.7.1 adapter reads Voice audio counters
through WebRTC `getStats`: cumulative energy, sample duration, received packets,
and jitter-buffer delay.

Only busy/quiet/unknown activity states are sent to the service. The adapter does
not capture, store, or reroute ChatGPT audio; measure speaker or tab-audible state;
extract cookies, tokens, or SDP; or send/replay private requests.

Missing counters, stalled networks, ambiguous peers, and stale reports mean
unknown activity and keep the call open. DOM markers may change when ChatGPT
updates. Without a clear completion marker and confirmed quiet audio, the idle
timer does not start. Completed text cannot override audio still playing.
Immediately before closing, the extension requests a fresh activity sample and
checks for 15 continuous idle seconds. Renewed activity cancels closing.
`last_voice_stop` in status/journal records the stop reason and activity flags,
without speech content.

After Voice has closed, a page stuck for more than 15 seconds may be reloaded
once, provided there is no draft, recording, or error/limit notice. Recovery does
not automatically start another call. Normal Voice endings return to local wake
listening; errors and limits never trigger an automatic Voice retry.

## Automated checks

Run from the project root:

```bash
python3 -m unittest discover -s tests -v
node tests/page.test.cjs
node tests/background.test.cjs
```

For the GTK menu and settings checks, use a virtual display and the system Python
with PyGObject installed. These use actual widgets with simulated service data,
without recording a microphone or changing the running app:

```bash
PYTHONPATH="$PWD" HEY_GPT_TEST_GTK=1 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p test_tray_ui.py -v
```

For the additional JavaScript suites:

```bash
node tests/voice-events.test.cjs
node tests/native-connection.test.cjs
node tests/popup.test.cjs
node tests/playback.test.cjs
node tests/typing-studio.test.cjs
```

Use `.venv/bin/python -B -m unittest discover -s tests -v` when running with the
application environment and avoiding bytecode output.

Regression checks cover reply interruption, microphone continuity, false stop
commands, dictation, and related state transitions. Chrome/microphone simulations
do not replace real Voice testing. Report simulated tests separately from real
microphone/Chrome verification, and distinguish synthetic speech from live speech.
See [Validation history and limitations](VALIDATION.md) for prior observations.
