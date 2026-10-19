"""Lamp-state regressions without a running simulator."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import carla
from scene_studio.engine import Session, StudioDriver
from scene_studio.lighting import lights_at
from scene_studio.schema import validate
from scene_studio.export_python import render_python

ROOT = Path(__file__).resolve().parents[1]


class VehicleLightsTests(unittest.TestCase):
    def test_initial_states_and_clip_boundary_restore_all_combinations(self):
        for turn in (0, 16, 32):
            for brake in (0, 8):
                base = turn | brake
                spec = {'lights': base, 'clips': [
                    {'id': 'lamp', 'type': 'lights', 'start': 1, 'duration': 2, 'value': 40},
                    {'id': 'disabled', 'type': 'lights', 'start': 4, 'duration': 1, 'value': 16, 'enabled': False}]}
                self.assertEqual([lights_at(spec, t) for t in (0, 1, 2.99, 3, 4)], [base, 40, 40, base, base])
                driver = object.__new__(StudioDriver)
                driver.timeline = True; driver.timeline_follow = False; driver.timeline_lights_before = None
                driver.spec = spec; driver.track = {'lane_width': 3.5}; driver.vice_car = Mock()
                driver.vice_car.get_light_state.return_value = carla.VehicleLightState(base)
                driver.timeline_update(1, {})
                self.assertEqual(int(driver.vice_car.set_light_state.call_args.args[0]), 40)
                driver.timeline_update(3, {})
                self.assertEqual(int(driver.vice_car.set_light_state.call_args.args[0]), base)

    def test_seek_updates_real_vehicle_lamps_and_restores_on_backward_seek(self):
        session = object.__new__(Session)
        session.end_time = 10; session.recording = None
        a = Mock(type_id='vehicle.tesla.model3')
        session.actors = {'ego': a}
        session.specs = {'ego': {'z': 1, 'lights': 8, 'clips': [
            {'id': 'lamp', 'type': 'lights', 'start': 1, 'duration': 2, 'value': 16}]}}
        session.plan = {'tracks': {'ego': {'frames': [[0, 1, 2, 1, 0], [3, 4, 2, 1, 0]]}}}
        for t, expected in ((2, 16), (3, 8), (0, 8)):
            session.preview_at(t)
            self.assertEqual(int(a.set_light_state.call_args.args[0]), expected)

    def test_schema_and_export_preserve_lamps_without_changing_old_scenes(self):
        scene = json.loads((ROOT/'scene_studio/templates/Timeline_Demo.json').read_text(encoding='utf-8'))
        self.assertNotIn('lights', validate(scene)['actors'][0])
        for value in (0, 8, 16, 24, 32, 40, 49):
            scene['actors'][0]['lights'] = value
            self.assertEqual(validate(scene)['actors'][0]['lights'], value)
        source = render_python(scene, ROOT)
        scope = {'__name__': 'lamp_export_test'}
        exec(compile(source, '<export>', 'exec'), scope)
        self.assertEqual(scope['SCENE']['actors'][0]['lights'], 49)
        for value in (True, -1, 2048, .5, float('nan')):
            bad = copy.deepcopy(scene); bad['actors'][0]['lights'] = value
            with self.assertRaises(ValueError):validate(bad)

    def test_snapshot_records_actual_lamps_for_replay_and_hud(self):
        session = object.__new__(Session)
        a = Mock(type_id='vehicle.tesla.model3', id=101)
        a.get_control.return_value = carla.VehicleControl(brake=0)
        a.get_light_state.return_value = carla.VehicleLightState(40)
        state = Mock(); state.get_transform.return_value = carla.Transform()
        state.get_velocity.return_value = carla.Vector3D()
        session.actors = {'ego': a}; session.recording = None
        snapshot = Mock(); snapshot.find.return_value = state
        session.snapshot(snapshot)
        self.assertEqual(session.states['ego']['lights'], 40)
        self.assertEqual(session.states['ego']['brake'], 0)


if __name__ == '__main__':unittest.main()
