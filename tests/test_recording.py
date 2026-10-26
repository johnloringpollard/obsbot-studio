import os,sys,time,json,tempfile,subprocess
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.preview import Preview
app=QCoreApplication([])
for slow in (False,True):
    directory=Path(tempfile.mkdtemp(prefix='obsbot-recording-test-'))
    path=directory/'clip.mp4'
    p=Preview(); frames=[]; finished=[]; errors=[]
    p.frame.connect(lambda image: frames.append(image.size()))
    p.recording_finished.connect(lambda name,success: finished.append((name,success)))
    p.error.connect(errors.append)
    args=p.arguments('/dev/fake','720p · 60 fps',str(path),slow)
    assert args.count('-i') == 1
    start=args.index('-f'); end=args.index('-i')+2
    args[start:end]=['-re','-f','lavfi','-i','testsrc=size=320x240:rate=60']
    p.recording_path=str(path)
    p.process.start('ffmpeg',args)
    deadline=time.monotonic()+6
    while len(frames)<24 and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert frames, errors
    p.stop()
    deadline=time.monotonic()+20
    while p.running and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    app.processEvents()
    assert not p.running
    assert finished==[(str(path),True)],(finished,errors)
    assert not errors,errors
    meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))
    stream=meta['streams'][0]
    assert stream['codec_name']=='h264'
    assert stream['avg_frame_rate']==('30/1' if slow else '60/1'),stream
    assert float(stream['duration'])>.5
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,capture_output=True)
    before=path.read_bytes()
    p.start('/dev/fake','720p · 60 fps',str(path),slow)
    assert not p.running and path.read_bytes()==before
    print('PASS', 'slow motion' if slow else 'normal', 'shared-input preview frames',len(frames),'saved',path,'fps',stream['avg_frame_rate'],'duration',stream['duration'],'no overwrite')
