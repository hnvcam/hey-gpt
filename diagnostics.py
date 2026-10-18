"""Content-free structured diagnostics; systemd's user journal retains/rotates them."""
import json
import time
import traceback


def trace(component, event, **metadata):
    # Never accept speech or recording fields, even if a future caller adds one.
    forbidden={'text','transcript','audio','pcm','preview_text','cookie','token'}
    safe={k:v for k,v in metadata.items() if k not in forbidden}
    print(json.dumps({'at':int(time.time()),'component':component,'event':event,**safe},
                     separators=(',',':')),flush=True)


def trace_error(component, event, error, **metadata):
    # Locations and exception class are useful without exception messages,
    # which could contain dictated text. No locals, audio, or transcript hashes.
    frames=[f'{frame.filename.rsplit("/",1)[-1]}:{frame.lineno}:{frame.name}'
            for frame in traceback.extract_tb(error.__traceback__)[-6:]]
    trace(component,event,error_type=type(error).__name__,frames=frames,**metadata)
