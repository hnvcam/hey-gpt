# Hey GPT project

This directory is the canonical application source. Keep the Chrome extension in
`extension/` and install it from that directory. Do not move application sources
back into a generated chat output directory.

The Python service, status indicator, Chrome native messaging host and extension
form one local application. `install.py` derives all installed paths from this
project root. Re-run it after relocating the project.

Preserve Vietnamese local speech recognition, no OpenAI API billing, no cookie or
token extraction, no private ChatGPT endpoints, and no quota bypass or automatic
Voice retry after errors or limits. Ending Voice normally should return to local
wake listening without requiring a mouse click.

Keep `.venv/`, downloaded models, generated `native-host.sh`, logs, recordings and
credentials out of future commits. The extension manifest key is public and is
kept to preserve the extension ID.

Validation:

```sh
python3 -m unittest discover -s tests -v
node tests/page.test.cjs
node tests/background.test.cjs
```

Report simulated tests separately from real microphone/Chrome verification.
