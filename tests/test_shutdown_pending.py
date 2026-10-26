from test_ui import app, Camera
from obsbot_studio.ui import MainWindow
from obsbot_studio.preview import Preview
from PySide6.QtCore import QProcess
import time

def pump(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end: app.processEvents(); time.sleep(.005)

def synthetic(path,mode,*args):
 return ['-hide_banner','-loglevel','error','-re','-f','lavfi','-i','testsrc2=size=320x240:rate=30','-c:v','mjpeg','-f','image2pipe','pipe:1']
Preview.arguments=staticmethod(synthetic)
w=MainWindow();w.show();pump(.2)
w._toggle_preview();pump(.4)
assert w.preview.running
writes=len(Camera.writes)
w.request('apply',['sleep',1]);w.close();pump(1)
assert not w.isVisible() and not w.thread.isRunning() and not w.preview.running
assert len(Camera.writes)==writes
print('PASS closing cancels undispatched sleep and reaps process/thread')
