"""V4L2 and bounded Tiny 3 UVC-XU operations. No SDK or network service."""
from __future__ import annotations
import ctypes
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from datetime import datetime, timezone

class CameraError(RuntimeError):
    pass

class XUQuery(ctypes.Structure):
    _fields_ = [('unit',ctypes.c_uint8),('selector',ctypes.c_uint8),('query',ctypes.c_uint8),('size',ctypes.c_uint16),('data',ctypes.POINTER(ctypes.c_uint8))]


def crc16(data):
    crc=0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8): crc=(crc>>1)^0xa001 if crc&1 else crc>>1
    return crc ^ 0xffff


def frame(command, receiver, payload, sequence=1):
    if len(payload)>44: raise CameraError('Vendor payload is too large')
    result=bytearray(60)
    struct.pack_into('<BBHHHBBH',result,0,0xaa,0x25,sequence,12,0,10,receiver,command)
    struct.pack_into('<H',result,6,crc16(result[:12]))
    struct.pack_into('<HH',result,12,len(payload),0)
    result[16:16+len(payload)]=payload
    struct.pack_into('<H',result,14,crc16(result[12:16+len(payload)]))
    return bytes(result)


def parse_controls(text):
    result={}; current=None
    for line in text.splitlines():
        m=re.match(r'\s*(\w+)\s+0x[0-9a-f]+\s+\(([^)]+)\)\s*:\s*(.*)',line)
        if m:
            key,kind,details=m.groups()
            nums={k:int(v) for k,v in re.findall(r'(min|max|step|default|value)=(-?\d+)',details)}
            if 'value' not in nums: continue
            current={'id':key,'kind':kind,**nums,'inactive':'inactive' in details,'options':[]}
            result[key]=current
        elif current and (m:=re.match(r'\s+(-?\d+):\s+(.+)',line)):
            current['options'].append({'value':int(m[1]),'label':m[2]})
    return result

# Published protocol facts, cross-checked against SDK layout; provenance in docs/RESEARCH.md.
VENDOR={
 'hdr':(0x01,6,0,1), 'face_exposure':(0x03,7,0,1),
 'fov':(0x04,17,0,2), 'auto_sleep':(0x0b,10,0,3600),
 'sleep_microphone':(0x13,16,0,1), 'mirror':(0x14,19,0,1),
 'audio_agc':(0x17,25,0,1), 'pickup_distance':(0x1b,34,0,2),
 'microphone':(0x1c,34,0,1), 'led':(0x1a,33,0,3),
}
# Filled from same-device round-trip results; unverified features remain visible but disabled.
VERIFIED_VENDOR={'hdr','face_exposure','face_focus','fov','mirror','audio_agc','pickup_distance','microphone','sleep_microphone','sleep','tracking','framing','led'}

STANDARD={
 'brightness':('Brightness','Image','Color'), 'contrast':('Contrast','Image','Color'),
 'saturation':('Saturation','Image','Color'), 'hue':('Hue','Image','Color'),
 'sharpness':('Sharpness','Image','Color'),
 'white_balance_automatic':('Auto white balance','Image','White balance'),
 'white_balance_temperature':('Temperature · K','Image','White balance'),
 'red_balance':('Red channel gain','Image','Advanced white balance'),
 'blue_balance':('Blue channel gain','Image','Advanced white balance'),
 'gain':('Sensor gain · device units','Image','Exposure'),
 'auto_exposure':('Exposure mode','Image','Exposure'),
 'exposure_time_absolute':('Shutter · 100 µs units','Image','Exposure'),
 'backlight_compensation':('Exposure compensation','Image','Exposure'),
 'power_line_frequency':('Anti-flicker','Image','Exposure'),
 'focus_automatic_continuous':('Auto focus','Image','Focus'),
 'focus_absolute':('Manual focus','Image','Focus'),
 'pan_absolute':('Pan · degrees','Console','Gimbal'),
 'tilt_absolute':('Tilt · degrees','Console','Gimbal'),
 'zoom_absolute':('Zoom · device units','Console','Gimbal'),
}


def opts(*labels): return [{'value':i,'label':s} for i,s in enumerate(labels)]

class Camera:
    def __init__(self,path,*,probe=False,state_dir=None):
        devices=self.discover()
        match=next((d for d in devices if os.path.realpath(d['path'])==os.path.realpath(path)),None)
        if not match: raise CameraError('Selected Tiny 3 is no longer connected. Refresh devices.')
        self.path=match['path']; self.device=match; self.probe=probe
        self.state_dir=Path(state_dir or Path.home()/'.local/state/obsbot-studio')
        self.state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.key=hashlib.sha256(self.path.encode()).hexdigest()[:16]
        self.last_error=''
        self._sequence=0
        self.baseline_path=self.state_dir/f'{self.key}-baseline.json'
        if not self.baseline_path.exists():
            self._write_json(self.baseline_path,self.export_snapshot())

    @staticmethod
    def discover():
        result=[]
        for path in sorted(glob.glob('/dev/v4l/by-id/*OBSBOT_Tiny_3-video-index0')):
            node=Path(path).resolve().name
            namefile=Path('/sys/class/video4linux')/node/'name'
            name=namefile.read_text().strip() if namefile.exists() else 'OBSBOT Tiny 3'
            result.append({'path':path,'name':name.split(':')[0]})
        return result

    def _run(self,*args):
        try:
            r=subprocess.run(['v4l2-ctl','-d',self.path,*args],text=True,capture_output=True,timeout=5)
        except (OSError,subprocess.TimeoutExpired) as e: raise CameraError(f'Camera command failed: {e}') from e
        if r.returncode: raise CameraError(r.stderr.strip() or r.stdout.strip() or 'Camera unavailable')
        return r.stdout

    def _xu(self,selector,query,data):
        buffer=(ctypes.c_uint8*len(data))(*data)
        request=XUQuery(2,selector,query,len(data),buffer)
        try:
            fd=os.open(self.path,os.O_RDWR|os.O_NONBLOCK)
            try: fcntl.ioctl(fd,0xC0107521,request)
            finally: os.close(fd)
        except OSError as e: raise CameraError(f'Camera extension control failed: {e.strerror}') from e
        return bytes(buffer)

    def _status(self):
        length=struct.unpack('<H',self._xu(6,0x85,b'\0\0'))[0]
        if length!=60: raise CameraError(f'Unsupported Tiny 3 status layout: {length} bytes')
        return self._xu(6,0x81,bytes(60))

    @staticmethod
    def _vendor_value(key,s):
        if key=='face_focus': return s[13]
        if key=='tracking': return s[24]
        if key=='framing': return s[28]
        if key=='sleep': return int(s[9] in (3,4))
        if key=='auto_sleep': return int.from_bytes(s[10:12],'little')
        if key=='microphone': return (s[34]>>4)&1
        if key=='pickup_distance': return s[34]&15
        return s[VENDOR[key][1]]

    def export_snapshot(self):
        standard=parse_controls(self._run('--list-ctrls-menus'))
        try: s=self._status()
        except CameraError: s=None
        vendor={k:self._vendor_value(k,s) for k in [*VENDOR,'face_focus','tracking','framing','sleep']} if s else {}
        return {'version':1,'device':self.device,'captured_at':datetime.now(timezone.utc).isoformat(),
                'standard':{k:v['value'] for k,v in standard.items()},'vendor':vendor,'raw_status_hex':s.hex() if s else None}

    def snapshot(self):
        raw=parse_controls(self._run('--list-ctrls-menus'))
        vendor_error=''
        try: s=self._status()
        except CameraError as e: s=None; vendor_error=str(e)
        controls=[]
        for key,(label,section,group) in STANDARD.items():
            if key not in raw: continue
            r=raw[key]
            d={'id':key,'label':label,'section':section,'group':group,'kind':'bool' if r['kind']=='bool' else 'select' if r['kind']=='menu' else 'int','value':r['value'],'min':r.get('min',0),'max':r.get('max',1),'step':r.get('step',1),'options':r['options'],'enabled':not r['inactive'],'reason':'Switch the automatic setting off to adjust manually.' if r['inactive'] else ''}
            if key in ('pan_absolute','tilt_absolute'):
                for attr in ('value','min','max','step'): d[attr]//=3600
                d['reason']='Driver setpoint; tracking may move the camera independently.'
                if key=='tilt_absolute':
                    d['min']=max(d['min'],-60); d['max']=min(d['max'],32)
            if key=='backlight_compensation':
                d.update(kind='select',options=[{'value':i,'label':f'{(i-9)/3:+.2f} EV'} for i in range(19)])
            if key in ('red_balance','blue_balance'):
                d['reason']='Advanced: writing channel gains overrides temperature tuning. Use Auto white balance to recover.'
            if key=='gain' and raw.get('auto_exposure',{}).get('value')!=1:
                d.update(enabled=False,reason='Select Manual exposure to set sensor gain.')
            if key=='white_balance_temperature' and raw.get('white_balance_automatic',{}).get('value'):
                d.update(enabled=False,reason='Turn off Auto white balance to set a temperature.')
            controls.append(d)
        def vendor(key,label,section,group,kind='bool',options=None,minimum=0,maximum=1,reason=''):
            available=s is not None and key!='auto_sleep' and (key in VERIFIED_VENDOR or self.probe)
            controls.append({'id':key,'label':label,'section':section,'group':group,'kind':kind,'value':self._vendor_value(key,s) if s else None,'min':minimum,'max':maximum,'step':1,'options':options or [],'enabled':available,'reason':reason if available else vendor_error or 'Not yet verified on this Tiny 3.'})
        vendor('hdr','HDR','Image','Image style')
        vendor('face_focus','Auto focus priority','Image','Focus','select',opts('Global','Face'))
        vendor('face_exposure','Auto exposure priority','Image','Exposure','select',opts('Global','Face'))
        vendor('fov','Field of view','Console','Gimbal','select',opts('Wide','Medium','Narrow'),maximum=2)
        vendor('tracking','Tracking mode','Console','AI tracking','select',opts('Off','Group','Single'),maximum=2,reason='Single mode needs a person in view. The camera may return to Off if it cannot acquire a target.')
        vendor('framing','Human framing','Console','AI tracking','select',opts('Normal / full body','Upper body','Close-up','Headless','Lower body'),maximum=4,reason='Applies to Single mode. Frame readback confirms mode, not target acquisition.')
        vendor('sleep','Camera asleep','More','Device')
        vendor('auto_sleep','Auto sleep · seconds (0 = never)','More','Device','int',minimum=0,maximum=3600)
        vendor('mirror','Mirror camera output','More','Device')
        vendor('led','Indicator brightness','More','Device','select',opts('Off','Low','Medium','High'),maximum=3)
        vendor('microphone','Microphone enabled','More','Audio')
        vendor('sleep_microphone','Microphone while asleep','More','Audio')
        vendor('audio_agc','Automatic microphone gain','More','Audio')
        vendor('pickup_distance','Microphone pickup distance','More','Audio','select',opts('Near','Normal','Far'),maximum=2)
        for d in controls:
            if d['id']=='auto_sleep':
                d['reason']='Disabled: the camera disconnected during this control’s hardware test.'
        unavailable=[
          ('image_style','Image Style · Standard / Streaming','Image','Image style','Available in OBSBOT Center. The Tiny 3 command and exact processing differences are not yet verified; this selector is not implemented.'),
          ('iso_limits','Auto ISO lower / upper limit','Image','Exposure','Tiny 3 ISO-limit commands are not verified. Sensor gain is available in manual exposure; it is not an ISO range limit.'),
          ('wb_shift','Blue–amber / green–magenta shift','Image','White balance','No verified Tiny 3 control. Temperature and red/blue gains are available.'),
          ('curves','Custom exposure curves','Image','Color','Device curve commands are unverified. Software gamma is available in Effects.'),
          ('special_tracking','Hand / whiteboard / desk tracking','Console','AI tracking','Documented SDK modes; not enabled until tested on this Tiny 3.'),
          ('zone','Zone tracking boundaries','Console','AI tracking','No verified Tiny 3 boundary payload. No guessed coordinates are sent.'),
          ('sound_tracking','Sound source assisted tracking','Console','AI tracking','Not the same as microphone gain. No verified Tiny 3 voice-localization command.'),
          ('object','Object tracking and selection','Console','AI tracking','Target-selection protocol not verified on Tiny 3.'),
          ('only_me','Only Me / face framing / composition','Console','AI tracking','Target identity and composition APIs are not verified.'),
          ('tracking_speed','Tracking speed','Console','AI tracking','Tiny 3 modes differ from Tiny 2. No verified Tiny 3 setter.'),
          ('gestures','Gesture controls','More','Hands-free control','SDK command IDs differ between releases. Unverified on this firmware.'),
          ('voice','Voice command configuration','More','Hands-free control','Voice status bits and command IDs differ. Unverified on this firmware.'),
          ('spatial_audio','Pure / Spatial / Smart Omni / Directional / Dual-Directional','More','Audio','Spatial audio presets are not the same as pickup distance. No verified Tiny 3 command.'),
          ('firmware','Firmware update / factory reset','More','Device','Use official OBSBOT Center for firmware and full factory reset. This app does not flash firmware.'),
          ('beauty','Face retouching / Eye Contact','More','OBSBOT Center features','These proprietary effects are unavailable. Open Effects for local background blur and replacement.'),
          ('production','Multiple camera PiP / multiview','More','OBSBOT Center features','Multiple camera mixing is not implemented. A PNG overlay is available in Effects.'),
        ]
        for key,label,section,group,reason in unavailable:
            controls.append(dict(id=key,label=label,section=section,group=group,kind='unavailable',value=None,enabled=False,reason=reason))
        if s:
            auto=raw.get('auto_exposure',{}).get('value')
            for d in controls:
                if d['id']=='framing' and s[24]!=2: d.update(enabled=False,reason='Select Single tracking to change human framing.')
                if d['id']=='face_focus' and not raw.get('focus_automatic_continuous',{}).get('value'): d.update(enabled=False,reason='Enable Auto focus first.')
                if d['id']=='face_exposure' and auto==1: d.update(enabled=False,reason='Select an automatic exposure mode first.')
            status={'sleeping':s[9] in (3,4),'hdr':s[6],'ai_mode':s[24],'ai_framing':s[28],'fps':s[31],'last_error':self.last_error}
        else: status={'last_error':vendor_error}
        group_order=['Image style','Focus','Exposure','White balance','Color','Advanced white balance','Gimbal','AI tracking','Audio','Device','Hands-free control','OBSBOT Center features']
        controls.sort(key=lambda d: group_order.index(d['group']))
        return {'device':self.device,'controls':controls,'status':status,'baseline_path':str(self.baseline_path)}

    @staticmethod
    def _validate(descriptor,value):
        if isinstance(value,bool): value=int(value)
        if not isinstance(value,int): raise CameraError('Control value must be an integer')
        if not descriptor['enabled']: raise CameraError(descriptor['reason'] or 'Control is unavailable')
        if descriptor['kind']=='select':
            if value not in [o['value'] for o in descriptor['options']]: raise CameraError('Unsupported selection')
        elif not descriptor['min']<=value<=descriptor['max']: raise CameraError('Value is outside the camera range')
        if descriptor['kind']=='int' and (value-descriptor['min'])%descriptor['step']: raise CameraError('Value does not match the camera step')
        return value

    def apply(self,key,value):
        lock=self.state_dir/'control.lock'
        with lock.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            state=self.snapshot()
            d=next((x for x in state['controls'] if x['id']==key),None)
            if not d: raise CameraError('Unknown camera control')
            value=self._validate(d,value)
            if key in STANDARD:
                target=value*3600 if key in ('pan_absolute','tilt_absolute') else value
                self._run(f'--set-ctrl={key}={target}')
                time.sleep(.08)
                result=self.snapshot()
                observed=next(c['value'] for c in result['controls'] if c['id']==key)
            else:
                if key in ('face_focus','sleep'):
                    self._sequence=(self._sequence+1)%65536
                    self._xu(2,0x01,frame(0x3602 if key=='face_focus' else 0xa0c2,2,struct.pack('<i',value),self._sequence))
                else:
                    s=self._status()
                    if key=='tracking': data=bytes([0x16,2,value,s[28] if value==2 else 0])
                    elif key=='framing': data=bytes([0x16,2,2,value])
                    elif key=='auto_sleep': data=bytes([0x0b,2])+struct.pack('<H',value)
                    else: data=bytes([VENDOR[key][0],1,value])
                    self._xu(6,0x01,data.ljust(60,b'\0'))
                observed=None
                for _ in range(50 if key in ('tracking','framing') else 30):
                    time.sleep(.1)
                    observed=self._vendor_value(key,self._status())
                    if observed==value: break
                result=self.snapshot()
            if observed!=value:
                self.last_error=('Single tracking did not stay on. Aim the camera at a clearly visible person and try again.' if key=='tracking' and value==2 and observed==0 else f'{key}: requested {value}, camera reports {observed}. Setting was not confirmed.')
                raise CameraError(self.last_error)
            self.last_error=''
            result['status']['last_error']=''
            return result

    @staticmethod
    def _write_json(path,data):
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(data,indent=2)+'\n')
        temp.chmod(0o600)
        temp.replace(path)

    def save_preset(self,slot,name=''):
        if type(slot)!=int or not 1<=slot<=4: raise CameraError('Local preset must be 1–4')
        data=self.export_snapshot(); data['name']=str(name)[:80]
        self._write_json(self.state_dir/f'{self.key}-preset-{slot}.json',data)
        return self.snapshot()

    def recall_preset(self,slot):
        if type(slot)!=int or not 1<=slot<=4: raise CameraError('Local preset must be 1–4')
        path=self.state_dir/f'{self.key}-preset-{slot}.json'
        if not path.exists(): raise CameraError('This local preset is empty. Save it first.')
        return self.restore(json.loads(path.read_text()))

    def restore(self,data):
        if data.get('device',{}).get('path')!=self.path: raise CameraError('Snapshot belongs to a different camera')
        errors=[]
        # Red/blue gains are excluded: last-written gains override temperature on this firmware.
        order=['auto_exposure','focus_automatic_continuous','white_balance_automatic',
               'brightness','contrast','saturation','hue','sharpness','power_line_frequency',
               'backlight_compensation','exposure_time_absolute','gain','focus_absolute',
               'pan_absolute','tilt_absolute','zoom_absolute','white_balance_temperature']
        for key in order:
            if key not in data['standard']: continue
            d=next((c for c in self.snapshot()['controls'] if c['id']==key),None)
            if not d or not d['enabled']: continue
            value=data['standard'][key]//3600 if key in ('pan_absolute','tilt_absolute') else data['standard'][key]
            if d['value']==value: continue
            try: self.apply(key,value)
            except CameraError as e: errors.append(str(e))
        for key in [*VENDOR,'face_focus','tracking','framing']:
            d=next((c for c in self.snapshot()['controls'] if c['id']==key),None)
            if not d or not d['enabled'] or key not in data['vendor']: continue
            if d['value']==data['vendor'][key]: continue
            try: self.apply(key,data['vendor'][key])
            except CameraError as e: errors.append(str(e))
        if errors: raise CameraError('Some settings could not be restored: '+'; '.join(errors))
        return self.snapshot()
