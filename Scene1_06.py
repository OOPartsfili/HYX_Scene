from vehicle_method import *
from config01 import*
import Set_sensor
import Set_request
import Set_taskpoint
import Set_info
import time
import random
import scene_runtime as runtime
from scene_setup import setup_scene
from optimization_config import ROOT


"""
保守决策
大车遮挡
前车急刹

"""

# 新的页面窗口
class Window:
    def __init__(self, vehicle, world, info):
        self.world = world
        self.vehicle = vehicle
        self.SCREEN_WIDTH, self.SCREEN_HEIGHT = 5740, 1010  # 屏幕大小
        self.clock = pygame.time.Clock()
        self.fps = 60  # 帧率
        self.info = info
        self.Process_flag = True

        self.Process = threading.Thread(target=self.show_screen)
        runtime.register(self)
        self.Process.start()

    def show_screen(self):  # 显示窗口
        try:
            # 创建窗口
            self.display_manager = Set_sensor.DisplayManager(grid_size=[1, 3],
                                                             window_size=[self.SCREEN_WIDTH, self.SCREEN_HEIGHT])
    
            # 前景
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=1.4, y=-0.18, z=1.04), carla.Rotation(yaw=+00)),
                                     self.vehicle, {'fov': '150'}, display_pos=[0, 1], Sp_flag=[[0, 0], [5740, 1010]])
            # 左后视镜
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=0.6, y=-1, z=0.9), carla.Rotation(yaw=-140)),
                                     self.vehicle, {}, display_pos=[0, 0], Sp_flag=[[700, 580], [670, 420]])  # 左侧为坐标，右侧为画面长宽
            # 右后视镜
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=0.6, y=1, z=0.9), carla.Rotation(yaw=+140)),
                                     self.vehicle, {}, display_pos=[0, 2], Sp_flag=[[4719, 570], [655, 415]])
            # 正后视镜
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=-2.2, y=0, z=1.35), carla.Rotation(yaw=+180)),
                                     self.vehicle, {'fov': '120'}, display_pos=[1, 1], Sp_flag=[[2890, 210], [650, 190]])
    
            while self.Process_flag and not runtime.STOP.is_set():
                # screen.fill((0, 0, 0))  # 使用黑色清除屏幕
                self.display_manager.render(speed=get_speed(self.vehicle))
    
                self.clock.tick(self.fps)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:  # 窗口关闭
                        self.Process_flag = False
                        runtime.request_stop()
                        break
        except Exception as exc:
            runtime.metadata(display_error=str(exc))
            print('Display stopped:', exc)
            runtime.request_stop()
        finally:
            self.Process_flag = False

    def stop(self):
        self.Process_flag = False
        if self.Process is not threading.current_thread():
            self.Process.join(timeout=3)
            if self.Process.is_alive():
                raise RuntimeError('Display thread has not stopped')


if __name__ == '__main__':
    try:
        destroy_all_vehicles_traffics()
        log_filename = 'Scene_1_06'
        carla_data_filename = 'carla_data/Scene_1_06'

        Set_request.BGM_requset()
        # threading.Thread(target=pedal_receiver).start()
        # threading.Thread(target=parse_euler, daemon=True).start()


        # 主车、路障车坐标在config中

        # 获取副车的位置
        Car1 = env_map.get_waypoint(main_vehicle_location).get_left_lane().previous(20)[0].transform.location  # 左侧车

        Car2 = env_map.get_waypoint(main_vehicle_location).next(40)[0].transform.location # 前车

        Car3 = env_map.get_waypoint(main_vehicle_location).get_right_lane().previous(15)[0].transform.location # 大车

        Car4 = env_map.get_waypoint(main_vehicle_location).get_right_lane().get_right_lane().previous(11)[0].transform.location    # 摩托车
      


        # 生成交互车s
        V_Car1 = create_actor(Car1, model="vehicle.audi.tt")
        V_Car2 = create_actor(Car2, model="vehicle.audi.tt")
        V_Car3 = create_actor(Car3, model="vehicle.carlamotors.firetruck")
        V_Car4 = create_actor(Car4, model="vehicle.kawasaki.ninja")



        # 主车生成
        main_vehicle = create_actor(main_vehicle_location, model="vehicle.tesla.model3", role_name="hero")
        scene_environment = setup_scene(client, main_vehicle)


        # 数据采集文件名
        time_now = str(int(time.time()))
        file_name1 = carla_data_filename + '_' + time_now + '.csv'


        # 信息收集
        info = Set_info.Info(dict_index, Set_info.dict_0, file_name1)
        info.car_list =  [main_vehicle,V_Car1,V_Car2,V_Car3,V_Car4]
        info.get_info()


        # 主车窗口
        window = Window(main_vehicle, world, info)
        # sleep(10)
        # 配置碰撞传感器
        collision_sensor = world.spawn_actor(blueprint_library.find('sensor.other.collision'),
                                             carla.Transform(carla.Location(x=1.0, z=2.5)), attach_to=main_vehicle)
        
        # 添加碰撞音效标志，确保只播放一次
        collision_sound_played = False
        
        def on_collision(event):
            global collision_sound_played
            other_actor = event.other_actor
            if 'vehicle' in other_actor.type_id and not collision_sound_played:
                info.Collision_flag = other_actor.id
                Set_request.BOOM_requset()
                collision_sound_played = True
                print("碰撞发生，播放碰撞音效")
                # 停止碰撞传感器监听，结束碰撞检测线程
                collision_sensor.stop()
                return

        runtime.register(collision_sensor, 'destroy')
        collision_sensor.listen(on_collision)  # 监听碰撞事件



        # # ==== 周边随机车添加 ====
        # main_wp = env_map.get_waypoint(main_vehicle_location)

        # bg_locations = [
        #     main_wp.get_left_lane().next(30)[0].transform.location,     # 左侧前方30m
        #     main_wp.get_left_lane().previous(50)[0].transform.location, # 左侧后方20m
        #     main_wp.next(40)[0].transform.location,                     # 正前方30m
        #     main_wp.get_right_lane().previous(30)[0].transform.location, # 右侧后方30m
        #     main_wp.get_right_lane().next(50)[0].transform.location     # 右侧前方50m
        # ]
        # # ==== 创建车辆并启用自动驾驶 ====
        # bg_cars = []
        # for loc in bg_locations:
        #     car = create_actor(loc, model="vehicle.audi.tt")
        #     bg_cars.append(car)
        # # ==== （可选）设置自动驾驶速度与行为 ====
        # for car in bg_cars:
        #     control =  Ramp_Vice_Control(car)
        #     control.speed_limit = 50
        #     control.follow_road()
        # info.car_list.extend(bg_cars)


        # 主车初始化控制
        vehicle_control = Vehicle_Control(main_vehicle)
        vehicle_control.autopilot_speed_limit = 50
        vehicle_control.follow_lane()
        # vehicle_control.lane_offset = 1.15

        # 副车初始化控制
        vice_control1 = Ramp_Vice_Control(V_Car1, behavior="scripted")
        vice_control1.speed_limit = 50
        vice_control1.follow_road()

        vice_control2 = Ramp_Vice_Control(V_Car2, behavior="scripted")
        vice_control2.speed_limit = 50
        vice_control2.follow_road()

        vice_control3 = Ramp_Vice_Control(V_Car3, behavior="scripted")
        vice_control3.speed_limit = 50
        vice_control3.follow_road()

        vice_control4 = Ramp_Vice_Control(V_Car4, behavior="scripted")
        vice_control4.speed_limit = 50
        vice_control4.follow_road()


        # 开始记录回放日志
        client.start_recorder(str(ROOT / "log_data" / f"{log_filename}_{time_now}.log"))
        print('start_recorder')


        # 设置主动干预监听线程
        def listen_for_takeover():
            global info
            while not runtime.STOP.is_set():
                # steerCmd, acc, brake = get_sensor_data()
                steerCmd, acc, brake = get_steering_wheel_info()
                if brake >= 0.5 or steerCmd >= 0.1 or steerCmd <= -0.1 or acc >= 0.5: #方向盘数值得看下
                    info.Handchange_flag = 1
                    vehicle_control.autopilot_flag = False
                    print("切换成功！")
                    break
                time.sleep(0.05)  # 防止CPU占用过高

        listener_thread = threading.Thread(target=listen_for_takeover, daemon=True)
        runtime.register_thread(listener_thread)
        listener_thread.start()




        # 第一阶段起点
        while main_vehicle.get_location().y < stage1_location.y :
            sleep(0.01)
        print('stage1 开始')
        info.stage_flag = 1

        vice_control2.speed_limit = 33  # 前车减速
        vehicle_control.autopilot_speed_limit = 40  # 主车也减速

        vice_control3.speed_limit = 53  # 大车微微加速
        vice_control4.speed_limit = 53.5  # 摩托微微加速

        
        # 第二阶段起点
        while main_vehicle.get_location().y < stage2_location.y :
            sleep(0.01)
        print('stage2 开始')
        info.stage_flag = 2

        vice_control1.speed_limit = 60  # 左车前冲
        vice_control2.speed_limit = 62  # 前车前冲
        vehicle_control.autopilot_speed_limit = 50 #主车恢复

        vice_control3.speed_limit = 48 #大车慢慢减速
        vice_control4.speed_limit = 52 #摩托准备冲出



        # 第三阶段起点
        while main_vehicle.get_location().y < stage3_location.y :
            sleep(0.01)
        print('stage3 开始')
        info.stage_flag = 3 

        vice_control2.speed_limit = 10
        sleep(2)
        vehicle_control.right_left_lane(direction='left')






        # 绘制接管终点线
        Set_taskpoint.draw_arrow_example(world, start_location, end_location)


        # 超过终点线，场景结束
        while main_vehicle.get_location().y < start_location.y:
            sleep(0.01)
        print("已到达终点线，场景结束")
        pygame.event.post(pygame.event.Event(pygame.QUIT))



        # 保证线程不会瞬间消失，导致数据丢失
        while True:
            sleep(1)

    except (runtime.SceneStopped, KeyboardInterrupt):
        pass
    finally:
        runtime.shutdown()
        pygame.quit()
