from vehicle_method import *
from config02 import*
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
更新版本

新增车内图片、语言接管提示

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
                                     carla.Transform(carla.Location(x=2, y=-0.18, z=1.3), carla.Rotation(yaw=+00)),
                                     self.vehicle, {'fov': '150'}, display_pos=[0, 1], Sp_flag=[[0, 0], [5740, 1010]])
            # 左后视镜
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=1.5, y=-1, z=1.1), carla.Rotation(yaw=-140)),
                                     self.vehicle, {}, display_pos=[0, 0], Sp_flag=[[700, 430], [670, 390]])
            # 右后视镜
            Set_sensor.SensorManager(world, self.display_manager, 'RGBCamera',
                                     carla.Transform(carla.Location(x=1.5, y=1, z=1.1), carla.Rotation(yaw=+140)),
                                     self.vehicle, {}, display_pos=[0, 2], Sp_flag=[[4719, 420], [670, 385]])
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
        log_filename = 'Scene_2_01'
        carla_data_filename = 'carla_data/Scene_2_01'

        # threading.Thread(target=pedal_receiver).start()
        # threading.Thread(target=parse_euler, daemon=True).start()


        # 主车、路障车坐标在config中

        # 获取副车的位置
        Car1 = right_vehicle_location  # 一号风险源

        Car2 =env_map.get_waypoint(main_vehicle_location).get_left_lane().next(190)[0].transform.location  # 二号风险源（两辆静止车）
        Car2_2 = env_map.get_waypoint(main_vehicle_location).next(185)[0].transform.location  # 二号风险源（两辆静止车）

        Car3 = env_map.get_waypoint(main_vehicle_location).previous(40)[0].transform.location # 三号风险源（后车）
      
        Car4 = env_map.get_waypoint(main_vehicle_location).next(40)[0].transform.location    # 线索


        # 生成交互车s
        V_Car1 = create_actor(Car1, model="vehicle.kawasaki.ninja")
        V_Car2 = create_actor(Car2, model="vehicle.audi.tt")
        V_Car2_2 = create_actor(Car2_2, model="vehicle.audi.tt")
        V_Car3 = create_actor(Car3, model="vehicle.audi.tt")
        V_Car4 = create_actor(Car4, model="vehicle.audi.tt")

       

        # 主车生成
        main_vehicle = create_actor(main_vehicle_location, model="vehicle.tesla.model3", role_name="hero")
        scene_environment = setup_scene(client, main_vehicle)


        # 数据采集文件名
        time_now = str(int(time.time()))
        file_name1 = carla_data_filename + '_' + time_now + '.csv'



        # 信息收集
        info = Set_info.Info(dict_index, Set_info.dict_0, file_name1)
        info.car_list =  [main_vehicle,V_Car1,V_Car2,V_Car3,V_Car4,V_Car2_2]
        info.get_info()


        # 主车窗口
        window = Window(main_vehicle, world, info)
        # 配置碰撞传感器
        collision_sensor = world.spawn_actor(blueprint_library.find('sensor.other.collision'),
                                             carla.Transform(carla.Location(x=1.0, z=2.5)), attach_to=main_vehicle)
        def on_collision(event):
            other_actor = event.other_actor
            if 'vehicle' in other_actor.type_id:
                info.Collision_flag = other_actor.id

        runtime.register(collision_sensor, 'destroy')
        collision_sensor.listen(on_collision)  # 监听碰撞事件



        # 生成背景车





        # 主车初始化控制
        vehicle_control = Vehicle_Control(main_vehicle)
        vehicle_control.autopilot_speed_limit = 50.01
        vehicle_control.follow_lane()

        # 副车初始化控制（二号风险源不用动）
        vice_control1 = Ramp_Vice_Control(V_Car1, behavior="scripted")
        vice_control1.speed_limit = 0
        vice_control1.follow_road()



        vice_control3 = Ramp_Vice_Control(V_Car3, behavior="scripted") #后车
        vice_control3.follow_car(lead_vehicle=main_vehicle, reaction_time=0.8, min_distance=0.5)

        vice_control4 = Ramp_Vice_Control(V_Car4, behavior="scripted") #线索
        vice_control4.speed_limit = 50
        vice_control4.follow_road()




        # 时间节点1：TOR发出，旁车开始侧向压迫
        while main_vehicle.get_location().distance(TOR_location) > 5:  # 使用5米作为触发距离阈值
            sleep(0.01)

        # 接管切换监听线程
        def listen_for_takeover():
            global info
            while not runtime.STOP.is_set():
                # steerCmd, acc, brake = get_sensor_data()
                steerCmd, acc, brake = get_steering_wheel_info()
                # print(brake)
                if brake >= 0.5 or steerCmd >= 0.1 or steerCmd <= -0.1 or acc >= 0.5: #方向盘数值得看下
                    info.Handchange_flag = 1
                    vehicle_control.autopilot_flag = False
                    print("切换成功！")
                    break
                time.sleep(0.01)  # 防止CPU占用过高


        listener_thread = threading.Thread(target=listen_for_takeover, daemon=True)
        runtime.register_thread(listener_thread)
        listener_thread.start()


        # 发出接管提示音
        Set_request.Video_requset()
        client.start_recorder(str(ROOT / "log_data" / f"{log_filename}_{time_now}.log")) # 记录日志
        info.TOR_flag = 1 # 代表接管提示已发出
        print('start_recorder')
        print("请接管")


      

        # 时间节点1
        while main_vehicle.get_location().x > TOR_location.x-5 :
            sleep(0.01)
        # 接管后，风险源1开始启动cut-in线程
        vice_control1.speed_limit = 45
        vice_control4.speed_limit = 25


        while main_vehicle.get_location().x > TOR_location.x - 35:
            sleep(0.01)
        vice_control4.right_left_lane(direction="right",line_number=1)

        vice_control4.speed_limit = 50
        

        # 绘制接管终点线
        Set_taskpoint.draw_arrow_example(world, start_location, end_location)
        # 时间节点3：超过终点线，场景结束
        while main_vehicle.get_location().x > start_location.x:
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
