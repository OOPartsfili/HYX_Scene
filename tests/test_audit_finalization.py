"""Final result publication and cleanup fault injection, without a live world."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from scene_studio.engine import Session


class FinalizationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        session=object.__new__(Session);self.session=session
        session.folder=self.folder;session.start=Mock();session.initial_snapshot=NS(frame=200)
        session.error=None;session.camera=None;session.closed=False;session.owned=[]
        session.world=Mock();session.world.get_settings.return_value=NS(synchronous_mode=False)
        session.original_weather=object();session.original_settings=object()
        session.recorder=Mock();session.recording=None
        session.recorder.close.side_effect=lambda error:(self.folder/'take.json').write_text(json.dumps({'error':error}),encoding='utf-8')
        session.records=[];session.fired={};session.collisions=[];session.override=False
        session.camera_samples=[];session.unmapped_camera_frames=0
        session.image_lock=threading.Lock();session.first_recorded_frame=None
        session.preview=False;session.recordable_frames=set()
        session.owner=NS(owner='auto',state=lambda:{'owner':'auto'});session.states={}
        session.write_status=Mock()
        for name,value in [('runtime.STOP',NS(is_set=lambda:True)),('weather_dict',Mock(return_value={}))]:
            p=patch('scene_studio.engine.'+name,value);p.start();self.addCleanup(p.stop)
        p=patch('scene_studio.engine.runtime.shutdown');self.shutdown=p.start();self.addCleanup(p.stop)

    def test_finished_is_published_only_after_required_results_exist(self):
        def publish():
            self.assertEqual(self.session.status,'finished')
            for name in ('telemetry.csv','take.json','events.json'):
                self.assertTrue((self.folder/name).is_file(),name)
            self.assertIsNone(json.loads((self.folder/'events.json').read_text(encoding='utf-8'))['error'])
        self.session.write_status.side_effect=publish
        self.session.run()
        self.session.write_status.assert_called_once()

    def test_failed_event_output_publishes_error_after_cleanup(self):
        with patch('scene_studio.engine.atomic_json',side_effect=OSError('events disk failure')):
            self.session.run()
        self.assertEqual(self.session.status,'error')
        self.assertIn('events disk failure',self.session.error)
        self.session.write_status.assert_called_once();self.shutdown.assert_called_once()
        self.session.world.set_weather.assert_called_once_with(self.session.original_weather)
        self.session.world.apply_settings.assert_called_once_with(self.session.original_settings)

    def test_failed_event_output_keeps_prior_error(self):
        self.session.error='earlier failure'
        with patch('scene_studio.engine.atomic_json',side_effect=OSError('events disk failure')):
            self.session.run()
        self.assertEqual(self.session.status,'error')
        self.assertIn('earlier failure',self.session.error)
        self.assertIn('events disk failure',self.session.error)

    def test_failed_telemetry_close_does_not_skip_world_restoration(self):
        original_open=Path.open
        class FailOnClose:
            def __init__(self,stream):self.stream=stream
            def __getattr__(self,name):return getattr(self.stream,name)
            def close(self):self.stream.close();raise OSError('telemetry close failure')
        def opening(path,*args,**kwargs):
            stream=original_open(path,*args,**kwargs)
            return FailOnClose(stream) if path.name=='telemetry.csv' and args and args[0]=='w' else stream
        with patch.object(Path,'open',opening):self.session.run()
        self.assertEqual(self.session.status,'error');self.assertIn('telemetry close failure',self.session.error)
        self.shutdown.assert_called_once()
        self.session.world.set_weather.assert_called_once_with(self.session.original_weather)
        self.session.world.apply_settings.assert_called_once_with(self.session.original_settings)
        self.session.recorder.close.assert_called_once_with(self.session.error)
        self.assertIn('telemetry close failure',json.loads((self.folder/'events.json').read_text(encoding='utf-8'))['error'])
        self.session.write_status.assert_called_once()


if __name__=='__main__':unittest.main()
