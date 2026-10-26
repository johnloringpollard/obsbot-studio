"""Run with a consenting person in view; restores tracking/framing/FOV/zoom."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.camera import Camera
from obsbot_studio.preview import Preview
app=QCoreApplication([]);c=Camera(Camera.discover()[0]['path'])
before=c.export_snapshot();p=Preview();images=[];errors=[]
p.frame.connect(lambda im:images.append(im.copy()) if len(images)<1 else images.__setitem__(0,im.copy()))
p.error.connect(errors.append)
result={'before':before,'checks':[]}
def wait(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:app.processEvents();time.sleep(.01)
def shot(name):
 if images:images[0].save(f'evidence/tracking-{name}.png')
try:
 p.start(c.path,'1080p · 30 fps');wait(2);shot('before')
 c.apply('tracking',2);wait(4)
 result['checks'].append({'tracking':c.export_snapshot()['vendor']['tracking']});shot('single')
 print('Single',result['checks'][-1],flush=True)
 for framing in (1,2,0):
  c.apply('framing',framing);wait(3)
  result['checks'].append({'framing_requested':framing,'vendor':c.export_snapshot()['vendor']});shot(str(framing))
  print('Framing',framing,result['checks'][-1]['vendor']['framing'],flush=True)
except Exception as e:
 result['error']=str(e);print('STOP',str(e),flush=True)
finally:
 try:
  if c.export_snapshot()['vendor']['tracking']==2:c.apply('framing',before['vendor']['framing'])
 finally:
  c.apply('tracking',before['vendor']['tracking'])
 c.apply('fov',before['vendor']['fov'])
 c.apply('zoom_absolute',before['standard']['zoom_absolute'])
 c.apply('pan_absolute',before['standard']['pan_absolute']//3600)
 c.apply('tilt_absolute',before['standard']['tilt_absolute']//3600)
 p.stop();wait(1);p.shutdown()
 result['after']=c.export_snapshot();result['capture_errors']=errors
 Path('evidence/person-tracking.json').write_text(json.dumps(result,indent=2))
 print('Restored tracking, framing, field of view and zoom.',flush=True)
