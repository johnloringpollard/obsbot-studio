import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys, types, time
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
fake = types.ModuleType('obsbot_studio.camera')
class CameraError(Exception): pass
class Camera:
    writes = []
    @staticmethod
    def discover(): return [{'name': 'OBSBOT Tiny 2', 'path': '/dev/fake'}]
    def __init__(self, path): self.value = 20
    def snapshot(self):
        return {'device': {'name': 'OBSBOT Tiny 2', 'path': '/dev/fake'}, 'status': {}, 'controls': [
            dict(id='brightness',label='Brightness',section='Image',group='Exposure',kind='int',value=self.value,min=0,max=100,step=1,enabled=True),
            dict(id='auto',label='Auto exposure',section='Image',group='Exposure',kind='bool',value=True,enabled=True),
            dict(id='mode',label='Tracking mode',section='Console',group='Tracking',kind='select',value=1,options=[dict(value=1,label='Normal'),dict(value=2,label='Motion')],enabled=True),
            dict(id='beauty',label='Beauty',section='More',group='Effects',kind='unavailable',enabled=False,reason='Requires proprietary processing.'),
        ]}
    def apply(self,k,v):
        self.writes.append((k,v))
        if v == 99: raise CameraError('Rejected by camera')
        self.value = v
        return self.snapshot()
    def save_preset(self,slot): return self.snapshot()
    def recall_preset(self,slot): return self.snapshot()
fake.Camera=Camera; fake.CameraError=CameraError
sys.modules[fake.__name__]=fake
from PySide6.QtWidgets import QApplication,QSpinBox,QSlider,QLabel
from obsbot_studio.ui import MainWindow,STYLE
app=QApplication([]); app.setStyleSheet(STYLE)
w=MainWindow(); w.show()
def wait():
    for _ in range(100):
        app.processEvents(); time.sleep(.005)
        if not w.busy: return
wait()
assert w.snapshot is not None
assert Camera.writes == [], Camera.writes
assert not w.preview.running
w.tabs.setCurrentIndex(1)
slider=w.findChild(QSlider,'control_brightness_slider')
slider.setValue(32)
assert Camera.writes == []
slider.sliderReleased.emit(); wait()
assert Camera.writes == [('brightness',32)], Camera.writes
w.request('apply',['brightness',99]); wait()
assert w.snapshot['controls'][0]['value'] == 32
assert 'Rejected' in w.status.text()
assert not w.findChild(QLabel,'control_beauty').isEnabled()
w.grab().save('/tmp/obsbot-studio-mock-ui.png')
w.close(); app.processEvents()
assert not w.thread.isRunning()
print('PASS initialization has no writes, slider release applies once, error readback, unsupported disabled, clean thread shutdown')
