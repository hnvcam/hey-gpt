# Everyday use

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [English dictation](DICTATION.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Start a Voice conversation

To reopen Hey GPT after it exits or its tray icon is hidden, search for **Hey GPT**
in the desktop application launcher and open it. This starts both local services
and respects your saved automatic listening preference.

Say **“Hey GPT”**, wait for the two ascending ready tones, then ask your question.
Vietnamese Wav2Vec2 and Silero VAD on the configured RTX 4060 recognize wake and
stop commands. Optional personal audio samples can improve matching. The Voice
listener stays on the configured GPU. English dictation commands use a separate
English Vosk detector on CPU. Say “nhập lệnh” or “gõ câu” for Vietnamese dictation
with Wav2Vec2 + 4-gram decoding; see [dictation](DICTATION.md). Both languages paste
their final text through the clipboard, preserving Vietnamese accents.

If Chrome is closed, the application launches it through systemd user services,
outside the listener's sandbox. The extension reconnects and uses the attached
ChatGPT tab, an active/recently used tab, or a new tab if needed. To change the
preferred tab, turn the assistant off and on from that tab's extension popup.

Closing Chrome or its tab leaves the local listener running. Chrome launches
only after a new wake command. A pending preparation request expires after
90 seconds; Voice calls are not queued.

The ready cue plays once only after the Voice data channel is open, the server
is listening, the outgoing microphone audio is active, and the interface has
not muted the microphone. A loaded page or visible Voice window is insufficient.
Timeouts, errors, limits, and an unready microphone produce no ready cue and no
automatic Voice retry.

## End a Voice conversation

After a pause of about 1–2 seconds, say **“hết”**, **“kết thúc”**, **“dừng lại”**,
or **“done”** as a separate utterance. These words inside a longer sentence do
not count as stop commands. Local stop commands are accepted only after ChatGPT
audio has stopped; keywords captured while ChatGPT speaks are ignored to avoid
speaker audio ending the call. To interrupt immediately, use **End Voice** or
clear **Bật trợ lý** in the tray menu. The latter also turns off local listening
and unloads all models.

Voice also closes after **15 seconds** with no further user speech, once the
interface has completed the reply and Voice audio is confirmed quiet. The timer
does not run while a reply is processing or playing.

Ending Voice normally returns to local wake listening without a mouse click.
Errors, account limits, and screen locks do not automatically start another call.

## Microphone and status indicators

The local microphone listens continuously while the assistant is enabled,
including during Voice. Chrome opens its own microphone source; the application
does not reroute everyday audio.

The desktop panel uses distinct monochrome shapes and readable labels:

| Label | Shape | Meaning |
| --- | --- | --- |
| Listening | Microphone | Waiting for a wake command |
| Hearing | Sound bars | The local microphone detects sound |
| Dictating | Pencil | Recording English or Vietnamese dictation |
| Finishing / Loading | Hourglass | Transcribing or loading the model |
| Typing | Keyboard | Inserting finished text |
| Voice | Chat bubbles | A browser Voice/dictation session is active |
| Off | Power symbol | The assistant is disabled |
| Error | Warning triangle | A problem needs attention |

Hearing means sound was detected; it does not mean English dictation has started.
No desktop state depends on color. The Chrome popup separately reports the
listener state, microphone status, browser state, and any problem needing attention.

Clear **Bật trợ lý** in the tray menu to turn the assistant off. Hiding the icon
or closing Chrome does not turn off the local microphone. Locking the screen
stops listening and unloads models; after unlocking, enable it again through the GPT menu. If the
browser connection is lost, check Chrome's microphone/Voice state yourself.

## Local controls

Run these from the project root:

| Command | Action |
| --- | --- |
| `python3 hey_gpt_ctl.py status` | Show local listener and browser status |
| `python3 hey_gpt_ctl.py enable` | Load all models and listen without opening Chrome |
| `python3 hey_gpt_ctl.py disable` | Stop listening, unload all models and request the end of Voice |
| `python3 hey_gpt_ctl.py disarm` | Stop local listening and unload all models |
| `python3 hey_gpt_ctl.py wake` | Manually trigger the Chrome/ready-cue flow once |

The manual wake requires an enabled listener and an unlocked screen. It simulates
a wake command; it does not verify spoken wake recognition.

Choose **Cài đặt → Tự động bắt đầu nghe khi khởi động** to control automatic
listening and model loading together. Turning it off stops listening and unloads
all models immediately; later logins keep models unloaded. Turning it on loads
the models and starts listening immediately. The menu's assistant on/off controls
only the current session and always loads/unloads models with listening.

To stop both services and disable automatic startup at login:

```bash
systemctl --user disable --now hey-gpt.service hey-gpt-tray.service
```

For dictation-specific controls, see [English dictation](DICTATION.md).
