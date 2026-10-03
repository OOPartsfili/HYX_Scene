"""按配置频率逐行写入 CSV；同一行车辆状态取自同一个世界快照。"""
import csv
import math
import threading
import time
from pathlib import Path
from vehicle_method import get_steering_wheel_info, world
import scene_runtime as runtime

dict_0 = {key: [] for key in ('time','steering','accelerator','brake','stage_flag','Handchange_flag','Collision_flag')}

class Info:
    def __init__(self, dict_index, dict_0, file_name, fps=60):
        if fps <= 0:
            raise ValueError('fps must be positive')
        self.car_list = []
        self.flag = True
        self.dict_index = dict(dict_index)
        self.dict_0 = {key: [] for key in dict_0}  # 每次实验独立；不再累积全程列数组。
        self.fps, self.file_name = fps, file_name
        self.stage_flag = self.Handchange_flag = self.Collision_flag = self.TOR_flag = 0
        self._thread = self._file = None
        self._saved = False
        self._lock = threading.Lock()
        self.samples = 0
        runtime.register(self, 'save_info')

    def get_info(self):
        if self._thread:
            return
        path = Path(self.file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open('w', newline='', encoding='utf-8')
        writer = csv.writer(self._file)
        cars = tuple(self.car_list)
        names = [self.dict_index.get(i, f'Car{i}') for i in range(len(cars))]
        fields = ('id','x','y','z','speed(km/h)','accx','accy','pitch','yaw','roll')
        writer.writerow(['time','steering','accelerator','brake','stage_flag','Handchange_flag',
                         'Collision_flag','TOR_flag','frame','sim_time'] + [f'{n}_{f}' for n in names for f in fields])
        def collect():
            deadline = time.perf_counter()
            last_frame = -1
            last_flush = deadline
            try:
                while self.flag and not runtime.STOP.is_set():
                    snapshot = world.get_snapshot()
                    if snapshot.frame != last_frame:
                        last_frame = snapshot.frame
                        steering, accelerator, brake = get_steering_wheel_info()
                        row = [round(time.time(),6), steering, accelerator, brake, self.stage_flag,
                               self.Handchange_flag,self.Collision_flag,self.TOR_flag,
                               snapshot.frame,snapshot.timestamp.elapsed_seconds]
                        for car in cars:
                            state = snapshot.find(car.id)
                            if state is None:
                                row.extend([car.id]+[None]*9)
                                continue
                            tf, v, acc = state.get_transform(), state.get_velocity(), state.get_acceleration()
                            row.extend([car.id,tf.location.x,tf.location.y,tf.location.z,
                                3.6*math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z),acc.x,acc.y,
                                tf.rotation.pitch,tf.rotation.yaw,tf.rotation.roll])
                        writer.writerow(row)
                        self.samples += 1
                    now = time.perf_counter()
                    if now-last_flush >= 1:
                        self._file.flush()
                        last_flush = now
                    deadline += 1/self.fps
                    if deadline < now:
                        deadline = now + 1/self.fps
                    runtime.STOP.wait(max(0, deadline-time.perf_counter()))
            except Exception as exc:
                runtime.metadata(csv_error=str(exc))
                runtime.request_stop()
        self._thread = threading.Thread(target=collect, name='csv-recorder', daemon=True)
        self._thread.start()

    def save_info(self):
        with self._lock:
            if self._saved:
                return
            self.flag = False
            if self._thread and self._thread is not threading.current_thread():
                self._thread.join(timeout=3)
                if self._thread.is_alive():
                    raise RuntimeError('CSV thread has not stopped; refusing concurrent close')
            if self._file:
                self._file.flush()
                self._file.close()
            self._saved = True
            runtime.metadata(csv_file=str(self.file_name), csv_rows=self.samples, csv_requested_fps=self.fps)
