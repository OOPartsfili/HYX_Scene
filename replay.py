# -*- coding: utf-8 -*-
"""
Created on Sun Mar 24 14:30:18 2024

@author: Lenovo
"""
from disposition import *
import carla
import argparse
import numpy as np
import pygame
import time
import pandas as pd
import Set_sensor
import scene_runtime as runtime
from optimization_config import ROOT

import os



def get_main_car_id(folder):
    files = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if not files:
        return "文件夹中没有文件。"
    # 获取最新的文件
    latest_file = max(files, key=os.path.getctime)
    df = pd.read_csv(latest_file)
    main_car_id = df['main_car_id'].iloc[0]

    return main_car_id




# 输入文件夹，输出文件夹里最新创建文件的文件名
def get_latest_file(folder):
    try:
        # 获取文件夹中的所有文件
        files = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        if not files:
            return "文件夹中没有文件。"
        # 获取最新的文件
        latest_file = max(files, key=os.path.getctime)
        return os.path.basename(latest_file)
    except Exception as e:
        return str(e)





CFG = dict(
        host="127.0.0.1",
        port=2000,
        start=0.0,
        duration=0.0,
        camera=0,
        time_factor=0.8, #这个是控制快慢程度的
        ignore_hero=False,
        move_spectator=False,
        spawn_sensors=False)

def main():
    latest_file = get_latest_file(str(ROOT / "log_data"))
    recorder_filename = str(ROOT / "log_data" / latest_file)

    client = carla.Client(CFG["host"], CFG["port"])
    client.set_timeout(10.0)

    client.set_replayer_time_factor(CFG["time_factor"])
    client.set_replayer_ignore_hero(CFG["ignore_hero"])
    client.set_replayer_ignore_spectator(not CFG["move_spectator"])

    client.replay_file(
        recorder_filename,
        CFG["start"],
        CFG["duration"],
        CFG["camera"],
        CFG["spawn_sensors"]
    )

    world = client.get_world()

    # 寻找主车
    vehicles = world.get_actors().filter('vehicle.*')
    print(vehicles)

    main_car_id = get_main_car_id(str(ROOT / 'carla_data'))
    vehicle = vehicles.find(int(main_car_id))

    # 初始化pygame
    pygame.init()
    pygame.font.init()

    #pygame_display = pygame.display.set_mode([800, 600], pygame.HWSURFACE | pygame.DOUBLEBUF)
    # rgb_camera = world.try_spawn_actor(rgb_camera_bp, rgb_camera_tf, attach_to=ego_vehicle)

    display_manager = Set_sensor.DisplayManager(grid_size=[1, 3], window_size=[5740, 1010])

    # 前景
    Set_sensor.SensorManager(world, display_manager, 'RGBCamera',
                             carla.Transform(carla.Location(x=1.4, y=-0.18, z=1.04), carla.Rotation(yaw=+00)),
                             vehicle, {'fov': '150'}, display_pos=[0, 1], Sp_flag=[[0, 0], [5740, 1010]])
    # 左后视镜
    Set_sensor.SensorManager(world, display_manager, 'RGBCamera',
                             carla.Transform(carla.Location(x=0.6, y=-1, z=0.9), carla.Rotation(yaw=-140)),
                             vehicle, {}, display_pos=[0, 0], Sp_flag=[[700, 580], [670, 420]])  # 左侧为坐标，右侧为画面长宽
    # 右后视镜
    Set_sensor.SensorManager(world, display_manager, 'RGBCamera',
                             carla.Transform(carla.Location(x=0.6, y=1, z=0.9), carla.Rotation(yaw=+140)),
                             vehicle, {}, display_pos=[0, 2], Sp_flag=[[4719, 570], [655, 415]])
    # 正后视镜
    Set_sensor.SensorManager(world, display_manager, 'RGBCamera',
                             carla.Transform(carla.Location(x=-2.2, y=0, z=1.35), carla.Rotation(yaw=+180)),
                             vehicle, {'fov': '120'}, display_pos=[1, 1], Sp_flag=[[2890, 210], [650, 190]])

    # 设置刷新帧率
    clock = pygame.time.Clock()
    fps = 60

    running = True
    while running:
        # pygame
        # pygame渲染刷新
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        # end of own scripts

        # Render received data
        display_manager.render(speed=get_speed(vehicle))
        clock.tick(fps)


if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.shutdown()
        pygame.quit()
        print('\ndone.')
