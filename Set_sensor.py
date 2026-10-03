# -*- coding: utf-8 -*-
"""相机显示：画质档位、最新帧缓存、明确后视镜方向和转换耗时统计。"""

import glob
import os
import sys

import carla
import argparse
import random
import time
import numpy as np
import pygame
import threading
from pathlib import Path
from optimization_config import camera_settings
from display_font import arial
import scene_runtime as runtime


class CustomTimer:
    def __init__(self):
        try:
            self.timer = time.perf_counter
        except AttributeError:
            self.timer = time.time

    def time(self):
        return self.timer()


# 输入 grid_size逻辑格[2,3]代表2行3列, window_size窗口大小这里1280X720
class DisplayManager:
    def __init__(self, grid_size, window_size):
        pygame.init()
        pygame.font.init()
        # 显示屏设置，这里是整个屏的大小
        self.display = pygame.display.set_mode(window_size, pygame.HWSURFACE | pygame.DOUBLEBUF)

        # 逻辑格大小
        self.grid_size = grid_size

        # 窗口大小，这个也是整个屏大小
        self.window_size = window_size

        # 初始化传感器列表
        self.sensor_list = []

        # 读取前景图片
        image_path = str(Path(__file__).resolve().parent / 'asset' / '123V1.0.png')
        self.transparent_image = pygame.image.load(image_path).convert_alpha()
        self.speed_font = arial(50)
        self._last_speed = None
        self._speed_surface = None
        self._last_render = None
        runtime.register(self, 'destroy')


    # 获取显示屏
    def get_display(self):
        return self.display

    # 获取当前窗口大小
    # 输出[x,y]尺寸
    def get_window_size(self):
        return [int(self.window_size[0]), int(self.window_size[1])]

    # 实际显示大小，这里self.window_size[0]/self.grid_size[1]是算出小屏的尺寸
    # 输出小屏的尺寸[x,y]
    def get_display_size(self):
        return [int(self.window_size[0] / self.grid_size[1]), int(self.window_size[1] / self.grid_size[0])]

    # gridPos=[1, 0]，代表小屏的位置坐标
    # 输入位置坐标，输出一个小屏左上角起点坐标,如果有特殊位置就按特殊位置设置
    def get_display_offset(self, gridPos):
        dis_size = self.get_display_size()  # 这里得到的是小屏的尺寸
        x0 = int(gridPos[1] * dis_size[0])
        y0 = int(gridPos[0] * dis_size[1])

        return [x0, y0]

    # 输入一个传感器，结果是DisplayManager里增加一个传感器
    def add_sensor(self, sensor):
        self.sensor_list.append(sensor)

    # 获取传感器列表
    def get_sensor_list(self):
        return self.sensor_list


    def show_speed(self, speed):
        value = int(speed)
        if value != self._last_speed:
            self._speed_surface = self.speed_font.render(f'{value} km/h', True, (255, 255, 255))
            self._last_speed = value
        self.display.blit(self._speed_surface, (2800, 600))


    def render(self, speed=0, present=True):
        # 渲染没有打开，就返回空值,然后啥也不做
        if not self.render_enabled():
            return
        started = time.perf_counter()
        if self._last_render is not None:
            runtime.observe('display_interval_ms', (started - self._last_render) * 1000)
        self._last_render = started
        # s就是传感器
        for s in self.sensor_list:
            # 激发传感器渲染图像
            s.render()

        # 将具有透明度的图片渲染到窗口上
        self.display.blit(self.transparent_image, (400, 0))  # 你可以调整位置
        self.show_speed(speed)
        # 更新屏幕显示
        if present:
            pygame.display.flip()
        runtime.observe('display_work_ms', (time.perf_counter() - started) * 1000)





    #   清除传感器
    def destroy(self):
        errors = []
        for s in self.sensor_list:
            try:
                s.destroy()
            except Exception as exc:
                errors.append(str(exc))
        self.sensor_list.clear()
        if errors:
            raise RuntimeError('Camera cleanup: ' + '; '.join(errors))

    # 输出一个布尔值，display为none时，为False，表示别传感器渲染
    def render_enabled(self):
        return self.display != None


# 传感器控制器
# 输入世界、显示器、显示器位置、以及一个sensor生成的基本信息
class SensorManager:
    """回调只保留最新帧，所有 Pygame 图像转换都在显示线程执行。"""
    def __init__(self, world, display_man, sensor_type, transform, attached,
                 sensor_options, display_pos, Sp_flag):
        self.world, self.display_man = world, display_man
        self.display_pos, self.Sp_flag = display_pos, Sp_flag
        self.sensor_options = dict(sensor_options)
        self.surface = None
        self._pending = None
        self._frame_lock = threading.Lock()
        self._closed = False
        self._last_received = None
        self._last_frame = -1
        self.sensor_type = sensor_type
        self.is_mirror = abs(transform.rotation.yaw) > 90
        self.mirror = self.sensor_options.pop('mirror', self.is_mirror)
        if isinstance(self.mirror, str):
            self.mirror = self.mirror.lower() == 'true'
        self.target_size = tuple(Sp_flag[1] if Sp_flag else display_man.get_display_size())
        self.metric_name = 'camera_' + str(display_pos)
        self.sensor = self.init_sensor(sensor_type, transform, attached, self.sensor_options)
        display_man.add_sensor(self)

    def init_sensor(self, sensor_type, transform, attached, sensor_options):
        types = {'RGBCamera': 'sensor.camera.rgb', 'SS': 'sensor.camera.semantic_segmentation',
                 'IS': 'sensor.camera.instance_segmentation'}
        if sensor_type not in types:
            raise ValueError('Unsupported camera: ' + sensor_type)
        bp = self.world.get_blueprint_library().find(types[sensor_type])
        # 标注相机保持原尺寸；RGB 可按档位缩放，显示区域大小始终不变。
        size, interval = camera_settings(self.target_size, self.is_mirror)
        if sensor_type != 'RGBCamera':
            size = self.target_size
        defaults = {'image_size_x': str(size[0]), 'image_size_y': str(size[1]),
                    'sensor_tick': str(interval)}
        if sensor_type == 'RGBCamera':
            defaults.update(gamma='2.2', motion_blur_intensity='0.0')
        defaults.update(sensor_options)
        for key, value in defaults.items():
            if bp.has_attribute(key):
                bp.set_attribute(key, str(value))
            else:
                raise ValueError('Camera attribute unavailable: ' + key)
        camera = self.world.spawn_actor(bp, transform, attach_to=attached)
        camera.listen(self.save_rgb_image)
        return camera

    def get_sensor(self):
        return self.sensor

    def save_rgb_image(self, image):
        now = time.perf_counter()
        with self._frame_lock:
            if self._closed or image.frame <= self._last_frame:
                return
            if self._pending is not None:
                runtime.count(self.metric_name + '_superseded')
            if self._last_received is not None:
                runtime.observe(self.metric_name + '_arrival_ms', (now-self._last_received)*1000)
            self._last_received = now
            self._last_frame = image.frame
            self._pending = (image, now)
        runtime.count(self.metric_name + '_received')

    save_SS_image = save_rgb_image
    save_IS_image = save_rgb_image

    def render(self):
        with self._frame_lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            image, arrived = pending
            started = time.perf_counter()
            if self.sensor_type == 'SS':
                image.convert(carla.ColorConverter.CityScapesPalette)
            # CARLA 本来就是 BGRA，无需 NumPy 的两次切片及通道复制。
            surface = pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA').convert()
            if self.mirror:
                surface = pygame.transform.flip(surface, True, False)
            if surface.get_size() != self.target_size:
                surface = pygame.transform.smoothscale(surface, self.target_size)
            self.surface = surface
            runtime.observe(self.metric_name + '_queue_ms', (started-arrived)*1000)
            runtime.observe(self.metric_name + '_convert_ms', (time.perf_counter()-started)*1000)
            runtime.count(self.metric_name + '_displayed')
        if self.surface is not None:
            offset = self.Sp_flag[0] if self.Sp_flag else self.display_man.get_display_offset(self.display_pos)
            self.display_man.display.blit(self.surface, offset)

    def destroy(self):
        with self._frame_lock:
            if self._closed:
                return
            self._closed = True
            self._pending = None
        if self.sensor is not None and self.sensor.is_alive:
            try:
                self.sensor.stop()
            finally:
                if self.sensor.destroy() is False:
                    raise RuntimeError('Camera destroy returned False')
        self.surface = None


def run_simulation(args, client):
    """This function performed one test run using the args parameters
    and connecting to the carla client passed.
    """
    # 初始化场景
    display_manager = None
    vehicle = None
    vehicle_list = []
    timer = CustomTimer()

    try:
        # 获取世界对象和基本设置
        world = client.get_world()
        original_settings = world.get_settings()

        if args.sync:  # 如果有输入的参数
            # 创建一个与Carla服务器交互的TrafficManager对象，并将其连接到本地主机的8000端口。
            traffic_manager = client.get_trafficmanager(8000)
            settings = world.get_settings()
            # 在异步模式下，模拟器的不同组件可以并行执行，每个组件根据其自己的时间步长进行更新。
            # 您可能需要将模拟器设置为同步模式，以便所有组件在每个时间步骤中以固定的顺序和时间间隔进行更新。
            traffic_manager.set_synchronous_mode(True)
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 0.05
            world.apply_settings(settings)

        # 实例化我们安装传感器的车辆
        bp = world.get_blueprint_library().filter('model3')[0]

        # 随机选一个出生点来生成车辆
        vehicle = world.spawn_actor(bp, random.choice(world.get_map().get_spawn_points()))
        # 加入车库
        vehicle_list.append(vehicle)
        # 之前那辆车开启自动驾驶
        vehicle.set_autopilot(True)

        # 显示管理器在一个窗口中组织所有传感器及其显示
        # 它可以很容易地配置网格和总窗口大小
        display_manager = DisplayManager(grid_size=[1, 3], window_size=[args.width, args.height])

        clock = pygame.time.Clock()


        # 前景
        SensorManager(world, display_manager, 'RGBCamera',
                                 carla.Transform(carla.Location(x=2, y=-0.18, z=1.3), carla.Rotation(yaw=+00)),
                                 vehicle, {'fov': '135'}, display_pos=[0, 1], Sp_flag=[[0, 0], [5740, 1010]])
        # 左后视镜
        SensorManager(world, display_manager, 'RGBCamera',
                                 carla.Transform(carla.Location(x=1.5, y=-1, z=1.1), carla.Rotation(yaw=-140)),
                                 vehicle, {}, display_pos=[0, 0], Sp_flag=[[700, 570], [670, 430]])
        # 右后视镜
        SensorManager(world, display_manager, 'RGBCamera',
                                 carla.Transform(carla.Location(x=1.5, y=1, z=1.1), carla.Rotation(yaw=+140)),
                                 vehicle, {}, display_pos=[0, 2], Sp_flag=[[4719, 560], [670, 430]])
        # 正后视镜
        SensorManager(world, display_manager, 'RGBCamera',
                                 carla.Transform(carla.Location(x=-2.2, y=0, z=1.35), carla.Rotation(yaw=+180)),
                                 vehicle, {'fov': '120'}, display_pos=[1, 1], Sp_flag=[[2890, 210], [650, 190]])

        # client.start_recorder('BIG_TRY.log')
        # print(display_manager.get_sensor_list())

        # 仿真循环
        call_exit = False
        time_init_sim = timer.time()
        while True:
            # Carla Tick
            if args.sync:
                world.tick()
            else:
                world.wait_for_tick()
            # Render received data
            display_manager.render()
            clock.tick(60)
            # 这里给出了几种退出的方法（但是没有用）
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    call_exit = True
            if call_exit:
                break

    finally:
        # 如果display_manager还存在，就将其摧毁
        if display_manager:
            display_manager.destroy()
        # 摧毁所有对象Actor
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicle_list])
        # 还原世界设置
        world.apply_settings(original_settings)

        # print("Stop recording")
        # client.stop_recorder()


def main():
    argparser = argparse.ArgumentParser(
        description='CARLA Sensor tutorial')
    argparser.add_argument(
        '--host',
        metavar='H',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        metavar='P',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '--sync',
        action='store_true',
        help='Synchronous mode execution')
    argparser.add_argument(
        '--async',
        dest='sync',
        action='store_false',
        help='Asynchronous mode execution')
    argparser.set_defaults(sync=True)
    argparser.add_argument(
        '--res',
        metavar='WIDTHxHEIGHT',
        default='5740x1010',
        help='window resolution (default: 3600x1200)')

    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split('x')]

    try:
        client = carla.Client(args.host, args.port)
        # 设置超时时间
        client.set_timeout(5.0)

        run_simulation(args, client)

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')


if __name__ == '__main__':
    main()
