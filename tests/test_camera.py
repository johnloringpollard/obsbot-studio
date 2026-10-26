import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from obsbot_studio.camera import Camera, CameraError, STANDARD, VERIFIED_VENDOR, crc16, frame, parse_controls

CONTROL_TEXT='''
 brightness 0x00980900 (int) : min=0 max=100 step=1 default=50 value=50
 white_balance_temperature 0x0098091a (int) : min=2000 max=10000 step=100 default=5000 value=5800 flags=inactive
 auto_exposure 0x009a0901 (menu) : min=0 max=3 default=0 value=0 (Auto Mode)
    0: Auto Mode
    1: Manual Mode
    3: Aperture Priority Mode
 focus_automatic_continuous 0x009a090c (bool) : default=1 value=1
'''
STATUS=bytes.fromhex('2e0001020600000100037800000101000001000001002100000043000000001e000310000000000008000201030101000000000000000000000000000000')

class CameraTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.devices=[{'path':'/dev/fake-tiny3','name':'OBSBOT Tiny 3'}]
        for target,value in [('discover',self.devices),('_run',CONTROL_TEXT),('_status',STATUS)]:
            mock=patch.object(Camera,target,return_value=value)
            setattr(self,target+'_mock',mock.start()); self.addCleanup(mock.stop)
        self.camera=Camera('/dev/fake-tiny3',state_dir=self.directory.name)

    def test_constructor_reads_and_backs_up_without_writes(self):
        self.assertTrue(self.camera.baseline_path.exists())
        self.assertTrue(all(call.args==('--list-ctrls-menus',) for call in self._run_mock.call_args_list))
        self.assertEqual(self.camera.baseline_path.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(self.camera.baseline_path.read_text())['vendor']['auto_sleep'],120)

    def test_vendor_failure_preserves_standard_controls(self):
        self._status_mock.side_effect=CameraError('Unsupported firmware')
        state=self.camera.snapshot()
        self.assertTrue(next(c for c in state['controls'] if c['id']=='brightness')['enabled'])
        self.assertFalse(next(c for c in state['controls'] if c['id']=='hdr')['enabled'])
        self.assertEqual(self.camera.export_snapshot()['vendor'],{})

    def test_unknown_device_rejected(self):
        with self.assertRaises(CameraError): Camera('/dev/unrelated',state_dir=self.directory.name)

    def test_autosleep_disabled_even_in_probe_mode(self):
        self.camera.probe=True
        with patch.object(self.camera,'_xu') as write:
            with self.assertRaisesRegex(CameraError,'disconnected'): self.camera.apply('auto_sleep',180)
            write.assert_not_called()

    def test_unknown_control_rejected_without_write(self):
        with patch.object(self.camera,'_xu') as write:
            with self.assertRaises(CameraError): self.camera.apply('guessed_opcode',1)
            write.assert_not_called()

    def test_invalid_values_never_reach_device(self):
        for key,value in [('brightness',101),('brightness','50'),('brightness',50.1),('auto_exposure',2)]:
            with self.subTest(key=key,value=value):
                self._run_mock.reset_mock()
                with self.assertRaises(CameraError): self.camera.apply(key,value)
                self.assertTrue(all(call.args==('--list-ctrls-menus',) for call in self._run_mock.call_args_list))

    def test_inactive_control_rejected(self):
        with self.assertRaisesRegex(CameraError,'automatic'): self.camera.apply('white_balance_temperature',5900)

    def test_step_validation(self):
        descriptor={'enabled':True,'kind':'int','min':2000,'max':10000,'step':100}
        with self.assertRaises(CameraError): Camera._validate(descriptor,5850)
        self.assertEqual(Camera._validate(descriptor,5800),5800)

    def test_hdr_write_and_readback(self):
        modified=bytearray(STATUS); modified[6]=1
        def xu(selector,query,data):
            self.assertEqual((selector,query,data[:3]),(6,1,b'\x01\x01\x01'))
            self.assertEqual(len(data),60)
            self._status_mock.return_value=bytes(modified)
        with patch.object(self.camera,'_xu',side_effect=xu),patch('obsbot_studio.camera.time.sleep'):
            state=self.camera.apply('hdr',1)
        self.assertEqual(state['status']['hdr'],1)

    def test_rejected_readback_surfaces_error(self):
        with patch.object(self.camera,'_xu'),patch('obsbot_studio.camera.time.sleep'):
            with self.assertRaisesRegex(CameraError,'not confirmed'): self.camera.apply('hdr',1)

    def test_led_write_readback_and_bounds(self):
        modified=bytearray(STATUS); modified[33]=2
        def xu(selector,query,data):
            self.assertEqual((selector,query,data),(6,1,b'\x1a\x01\x02'+bytes(57)))
            self._status_mock.return_value=bytes(modified)
        with patch.object(self.camera,'_xu',side_effect=xu),patch('obsbot_studio.camera.time.sleep'):
            state=self.camera.apply('led',2)
        self.assertEqual(next(c['value'] for c in state['controls'] if c['id']=='led'),2)
        with patch.object(self.camera,'_xu') as write:
            with self.assertRaises(CameraError): self.camera.apply('led',4)
            write.assert_not_called()

    def test_face_focus_frame(self):
        modified=bytearray(STATUS); modified[13]=0
        def xu(selector,query,data):
            self.assertEqual((selector,query),(2,1))
            self.assertEqual(struct.unpack_from('<H',data,10)[0],0x3602)
            self.assertEqual(data[16:20],bytes(4))
            self._status_mock.return_value=bytes(modified)
        with patch.object(self.camera,'_xu',side_effect=xu),patch('obsbot_studio.camera.time.sleep'):
            self.camera.apply('face_focus',0)

    def test_presets_scoped_and_empty_error(self):
        with self.assertRaisesRegex(CameraError,'empty'): self.camera.recall_preset(1)
        for slot in (0,5,True,'../'):
            with self.assertRaises(CameraError): self.camera.save_preset(slot)
        self.camera.save_preset(1)
        self.assertTrue((Path(self.directory.name)/f'{self.camera.key}-preset-1.json').exists())
        with self.assertRaisesRegex(CameraError,'different camera'): self.camera.restore({'device':{'path':'/dev/other'}})

class ProtocolTests(unittest.TestCase):
    def test_crc_usb_known_vector(self):
        self.assertEqual(crc16(b'123456789'),0xb4c8)
    def test_packet_crc_and_bounds(self):
        data=frame(0x3602,2,struct.pack('<i',1),sequence=7)
        self.assertEqual(len(data),60)
        self.assertEqual(data[:6],bytes.fromhex('aa2507000c00'))
        header=bytearray(data[:12]); header[6:8]=bytes(2)
        self.assertEqual(crc16(header),int.from_bytes(data[6:8],'little'))
        body=bytearray(data[12:20]); body[2:4]=bytes(2)
        self.assertEqual(crc16(body),int.from_bytes(data[14:16],'little'))
        with self.assertRaises(CameraError): frame(1,2,bytes(45))
    def test_parser_menu_and_inactive(self):
        parsed=parse_controls(CONTROL_TEXT)
        self.assertEqual(parsed['auto_exposure']['options'],[{'value':0,'label':'Auto Mode'},{'value':1,'label':'Manual Mode'},{'value':3,'label':'Aperture Priority Mode'}])
        self.assertTrue(parsed['white_balance_temperature']['inactive'])
        self.assertEqual(parsed['brightness']['value'],50)
    def test_packed_microphone_and_distance(self):
        self.assertEqual(Camera._vendor_value('microphone',STATUS),1)
        self.assertEqual(Camera._vendor_value('pickup_distance',STATUS),0)
        self.assertEqual(Camera._vendor_value('sleep',STATUS),1)

if __name__=='__main__': unittest.main()
