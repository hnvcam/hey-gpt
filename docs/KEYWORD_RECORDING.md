# Personal command recording

[Project overview](../README.md) · [Everyday use](USAGE.md) · [English dictation](DICTATION.md) · [Validation history](VALIDATION.md)

Run commands from the project root, not from `docs/`. The recorder saves local
samples only when you explicitly start recording. Spoken Vietnamese examples
below are intentional test material; the instructions are in English.

## Vietnamese wake and stop commands

Each numbered item is **one separate take**. Do not read the number. Wait for
the green signal, speak naturally once, then pause. For silence items, say nothing.

Turn off the assistant and close Voice before recording. Keep room noise similar
to everyday use. The recorder saves both raw and filtered microphone audio as
mono PCM16 16 kHz WAV files; it does not upload them.

1. [10 seconds of silence — room noise]
2. Hey GPT
3. Hey GPT
4. Hey GPT
5. Hey GPT
6. Hey GPT
7. hết
8. hết
9. kết thúc
10. kết thúc
11. dừng lại
12. dừng lại
13. done
14. done
15. Tôi vẫn chưa nói hết.
16. Câu này có dấu chấm hết.
17. Đừng dừng lại, tôi đang nói.
18. Kết thúc bài này bằng một ví dụ.
19. Hôm nay trời đẹp, tôi muốn hỏi một câu.
20. [10 seconds of silence — keyboard noise is allowed]

### Open the recorder

```bash
python3 tools/keyword_dataset.py serve
```

Open the local URL it prints. Click **Bắt đầu thu 20 mục** (“Start recording
20 items”) only when ready; the recorder microphone stays closed before that.
Use **Dừng thu** (“Stop recording”) or **Thu câu này** (“Record this item”) to
stop or repeat individual takes. Old WAVs are kept, and each tool run creates a
new session directory.

Data is stored in `recordings/<date-time>-<id>/`: WAV files, a `manifest.json`
with labels, sources, and checksums, and a `report.json` after evaluation.
Directories use permissions 0700 and files 0600. Git ignores all of `recordings/`.
Files remain until you deliberately delete them; nothing is automatically
uploaded or deleted.

### Replay the same data

Click **Chạy kiểm tra từ bản ghi** (“Run checks from recordings”), or run:

```bash
.venv/bin/python -B tools/keyword_dataset.py evaluate recordings/<session-directory>
```

The current evaluator uses Wav2Vec2 and Silero VAD on the RTX 4060 selected by
the existing GPU configuration, plus enrolled acoustic samples if available.
It replays WAV files through the current keyword rules, without Vietnamese Vosk.
It does not open Chrome, play sound through speakers, change configuration, or
automatically lower thresholds.

Reports separate raw/filtered audio, development (`dev`)/validation (`test`)
splits, wake/stop commands, misses, and false activations. Reports retain
recognizer output for analysis of explicitly recorded data and record source
code and threshold-configuration checksums for comparisons. Validation results
are not used to automatically select thresholds; broader conclusions require
additional independent samples.

### Recording limitations and server behavior

These checks replay isolated recordings. They do not reproduce contention between
recognizers, Voice interactions, continuous latency, or false activations per
hour. Noise suppression does not guarantee removal of someone else's speech from
speakers. Raw and filtered sources are recorded in parallel without guaranteed
sample-level synchronization.

The tool records and replays samples; it does not modify system audio filters or
the Chrome extension. The server binds only to loopback, uses a secret URL,
checks Origin/Host, and expires after one hour. **Closing the tab does not stop
recording**: click Stop recording or stop the process to end capture immediately.

## Vietnamese dictation commands

The `typing-vi` profile records **40 items**: five takes each of “nhập lệnh”,
“gõ câu”, “dừng nhập”, “ngừng nhập”, “hết” and “kết thúc”, eight ordinary sentences
and two background-noise clips. For each phrase, three takes become acoustic
references and two are separate checks. Sentences containing these words help
check false activations. Pause before a stop command and say it as an isolated
utterance; “hết” inside “tôi chưa nói hết” must not finish dictation.

```sh
.venv/bin/python tools/keyword_dataset.py serve --profile typing-vi
```

Open the printed local URL. The microphone stays closed until you click Record.
Recording pauses and unloads Hey GPT automatically. Wait for READ NOW, say the
displayed phrase once, and then stay quiet. Click Train after recording. Only
capture problems require a retake; recognizer misses keep your saved recordings
for adjustment. The app enables itself after successful installation, loading
the new samples.

The bank lives in ignored `data/vietnamese-typing-templates/`. English dictation
and Voice wake/stop banks remain intact. No extra neural model is loaded: the
same CUDA Wav2Vec2 extracts acoustic features. A strict whole-utterance start
match can recover a command misspelled by the transcriber; it compares against
ordinary speech, stop commands, English commands and Voice samples. Broader
similarity still requires lexical confirmation, optionally through the 4-gram. A trained
whole-utterance stop match can finish Vietnamese dictation after the required
pause. The report checks acoustic templates against dev and separate test clips;
it is not a blind evaluation of the entire live microphone/transcription flow.

## English typing commands

Run `.venv/bin/python tools/keyword_dataset.py serve --profile typing` and open
the local URL it prints. Click **Record all 33 items**: five takes for each of
“typing this”, “type this”, “stop typing”, “end typing” and “typing end”, plus
silence and ordinary sentences. Wait for green, speak once, then stay quiet.
Recording pauses the agent; no enrollment microphone opens before Record is
clicked. Both raw and filtered recordings stay private under ignored `recordings/`.

Click **Train & check my voice samples** after recording. Three takes per phrase
form references; two separate takes and the ordinary sentences/noise are replayed
through Silero and the real speech gate. Only reference takes are enrolled.
All checks must pass before the candidate replaces `data/typing-templates`; old
banks remain backed up. Recording problems identify the exact item to retry;
recognition misses are agent issues and do not require a different pronunciation.
The existing `data/keyword-templates` bank for Hey GPT and Vietnamese stops is
never overwritten.

Personal English matching uses the already-loaded Wav2Vec2 acoustic features on
the RTX 4060, so it can recognize your typing trigger with Parakeet unloaded.
Successful training enables the assistant again, loading the new references
with its models. If you abandon the recorder, turn the agent back on
from its tray menu. The local recorder expires after an hour; recordings remain
on disk. The automatic checks do not replace live voice/cursor verification.

Recording feedback distinguishes capture problems from recognition problems.
Each issue names its item, phrase and take, with a reason. Empty, unreadable or
heavily clipped audio gets a direct Retry button; a recognizer miss keeps the
recording and is labeled as an agent adjustment, not a pronunciation failure.
Personal English commands use a separate energy-assisted speech gate so clear
user speech is not discarded solely because Silero misses it. The original
ChatGPT Voice activity and hang-up gates are unchanged.

See [Validation history](VALIDATION.md#personal-english-command-replay) for the saved-session replay result.
