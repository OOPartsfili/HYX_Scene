"""Offline regression checks for the 2026-10 code audit; no live CARLA calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock, patch

from scene_studio import server
from scene_studio.schema import validate
from scene_studio.timeline import motion_hash

ROOT=Path(__file__).resolve().parents[1]


def sample():
    scene=json.loads((ROOT/'scene_studio/templates/Scene1_01.json').read_text(encoding='utf-8'))
    scene['events']=[]
    for actor in scene['actors']:actor['clips']=[]
    return validate(scene)


class SchemaAuditTests(unittest.TestCase):
    def setUp(self):self.scene=sample()

    def test_boolean_strings_cannot_enable_events_or_spawn_actors(self):
        for field in ('spawn_at_start','start_in_motion','snap'):
            with self.subTest(field=field):
                scene=copy.deepcopy(self.scene);scene['actors'][0][field]='false'
                with self.assertRaisesRegex(ValueError,'布尔'):validate(scene)
        self.scene['events']=[{'id':'event','enabled':'false','action':{'type':'marker'}}]
        with self.assertRaisesRegex(ValueError,'布尔'):validate(self.scene)

    def test_malformed_nested_objects_raise_validation_errors(self):
        changes=[('actors',[None]),('events',[None]),('look',[]),('camera',[])]
        for field,value in changes:
            with self.subTest(field=field):
                scene=copy.deepcopy(self.scene);scene[field]=value
                with self.assertRaises(ValueError):validate(scene)
        for field,value in [('route',[None]),('clips',[None]),('model',7),('id',[]),('color',7)]:
            with self.subTest(actor_field=field):
                scene=copy.deepcopy(self.scene);scene['actors'][0][field]=value
                with self.assertRaises(ValueError):validate(scene)

    def test_vehicle_actions_reject_walker_and_static_targets(self):
        self.scene['actors']+=[{'id':'ped','model':'walker.pedestrian.0001','behavior':'walker'},
                              {'id':'prop','model':'static.prop.barrel','behavior':'parked'}]
        for kind in ('brake','offset','lane_change','follow','route','lights'):
            with self.subTest(action=kind):
                self.scene['events']=[{'id':'bad','action':{'type':kind,'actor':'ped','target':self.scene['ego']}}]
                with self.assertRaisesRegex(ValueError,'只支持车辆'):validate(self.scene)
        self.scene['events']=[{'id':'bad','action':{'type':'speed','actor':'prop','value':10}}]
        with self.assertRaisesRegex(ValueError,'只支持车辆或行人'):validate(self.scene)
        self.scene['events']=[{'id':'bad','action':{'type':'follow','actor':self.scene['ego'],'target':'ped'}}]
        with self.assertRaisesRegex(ValueError,'目标车辆'):validate(self.scene)
        self.scene['events']=[]
        self.scene['actors'][0]['clips']=[{'id':'follow','type':'follow','start':0,'duration':1,'target':'ped'}]
        with self.assertRaisesRegex(ValueError,'目标车'):validate(self.scene)

    def test_event_timeline_channel_conflict_is_explicit(self):
        actor=self.scene['actors'][0]
        combinations=[('speed','brake'),('brake','speed'),('offset','lane_change'),
                      ('lane_change','lane_change'),('follow','follow'),('lights','lights')]
        other=next(a['id'] for a in self.scene['actors'] if a['id']!=actor['id'])
        for action,clip in combinations:
            with self.subTest(action=action,clip=clip):
                actor['clips']=[{'id':'clip','type':clip,'start':0,'duration':1,'target':other}]
                self.scene['events']=[{'id':'event','action':{'type':action,'actor':actor['id'],'target':other}}]
                with self.assertRaisesRegex(ValueError,'请选择一种编排方式'):validate(self.scene)

    def test_independent_channels_and_disabled_edits_remain_valid(self):
        actor=self.scene['actors'][0]
        actor['clips']=[{'id':'clip','type':'speed','start':0,'duration':1,'value':20}]
        self.scene['events']=[{'id':'event','action':{'type':'lane_change','actor':actor['id']}}]
        validate(self.scene)
        self.scene['events'][0].update(enabled=False,action={'type':'speed','actor':actor['id'],'value':0})
        validate(self.scene)
        self.scene['events'][0]['enabled']=True;actor['clips'][0]['enabled']=False
        validate(self.scene)

    def test_duration_matches_fixed_physics_clock(self):
        self.scene['duration']=1.03
        with self.assertRaisesRegex(ValueError,'整数倍'):validate(self.scene)
        self.scene['duration']=1.05
        self.assertEqual(validate(self.scene)['duration'],1.05)

    def test_motion_hash_tracks_visual_predecessor_timing_transitively(self):
        self.scene['events']=[
            {'id':'weather','trigger':{'type':'time','value':2},'action':{'type':'weather','preset':'clear'}},
            {'id':'cue','trigger':{'type':'after_event','event':'weather','value':1},'action':{'type':'marker','label':'cue'}},
            {'id':'brake','trigger':{'type':'after_event','event':'cue','value':1},'action':{'type':'brake','actor':self.scene['ego'],'value':1}}]
        original=validate(self.scene);baseline=motion_hash(original)
        changed=copy.deepcopy(original);changed['events'][0]['trigger']['value']=12
        self.assertNotEqual(baseline,motion_hash(changed))
        changed=copy.deepcopy(original);changed['events'][0]['action']['preset']='golden';changed['events'][1]['action']['label']='another label'
        self.assertEqual(baseline,motion_hash(changed))


class ServerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);runs=root/'runs';scenes=root/'scenes';runs.mkdir();scenes.mkdir()
        values={'DATA':root,'RUNS':runs,'SCENES':scenes,'CURRENT':None,'PROCESS':None,'LOG':None,
                'PLAN_CACHE':{},'PLANNER':None,'PLANNER_MAP':None}
        for key,value in values.items():
            p=patch.object(server,key,value);p.start();self.addCleanup(p.stop)
        self.connection=patch.object(server,'connection',side_effect=AssertionError('Tests must not connect to CARLA'))
        self.connection.start();self.addCleanup(self.connection.stop)
        self.client=server.app.test_client();self.scene=sample()

    def make_run(self):
        server.CURRENT=server.RUNS/'run_current';server.CURRENT.mkdir();(server.CURRENT/'commands').mkdir()
        (server.CURRENT/'scene.json').write_text(json.dumps(self.scene),encoding='utf-8')
        server.PROCESS=Mock(poll=Mock(return_value=None))

    def fake_world(self):
        return N(get_map=lambda:N(name=self.scene['map']),get_settings=lambda:N(synchronous_mode=False,no_rendering_mode=False))

    def test_nonobject_payload_has_clear_error(self):
        for endpoint in ('snap','preset','start','command','input'):
            with self.subTest(endpoint=endpoint):
                response=self.client.post('/api/'+endpoint,json=[])
                self.assertEqual(response.status_code,400)
                self.assertIn('必须为对象',response.json['error'])

    def test_ipv6_and_ipv4_local_addresses_both_allowed(self):
        response=self.client.get('/api/status',base_url='http://[::1]:8877',environ_base={'REMOTE_ADDR':'::1'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/status').status_code,200)
        self.assertEqual(self.client.get('/api/status',base_url='http://attacker.example').status_code,403)

    def test_snap_rejects_nonfinite_z_before_carla(self):
        response=self.client.post('/api/snap',json={'x':1,'y':2,'z':'NaN'})
        self.assertEqual(response.status_code,400);self.assertIn('z 超出范围',response.json['error'])

    def test_cached_plan_cannot_bypass_current_map_check(self):
        server.PLAN_CACHE[motion_hash(self.scene)]={'cached':'wrong-map'}
        with patch.object(server,'connection',return_value=(None,N(get_map=lambda:N(name='another-map')))):
            with self.assertRaisesRegex(ValueError,'地图不同'):server.compiled(self.scene)

    def test_stale_run_commands_are_not_written(self):
        self.make_run()
        response=self.client.post('/api/command',json={'type':'stop','run_id':'previous_run'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(list((server.CURRENT/'commands').iterdir()),[])
        response=self.client.post('/api/command',json={'type':'stop','run_id':server.CURRENT.name})
        self.assertEqual(response.status_code,200)

    def test_transform_default_actor_is_materialized_in_queued_command(self):
        self.make_run()
        response=self.client.post('/api/command',json={'type':'transform','pose':{'x':0,'y':0,'z':1,'yaw':0}})
        self.assertEqual(response.status_code,200)
        value=json.loads(next((server.CURRENT/'commands').iterdir()).read_text(encoding='utf-8'))
        self.assertEqual(value['actor'],self.scene['ego'])

    def test_failed_process_launch_is_terminal_and_closes_log(self):
        with patch.object(server,'connection',return_value=(None,self.fake_world())),patch.object(server,'compiled',return_value={}),patch.object(server.subprocess,'Popen',side_effect=OSError('launch failed')):
            response=self.client.post('/api/start',json={'scene':self.scene})
        self.assertEqual(response.status_code,400)
        self.assertEqual(server.state()['state'],'error')
        self.assertIn('launch failed',server.state()['error'])
        self.assertIsNone(server.PROCESS);self.assertIsNone(server.LOG)

    def test_second_start_does_not_spawn_another_worker(self):
        self.make_run()
        with patch.object(server.subprocess,'Popen') as launch:
            response=self.client.post('/api/start',json={'scene':self.scene})
        self.assertEqual(response.status_code,400);launch.assert_not_called()
        server.PROCESS.wait.assert_not_called()

    def test_terminal_worker_is_reaped_before_next_start(self):
        for terminal in ('finished','error'):
            with self.subTest(terminal=terminal):
                folder=server.RUNS/('ending_'+terminal);folder.mkdir();(folder/'commands').mkdir()
                (folder/'status.json').write_text(json.dumps({'state':terminal}),encoding='utf-8')
                server.CURRENT=folder;previous=Mock(poll=Mock(return_value=None),wait=Mock(return_value=0));server.PROCESS=previous
                next_process=Mock(poll=Mock(return_value=None))
                with patch.object(server,'connection',return_value=(None,self.fake_world())),patch.object(server,'compiled',return_value={}),patch.object(server.subprocess,'Popen',return_value=next_process) as launch:
                    response=self.client.post('/api/start',json={'scene':self.scene})
                self.assertEqual(response.status_code,200)
                previous.wait.assert_called_once_with(timeout=5);previous.terminate.assert_not_called();previous.kill.assert_not_called()
                launch.assert_called_once();self.assertIs(server.PROCESS,next_process)
                server.LOG.close();server.LOG=None

    def test_terminal_worker_timeout_does_not_launch_or_terminate(self):
        self.make_run();folder=server.CURRENT;previous=server.PROCESS
        (folder/'status.json').write_text(json.dumps({'state':'finished'}),encoding='utf-8')
        previous.wait.side_effect=server.subprocess.TimeoutExpired('worker',5)
        with patch.object(server.subprocess,'Popen') as launch:
            response=self.client.post('/api/start',json={'scene':self.scene})
        self.assertEqual(response.status_code,400);self.assertIn('仍在收尾',response.json['error'])
        launch.assert_not_called();previous.terminate.assert_not_called();previous.kill.assert_not_called()
        self.assertIs(server.PROCESS,previous);self.assertEqual(server.CURRENT,folder)

    def test_atomic_failure_removes_owned_temporary_file(self):
        path=Path(self.temp.name)/'document.json';path.write_text('original',encoding='utf-8')
        with patch.object(server.os,'replace',side_effect=PermissionError('locked')),patch.object(server.time,'sleep'):
            with self.assertRaises(PermissionError):server.atomic(path,{'new':True})
        self.assertEqual(path.read_text(encoding='utf-8'),'original')
        self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_scene_identifier_cannot_escape_scene_directory(self):
        for value in ('../escape','..\\escape','C:\\escape','scene/other'):
            with self.subTest(value=value),self.assertRaises(ValueError):server.scene_path(value)

    def test_run_manifest_download_keeps_file_whitelist_and_path_boundary(self):
        self.make_run();manifest={'version':1,'run_id':server.CURRENT.name,'dt':.05}
        (server.CURRENT/'run_manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        (server.CURRENT/'private.json').write_text('not downloadable',encoding='utf-8')
        with self.client.get('/api/runs/run_current/run_manifest.json') as response:
            self.assertEqual(response.status_code,200);self.assertEqual(response.json,manifest)
            self.assertIn('attachment',response.headers['Content-Disposition'])
        for url in ('/api/runs/run_current/private.json','/api/runs/../run_manifest.json',
                    '/api/runs/run_current/..%2Fprivate.json','/api/runs/run_current/..%5Cprivate.json'):
            with self.subTest(url=url),self.client.get(url) as response:
                self.assertIn(response.status_code,(400,404))

    def test_latest_editor_run_is_visible_above_many_prefixed_batch_runs(self):
        for index in range(66):
            rid='20261010_182638_new' if index==65 else f'case172_20261010_100000_{index:03d}'
            folder=server.RUNS/rid;folder.mkdir()
            (folder/'scene.json').write_text(json.dumps(self.scene),encoding='utf-8')
            (folder/'status.json').write_text(json.dumps({'state':'finished','elapsed':25}),encoding='utf-8')
            (folder/'run_manifest.json').write_text(json.dumps({'started_unix_ns':1000+index}),encoding='utf-8')
            (folder/'take.json').write_text(json.dumps({'complete':True,'id':rid,'scene':self.scene,
                'duration':25,'frame_count':501,'dt':.05,'manual_override':False}),encoding='utf-8')
        broken=server.RUNS/'newer_broken';broken.mkdir()
        (broken/'run_manifest.json').write_text(json.dumps({'started_unix_ns':9999}),encoding='utf-8')
        for name in ('scene.json','status.json','take.json'):(broken/name).write_text('null',encoding='utf-8')
        for endpoint,limit in (('/api/runs',40),('/api/takes',60)):
            with self.subTest(endpoint=endpoint):
                response=self.client.get(endpoint)
                self.assertEqual(response.status_code,200)
                self.assertEqual(len(response.json),limit)
                self.assertEqual(response.json[0]['id'],'20261010_182638_new')

    def test_legacy_run_order_uses_scene_time_when_manifest_is_missing_or_invalid(self):
        import os
        for rid,stamp,manifest in [('z_old',100,None),('a_new',300,'null'),('m_middle',200,'{"started_unix_ns":"invalid"}')]:
            folder=server.RUNS/rid;folder.mkdir();snapshot=folder/'scene.json'
            snapshot.write_text('{}',encoding='utf-8');os.utime(snapshot,ns=(stamp,stamp))
            if manifest is not None:(folder/'run_manifest.json').write_text(manifest,encoding='utf-8')
        self.assertEqual([p.name for p in server.ordered_run_folders()],['a_new','m_middle','z_old'])


if __name__=='__main__':unittest.main()
