"""Vietnamese presentation shared by the status indicator and settings."""


def display(status):
    if not status:return 'error','Không kết nối được dịch vụ'
    detail=status.get('detail')
    if detail=='unloading-models':return 'waiting','Đang giải phóng bộ nhớ GPU…'
    if detail=='models-unloaded':return 'off','Đã giải phóng GPU · trợ lý tạm dừng'
    typing=status.get('dictation',{}).get('phase')
    labels={'typing-loading':'Đang chuẩn bị nhập giọng nói…',
            'typing-recording':'Đang nghe để nhập văn bản',
            'typing-transcribing':'Đang hoàn thiện văn bản…',
            'typing-inserting':'Đang gõ văn bản…'}
    if typing in labels:
        icons={'typing-recording':'dictating','typing-inserting':'typing'}
        return icons.get(typing,'waiting'),labels[typing]
    if status.get('dictation',{}).get('error'):
        return 'error','Lỗi nhập giọng nói · xem cài đặt'
    state=status.get('browser_state')
    if status.get('state')=='CLOSING':return 'waiting','Đang kết thúc Voice…'
    if status.get('state')=='OPENING':return 'waiting','Đang mở Voice…'
    if state=='VOICE' and status.get('enabled'):
        remain=status.get('idle_remaining')
        if status.get('reply_ui_state')=='idle' and remain is not None:
            return 'voice',f'Voice đang nghỉ · kết thúc sau {int(remain)+1} giây'
        return 'voice','Đang trò chuyện với ChatGPT'
    if state=='DICTATION':return 'voice','ChatGPT đang nhập giọng nói'
    if state=='WAITING' and status.get('enabled'):return 'waiting','Đang chờ Chrome'
    if status.get('local_mic_open'):
        icon='hearing' if status.get('voice_activity',{}).get('speech') else 'listening'
        return icon,'Đang nghe · gọi “Hey GPT” hoặc “typing this”'
    if state=='NEEDS_ACTION':return 'error','Cần kiểm tra ChatGPT trên Chrome'
    if status.get('state')=='ARMING':return 'waiting','Đang chuẩn bị bộ nghe…'
    if status.get('enabled'):return 'waiting','Đang chờ kết nối…'
    details={'screen-locked-or-session-unavailable':'Đã tạm dừng · phiên làm việc bị khóa',
             'model-or-audio-error':'Lỗi mô hình hoặc micro · đã tạm dừng',
             'microphone-unavailable':'Không truy cập được micro · đã tạm dừng',
             'models-not-ready':'Không nạp đủ mô hình · đã tắt và gỡ mô hình; xem log dịch vụ'}
    return 'off',details.get(detail,'Trợ lý đã tắt · micro đã đóng')


def model_state(value):
    return {'not-loaded':'chưa nạp','unloaded':'chưa nạp','loading':'đang nạp',
            'ready':'sẵn sàng','transcribing':'đang xử lý','unavailable':'không khả dụng',
            'model-missing':'thiếu mô hình','dependencies-missing':'thiếu thư viện',
            'gpu-not-configured':'chưa chọn GPU','cuda-unavailable':'GPU không khả dụng',
            'wrong-cuda-gpu':'sai GPU','load-error':'lỗi nạp','decode-error':'lỗi nhận giọng',
            'error':'có lỗi'}.get(value,'chưa sẵn sàng')


def recognizer_text(status):
    if not status:return 'Không kết nối được dịch vụ'
    wake=status.get('recognizers',{}).get('wav2vec2',{})
    typing=status.get('dictation',{})
    lines=[f"Tiếng Việt · Wav2Vec2 (GPU): {model_state(wake.get('state'))}",
           f"Lệnh nhập văn bản · Vosk tiếng Anh (CPU): {model_state(typing.get('commands'))}",
           f"Văn bản tiếng Anh · Parakeet (GPU): {model_state(typing.get('state'))}",
           f"Phát hiện giọng · Silero (GPU): {model_state(status.get('voice_activity',{}).get('state'))}"]
    if typing.get('error'):lines.append('Nhập giọng nói: '+typing['error'])
    return '\n'.join(lines)


def panel_label(status):
    """Readable even when a desktop theme replaces an icon's colors."""
    if not status:return 'GPT · Mất kết nối'
    if status.get('detail')=='unloading-models':return 'GPT · Đang gỡ'
    if status.get('detail')=='models-unloaded':return 'GPT · Đã gỡ'
    phase=status.get('dictation',{}).get('phase')
    labels={'typing-recording':'Đang nhập','typing-loading':'Đang nạp',
            'typing-transcribing':'Đang xử lý','typing-inserting':'Đang gõ'}
    if phase in labels:return 'GPT · '+labels[phase]
    if status.get('dictation',{}).get('error'):return 'GPT · Lỗi'
    state=status.get('state')
    if state=='CLOSING':return 'GPT · Đang kết thúc'
    if state=='OPENING':return 'GPT · Đang mở'
    if status.get('browser_state')=='NEEDS_ACTION':return 'GPT · Cần kiểm tra'
    if status.get('enabled') and status.get('browser_state') in {'VOICE','DICTATION'}:return 'GPT · Trò chuyện'
    if state=='ARMING':return 'GPT · Đang nạp'
    if status.get('local_mic_open'):
        return 'GPT · Có giọng nói' if status.get('voice_activity',{}).get('speech') else 'GPT · Đang nghe'
    if display(status)[0]=='error':return 'GPT · Lỗi'
    if status.get('enabled'):return 'GPT · Đang chờ'
    return 'GPT · Đã tắt'
