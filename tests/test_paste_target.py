"""Simulated Wayland responses; never read the real desktop or send input."""
import os
import struct
import unittest
from unittest.mock import patch

from paste_target import active_app_id, terminal_app


def uint(value):
    return struct.pack('=I',value)


def string(value):
    raw=value.encode()+b'\0'
    return uint(len(raw))+raw+b'\0'*(-len(raw)%4)


def event(obj,opcode,payload=b''):
    return struct.pack('=II',obj,((len(payload)+8)<<16)|opcode)+payload


def window(handle,app,states=(2,),title='private window title'):
    state=b''.join(uint(s) for s in states)
    return (event(4,0,uint(handle))+event(handle,2,string(title))+
            event(handle,3,string(app))+event(handle,8,uint(len(state))+state)+event(handle,1))


REGISTRY=event(2,0,uint(99)+string('zcosmic_toplevel_info_v1')+uint(3))+event(3,0,uint(0))
DONE=event(5,0,uint(0))


class FakeSocket:
    def __init__(self,data):
        self.data=data;self.sent=[];self.timeouts=[]

    def __enter__(self):return self
    def __exit__(self,*args):pass
    def connect(self,path):self.path=path
    def settimeout(self,timeout):self.timeouts.append(timeout)
    def sendall(self,data):self.sent.append(data)
    def recv(self,size):
        # Exercise fragmentation across both headers and UTF-8 strings.
        count=min(size,3)
        result,self.data=self.data[:count],self.data[count:]
        return result


class PasteTarget(unittest.TestCase):
    def snapshot(self,events,registry=REGISTRY):
        sock=FakeSocket(registry+events)
        with patch.dict(os.environ,{'XDG_RUNTIME_DIR':'/run/user/1000','WAYLAND_DISPLAY':'wayland-1'}), \
             patch('paste_target.socket.socket',return_value=sock):
            result=active_app_id()
        return result,sock

    def test_tabby_and_terminal_ids_are_exact_and_case_insensitive(self):
        for app in ('tabby','Tabby.desktop','com.system76.CosmicTerm','org.gnome.Terminal',
                    'org.kde.konsole','kitty','Alacritty','com.mitchellh.ghostty'):
            with self.subTest(app=app):self.assertTrue(terminal_app(app))
        for app in (None,'google-chrome','code','tabby-notes','my-terminal-editor'):
            with self.subTest(app=app):self.assertFalse(terminal_app(app))

    def test_active_window_only_and_fragmented_messages(self):
        result,sock=self.snapshot(window(0xff000000,'google-chrome',())+
                                  window(0xff000001,'tabby')+DONE)
        self.assertEqual(result,'tabby')
        self.assertEqual(sock.path,'/run/user/1000/wayland-1')
        # Even when v3 is advertised, explicitly request the v1 event layout.
        self.assertIn(string('zcosmic_toplevel_info_v1')+uint(1)+uint(4),sock.sent[2])
        self.assertTrue(all(0<t<=.3 for t in sock.timeouts))

    def test_window_title_cannot_select_terminal_shortcut(self):
        result,_=self.snapshot(window(0xff000000,'google-chrome',title='Tabby terminal')+DONE)
        self.assertFalse(terminal_app(result))

    def test_closed_and_deactivated_windows_are_ignored(self):
        old,new=0xff000000,0xff000001
        result,_=self.snapshot(window(old,'tabby')+window(new,'google-chrome')+
                               event(old,8,uint(0))+DONE)
        self.assertEqual(result,'google-chrome')
        result,_=self.snapshot(window(old,'tabby')+event(old,0)+window(new,'kitty')+DONE)
        self.assertEqual(result,'kitty')

    def test_missing_or_ambiguous_focus_does_not_guess(self):
        for events in (DONE,window(0xff000000,'tabby',())+DONE,
                       window(0xff000000,'tabby')+window(0xff000001,'kitty')+DONE):
            self.assertIsNone(self.snapshot(events)[0])

    def test_unsupported_protocol_disconnect_and_malformed_data(self):
        self.assertIsNone(self.snapshot(b'',registry=event(3,0,uint(0)))[0])
        for events in (b'',struct.pack('=II',4,4<<16),
                       window(0xff000000,'tabby')+event(0xff000000,8,uint(4))+DONE,
                       event(1,0)):
            self.assertIsNone(self.snapshot(events)[0])

    def test_unavailable_desktop_and_timeout_use_default(self):
        with patch.dict(os.environ,{},clear=True),patch('paste_target.socket.socket') as connect:
            self.assertIsNone(active_app_id())
            connect.assert_not_called()
        with patch.dict(os.environ,{'WAYLAND_DISPLAY':'/tmp/wayland-test'}), \
             patch('paste_target.socket.socket') as connect:
            connect.return_value.__enter__.return_value.connect.side_effect=TimeoutError
            self.assertIsNone(active_app_id())


if __name__=='__main__':unittest.main()
