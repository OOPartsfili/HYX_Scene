import carla

from disposition import *
from config01 import stage1_location as TOR_location01
from types import SimpleNamespace

# from sensor.steering_angle import parse_euler, get_steering_angle
# from sensor.pedal import get_data,pedal_receiver

"""
以下是远程调试-实际实验 中调试代码的切换教程

每次修改代码记得保存

远程调试模式：
1、Vehicle_Control的follow_lane()方法中，steer, throttle,brake  = get_sensor_data() 这个函数注释掉
2、场景对应两个线程脚本取消注释，listen_for_takeover()这里监听操作的函数修改
3、本函数上面两个from 注释掉
4、get_info里数据收集的函数也改为get_steering_wheel_info()
5、DRAW画线的已经全部注释了，要改就取消注释

实际实验模式：
1、Vehicle_Control的follow_lane()方法中，steer, throttle,brake  = get_sensor_data() 这个函数打开
3、上面两个from 打开
4、get_info里数据收集的函数修改

"""



# 添加一个全局变量来存储上一次的传感器数据
last_sensor_data = {
    'steer': 0,
    'throttle': 0,
    'brake': 0
}


# def get_sensor_data():
#     K1 = 0.25
#     steer = get_steering_angle() / 550
#     steerCmd = K1 * math.tan(1.1 * steer)
#     acc,brake = get_data()
#     acc /= 1.2
#     brake *= 2.3
#     if brake > 1:
#         brake = 1
#     if acc > 0.2:
#         brake =0
#     return  steerCmd, acc, brake



# 场景共用的物理控车实现。
from optimized_control import Vehicle_Control, Ramp_Vice_Control, shared_view
import scene_runtime as runtime


def pedestrian_control(people, speed=8, yaw=0, target_location=None):
    def con():
        people_control = carla.WalkerControl(speed=speed / 3.6)
        people_rotation = carla.Rotation(0, yaw, 0)
        people_control.direction = people_rotation.get_forward_vector()
        people.apply_control(people_control)

        if target_location:
            while True:
                if people.get_location().distance(target_location) < 2:
                    control = carla.WalkerControl()
                    control.direction.x = 0
                    control.direction.z = 0
                    control.direction.y = 0
                    people.apply_control(control)
                    break
                sleep(0.01)

    threading.Thread(target=con).start()


def create_actor(locations, model="vehicle.mini.cooper_s_2021", height=0.1, role_name='scenario'):
    def create(location):
        waypoint = env_map.get_waypoint(location)
        if waypoint is None:
            raise RuntimeError(f'No driving waypoint at {location}')
        transform = waypoint.transform
        transform.location.z += height
        models = blueprint_library.filter(model)
        if not models:
            raise RuntimeError(f'No vehicle blueprint matches {model}')
        blueprint = random.choice(models)
        blueprint.set_attribute('role_name', role_name)
        actor = world.try_spawn_actor(blueprint, transform)
        if actor is None:
            raise RuntimeError(f'Cannot spawn {model} at {transform.location}; check occupied spawn point')
        runtime.register(actor, 'destroy')
        return actor
    return [create(location) for location in locations] if isinstance(locations, list) else create(locations)


# 控制车辆刹车
def brake_throttle_retard(vehicle, acceleration, target_speed):
    """
    加减速
    :param vehicle: 目标车辆
    :param acceleration: 加速度
    :param target_speed: 目标速度
    :return:
    """
    pid = VehiclePIDController(vehicle, args_lateral=args_lateral_dict, args_longitudinal=args_long_dict)
    t = time.time()
    speed = get_speed(vehicle)
    while abs(get_speed(vehicle) - target_speed) > 1:
        # 获取前方道路
        waypoint = env_map.get_waypoint(vehicle.get_location()).next(max(1, int(get_speed(vehicle) / 6)))
        if waypoint:
            waypoint = waypoint[0]
        else:
            print(f"前方没有路了,当前车子坐标{vehicle.get_location()},车子对象为{vehicle}")
            return
        result = pid.run_step(target_speed, waypoint)
        result.brake = 0
        result.throttle = 0
        vehicle.apply_control(result)  # 这个只控制方向盘

        sp = (max(0, speed + acceleration * (time.time() - t) * 3.6))
        set_speed(vehicle, sp)
        sleep(0.01)
    for _ in range(10):
        set_speed(vehicle, target_speed)
        sleep(0.1)


def load_map(xodr_path):
    """
    导入地图
    :param xodr_path :  xodr文件路径
    """
    with open(xodr_path, encoding="utf-8") as f:
        data = f.read()
        vertex_distance = 1
        max_road_length = 500
        wall_height = 0.5
        extra_width = 1
        client.generate_opendrive_world(data,
                                        carla.OpendriveGenerationParameters(vertex_distance=vertex_distance,
                                                                            max_road_length=max_road_length,
                                                                            wall_height=wall_height,
                                                                            additional_width=extra_width,
                                                                            smooth_junctions=True, enable_mesh_visibility=True))


# 获取当前车道的车辆，返回升序车辆列表
def get_now_road_car(vehicle, next_vehicle=False, previous_vehicle=False):
    front = True if next_vehicle else False if previous_vehicle else None
    return shared_view(world).nearby(vehicle, front=front)


def timed_function(interval, stop_event):
    """
    在函数上加上一下内容就可以实现定时器
    stop_event = threading.Event()  # 用于停止定时器，执行stop_event.set()就可以停止该定时器
    @timed_function(interval=0.01, stop_event=stop_event)
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 定义定时器回调函数
            def timer_callback():
                func(*args, **kwargs)
                # 递归调用定时器，实现周期性执行
                if not stop_event.is_set():
                    threading.Timer(interval, timer_callback).start()

            # 启动定时器
            threading.Timer(interval, timer_callback).start()

        return wrapper

    return decorator



def get_vehicle_steer(vehicle):
    """
    获取carla中车子方向盘值
    :param vehicle: 车子对象
    :return:
    """
    return vehicle.get_control().steer


def get_vehicle_length(vehicle):
    """
    获取车子的长度
    :param vehicle: 车子对象
    :return: 返回车子的长宽高
    """
    car_length = vehicle.bounding_box.extent
    return car_length.x * 2, car_length.y * 2, car_length.z * 2


def draw_line(location1=None, location2=None, locations=None, thickness=0.1, life_time=10.0, color=carla.Color(255, 0, 0)):
    """
    用直线连接两个点或者多个点
    :param location1: carla坐标点1
    :param location2: carla坐标点2
    :param locations: 坐标点列表，如果传入坐标点列表，前面两个点失效,carla坐标点列表
    :param thickness: 亮度
    :param life_time: 存活时间
    :param color: 颜色
    :return: 没有返回，绘制出连线点
    """
    if locations:
        for index, location in enumerate(locations[1:]):
            world.debug.draw_line(locations[index], location, thickness=thickness, color=color, life_time=life_time)
        return
    world.debug.draw_line(location1, location2, thickness=thickness, color=color, life_time=life_time)


def set_speed(vehicle, speed_kmh):
    """
    强制设置车子速度
    :param vehicle: 车子对象
    :param speed_kmh: 车子速度
    :return:
    """
    speed = speed_kmh / 3.6
    # 获取车辆的当前速度方向
    forward_vector = vehicle.get_transform().rotation.get_forward_vector()
    # 设置车子速度
    vehicle.set_target_velocity(carla.Vector3D(forward_vector.x * speed, forward_vector.y * speed, forward_vector.z * speed))


def draw_arrow(locations, distance=10, height=1):
    """
    绘制起点专用的，绘制世界中箭头，一直存在的
    :param locations: carla.Location列表
    :param distance: 箭头绘制的距离
    :param height: 绘制的高度
    """
    debug = world.debug
    for location in locations:
        arrow_location = location + carla.Location(z=height)  # 假设箭头位置略高于地面
        target_location = env_map.get_waypoint(arrow_location).next(distance)[0].transform.location
        target_location.z += height
        # 绘制箭头
        debug.draw_arrow(arrow_location, target_location, thickness=0.3, arrow_size=0.5, color=carla.Color(255, 0, 0))

#
# def get_steering_wheel_info():
#     """
#     return: 方向盘、刹车、油门
#     """
#     # 这里0,2,3根据实际情况的方向盘参数
#     return joystick.get_axis(0),  (-joystick.get_axis(1) + 1)/2, (-joystick.get_axis(2) + 1) / 2 


def get_steering_wheel_info():
    keys = pygame.key.get_pressed()
    throttle, brake, steer = (0, 0, 0)

    if keys[pygame.K_UP] or keys[pygame.K_w]:
        throttle = 1.0
    if keys[pygame.K_DOWN] or keys[pygame.K_s]:
        brake = 1.0
    if keys[pygame.K_LEFT] or keys[pygame.K_a]:
        steer = -0.5
    if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
        steer = 0.5
    return steer, throttle, brake


def destroy_all_vehicles_traffics(vehicle_flag=True, traffic_flag=False, people_flag=True, sensor_flag=True):
    """
    销毁世界中的所有车辆，交通标志，行人和传感器
    :param vehicle_flag: 是否销毁车辆，默认销毁
    :param traffic_flag: 是否销毁交通标志，默认销毁
    :param people_flag: 是否销毁行人，默认销毁
    :param sensor_flag: 是否销毁传感器，默认销毁
    :return:
    """
    actors = []
    if vehicle_flag:
        actors += list(world.get_actors().filter('*vehicle*'))
    if traffic_flag:
        actors += list(world.get_actors().filter("*prop*"))
    if people_flag:
        actors += list(world.get_actors().filter("*walker*"))
    if sensor_flag:
        actors += list(world.get_actors().filter("*sensor*"))

    # 销毁每个物体
    for actor in actors:
        actor.destroy()



