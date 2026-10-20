"""Read COSMIC's active app ID for paste shortcuts; no titles or text are kept.

Only registry, sync and toplevel-info v1 are needed, so use the standard Wayland
wire format without an extra desktop service or Python package. Protocols:
https://wayland.freedesktop.org/docs/book/Protocol.html
https://github.com/pop-os/cosmic-protocols/blob/main/unstable/cosmic-toplevel-info-unstable-v1.xml
"""
import os
from pathlib import Path
import socket
import struct
import time


INFO = 'zcosmic_toplevel_info_v1'
TERMINALS = frozenset({
    'tabby', 'org.tabby', 'com.tabby', 'com.eugeny.tabby',
    'com.system76.cosmicterm', 'cosmic-term',
    'org.gnome.terminal', 'gnome-terminal', 'gnome-terminal-server',
    'org.gnome.console', 'kgx', 'org.kde.konsole', 'konsole',
    'alacritty', 'org.alacritty.alacritty', 'kitty', 'net.kovidgoyal.kitty',
    'org.wezfurlong.wezterm', 'wezterm', 'org.codeberg.dnkl.foot', 'foot',
    'com.mitchellh.ghostty', 'ghostty', 'xfce4-terminal',
    'terminator', 'tilix', 'com.gexperts.tilix', 'xterm', 'uxterm',
})


def terminal_app(app_id):
    value = (app_id or '').casefold()
    if value.endswith('.desktop'):
        value = value[:-8]
    return value in TERMINALS


def _uint(value):
    return struct.pack('=I', value)


def _string(value):
    data = value.encode() + b'\0'
    return _uint(len(data)) + data + b'\0' * (-len(data) % 4)


def _read_string(data, offset=0):
    size, = struct.unpack_from('=I', data, offset)
    end = offset + 4 + size
    if not size or end > len(data) or data[end - 1] != 0:
        raise ValueError('invalid-wayland-string')
    return data[offset + 4:end - 1].decode(), offset + 4 + ((size + 3) & ~3)


class _Connection:
    def __init__(self, sock, deadline):
        self.sock = sock
        self.deadline = deadline

    def _timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('paste-target-timeout')
        self.sock.settimeout(remaining)

    def send(self, obj, opcode, payload=b''):
        self._timeout()
        self.sock.sendall(struct.pack('=II', obj, ((8 + len(payload)) << 16) | opcode) + payload)

    def _read(self, size):
        data = bytearray()
        while len(data) < size:
            self._timeout()
            part = self.sock.recv(size - len(data))
            if not part:
                raise OSError('wayland-disconnected')
            data.extend(part)
        return bytes(data)

    def events_until(self, callback):
        # Bound both elapsed time and event count, including malformed peers.
        for _ in range(8192):
            obj, header = struct.unpack('=II', self._read(8))
            size, opcode = header >> 16, header & 0xffff
            if size < 8 or size % 4:
                raise ValueError('invalid-wayland-message')
            payload = self._read(size - 8)
            if obj == 1 and opcode == 0:
                raise OSError('wayland-protocol-error')
            if obj == callback and opcode == 0:
                return
            yield obj, opcode, payload
        raise ValueError('too-many-wayland-events')


def active_app_id(timeout=.3):
    """Fresh COSMIC v1 snapshot, or None if unavailable/ambiguous; never cache focus."""
    display = os.environ.get('WAYLAND_DISPLAY')
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not display or (not os.path.isabs(display) and not runtime):
        return None
    path = display if os.path.isabs(display) else str(Path(runtime) / display)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            connection = _Connection(sock, time.monotonic() + timeout)
            connection._timeout()
            sock.connect(path)
            connection.send(1, 1, _uint(2))  # wl_display.get_registry
            connection.send(1, 0, _uint(3))  # wl_display.sync
            global_name = None
            for obj, opcode, payload in connection.events_until(3):
                if obj == 2 and opcode == 0:  # wl_registry.global
                    interface, _ = _read_string(payload, 4)
                    if interface == INFO:
                        global_name, = struct.unpack_from('=I', payload)
            if global_name is None:
                return None
            # Bind v1 deliberately: newer COSMIC versions preserve its app_id
            # and activated-state events without ext-foreign-toplevel objects.
            connection.send(2, 0, _uint(global_name) + _string(INFO) + _uint(1) + _uint(4))
            connection.send(1, 0, _uint(5))
            windows = {}
            for obj, opcode, payload in connection.events_until(5):
                if obj == 4 and opcode == 0:  # info.toplevel
                    handle, = struct.unpack('=I', payload)
                    windows[handle] = {'app_id': None, 'active': False}
                elif obj in windows:
                    if opcode == 0:  # handle.closed
                        del windows[obj]
                    elif opcode == 3:  # handle.app_id; title events are ignored
                        windows[obj]['app_id'], _ = _read_string(payload)
                    elif opcode == 8:  # handle.state: activated = 2
                        length, = struct.unpack_from('=I', payload)
                        if length % 4 or length + 4 != len(payload):
                            raise ValueError('invalid-wayland-state')
                        windows[obj]['active'] = 2 in struct.unpack('='+ 'I' * (length // 4), payload[4:])
            active = [w['app_id'] for w in windows.values() if w['active']]
            return active[0] if len(active) == 1 else None
    except (OSError, ValueError, struct.error):
        return None
