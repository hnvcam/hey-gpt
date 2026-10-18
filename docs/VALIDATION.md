# Validation history and limitations

[Project overview](../README.md) · [Development and test commands](DEVELOPMENT.md#automated-checks) · [Troubleshooting](TROUBLESHOOTING.md)

These are historical observations preserved from the previous README. Dates,
versions, timings, and test totals describe those runs, not a fresh verification
of the current working tree. Automated simulations, recorded/synthetic audio,
and real Chrome/microphone checks are listed separately.

## Automated simulations

Automated checks simulate Chrome and microphones, including quiet startup,
Chrome launch/reconnection, the ready cue, and state transitions. They do not
replace real Voice testing or prove live wake/stop recognition.

- The Voice 0.7.1 validation recorded **90 Python and 84 JavaScript** tests.
- The 17 October 2026 dictation validation recorded **110 Python and 84 JavaScript**
  tests, covering state transitions, command boundaries, silence timing,
  cancellation, keystroke events, and existing Voice behavior.

Current test commands are in [Development](DEVELOPMENT.md#automated-checks).

## Real Chrome and microphone-path observations

### 16 October 2026: reply completion and idle timeout

A real Voice trial used a Vietnamese question synthesized through Chrome's test
microphone. The session stayed busy for nearly a minute. The 15-second countdown
started only after the interface completed the reply; Voice then closed and
returned to local listening. The local microphone stayed open throughout. This
used a real browser session with generated input, rather than the user's live voice.

### 17 October 2026: extension 0.7.0 startup and ready cue

With Chrome running and no ChatGPT tab, a local `wake` command simulated the wake
trigger. The extension created a tab, opened Voice, and confirmed both server
listening and active outgoing microphone audio. `paplay` completed the ready cue
after about four seconds. A second run reused the same tab and played exactly
one new cue after about one second.

Ending Voice returned to `LISTENING`, with the same single local microphone
capture and no errors. This verified real Chrome/microphone/ready-cue behavior
with a manual wake trigger. It did not verify spoken wake recognition or launching
from a state where all Chrome processes had exited.

### 17 October 2026: extension 0.7.1 long audio reply

A separate test tab received a non-sensitive request through Voice's text field
for a roughly two-minute story. Real reply audio played for nearly two minutes.
Activity stayed `busy`, `idle_remaining=null`, and no close request occurred
during playback.

After audio ended, activity moved through `unknown` to `quiet/idle`. Only after
15 idle seconds did `silence-timeout` occur. The closing report confirmed about
17.2 seconds of quiet audio, including initial verification time. The site
returned to Start Voice; the local listener retained one microphone capture
and reported no errors.

The wake trigger was a local command. This did not verify live microphone wake
or stop-command recognition, or the exact final playback sample under every
network condition.

## GPU dictation checks with synthetic speech

On 17 October 2026, real RTX 4060 testing loaded NVIDIA's checkpoint in about
19 seconds, transcribed 3–5 seconds of generated English speech in 51–98 ms with exact expected text,
and transcribed 180 seconds in about 1.4 seconds. After clearing inference caches,
idle model use was about 2.5 GB above the existing listener; terminating the worker
returned VRAM to baseline. The RTX 5070 Ti remained unused. The installed hardened
service reported both English commands and Parakeet ready with the original
Vietnamese listener active and one microphone capture. These GPU checks used
synthetic speech, not a claim of verified recognition of the user's live voice
or insertion into every desktop application.

## Personal English command replay

On 17 October 2026, replaying the user's saved 33-item session with the corrected
English speech gate recovered item 20 (“end typing”, take 4). All 33 items matched
their expected behavior, with no false triggers. This was recorded-audio
validation, not a new live microphone test.

The recording feedback distinguishes capture faults from recognition misses.
English personal commands use a separate energy-assisted speech gate so clear
speech is not rejected solely because Silero misses it. The original ChatGPT
Voice activity and hang-up gates are unchanged by that correction.

## Remaining limitations

- ChatGPT DOM markers can change. Missing, stale, or ambiguous audio activity
  keeps Voice open rather than starting an idle countdown.
- Wake and stop recognition depend on microphone conditions, noise, and personal
  samples. Isolated replay does not measure continuous false activations per hour.
- Synthetic speech and saved recordings do not establish recognition of the user's
  live voice, and simulated keystrokes do not verify every desktop application.
- Native Wayland controls draft-board placement; Xwayland placement can differ.

See [Development](DEVELOPMENT.md#voice-activity-and-recovery) for the activity
adapter and recovery rules, and [Command recording](KEYWORD_RECORDING.md) for
repeatable sample checks.
