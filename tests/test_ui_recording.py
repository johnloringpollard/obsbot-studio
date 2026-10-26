from test_ui import app, Camera, wait
import time,tempfile,subprocess
from pathlib import Path
from obsbot_studio import ui
from obsbot_studio.preview import Preview
root=tempfile.mkdtemp(prefix='obsbot-ui-recording-')
class Locations:
    MoviesLocation=0
    @staticmethod
    def writableLocation(kind): return root
ui.QStandardPaths=Locations
original=Preview.arguments
def synthetic(path,mode,recording_path=None,slow_motion=False,audio_source=None):
    args=original(path,mode,recording_path,slow_motion,audio_source)
    start=args.index('-f');end=args.index('-i')+2
    args[start:end]=['-re','-f','lavfi','-i','testsrc=size=320x240:rate=30']
    return args
Preview.arguments=staticmethod(synthetic)
w=ui.MainWindow();w.show()
deadline=time.monotonic()+5
while w.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
w._toggle_recording()
assert not w.devices.isEnabled() and not w.mode.isEnabled() and not w.tabs.isEnabled()
before=list(Camera.writes)
w.request('apply',['brightness',42])
assert Camera.writes==before
end=time.monotonic()+2
while time.monotonic()<end:app.processEvents();time.sleep(.01)
assert w.preview.recording_path
path=Path(w.preview.recording_path)
w.close()
deadline=time.monotonic()+20
while w.isVisible() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
assert not w.isVisible() and not w.preview.running and not w.thread.isRunning()
subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,capture_output=True)
assert 'Recording saved' in w.record_result.text()
print('PASS UI locks controls/mode/device while recording, ignores writes, close finalizes playable file and reaps capture/thread',path)
