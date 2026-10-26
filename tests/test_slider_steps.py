from test_ui import app, Camera
from obsbot_studio.ui import MainWindow
from PySide6.QtWidgets import QSlider,QSpinBox
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
import time

def pump():
 for _ in range(80): app.processEvents(); time.sleep(.005)
w=MainWindow();w.show();pump()
w.snapshot['controls']=[dict(id='temperature',label='Temperature',section='Image',group='White balance',kind='int',value=5800,min=2000,max=10000,step=100,enabled=True)]
w._render();w.tabs.setCurrentIndex(1);pump()
slider=w.findChild(QSlider,'control_temperature_slider')
spin=w.findChild(QSpinBox,'control_temperature')
requests=[]
w.request=lambda method,args=None:requests.append((method,args))
slider.setValue(39)
slider.sliderReleased.emit();pump()
assert spin.value()==5900 and requests[-1]==('apply',['temperature',5900]),requests
slider.setFocus();QTest.keyClick(slider,Qt.Key_Right);pump()
assert requests[-1]==('apply',['temperature',6000]),requests
slider.triggerAction(QSlider.SliderPageStepAdd);pump()
assert requests[-1][1][1]%100==0 and requests[-1][1][1]>6000,requests
w.close();pump()
print('PASS stepped drag, keyboard and trough actions submit accepted values')
