#!/usr/bin/env python3
"""Wayland keyboard writer using the user's uinput ACL. No clipboard or Enter."""
import json
import os
import subprocess
import sys
import time
from dictation import keyboard_text

# Linux evdev keycodes, US English layout. Shift is the only modifier emitted.
ROWS=[('1234567890-=',range(2,14)),('qwertyuiop[]',range(16,28)),
      ("asdfghjkl;'`",[*range(30,41),41]),('\\', [43]),('zxcvbnm,./',range(44,54)),(' ',[57])]
KEYS={c:code for chars,codes in ROWS for c,code in zip(chars,codes)}
SHIFTED=dict(zip('!@#$%^&*()_+{}:"~|<>?', '1234567890-=[];\'`\\,./'))

def unlocked(sid):
    try:
        result=subprocess.run(['loginctl','show-session',sid,'-p','Active','-p','Remote','-p','Type','-p','LockedHint'],
                              capture_output=True,text=True,timeout=2,check=True)
        props=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        return props=={'Active':'yes','Remote':'no','Type':'wayland','LockedHint':'no'}
    except (OSError,ValueError,subprocess.SubprocessError):return False


def write_text(device, text, sid, sleep=time.sleep):
    from evdev import ecodes as e
    text=keyboard_text(text)
    if not unlocked(sid):raise RuntimeError('screen-locked-or-session-unavailable')
    held=set()
    try:
        for index,char in enumerate(text):
            if index%32==0 and not unlocked(sid):raise RuntimeError('screen-locked-or-session-unavailable')
            shift=char.isupper() or char in SHIFTED
            base=SHIFTED.get(char,char.lower());code=KEYS[base]
            if shift:device.write(e.EV_KEY,e.KEY_LEFTSHIFT,1);held.add(e.KEY_LEFTSHIFT)
            device.write(e.EV_KEY,code,1);held.add(code);device.syn();sleep(.003)
            device.write(e.EV_KEY,code,0);held.discard(code)
            if shift:device.write(e.EV_KEY,e.KEY_LEFTSHIFT,0);held.discard(e.KEY_LEFTSHIFT)
            device.syn();sleep(.003)
    finally:
        for code in held:device.write(e.EV_KEY,code,0)
        device.syn()


def main():
    from evdev import UInput,ecodes as e
    with UInput({e.EV_KEY:sorted(set(KEYS.values())|{e.KEY_LEFTSHIFT})},name='Hey GPT dictation keyboard') as keyboard:
        time.sleep(.6) # let the compositor discover the new keyboard
        print(json.dumps({'state':'ready'}),flush=True)
        for line in sys.stdin:
            try:
                request=json.loads(line)
                write_text(keyboard,request['text'],request['session'])
                print(json.dumps({'state':'typed'}),flush=True)
            except Exception:
                print(json.dumps({'state':'error','error':'keyboard-input-failed'}),flush=True)

if __name__=='__main__':main()
