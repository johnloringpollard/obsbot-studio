"""Explicit, reversible hardware test. Run only with permission to move the camera."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from obsbot_studio.camera import Camera

camera=Camera(Camera.discover()[0]['path'],probe=True)
before=camera.export_snapshot()
Path('evidence/probe-before.json').write_text(json.dumps(before,indent=2))
results=[]
def value(key):
    return next(c['value'] for c in camera.snapshot()['controls'] if c['id']==key)
def check(key,target):
    original=value(key)
    record={'control':key,'before':original,'test':target}
    try:
        camera.apply(key,target)
        record['observed']=value(key)
        record['passed']=record['observed']==target
    except Exception as error:
        record['passed']=False; record['error']=str(error)
    finally:
        camera.apply(key,original)
        record['restored']=value(key)==original
        results.append(record)
        Path('evidence/hardware-roundtrip.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(record),flush=True)
        if not record['restored']: raise RuntimeError('Restoration failed; stop testing')

was_sleeping=value('sleep')
try:
    if was_sleeping: camera.apply('sleep',0)
    for key,target in [('brightness',51),('hdr',1),('face_exposure',0),('face_focus',0),('fov',2),('mirror',1),('audio_agc',1),('pickup_distance',1),('microphone',0),('sleep_microphone',1)]:
        check(key,target)
    tracking=value('tracking'); framing=value('framing')
    try:
        camera.apply('tracking',2)
        check('framing',1)
    finally:
        try:
            if value('tracking')==2:
                camera.apply('framing',framing)
        finally:
            camera.apply('tracking',tracking)
    for target in (1,2): check('tracking',target)
finally:
    try:
        if was_sleeping: camera.apply('sleep',1)
    finally:
        Path('evidence/probe-after.json').write_text(json.dumps(camera.export_snapshot(),indent=2))
