#!/usr/bin/env python3
"""COSMIC/Wayland status indicator and Vietnamese controls; no audio capture here."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import gi

gi.require_version('Gtk','3.0')
gi.require_version('AyatanaAppIndicator3','0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as Indicator

ROOT=Path(__file__).resolve().parent
SOCKET=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'hey-gpt/control.sock'


def exchange(cmd):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(2)
        sock.connect(str(SOCKET))
        reader=sock.makefile('rb')
        first=json.loads(reader.readline())
        if cmd=='status': return first
        sock.sendall(json.dumps({'cmd':cmd,'request':'tray'}).encode()+b'\n')
        while True:
            line=reader.readline()
            if not line: break
            msg=json.loads(line)
            if msg.get('type')=='ack': return first
        return first


def display(status):
    if not status:return 'error','Dịch vụ chưa chạy'
    if not status.get('browser_connected'):return 'off','Chưa kết nối tiện ích Chrome'
    state=status.get('browser_state')
    if status.get('state')=='CLOSING':return 'waiting','Đang kết thúc Voice · sẽ tự chờ “Hey GPT”'
    if status.get('state')=='OPENING':return 'waiting','Đang mở Voice · local vẫn nghe'
    if state=='VOICE' and status.get('enabled'):
        remain=status.get('idle_remaining')
        if status.get('reply_ui_state')=='idle' and remain is not None:return 'voice',f'ChatGPT đã idle · còn {int(remain)+1} giây · local vẫn nghe'
        return 'voice','Chờ ChatGPT xử lý/trả lời xong · chưa đếm 15 giây'
    if state=='DICTATION':return 'voice','ChatGPT đang nhập giọng nói'
    if state=='WAITING' and status.get('enabled'):return 'waiting','Chrome đang bận · micro local vẫn nghe “Hey GPT”'
    if status.get('local_mic_open'):return 'listening','Đang chờ “Hey GPT” · micro local bật'
    if state=='NEEDS_ACTION':
        code=status.get('browser_detail') or (status.get('last_error') or {}).get('code')
        labels={'voice-ended-unexpectedly':'Voice bị ngắt; cần kiểm tra Chrome',
                'voice-end-unconfirmed':'Chrome chưa xác nhận Voice đã đóng',
                'browser-notice':'ChatGPT có thông báo cần xem',
                'composer-has-draft':'Vùng nhập ChatGPT còn chữ chưa gửi',
                'voice-transition-pending':'Giao diện Voice chưa chuyển xong',
                'voice-button-missing-or-ambiguous':'Chưa xác định được nút Voice'}
        return 'error',labels.get(code,'Cần xem Chrome')+' · đã dừng nghe local'
    if status.get('state')=='ARMING':return 'waiting','Đang chuẩn bị bộ nghe tiếng Việt'
    if status.get('enabled'):return 'waiting','Đang chuyển sang ChatGPT'
    details={'screen-locked-or-session-unavailable':'Đã tắt nghe · màn hình khóa hoặc phiên không sẵn sàng',
             'model-or-audio-error':'Lỗi model hoặc micro · đã tắt nghe',
             'microphone-unavailable':'Không truy cập được micro · đã tắt nghe'}
    return 'off',details.get(status.get('detail'),'Trợ lý đã tắt · micro local đóng')


def recognizer_text(status):
    if not status or not status.get('recognizers'):
        return 'Bộ nhận giọng: dịch vụ chưa nạp bản hai bộ nhận'
    names = {'vosk': 'Vosk', 'wav2vec2': 'Wav2Vec2 tiếng Việt'}
    labels = {'not-loaded': 'chưa nạp', 'loading': 'đang nạp', 'ready': 'sẵn sàng',
              'model-missing': 'thiếu mô hình', 'dependencies-missing': 'thiếu thư viện',
              'gpu-not-configured': 'chưa chọn RTX 4060', 'cuda-unavailable': 'CUDA không sẵn sàng',
              'wrong-cuda-gpu': 'GPU không phải RTX 4060 · đã dừng bộ này',
              'load-error': 'lỗi nạp', 'decode-error': 'lỗi nhận giọng', 'disabled': 'đã tắt'}
    lines = [('Wav2Vec2 trên RTX 4060 · Vosk đã tắt' if status.get('engine_mode') == 'wav2vec2'
              else 'Hai bộ nhận cùng nghe · một bộ khớp rõ là kích hoạt')]
    if status['recognizers'].get('wav2vec2', {}).get('templates'):
        lines.append('Đang dùng thêm mẫu giọng đã thu · so khớp âm thanh')
    if status.get('voice_activity',{}).get('state')=='ready':
        lines.append('Phát hiện giọng Silero trên RTX 4060 · ' +
                     ('đang có giọng' if status['voice_activity']['speech'] else 'đang chờ giọng'))
    for key, stats in status['recognizers'].items():
        lines.append(f"{names.get(key,key)}: {labels.get(stats['state'],stats['state'])}"
                     f" · {stats['checks']} lần kiểm tra · {stats['matches']} lần khớp"
                     f" · lần gần nhất {stats['latency_ms']} ms"
                     + (' · ' + stats['device'] if stats.get('device') else ''))
    last = status.get('last_recognizer', 'none')
    if last != 'none': lines.append('Bộ nhận lệnh gần nhất: ' + names.get(last,last))
    return '\n'.join(lines)


class App:
    def __init__(self):
        self.status=None;self.busy=False;self.window=None
        self.indicator=Indicator.Indicator.new('hey-gpt',str(ROOT/'icons/off.svg'),Indicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title('Hey GPT')
        self.indicator.set_label('GPT','GPT')
        menu=Gtk.Menu()
        self.header=Gtk.MenuItem(label='Hey GPT · đang kiểm tra');self.header.set_sensitive(False);menu.append(self.header)
        menu.append(Gtk.SeparatorMenuItem())
        self.on=self.item(menu,'Bật trợ lý · chờ “Hey GPT”',lambda *_:self.action('enable'))
        self.off=self.item(menu,'Tắt trợ lý và kết thúc Voice',lambda *_:self.action('disable'))
        self.item(menu,'Mở bảng điều khiển',lambda *_:self.show_window())
        self.item(menu,'Mở ChatGPT trên Chrome',lambda *_:self.open_chat())
        self.item(menu,'Thiết lập tiện ích Chrome…',lambda *_:self.show_window(setup=True))
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu,'Ẩn biểu tượng (không tắt trợ lý)',lambda *_:Gtk.main_quit())
        menu.show_all();self.indicator.set_menu(menu)
        GLib.timeout_add_seconds(1,self.poll);self.poll()
        def setup_if_needed():
            if not self.status or not self.status.get('browser_connected'):
                self.show_window(setup=True)
            return False
        GLib.timeout_add_seconds(3,setup_if_needed)

    def item(self,menu,label,handler):
        item=Gtk.MenuItem(label=label);item.connect('activate',handler);menu.append(item);return item

    def open_chat(self):
        subprocess.Popen(['google-chrome','https://chatgpt.com/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def action(self,cmd):
        def run():
            try:exchange(cmd)
            except (OSError,ValueError):pass
            GLib.idle_add(self.poll)
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        if self.busy:return True
        self.busy=True
        def run():
            try:result=exchange('status')
            except (OSError,ValueError):result=None
            GLib.idle_add(self.update,result)
        threading.Thread(target=run,daemon=True).start()
        return True

    def update(self,status):
        self.busy=False;self.status=status
        color,text=display(status)
        self.indicator.set_icon_full(str(ROOT/f'icons/{color}.svg'),text)
        self.indicator.set_label('GPT','GPT')
        self.header.set_label(text)
        self.on.set_sensitive(bool(status and status.get('browser_connected')))
        self.off.set_sensitive(bool(status))
        if self.window:
            self.status_label.set_text(text)
            self.engines_label.set_text(recognizer_text(status))
            self.on_button.set_sensitive(bool(status and status.get('browser_connected')))
        return False

    def show_window(self,setup=False):
        if self.window:
            self.window.present();return
        win=Gtk.Window(title='Hey GPT · Trợ lý tiếng Việt');self.window=win
        win.set_default_size(510,410);win.set_border_width(22)
        win.connect('destroy',lambda *_:setattr(self,'window',None))
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);win.add(box)
        heading=Gtk.Label();heading.set_markup('<span size="xx-large" weight="bold">Hey GPT</span>');heading.set_xalign(0);box.pack_start(heading,False,False,0)
        self.status_label=Gtk.Label(label=display(self.status)[1]);self.status_label.set_xalign(0);self.status_label.set_line_wrap(True);box.pack_start(self.status_label,False,False,0)
        self.engines_label=Gtk.Label(label=recognizer_text(self.status));self.engines_label.set_xalign(0);self.engines_label.set_line_wrap(True);box.pack_start(self.engines_label,False,False,0)
        self.on_button=Gtk.Button(label='BẬT · chờ “Hey GPT”');self.on_button.connect('clicked',lambda *_:self.action('enable'));box.pack_start(self.on_button,False,False,0)
        off=Gtk.Button(label='TẮT · đóng micro local, kết thúc Voice');off.connect('clicked',lambda *_:self.action('disable'));box.pack_start(off,False,False,0)
        self.on_button.set_sensitive(bool(self.status and self.status.get('browser_connected')))
        help_text=('ChatGPT trên Chrome là bên trả lời. Bộ nghe local hoạt động liên tục khi trợ lý bật.\n'
                   'Nghỉ khoảng 1 giây rồi nói riêng “hết”, “kết thúc”, “dừng lại” hoặc “done”; '
                   'hoặc im lặng 15 giây: tự đóng Voice và chờ “Hey GPT” tiếp. Không cần tìm Chrome bấm kết thúc.\n\n'
                   'Lần đầu: mở chrome://extensions → Developer mode → Load unpacked, chọn thư mục bên dưới. '
                   'Sau đó mở một tab ChatGPT và bấm BẬT. Nhiều tab: chọn tab bằng popup tiện ích.')
        note=Gtk.Label(label=help_text);note.set_xalign(0);note.set_line_wrap(True);box.pack_start(note,False,False,0)
        folder=Gtk.Entry();folder.set_text(str(ROOT/'extension'));folder.set_editable(False);box.pack_start(folder,False,False,0)
        warning=Gtk.Label(label='TẮT chỉ yêu cầu kết thúc Voice ở tab đã gắn. Nếu mất kết nối, hãy kiểm tra micro trong Chrome.');warning.set_line_wrap(True);warning.set_xalign(0);box.pack_start(warning,False,False,0)
        win.show_all();win.present()


if __name__=='__main__':
    App();Gtk.main()
