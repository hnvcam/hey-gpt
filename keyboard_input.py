#!/usr/bin/env python3
"""Paste Unicode text into the focused Wayland field; never press Enter."""
import json
import shutil
import subprocess
import sys
import time
from dictation import keyboard_text


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
    if not text:return
    if not unlocked(sid):raise RuntimeError('screen-locked-or-session-unavailable')
    # Content travels on stdin, never argv, files, shell commands or logs.
    # wl-copy returns once the owner is ready. Clipboard replacement is explicit;
    # do not read it or restore stale clipboard data over another application's.
    subprocess.run(['wl-copy','--type','text/plain;charset=utf-8'],input=text.encode(),
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,check=True)
    if not unlocked(sid):raise RuntimeError('screen-locked-or-session-unavailable')
    held=set()
    try:
        for code in (e.KEY_LEFTCTRL,e.KEY_V):
            device.write(e.EV_KEY,code,1);held.add(code);device.syn();sleep(.02)
    finally:
        for code in (e.KEY_V,e.KEY_LEFTCTRL):
            if code in held:device.write(e.EV_KEY,code,0)
        device.syn()


def main():
    from evdev import UInput,ecodes as e
    if not shutil.which('wl-copy'):raise RuntimeError('wl-copy-unavailable')
    with UInput({e.EV_KEY:[e.KEY_LEFTCTRL,e.KEY_V]},name='Hey GPT dictation paste') as keyboard:
        time.sleep(.6)
        print(json.dumps({'state':'ready'}),flush=True)
        for line in sys.stdin:
            try:
                request=json.loads(line)
                write_text(keyboard,request['text'],request['session'])
                print(json.dumps({'state':'typed'}),flush=True)
            except Exception:
                print(json.dumps({'state':'error','error':'clipboard-paste-failed'}),flush=True)
            finally:request=None;line=''

if __name__=='__main__':main()
