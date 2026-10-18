"""Streaming pose recordings, validated indexed replay and locked-scene checks."""
import bisect
import copy
import hashlib
import json
import math
from pathlib import Path
from scene_studio.timeline import motion_hash


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' 必须是有限数值')
    return value


def _legacy_motion_hash(scene):
    """Version 1 stored this hash before event dependency tracking was added."""
    document = {
        'map': scene['map'], 'duration': scene['duration'], 'dt': scene.get('dt', .05), 'ego': scene['ego'],
        'actors': [{k: v for k, v in actor.items() if k not in ('name', 'color')} for actor in scene['actors']],
        'events': [event for event in scene.get('events', []) if event['action']['type'] not in ('weather', 'lights', 'marker')],
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _validate_frame(row, index, dt, duration, actor_ids, ego):
    if not isinstance(row, dict):
        raise ValueError('轨迹帧必须为对象')
    t = _finite(row.get('t'), '轨迹时间')
    # The last frame may be a fraction of dt when duration is not a multiple of dt.
    if abs(t - min(index * dt, duration)) > 1e-6:
        raise ValueError('轨迹时间轴缺帧、重复或顺序异常')
    actors = row.get('actors')
    if not isinstance(actors, dict) or ego not in actors or not set(actors).issubset(actor_ids):
        raise ValueError('轨迹参与者与基准场景不一致或缺少主车')
    for aid, pose in actors.items():
        if not isinstance(pose, dict):
            raise ValueError('轨迹参与者状态必须为对象')
        for key in ('x', 'y', 'z', 'yaw', 'pitch', 'roll', 'speed'):
            _finite(pose.get(key), aid + '.' + key)
        if pose['speed'] < 0:
            raise ValueError('轨迹速度不能为负数')
        for key in ('steer', 'throttle', 'brake', 'lights'):
            if key in pose:
                _finite(pose[key], aid + '.' + key)
    if not isinstance(row.get('control'), dict):
        raise ValueError('轨迹缺少控制归属信息')
    return t


class RecordingWriter:
    def __init__(self, folder, scene, weather):
        self.folder = Path(folder)
        self.scene = copy.deepcopy(scene)
        self.weather = copy.deepcopy(weather)
        self.stream = (self.folder / 'trajectory.jsonl').open('wb')
        self.digest = hashlib.sha256()
        self.count = 0
        self.last_t = 0
        self.paths = {}
        self.last_sample = -1.
        self.override = False
        self.actor_ids = {a['id'] for a in self.scene['actors']}

    def append(self, t, actors, control):
        clean = {aid: {k: v for k, v in a.items() if k not in ('id', 'carla_id')} for aid, a in actors.items()}
        row = {'t': round(t, 6), 'actors': clean, 'control': control}
        _validate_frame(row, self.count, self.scene['dt'], self.scene['duration'], self.actor_ids, self.scene['ego'])
        if self.count and row['t'] <= self.last_t:
            raise ValueError('轨迹时间必须递增')
        data = (json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        self.stream.write(data)
        self.stream.flush()
        self.digest.update(data)
        self.count += 1
        self.last_t = row['t']
        if control.get('owner') != 'auto':
            self.override = True
        if t - self.last_sample >= max(.1, self.scene['duration'] / 1500) - 1e-6:
            for aid, a in clean.items():
                self.paths.setdefault(aid, []).append([round(t, 6), a['x'], a['y'], a['z'], a['yaw'], a['speed']])
            self.last_sample = t

    def close(self, error=None):
        self.stream.close()
        value = {'version': 2, 'id': self.folder.name, 'scene': self.scene, 'weather': self.weather,
                 'dt': self.scene['dt'], 'duration': self.last_t, 'frame_count': self.count,
                 'motion_hash': motion_hash(self.scene), 'trajectory_sha256': self.digest.hexdigest(),
                 'manual_override': self.override, 'complete': error is None and self.count > 1,
                 'covers_scene_duration': abs(self.last_t - self.scene['duration']) <= 1e-6,
                 'error': error, 'paths': self.paths}
        # Publish the completion marker only after the full metadata is written.
        temporary = self.folder / 'take.json.tmp'
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(self.folder / 'take.json')
        return value


class Recording:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.stream = None
        try:
            self.header = json.loads((self.folder / 'take.json').read_text(encoding='utf-8'))
            if not isinstance(self.header, dict) or self.header.get('complete') is not True:
                raise ValueError('该次录制不完整，不能作为锁定轨迹')
            version = self.header.get('version', 1)
            if isinstance(version, bool) or version not in (1, 2):
                raise ValueError('不支持的录制版本')
            scene = self.header['scene']
            if not isinstance(scene, dict):
                raise ValueError('基准场景必须为对象')
            self.dt = _finite(self.header['dt'], '录制步长')
            duration = _finite(self.header['duration'], '录制时长')
            count = self.header['frame_count']
            if self.dt <= 0 or duration <= 0 or isinstance(count, bool) or not isinstance(count, int) or count < 2:
                raise ValueError('录制时长、步长或帧数无效')
            if abs(self.dt - scene.get('dt', .05)) > 1e-9 or duration > scene['duration'] + 1e-6:
                raise ValueError('录制时间与基准场景不一致')
            if count != math.ceil((duration - 1e-6) / self.dt) + 1:
                raise ValueError('录制时长与帧数不一致')
            hashes = {motion_hash(scene)}
            if version == 1:
                hashes.add(_legacy_motion_hash(scene))
            if self.header.get('motion_hash') not in hashes:
                raise ValueError('基准场景内容与录制标识不一致')
            actor_ids = {a['id'] for a in scene['actors']}
            self.stream = (self.folder / 'trajectory.jsonl').open('rb')
            self.offsets = []
            self.times = []
            digest = hashlib.sha256()
            while True:
                pos = self.stream.tell()
                line = self.stream.readline()
                if not line:
                    break
                row = json.loads(line)
                t = _validate_frame(row, len(self.offsets), self.dt, duration, actor_ids, scene['ego'])
                if self.times and t <= self.times[-1]:
                    raise ValueError('轨迹时间必须递增')
                self.offsets.append(pos)
                self.times.append(t)
                digest.update(line)
            if len(self.offsets) != count or abs(self.times[-1] - duration) > 1e-6:
                raise ValueError('轨迹文件不完整')
            if version == 2 and self.header.get('trajectory_sha256') != digest.hexdigest():
                raise ValueError('轨迹内容校验失败，录制文件已改变')
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
            self.close()
            raise ValueError('无法载入录制：' + str(exc)) from exc

    def frame(self, index):
        index = max(0, min(len(self.offsets) - 1, int(index)))
        self.stream.seek(self.offsets[index])
        return json.loads(self.stream.readline())

    def at(self, t):
        _finite(t, '重放时间')
        index = bisect.bisect_left(self.times, t)
        if index and (index == len(self.times) or t - self.times[index - 1] < self.times[index] - t):
            index -= 1
        return self.frame(index)

    def verify(self, scene):
        if motion_hash(scene) != motion_hash(self.header['scene']):
            raise ValueError('环境模式的车辆、轨迹、速度或时间轴已改变，请重新录制基准或恢复基准场景')
        return True

    def close(self):
        if self.stream is not None:
            self.stream.close()
