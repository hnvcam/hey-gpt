# Troubleshooting

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Everyday use](USAGE.md)

Run commands from the project root.

## Check the services

```bash
python3 hey_gpt_ctl.py status
systemctl --user status hey-gpt.service hey-gpt-tray.service
journalctl --user -u hey-gpt.service -n 50
```

If the project moved, rerun the [installer](INSTALLATION.md) and reload Chrome's
unpacked extension from this project's `extension/` directory. Installed paths
depend on the project root.

## Local diagnostic logs

Structured diagnostics are enabled in the **systemd user journal**, which manages
retention and rotation. They record state transitions, command acceptance or
rejection, pause lengths, inference timing, final stop checks, popup output and
placement, and sanitized exception locations. Dictation sessions have a short
random diagnostic ID. Logs do **not** contain audio, transcripts, clipboard
contents, credentials, or exception messages. Nothing is uploaded.

```sh
python3 hey_gpt_ctl.py logs           # recent listener + tray diagnostics
python3 hey_gpt_ctl.py logs --follow  # follow the next problem
```

## Chrome opens but there is no ready cue

Check ChatGPT sign-in, microphone permission, whether the microphone is muted,
and any visible error or account-limit notice. The cue requires confirmed Voice
readiness, not just a loaded page. After errors or limits, inspect the problem;
the application does not automatically retry Voice.

Check `browser.local.json` if the wrong Chrome profile opens. The extension and
ChatGPT account must be in the selected profile. To choose a different preferred
tab, turn the assistant off and on through that tab's extension popup.

With the listener enabled and screen unlocked, `python3 hey_gpt_ctl.py wake`
tests the browser/ready-cue flow without requiring a spoken wake command.

If a wake reaches `OPENING` and fails with `setup-required` after about a minute,
the extension could not identify the composer or Voice button. Editable writing
blocks in previous answers must not count as chat composers: the extension uses
the chat composer's own markers and excludes in-message writing blocks. Only an
unsent draft in the actual chat input blocks startup. Missing or multiple chat
composers still stop the operation for inspection.

## Voice stays open or a stop command is ignored

Speak a stop command as a separate utterance after a short pause (at least 0.35
seconds). A locally recognized end command interrupts Voice immediately, even
while ChatGPT speaks or playback status is unknown. Both local language decoders
listen in Voice and in either dictation language, using one shared set of end
commands. The browser's End Voice control and the tray's turn-off action remain
available if speech is not recognized.

The idle timer requires both a completed reply and confirmed quiet Voice audio.
Missing or stale activity information keeps the call open. See the
[Voice architecture](DEVELOPMENT.md#voice-activity-and-recovery) and
[validation limitations](VALIDATION.md) for details.

After Voice closes, the extension may reload a stuck page once after 15 seconds,
provided no draft, recording, error, or limit notice is present. This recovery
does not open a new call.

## The microphone is still listening

Closing Chrome, closing its tab, or hiding the tray icon leaves the local
listener running. Use the tray's **Tắt trợ lý và kết thúc Voice** or
`python3 hey_gpt_ctl.py disable`. If Chrome is disconnected, inspect its Voice
session separately. Screen lock disables local listening; enable it again after
unlocking.

If the audio source is missing, select a valid source as described in
[Installation](INSTALLATION.md#select-the-microphone-and-install-services).
Wake recognition depends on the microphone, noise, and personal voice samples;
use [personal command recording](KEYWORD_RECORDING.md) to inspect recorded samples.

## Dictation does not start or text goes to the wrong place

Wait for the ready cue after “typing this”, especially after unloading the model.
The Hearing label alone does not indicate dictation. Check model controls and
local diagnostics in the [dictation guide](DICTATION.md).

Keep the destination field focused. Wayland prevents the assistant from
inspecting another application's cursor; text goes wherever you place it.
Both languages paste Unicode text through `wl-copy` and Ctrl+V; install
`wl-clipboard` if paste is unavailable. Each insertion replaces the clipboard.
The logged-in desktop
user must have write access to `/dev/uinput`; do not run the agent as root or
make the device world writable. See [dictation setup](DICTATION.md#models-and-setup).

On COSMIC, the draft board follows the output configured for the panel containing
the status area, falling back to the primary monitor if needed. The tray selects
Xwayland explicitly when available, even if the desktop exports `GDK_BACKEND=wayland`.
The board uses an overlay so COSMIC cannot activate it in place of the paste target.
It appears during preparation and stays through recording and insertion.
Xwayland places it below the panel; native Wayland placement is controlled
by the compositor.
