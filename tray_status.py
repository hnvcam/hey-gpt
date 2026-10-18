"""Desktop-independent status presentation for the panel and control window."""

def display(status):
    if not status:return 'error','Dịch vụ chưa chạy'
    typing=status.get('dictation',{}).get('phase')
    labels={'typing-loading':'Preparing English dictation · wait for the ready sound',
            'typing-recording':'Listening · transcript board updates every ~5 s · “stop typing” to finish',
            'typing-transcribing':'Transcribing on RTX 4060…',
            'typing-inserting':'Typing into the focused field…'}
    if typing in labels:
        icons={'typing-recording':'dictating','typing-inserting':'typing'}
        return icons.get(typing,'waiting'),labels[typing]
    if status.get('dictation',{}).get('error'):
        return 'error','Dictation stopped · check the model or keyboard in the control panel'
    state=status.get('browser_state')
    if status.get('state')=='CLOSING':return 'waiting','Đang kết thúc Voice · sẽ tự chờ “Hey GPT”'
    if status.get('state')=='OPENING':return 'waiting','Đang mở Voice · local vẫn nghe'
    if state=='VOICE' and status.get('enabled'):
        remain=status.get('idle_remaining')
        if status.get('reply_ui_state')=='idle' and remain is not None:return 'voice',f'ChatGPT đã idle · còn {int(remain)+1} giây · local vẫn nghe'
        return 'voice','Chờ ChatGPT và âm thanh Voice hoàn tất · chưa đếm 15 giây'
    if state=='DICTATION':return 'voice','ChatGPT đang nhập giọng nói'
    if state=='WAITING' and status.get('enabled'):return 'waiting','Chrome đang bận · micro local vẫn nghe “Hey GPT”'
    if status.get('local_mic_open'):
        icon='hearing' if status.get('voice_activity',{}).get('speech') else 'listening'
        return icon,'Chờ “Hey GPT” hoặc “typing this” · micro local bật' + ('' if status.get('browser_connected') else ' · Chrome sẽ mở khi gọi')
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


def panel_label(status):
    """Readable even when a desktop theme replaces an icon's colors."""
    if not status:return 'GPT · Offline'
    phase=status.get('dictation',{}).get('phase')
    if phase=='typing-recording':return 'GPT · Dictating'
    if phase=='typing-loading':return 'GPT · Loading'
    if phase=='typing-transcribing':return 'GPT · Finishing'
    if phase=='typing-inserting':return 'GPT · Typing'
    if status.get('dictation',{}).get('error'):return 'GPT · Error'
    state=status.get('state')
    if state=='CLOSING':return 'GPT · Closing'
    if state=='OPENING':return 'GPT · Opening'
    if status.get('browser_state')=='NEEDS_ACTION':return 'GPT · Attention'
    if status.get('enabled') and status.get('browser_state') in {'VOICE','DICTATION'}:return 'GPT · Voice'
    if state=='ARMING':return 'GPT · Starting'
    if status.get('local_mic_open'):
        return 'GPT · Hearing' if status.get('voice_activity',{}).get('speech') else 'GPT · Listening'
    if display(status)[0]=='error':return 'GPT · Error'
    if status.get('enabled'):return 'GPT · Waiting'
    return 'GPT · Off'
