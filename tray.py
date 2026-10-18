#!/usr/bin/env python3
"""COSMIC/Wayland status indicator and Vietnamese controls; no audio capture here."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import sys
import gi

gi.require_version('Gtk','3.0')
gi.require_version('AyatanaAppIndicator3','0.1')
from gi.repository import Gtk, GLib, Gdk, Pango, AyatanaAppIndicator3 as Indicator

from tray_status import display, recognizer_text, panel_label
from tray_position import panel_output, choose_monitor, board_position
from diagnostics import trace, trace_error

ROOT=Path(__file__).resolve().parent
SOCKET=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'hey-gpt/control.sock'


def exchange(cmd, payload=None):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(2)
        sock.connect(str(SOCKET))
        reader=sock.makefile('rb')
        first=json.loads(reader.readline())
        if cmd=='status': return first
        sock.sendall(json.dumps({'cmd':cmd,'request':'tray',**(payload or {})}).encode()+b'\n')
        while True:
            line=reader.readline()
            if not line: break
            msg=json.loads(line)
            if cmd=='dictation-preview' and msg.get('type')=='dictation-preview':
                return {**first,'preview_text':msg.get('text','')}
            if msg.get('type')=='ack': return first
        return first


class App:
    def __init__(self):
        self.status=None;self.busy=False;self.window=None;self.board=None;self.board_display=None
        self.connection_failed=False;self.board_placement=None
        self.indicator=Indicator.Indicator.new('hey-gpt',str(ROOT/'icons/off.png'),Indicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title('Hey GPT')
        self.indicator.set_label('GPT · Starting','GPT · Listening')
        menu=Gtk.Menu()
        self.header=Gtk.MenuItem(label='Hey GPT · đang kiểm tra');self.header.set_sensitive(False);menu.append(self.header)
        self.menu_preview=Gtk.MenuItem();self.menu_preview.set_sensitive(False)
        self.menu_preview_label=Gtk.Label();self.menu_preview_label.set_xalign(0)
        self.menu_preview_label.set_line_wrap(True);self.menu_preview_label.set_max_width_chars(54)
        self.menu_preview.add(self.menu_preview_label);menu.append(self.menu_preview)
        menu.append(Gtk.SeparatorMenuItem())
        self.on=self.item(menu,'Bật trợ lý · chờ “Hey GPT”',lambda *_:self.action('enable'))
        self.off=self.item(menu,'Tắt trợ lý và kết thúc Voice',lambda *_:self.action('disable'))
        self.item(menu,'Load English dictation model',lambda *_:self.action('model-load'))
        self.item(menu,'Unload model · free GPU memory',lambda *_:self.action('model-unload'))
        self.board_item=self.item(menu,'Show transcript board',lambda *_:self.show_board())
        self.board_item.set_sensitive(False)
        self.item(menu,'Mở bảng điều khiển',lambda *_:self.show_window())
        self.item(menu,'Mở ChatGPT trên Chrome',lambda *_:self.open_chat())
        self.item(menu,'Thiết lập tiện ích Chrome…',lambda *_:self.show_window(setup=True))
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu,'Ẩn biểu tượng (không tắt trợ lý)',lambda *_:Gtk.main_quit())
        menu.show_all();self.menu_preview.hide();self.indicator.set_menu(menu)
        GLib.timeout_add_seconds(1,self.poll);self.poll()

    def item(self,menu,label,handler):
        item=Gtk.MenuItem(label=label);item.connect('activate',handler);menu.append(item);return item

    def open_chat(self):
        subprocess.Popen(['google-chrome','https://chatgpt.com/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def action(self,cmd,payload=None):
        def run():
            try:exchange(cmd,payload)
            except (OSError,ValueError) as exc:trace_error('tray','control-error',exc,command=cmd)
            GLib.idle_add(self.poll)
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        if self.busy:return True
        self.busy=True
        def run():
            try:result=exchange('dictation-preview')
            except (OSError,ValueError) as exc:
                if not self.connection_failed:trace_error('tray','connection-error',exc)
                self.connection_failed=True;result=None
            else:
                if self.connection_failed:trace('tray','connection-restored')
                self.connection_failed=False
            GLib.idle_add(self.update,result)
        threading.Thread(target=run,daemon=True).start()
        return True

    def update(self,status):
        self.busy=False;self.status=status
        color,text=display(status)
        self.indicator.set_icon_full(str(ROOT/f'icons/{color}.png'),text)
        self.indicator.set_label(panel_label(status),'GPT · Listening')
        self.header.set_label(text)
        self.on.set_sensitive(bool(status))
        self.off.set_sensitive(bool(status))
        self.update_board(status)
        if self.window:
            self.status_label.set_text(text)
            self.engines_label.set_text(recognizer_text(status))
            self.on_button.set_sensitive(bool(status))
            self.update_dictation(status)
        return False

    def show_board(self):
        if self.board:return
        # A popup on Xwayland can be placed below the panel without activating
        # a new toplevel. Native Wayland toplevel placement/focus is compositor-
        # controlled, so use the existing X display when it is available.
        if self.board_display is None and os.environ.get('DISPLAY'):
            self.board_display=Gdk.Display.open(os.environ['DISPLAY'])
        display=self.board_display or Gdk.Display.get_default()
        popup=bool(display and display.get_name().startswith(':'))
        board=Gtk.Window(type=Gtk.WindowType.POPUP if popup else Gtk.WindowType.TOPLEVEL)
        if self.board_display:board.set_screen(self.board_display.get_default_screen())
        self.board=board
        board.set_title('Hey GPT · Transcript')
        board.set_default_size(440,220);board.set_border_width(16)
        board.set_resizable(False);board.set_keep_above(True)
        board.set_accept_focus(False);board.set_focus_on_map(False)
        board.set_skip_taskbar_hint(True);board.set_skip_pager_hint(True)
        board.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);board.add(box)
        self.board_heading=Gtk.Label(label='Hey GPT · Dictation');self.board_heading.set_xalign(0)
        box.pack_start(self.board_heading,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(120);scroll.set_max_content_height(320)
        box.pack_start(scroll,True,True,0)
        self.board_text=Gtk.Label(label='Say “typing this” and wait for the ready sound.')
        self.board_text.set_xalign(0);self.board_text.set_yalign(0)
        self.board_text.set_line_wrap(True);self.board_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.board_text.set_max_width_chars(54)
        scroll.add(self.board_text)
        note=Gtk.Label(label='Draft updates every ~5 s · earlier words may change.\nFinish: pause, say “end typing” or “stop typing”.\nThe finished text is typed once. Press Enter yourself.')
        note.set_xalign(0);box.pack_start(note,False,False,0)
        board.connect('delete-event',self.hide_board)
        monitors=[]
        if display:
            for index in range(display.get_n_monitors()):
                monitor=display.get_monitor(index);area=monitor.get_workarea()
                monitors.append({'name':monitor.get_model(),'primary':monitor.is_primary(),
                                 'area':(area.x,area.y,area.width,area.height)})
        output=panel_output()
        monitor,reason=choose_monitor(monitors,output)
        if monitor:
            self.board_placement=(monitor['area'],monitor['name'])
            board.connect('size-allocate',self.position_board)
            board.move(*board_position(monitor['area'],440,220))
        trace('tray','board-open',panel_output=output,selected_output=monitor['name'] if monitor else None,
              reason=reason,monitors=monitors,popup=popup)
        board.show_all()

    def position_board(self,board,allocation):
        if self.board_placement:
            area,_=self.board_placement
            board.move(*board_position(area,allocation.width,allocation.height))

    def hide_board(self,*_):
        if self.board:
            trace('tray','board-closed')
            self.board.destroy();self.board=None
        return True

    def update_board(self,status):
        phase=(status or {}).get('dictation',{}).get('phase','idle')
        active=phase.startswith('typing')
        self.board_item.set_sensitive(active)
        self.menu_preview.set_visible(active)
        preview=(status or {}).get('preview_text','')
        self.menu_preview_label.set_text((preview[-400:] if len(preview)>400 else preview) or 'Preparing the transcript…')
        # Loading alone is not a recording. Show the board only after the
        # intentional trigger has completed preparation and the cue has played.
        if phase=='typing-recording' and not self.board:self.show_board()
        if not active:
            self.hide_board();return
        if not self.board:return
        info=status.get('dictation',{})
        seconds=info.get('recorded_seconds',0)
        title={'typing-loading':'Preparing model…','typing-recording':f'Dictating · {seconds:.0f} s',
               'typing-transcribing':'Finalizing transcript…','typing-inserting':'Typing finished text…'}
        if info.get('preview_busy') and phase=='typing-recording':title[phase]+= ' · Updating…'
        self.board_heading.set_text('Hey GPT · '+title.get(phase,phase))
        self.board_text.set_text(status.get('preview_text') or 'Waiting for the first five seconds of speech…')

    def update_dictation(self,status):
        info=(status or {}).get('dictation',{})
        model=info.get('state','unavailable')
        self.dictation_label.set_text('English dictation · Parakeet v2 · RTX 4060\nModel: '+model+
            (' · '+info['error'] if info.get('error') else ''))
        self.load_button.set_sensitive(bool(status) and model not in {'loading','ready','transcribing'})
        self.unload_button.set_sensitive(bool(status) and model!='unloaded')
        settings=info.get('settings',{'autoload':True,'silence_seconds':5})
        self.updating_settings=True
        self.autoload.set_active(settings['autoload'])
        self.silence.set_value(settings['silence_seconds'])
        self.updating_settings=False

    def dictation_settings_changed(self,*args):
        if self.updating_settings:return
        self.action('dictation-settings',{'settings':{'autoload':self.autoload.get_active(),
                                                     'silence_seconds':self.silence.get_value_as_int()}})

    def show_window(self,setup=False):
        if self.window:
            self.window.present();return
        win=Gtk.Window(title='Hey GPT · Trợ lý tiếng Việt');self.window=win
        win.set_default_size(560,720);win.set_border_width(22)
        win.connect('destroy',lambda *_:setattr(self,'window',None))
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);win.add(scroll)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);scroll.add(box)
        heading=Gtk.Label();heading.set_markup('<span size="xx-large" weight="bold">Hey GPT</span>');heading.set_xalign(0);box.pack_start(heading,False,False,0)
        self.status_label=Gtk.Label(label=display(self.status)[1]);self.status_label.set_xalign(0);self.status_label.set_line_wrap(True);box.pack_start(self.status_label,False,False,0)
        self.engines_label=Gtk.Label(label=recognizer_text(self.status));self.engines_label.set_xalign(0);self.engines_label.set_line_wrap(True);box.pack_start(self.engines_label,False,False,0)
        self.on_button=Gtk.Button(label='BẬT · chờ “Hey GPT”');self.on_button.connect('clicked',lambda *_:self.action('enable'));box.pack_start(self.on_button,False,False,0)
        off=Gtk.Button(label='TẮT · đóng micro local, kết thúc Voice');off.connect('clicked',lambda *_:self.action('disable'));box.pack_start(off,False,False,0)
        self.on_button.set_sensitive(bool(self.status))
        self.dictation_label=Gtk.Label();self.dictation_label.set_xalign(0);self.dictation_label.set_line_wrap(True)
        box.pack_start(self.dictation_label,False,False,0)
        controls=Gtk.Box(spacing=8);box.pack_start(controls,False,False,0)
        self.load_button=Gtk.Button(label='Load model');self.load_button.connect('clicked',lambda *_:self.action('model-load'));controls.pack_start(self.load_button,True,True,0)
        self.unload_button=Gtk.Button(label='Unload · free GPU memory');self.unload_button.connect('clicked',lambda *_:self.action('model-unload'));controls.pack_start(self.unload_button,True,True,0)
        self.updating_settings=True
        self.autoload=Gtk.CheckButton(label='Load dictation model when the agent starts')
        self.autoload.connect('toggled',self.dictation_settings_changed);box.pack_start(self.autoload,False,False,0)
        row=Gtk.Box(spacing=8);box.pack_start(row,False,False,0)
        row.pack_start(Gtk.Label(label='Finish after silence (seconds):'),False,False,0)
        self.silence=Gtk.SpinButton.new_with_range(2,30,1);self.silence.connect('value-changed',self.dictation_settings_changed);row.pack_start(self.silence,False,False,0)
        self.update_dictation(self.status)
        note=Gtk.Label(label='Say “typing this”, wait for the sound, then dictate in English.\nA transcript board updates about every five seconds. Say “stop typing” by itself after a short pause, or stay silent for the time above. The finished text is typed once. Keep the original field focused; press Enter yourself. Use a US English keyboard layout.')
        note.set_xalign(0);note.set_line_wrap(True);box.pack_start(note,False,False,0)
        help_text=('ChatGPT trên Chrome là bên trả lời. Bộ nghe local hoạt động liên tục khi trợ lý bật.\n'
                   'Nghỉ khoảng 1 giây rồi nói riêng “hết”, “kết thúc”, “dừng lại” hoặc “done”; '
                   'hoặc im lặng 15 giây: tự đóng Voice và chờ “Hey GPT” tiếp. Không cần tìm Chrome bấm kết thúc.\n\n'
                   'Lần đầu: mở chrome://extensions → Developer mode → Load unpacked, chọn thư mục bên dưới. '
                   'Đăng nhập và cấp quyền micro một lần. Sau đó chỉ cần nói “Hey GPT”, '
                   'đợi âm báo hai nốt rồi đặt câu hỏi; Chrome sẽ tự mở khi cần.')
        note=Gtk.Label(label=help_text);note.set_xalign(0);note.set_line_wrap(True);box.pack_start(note,False,False,0)
        folder=Gtk.Entry();folder.set_text(str(ROOT/'extension'));folder.set_editable(False);box.pack_start(folder,False,False,0)
        warning=Gtk.Label(label='TẮT chỉ yêu cầu kết thúc Voice ở tab đã gắn. Nếu mất kết nối, hãy kiểm tra micro trong Chrome.');warning.set_line_wrap(True);warning.set_xalign(0);box.pack_start(warning,False,False,0)
        win.show_all();win.present()


if __name__=='__main__':
    sys.excepthook=lambda kind,error,tb:trace_error('tray','unhandled-error',error)
    trace('tray','started')
    App();Gtk.main()
