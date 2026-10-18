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
        sock.settimeout(10 if cmd=='model-unload' else 2)
        sock.connect(str(SOCKET))
        reader=sock.makefile('rb')
        first=json.loads(reader.readline())
        if cmd=='status': return first
        sock.sendall(json.dumps({'cmd':cmd,'request':'tray',**(payload or {})}).encode()+b'\n')
        while True:
            line=reader.readline()
            if not line: break
            msg=json.loads(line)
            if msg.get('type')=='error':raise RuntimeError('control-request-failed')
            if msg.get('type')=='status':first=msg
            if cmd=='dictation-preview' and msg.get('type')=='dictation-preview':
                return {**first,'preview_text':msg.get('text','')}
            if msg.get('type')=='ack': return first
        return first


class App:
    def __init__(self):
        self.status=None;self.busy=False;self.window=None;self.board=None;self.board_display=None
        self.action_error=None
        self.connection_failed=False;self.board_placement=None
        self.indicator=Indicator.Indicator.new('hey-gpt',str(ROOT/'icons/off.png'),Indicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title('Hey GPT')
        self.indicator.set_label('GPT · Đang mở','GPT · Đang nghe')
        menu=self.menu=Gtk.Menu()
        self.header=Gtk.MenuItem(label='Hey GPT · đang kiểm tra');self.header.set_sensitive(False);menu.append(self.header)
        menu.append(Gtk.SeparatorMenuItem())
        self.updating_menu=False
        self.enabled_item=Gtk.CheckMenuItem(label='Bật trợ lý')
        self.enabled_item.connect('toggled',self.toggle_assistant);menu.append(self.enabled_item)
        self.item(menu,'Mở ChatGPT',lambda *_:self.open_chat())
        self.item(menu,'Cài đặt…',lambda *_:self.show_window())
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu,'Ẩn biểu tượng (không tắt trợ lý)',lambda *_:Gtk.main_quit())
        menu.show_all();self.indicator.set_menu(menu)
        GLib.timeout_add_seconds(1,self.poll);self.poll()

    def item(self,menu,label,handler):
        item=Gtk.MenuItem(label=label);item.connect('activate',handler);menu.append(item);return item

    def open_chat(self):
        subprocess.Popen(['google-chrome','https://chatgpt.com/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def toggle_assistant(self,item):
        if not self.updating_menu:
            self.action('enable' if item.get_active() else 'disable')

    def action(self,cmd,payload=None):
        def run():
            error=None
            try:exchange(cmd,payload)
            except (OSError,ValueError,RuntimeError) as exc:
                trace_error('tray','control-error',exc,command=cmd)
                error='Không thực hiện được thao tác. Hãy kiểm tra kết nối dịch vụ.'
            GLib.idle_add(self.action_finished,error)
        threading.Thread(target=run,daemon=True).start()

    def action_finished(self,error):
        self.action_error=error
        if self.window:
            self.feedback.set_text(error or '')
            self.feedback.set_visible(bool(error))
        self.poll()
        return False

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
        self.indicator.set_label(panel_label(status),'GPT · Đang nghe')
        self.header.set_label(text)
        self.updating_menu=True
        self.enabled_item.set_active(bool(status and status.get('enabled')))
        self.enabled_item.set_sensitive(bool(status))
        self.updating_menu=False
        self.update_board(status)
        if self.window:
            self.status_label.set_text(text)
            self.engines_label.set_text(recognizer_text(status))
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
        board.set_title('Hey GPT · Văn bản đang nhập')
        board.set_default_size(440,220);board.set_border_width(16)
        board.set_resizable(False);board.set_keep_above(True)
        board.set_accept_focus(False);board.set_focus_on_map(False)
        board.set_skip_taskbar_hint(True);board.set_skip_pager_hint(True)
        board.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);board.add(box)
        self.board_heading=Gtk.Label(label='Hey GPT · Nhập giọng nói');self.board_heading.set_xalign(0)
        box.pack_start(self.board_heading,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(120);scroll.set_max_content_height(320)
        box.pack_start(scroll,True,True,0)
        self.board_text=Gtk.Label(label='Nói “typing this” và chờ âm báo.')
        self.board_text.set_xalign(0);self.board_text.set_yalign(0)
        self.board_text.set_line_wrap(True);self.board_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.board_text.set_max_width_chars(54)
        scroll.add(self.board_text)
        note=Gtk.Label(label='Bản nháp cập nhật mỗi 5 giây và có thể thay đổi.\nNói riêng “stop typing” để kết thúc.\nVăn bản được gõ một lần; bạn tự nhấn Enter.')
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
        visible=(status or {}).get('dictation',{}).get('settings',{}).get('show_transcript',True)
        # Loading alone is not a recording. Show the board only after the
        # intentional trigger has completed preparation and the cue has played.
        if phase=='typing-recording' and visible and not self.board:self.show_board()
        if not active or not visible:
            self.hide_board();return
        if not self.board:return
        info=status.get('dictation',{})
        seconds=info.get('recorded_seconds',0)
        title={'typing-loading':'Đang chuẩn bị…','typing-recording':f'Đang nghe · {seconds:.0f} giây',
               'typing-transcribing':'Đang hoàn thiện văn bản…','typing-inserting':'Đang gõ văn bản…'}
        if info.get('preview_busy') and phase=='typing-recording':title[phase]+= ' · Đang cập nhật…'
        self.board_heading.set_text('Hey GPT · '+title.get(phase,phase))
        self.board_text.set_text(status.get('preview_text') or 'Văn bản sẽ xuất hiện sau khoảng 5 giây nói…')

    def update_dictation(self,status):
        info=(status or {}).get('dictation',{})
        model=info.get('state','unavailable')
        labels={'ready':'Sẵn sàng nhập tiếng Anh', 'unloaded':'Chưa nạp bộ nhập tiếng Anh',
                'loading':'Đang nạp bộ nhập tiếng Anh…', 'transcribing':'Đang chuyển giọng nói thành văn bản…'}
        self.dictation_label.set_text('Không kết nối được dịch vụ' if not status else
            'Lỗi nhập giọng nói · xem phần Chi tiết' if info.get('error') else labels.get(model,'Bộ nhập tiếng Anh chưa sẵn sàng'))
        self.load_button.set_visible(bool(status) and model not in {'loading','ready','transcribing'})
        self.unload_button.set_sensitive(bool(status))
        self.gpu_note.set_text('Bộ nhớ GPU đã được giải phóng.' if (status or {}).get('detail')=='models-unloaded'
                              else 'Tạm dừng trợ lý, kết thúc Voice và gỡ toàn bộ mô hình khỏi GPU.')
        settings=info.get('settings',{'autoload':True,'silence_seconds':5})
        self.updating_settings=True
        self.autoload.set_active(settings['autoload'])
        self.silence.set_value(settings['silence_seconds'])
        self.transcript.set_active(settings.get('show_transcript',True))
        for widget in (self.autoload,self.silence,self.transcript):widget.set_sensitive(bool(status))
        self.updating_settings=False

    def dictation_settings_changed(self,*args):
        if self.updating_settings:return
        self.action('dictation-settings',{'settings':{'autoload':self.autoload.get_active(),
                                                     'silence_seconds':self.silence.get_value_as_int(),
                                                     'show_transcript':self.transcript.get_active()}})

    @staticmethod
    def note(box,text):
        label=Gtk.Label(label=text);label.set_xalign(0);label.set_line_wrap(True)
        label.set_max_width_chars(58);box.pack_start(label,False,False,0)
        return label

    @staticmethod
    def section(box,title):
        frame=Gtk.Frame(label=title)
        content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        content.set_border_width(14);frame.add(content);box.pack_start(frame,False,False,0)
        return content

    def show_window(self):
        if self.window:
            self.window.present();return
        win=Gtk.Window(title='Hey GPT · Cài đặt');self.window=win
        win.set_default_size(520,620);win.set_border_width(18)
        win.connect('destroy',lambda *_:setattr(self,'window',None))
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);win.add(scroll)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16);scroll.add(box)
        self.status_label=self.note(box,display(self.status)[1])
        self.feedback=self.note(box,self.action_error or '')

        typing=self.section(box,'Nhập giọng nói tiếng Anh')
        self.dictation_label=self.note(typing,'')
        self.load_button=Gtk.Button(label='Nạp bộ nhập tiếng Anh')
        self.load_button.connect('clicked',lambda *_:self.action('model-load'))
        typing.pack_start(self.load_button,False,False,0)
        self.updating_settings=True
        self.autoload=Gtk.CheckButton(label='Nạp sẵn bộ nhập tiếng Anh khi khởi động')
        self.autoload.connect('toggled',self.dictation_settings_changed);typing.pack_start(self.autoload,False,False,0)
        self.transcript=Gtk.CheckButton(label='Hiện bảng văn bản khi nhập giọng nói')
        self.transcript.connect('toggled',self.dictation_settings_changed);typing.pack_start(self.transcript,False,False,0)
        row=Gtk.Box(spacing=10);typing.pack_start(row,False,False,0)
        row.pack_start(Gtk.Label(label='Kết thúc sau khoảng im lặng:'),False,False,0)
        self.silence=Gtk.SpinButton.new_with_range(2,30,1)
        self.silence.connect('value-changed',self.dictation_settings_changed);row.pack_start(self.silence,False,False,0)
        row.pack_start(Gtk.Label(label='giây'),False,False,0)

        gpu=self.section(box,'Bộ nhớ GPU')
        self.unload_button=Gtk.Button(label='Giải phóng bộ nhớ GPU')
        self.unload_button.connect('clicked',lambda *_:self.action('model-unload'));gpu.pack_start(self.unload_button,False,False,0)
        self.gpu_note=self.note(gpu,'')
        self.note(gpu,'Bật lại trợ lý từ menu để tiếp tục nghe.')

        help=Gtk.Expander(label='Cách sử dụng và kết nối Chrome')
        help_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);help_box.set_border_width(10);help.add(help_box)
        self.note(help_box,'Gọi “Hey GPT” để mở Voice. Nói riêng “hết”, “kết thúc”, “dừng lại” hoặc “done” sau một nhịp nghỉ để kết thúc.')
        self.note(help_box,'Nhập văn bản: nói “typing this”, chờ âm báo rồi nói tiếng Anh. Nói riêng “stop typing” để kết thúc. Giữ ô cần nhập được chọn, dùng bàn phím US; bạn tự nhấn Enter.')
        self.note(help_box,'Lần đầu: mở chrome://extensions → Developer mode → Load unpacked, chọn thư mục bên dưới. Đăng nhập ChatGPT và cấp quyền micro.')
        folder=Gtk.Entry();folder.set_text(str(ROOT/'extension'));folder.set_editable(False);help_box.pack_start(folder,False,False,0)
        box.pack_start(help,False,False,0)

        details=Gtk.Expander(label='Chi tiết bộ nhận giọng')
        detail_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);detail_box.set_border_width(10);details.add(detail_box)
        self.engines_label=self.note(detail_box,recognizer_text(self.status))
        box.pack_start(details,False,False,0)
        win.show_all();self.feedback.set_visible(bool(self.action_error))
        self.update_dictation(self.status);win.present()


if __name__=='__main__':
    sys.excepthook=lambda kind,error,tb:trace_error('tray','unhandled-error',error)
    trace('tray','started')
    App();Gtk.main()
