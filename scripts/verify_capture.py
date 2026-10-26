"""Explicit live-camera smoke test; records short silent clips locally."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.camera import Camera
from obsbot_studio.preview import Preview
app=QCoreApplication([])
c=Camera(Camera.discover()[0]['path'])
results=[]
for mode,slow in [('1080p · 60 fps',False),('1080p · 120 fps',True),('4K · 30 fps',False)]:
    p=Preview(); frames=[]; errors=[]; finished=[]
    p.frame.connect(lambda image:frames.append((image.width(),image.height())))
    p.error.connect(errors.append)
    p.recording_finished.connect(lambda path,ok:finished.append(ok))
    dest=Path('evidence')/f"capture-{int(time.time()*1000)}.mp4"
    p.start(c.path,mode,str(dest),slow)
    start=time.monotonic()
    while time.monotonic()-start<4 and (p.running or not frames):
        app.processEvents(); time.sleep(.01)
        if errors: break
    p.stop()
    deadline=time.monotonic()+18
    while p.running and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    p.shutdown()
    result={'mode':mode,'slow_motion':slow,'preview_frames':len(frames),'display_size':frames[-1] if frames else None,'errors':errors,'finalized':finished,'path':str(dest)}
    results.append(result); print(json.dumps(result),flush=True)
Path('evidence/capture-results.json').write_text(json.dumps(results,indent=2))
