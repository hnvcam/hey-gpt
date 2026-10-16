import ctypes as c, wave
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Tạo câu hỏi tiếng Việt local để thử Voice; không gửi hay phát âm thanh.')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
lib=c.CDLL('libespeak-ng.so.1')
lib.espeak_Initialize.argtypes=[c.c_int,c.c_int,c.c_char_p,c.c_int]
rate=lib.espeak_Initialize(2,0,None,0)
if rate<=0: raise RuntimeError('Không khởi tạo được giọng đọc local')
lib.espeak_SetVoiceByName.argtypes=[c.c_char_p]
if lib.espeak_SetVoiceByName(b'vi')!=0: raise RuntimeError('Không có giọng Việt')
lib.espeak_SetParameter(1,150,0)
parts=[]
@c.CFUNCTYPE(c.c_int,c.POINTER(c.c_short),c.c_int,c.c_void_p)
def audio(data,count,events):
 if data and count: parts.append(c.string_at(data,count*2))
 return 0
lib.espeak_SetSynthCallback(audio)
lib.espeak_Synth.argtypes=[c.c_void_p,c.c_size_t,c.c_uint,c.c_int,c.c_uint,c.c_uint,c.c_void_p,c.c_void_p]
text='Hãy kể một câu chuyện ngắn bằng tiếng Việt về một chú mèo đi lạc rồi tìm được đường về nhà. Hãy kể khoảng một phút để tôi kiểm tra chế độ giọng nói.'
data=text.encode('utf-8')+b'\0'
assert lib.espeak_Synth(data,len(data),0,1,0,1,None,None)==0
lib.espeak_Synchronize()
p=args.output
p.parent.mkdir(parents=True,exist_ok=True)
with wave.open(str(p),'wb') as f:
 f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(b''.join(parts))
print({'path':str(p.resolve()),'seconds':sum(map(len,parts))/2/rate,'sample_rate':rate})
