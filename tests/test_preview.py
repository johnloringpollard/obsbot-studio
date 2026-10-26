import os,sys,time
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.preview import Preview
app=QCoreApplication([])
p=Preview(); frames=[]; errors=[]; stopped=[]
p.frame.connect(lambda f: frames.append((f.width(),f.height())))
p.error.connect(errors.append); p.stopped.connect(lambda: stopped.append(True))
p.process.start('ffmpeg',['-hide_banner','-loglevel','error','-re','-f','lavfi','-i','testsrc=size=320x240:rate=30','-c:v','mjpeg','-f','image2pipe','pipe:1'])
end=time.monotonic()+5
while not frames and time.monotonic()<end: app.processEvents(); time.sleep(.01)
assert frames and frames[0]==(320,240), (frames, errors)
p.stop()
while p.running and time.monotonic()<end: app.processEvents(); time.sleep(.01)
assert not p.running
assert not errors,errors
p.start('/dev/does-not-exist','1080p · 30 fps')
end=time.monotonic()+5
while not errors and time.monotonic()<end: app.processEvents(); time.sleep(.01)
assert errors and '/dev/does-not-exist' in errors[-1],errors
p.shutdown()
print('PASS real ffmpeg synthetic source decoded, stop reaped process, invalid device diagnostics surfaced')
