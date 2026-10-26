import os,sys,time,tempfile,subprocess,json
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.preview import Preview
app=QCoreApplication([])
p=Preview();images=[];done=[];errors=[]
p.frame.connect(lambda f:images.append(f.size()));p.recording_finished.connect(lambda name,ok:done.append(ok));p.error.connect(errors.append)
path=Path(tempfile.mkdtemp(prefix='obsbot-audio-test-'))/'clip.mp4'
args=p.arguments('/dev/fake','1080p · 30 fps',str(path),False,'named-test-microphone')
assert args.count('-i')==2 and 'named-test-microphone' in args
start=args.index('-f');end=args.index('-i')+2
args[start:end]=['-re','-f','lavfi','-i','testsrc=size=320x240:rate=30']
start=args.index('pulse')-1;end=args.index('named-test-microphone')+1
args[start:end]=['-re','-f','lavfi','-i','sine=frequency=440:sample_rate=48000']
p.recording_path=str(path);p.process.start('ffmpeg',args)
end=time.monotonic()+2
while time.monotonic()<end:app.processEvents();time.sleep(.01)
p.stop();end=time.monotonic()+20
while p.running and time.monotonic()<end:app.processEvents();time.sleep(.01)
app.processEvents()
assert done==[True],(done,errors)
assert images and not errors,errors
meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))
assert [s['codec_name'] for s in meta['streams']]==['h264','aac'],meta
subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],capture_output=True,check=True)
try:p.arguments('/dev/fake','1080p · 60 fps',str(path),True,'microphone')
except ValueError:pass
else:raise AssertionError('slow motion must reject audio')
print('PASS one video+one named audio input, preview frames',len(images),'finalized H264/AAC full decode',path,'slow motion rejects audio')
