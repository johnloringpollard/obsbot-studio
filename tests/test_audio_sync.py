"""Different source start times must survive recording as the same A/V offset."""
import array
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from obsbot_studio.preview import Preview

def ff(*args):
 return subprocess.run(['ffmpeg','-v','error',*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20).stdout
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp); video=root/'video.mkv'; audio=root/'audio.mka'; out=root/'result.mp4'
 ff('-f','lavfi','-i','testsrc2=size=160x120:rate=30','-t','2','-c:v','ffv1','-output_ts_offset','1',str(video))
 ff('-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1.6','-c:a','pcm_s16le','-output_ts_offset','1.4',str(audio))
 args=Preview.arguments('/dev/fake','1080p · 30 fps',str(out),False,'fake-mic')
 # Preserve the production sync option and output filters; substitute finite input files.
 end=args.index('-map')
 args=args[:4]+['-i',str(video),'-isync','0','-i',str(audio)]+args[end:]
 subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=20)
 samples=array.array('h',ff('-i',str(out),'-vn','-ac','1','-ar','48000','-f','s16le','pipe:1'))
 onset=next(i for i,s in enumerate(samples) if abs(s)>500)/48000
 assert .37<onset<.43,onset
 print(f'PASS recording preserves 400ms input offset; measured tone starts at {onset:.4f}s')
