"""驾驶练习入口。使用 config01 的起点和与正式场景相同的键盘输入。"""
import time
import pygame
from vehicle_method import *
from config01 import main_vehicle_location, dict_index
from Scene1_01 import Window
from scene_setup import setup_scene
from optimization_config import ROOT
import scene_runtime as runtime
import Set_info

if __name__ == '__main__':
    try:
        destroy_all_vehicles_traffics()
        main_vehicle = create_actor(main_vehicle_location, model='vehicle.tesla.model3', role_name='hero')
        environment = setup_scene(client, main_vehicle)
        info = Set_info.Info(dict_index, Set_info.dict_0, str(ROOT/'carla_data'/f'practice_{int(time.time())}.csv'))
        info.car_list = [main_vehicle]
        info.get_info()
        window = Window(main_vehicle, world, info)
        controller = Vehicle_Control(main_vehicle)
        controller.autopilot_speed_limit = 30
        controller.follow_lane()
        while not runtime.STOP.is_set():
            steer, throttle, brake = get_steering_wheel_info()
            if brake > .5 or abs(steer) >= .1:
                info.Handchange_flag = 1
                controller.autopilot_flag = False
            sleep(.05)
    except (runtime.SceneStopped, KeyboardInterrupt):
        pass
    finally:
        runtime.shutdown()
        pygame.quit()
