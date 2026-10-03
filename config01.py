import carla


# 主车坐标
main_vehicle_location = carla.Location(x=693.00, y=-637)


stage1_location = carla.Location(x=693.00, y=-537) # 紧急接管发起点

stage2_location = carla.Location(x=693.00, y=-437) # 紧急接管发起点

stage3_location = carla.Location(x=693.00, y=-337) # 紧急接管发起点


# 接管终点
# 十字路口终点坐标
start_location = carla.Location(x=691.00, y=-237, z=9.5)
end_location = carla.Location(x=695.00, y=-237, z=9.5)


# 数据记录信息
dict_index = {
    0: "main_car",
    1: "Car1",
    2: "Car2",
    3: "Car3",
    4: "Car4",
    5: "Car5",
    6: "Car6",
    7: "Car7",
    8: "Car8",
    9: "Car9"
}


file_name1 = 'carla_data/data01.csv'
file_name2 = 'carla_data/data01_ARHUD.csv'


