#!/usr/bin/env python3
"""Chrome native-messaging frames <-> same-user Unix socket. No commands/shell."""
import json
import os
from pathlib import Path
import select
import socket
import struct
import sys

MAX = 4096


def exact(stream, length):
    chunks = bytearray()
    while len(chunks) < length:
        block = stream.read(length - len(chunks))
        if not block:
            raise EOFError
        chunks.extend(block)
    return bytes(chunks)


def send(message):
    body = json.dumps(message, separators=(",", ":")).encode()
    sys.stdout.buffer.write(struct.pack("=I", len(body)) + body)
    sys.stdout.buffer.flush()


def clean_voice_events(value):
    import re
    if not isinstance(value,dict):return {}
    count=value.get('event_count',0)
    types=value.get('event_types',[])
    playback=value.get('playback_state')
    quiet=value.get('playback_quiet_ms')
    return {'playback_state':playback if isinstance(playback,str) and playback in {'busy','quiet','unknown'} else 'unknown',
            'playback_quiet_ms':min(max(quiet,0),3600000) if type(quiet) in {int,float} and 0<=quiet<=3600000 else 0,
            'source':'data-channel','connected':value.get('connected') is True,
            'supported':value.get('supported') is True,
            'event_count':min(max(count,0),1000000000) if type(count) is int else 0,
            'event_types':[s for s in types[:8] if isinstance(s,str) and re.fullmatch(r'[a-z0-9_.]{1,80}',s)] if isinstance(types,list) else []}


def clean_message(msg):
    """Validate the complete extension protocol before crossing the local socket."""
    allowed = {"arm", "disarm", "status", "register", "report", "session", "resume", "activity", "defer", "voice-ready", "detach", "stop-vetoed"}
    if not isinstance(msg, dict) or msg.get("cmd") not in allowed:
        raise ValueError("unsupported-command")
    cmd = msg["cmd"]
    clean = {"cmd": cmd}
    if cmd in {"session", "resume", "activity", "voice-ready", "stop-vetoed"}:
        token = msg.get("session")
        if not isinstance(token, str) or not 8 <= len(token) <= 64:
            raise ValueError("invalid-session")
        clean["session"] = token
    if cmd == "session":
        clean["existing"] = msg.get("existing") is True
        if isinstance(msg.get("wake_id"), str) and len(msg["wake_id"]) == 32:
            clean["wake_id"] = msg["wake_id"]
    if cmd == "activity":
        state = msg.get("ui_state")
        clean["ui_state"] = state if isinstance(state,str) and state in {"idle", "busy", "unknown"} else "busy" if msg.get("busy") is True else "unknown"
        clean['voice_events'] = clean_voice_events(msg.get('voice_events'))
    if cmd == "register":
        version = msg.get("extension_version")
        if isinstance(version, str) and 0 < len(version) <= 24 and all(c in "0123456789." for c in version):
            clean["extension_version"] = version
    if cmd == "report":
        state = msg.get("state")
        if state not in {"IDLE", "VOICE", "DICTATION", "WAITING", "NEEDS_ACTION", "STOPPED"}:
            raise ValueError("invalid-state")
        clean["state"] = state
    for key in ({"report": ("detail",), "disarm": ("reason",)}.get(cmd, ())):
        if isinstance(msg.get(key), str):
            clean[key] = msg[key][:128]
    if isinstance(msg.get("request"), str):
        clean["request"] = msg["request"][:64]
    return clean


def run():
    # Chrome also enforces this exact origin in the native host manifest.
    config = json.loads((Path(__file__).parent / "identity.json").read_text())
    expected = f"chrome-extension://{config['extension_id']}/"
    if len(sys.argv) < 2 or sys.argv[1] != expected:
        return 1
    path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hey-gpt/control.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        try:
            sock.connect(str(path))
        except OSError:
            send({"type": "error", "detail": "service-unavailable"})
            return 1
        buffered = bytearray()
        stdin = sys.stdin.buffer.raw
        while True:
            ready, _, _ = select.select([stdin, sock], [], [])
            if stdin in ready:
                try:
                    size = struct.unpack("=I", exact(stdin, 4))[0]
                    if size > MAX:
                        return 1
                    msg = json.loads(exact(stdin, size))
                    clean = clean_message(msg)
                    sock.sendall(json.dumps(clean).encode() + b"\n")
                except (EOFError, ValueError):
                    return 0
            if sock in ready:
                chunk = sock.recv(MAX)
                if not chunk:
                    return 0
                buffered.extend(chunk)
                if len(buffered) > MAX * 2:
                    return 1
                while b"\n" in buffered:
                    line, _, rest = buffered.partition(b"\n")
                    buffered = bytearray(rest)
                    send(json.loads(line))


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (OSError, ValueError):
        sys.exit(1)
