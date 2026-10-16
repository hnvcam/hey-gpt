const $=id=>document.getElementById(id);
$('version').textContent=chrome.runtime.getManifest().version+' · Nghe local liên tục · Không OpenAI API';
const states={DISARMED:'Đã tắt',LISTENING:'Đang chờ “Hey GPT”',ARMING:'Đang chuẩn bị',OPENING:'Đang mở Voice',CONVERSATION:'Đang nghe lệnh dừng',CLOSING:'Đang đóng Voice',ERROR:'Có lỗi',DISCONNECTED:'Chưa kết nối dịch vụ'};
const details={
 'reloading-chatgpt':'Chrome kẹt quá 15 giây · đang tải lại tab một lần; micro local vẫn nghe',
 'recovery-timeout':'Chrome chưa sẵn sàng sau lượt phục hồi · micro local vẫn nghe',
 'response-generating':'ChatGPT đang trả lời; micro local vẫn nghe',
 'voice-start-unavailable':'Chrome chưa mở lại nút Voice; micro local vẫn nghe',
 'chrome-busy-local-still-listening':'Chrome đang bận; gọi lại khi sẵn sàng',
 'native-connect-timeout':'Dịch vụ local không trả lời sau 5 giây. Đóng rồi mở lại tiện ích để thử kết nối lại.',
 'service-unavailable':'Dịch vụ local chưa chạy.', 'disconnected':'Mất kết nối dịch vụ local.',
 'not-connected':'chưa nối dịch vụ', 'service-ready-microphone-closed':'micro local đang đóng',
 'offline-hey-gpt-only':'nhận từ khóa bằng model tiếng Việt trên máy',
 'chrome-connected':'đã kết nối Chrome',
 'user-disarmed':'bạn đã tắt trợ lý', 'waiting-for-service':'chờ dịch vụ',
 'loading-offline-model':'nạp model tiếng Việt', 'screen-locked-or-session-unavailable':'màn hình khóa hoặc phiên không sẵn sàng',
 'microphone-unavailable':'không mở được micro', 'model-or-audio-error':'lỗi model hoặc âm thanh',
 'composer-has-draft':'vùng nhập đang có nội dung chưa gửi', 'composer-not-found':'không thấy vùng nhập',
 'voice-button-missing-or-ambiguous':'không xác định được nút Voice', 'browser-notice':'hãy xem thông báo của ChatGPT',
 'voice-ended-unexpectedly':'Voice đã ngắt; trợ lý dừng để bạn kiểm tra',
 'voice-end-unconfirmed':'chưa xác nhận Voice đã đóng',
 'voice-end-failed':'lỗi khi kết thúc Voice',
 'voice-transition-pending':'giao diện Voice chưa chuyển xong',
 'rearm-failed':'chưa trở về chế độ nghe từ khóa',
 'setup-required':'cần chọn tab ChatGPT và kiểm tra thiết lập',
 'review-browser-permission-limit-or-start-button':'hãy kiểm tra quyền micro, giới hạn hoặc nút Voice',
 'browser-operation-failed':'không điều khiển được tab ChatGPT', 'native-host-unavailable':'chưa nối được cầu nối local',
 'stop-dictation-in-chatgpt':'hãy dừng ghi âm trong ChatGPT',
 'returning-to-wake-listening':'sắp chờ lần gọi tiếp theo', 'cooldown-wait-10-seconds':'chờ vài giây trước khi bật lại'
};
const browsers={IDLE:'Chrome: sẵn sàng',BROWSER_VOICE:'Chrome: Voice đang mở',BROWSER_DICTATION:'Chrome: đang nhập giọng nói',WAITING:'Chrome đang bận · trợ lý vẫn nghe local',STOPPED:'Chrome: đã yêu cầu kết thúc Voice',BLOCKED:'Cần kiểm tra Chrome',NEEDS_CLICK:'Đã dừng · cần kiểm tra Chrome'};
let inFlight=false,connectionFailed=false;
async function update(cmd='info'){
 if(inFlight||(cmd==='info'&&connectionFailed))return;
 inFlight=true;let timeout;
 try{
  const result=await Promise.race([chrome.runtime.sendMessage({cmd,mode:$('mode').value}),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new Error('Tiện ích chờ quá lâu. Đóng rồi mở lại popup để kết nối lại.')),22000);})]);
  if(!result?.ok){connectionFailed=true;$('mic').textContent='Micro local: chưa xác nhận';$('status').textContent=details[result?.error]||result?.error||'Không kết nối được.';return;}
  connectionFailed=false;
  $('mic').textContent='Micro local: '+(result.local.local_mic_open?(result.local.listen_mode==='conversation'?'NGHE LỆNH KẾT THÚC':'ĐANG NGHE'):'ĐÃ ĐÓNG');
  $('arm').disabled=Boolean(result.enabled);
  $('turn').textContent=result.local.listen_mode==='conversation'?(result.local.reply_ui_state==='idle'&&result.local.idle_remaining!==null?'ChatGPT đang chờ · còn '+Math.ceil(result.local.idle_remaining)+' giây':result.local.reply_ui_state==='busy'?'ChatGPT đang xử lý/trả lời · chưa đếm 15 giây':'Chờ trạng thái phiên · chưa đếm 15 giây'):'';
  const eventInfo=result.local.voice_events;
  $('events').textContent=result.local.listen_mode==='conversation'?(eventInfo?.connected?(eventInfo.supported?'Đã nhận trạng thái phiên trực tiếp':'Đã nối kênh sự kiện · đang xác định trạng thái'):'Chưa nhận được kênh trạng thái · chưa đếm 15 giây'):'';
  const activity=result.local.voice_activity;
  $('activity').textContent=activity?.state==='ready'?'Phát hiện giọng: '+(activity.speech?'đang có giọng':'đang chờ giọng'):'';
  $('mic').style.color=result.local.local_mic_open?'#186548':'#596c63';
  $('status').textContent=(result.enabled?'Trợ lý đang bật · ':'Trợ lý đang tắt · ')+(states[result.local.state]||'Đang kiểm tra');
  $('browser').textContent=browsers[result.browser.state]||'Chrome: cần kiểm tra';
  if(details[result.browser.detail])$('browser').textContent+=' · '+details[result.browser.detail];
  else if(details[result.local.browser_detail])$('browser').textContent+=' · '+details[result.local.browser_detail];
  else if(details[result.local.detail])$('browser').textContent+=' · '+details[result.local.detail];
  else if(!result.enabled&&result.local.last_error?.code)$('browser').textContent+=' · '+(details[result.local.last_error.code]||result.local.last_error.code);
 }catch(error){connectionFailed=true;$('mic').textContent='Micro local: chưa xác nhận';$('status').textContent=error.message||'Không liên lạc được với tiện ích.';}
 finally{clearTimeout(timeout);inFlight=false;}
}
$('arm').onclick=()=>update('arm');$('off').onclick=()=>update('disarm');update();setInterval(()=>update(),1000);
