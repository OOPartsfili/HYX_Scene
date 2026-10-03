# -*- coding: utf-8 -*-
"""
Created on Sun Mar 24 14:30:18 2024
@author: Lenovo
"""

from disposition import *  # 你的 get_speed 等函数在这里
import carla
import numpy as np
import pygame
import time
import pandas as pd
import Set_sensor
import scene_runtime as runtime
from optimization_config import ROOT
import os
import re
from pathlib import Path
from datetime import datetime


def get_main_car_id(folder):
    files = [os.path.join(folder, f) for f in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, f))]
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    df = pd.read_csv(latest_file)
    main_car_id = df['main_car_id'].iloc[0]
    return main_car_id


def get_latest_file(folder):
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f))]
        if not files:
            return None
        latest_file = max(files, key=os.path.getctime)
        return os.path.basename(latest_file)
    except Exception:
        return None


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def get_total_duration_from_recorder_info(client: carla.Client, recorder_filename: str):
    """
    尝试从 CARLA recorder info 中解析总时长（秒）。
    如果解析失败，返回 None。
    """
    try:
        info = client.show_recorder_file_info(recorder_filename, False)
        # 常见输出里会有 "Duration: 12.34" 或类似字段；这里做宽松匹配
        m = re.search(r"Duration\s*:\s*([0-9]+(?:\.[0-9]+)?)", info)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


CFG = dict(
    host="127.0.0.1",
    port=2000,
    start=0.0,
    duration=0.0,          # 0 表示回放到文件结束（会尝试从文件信息推断总时长）
    camera=0,
    time_factor=0.8,       # 控制回放快慢
    ignore_hero=False,
    move_spectator=False,
    spawn_sensors=False,
)

SCORE_CFG = dict(
    initial_score=5,       # 初始分（你可改成 0）
    min_score=0,
    max_score=10,
    step=1,
    key_minus=pygame.K_a,  # A 扣分
    key_plus=pygame.K_d,   # D 加分
)


def main():
    # 1) 取最新 log 文件
    latest_file = get_latest_file(str(ROOT / "log_data"))
    if not latest_file:
        print("log_data 文件夹中没有可用 log 文件")
        return

    recorder_filename = str((ROOT / "log_data") / latest_file)

    # 2) 启动回放
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

    # 3) 找主车
    vehicles = world.get_actors().filter('vehicle.*')
    main_car_id = get_main_car_id(str(ROOT / 'carla_data'))
    if main_car_id is None:
        print("carla_data 文件夹中没有可用主车ID文件")
        return

    vehicle = vehicles.find(int(main_car_id))
    if vehicle is None:
        print(f"未找到主车 actor_id={main_car_id}")
        return

    # 4) 初始化 pygame
    pygame.init()
    pygame.font.init()

    # DisplayManager 可能会自行 set_mode；这里确保有窗口 surface（用于评分可视化叠加）
    window_size = (5740, 1010)
    screen = pygame.display.get_surface()
    if screen is None:
        pygame.display.set_mode(window_size, pygame.HWSURFACE | pygame.DOUBLEBUF)
        screen = pygame.display.get_surface()

    pygame.display.set_caption("Replay + Scoring (A:-1, D:+1)")

    # 5) 传感器/显示
    display_manager = Set_sensor.DisplayManager(grid_size=[1, 3], window_size=[5740, 1010])

    # 前景
    Set_sensor.SensorManager(
        world, display_manager, 'RGBCamera',
        carla.Transform(carla.Location(x=1.4, y=-0.18, z=1.04), carla.Rotation(yaw=+00)),
        vehicle, {'fov': '150'}, display_pos=[0, 1], Sp_flag=[[0, 0], [5740, 1010]]
    )
    # 左后视镜
    Set_sensor.SensorManager(
        world, display_manager, 'RGBCamera',
        carla.Transform(carla.Location(x=0.6, y=-1, z=0.9), carla.Rotation(yaw=-140)),
        vehicle, {}, display_pos=[0, 0], Sp_flag=[[700, 580], [670, 420]]
    )
    # 右后视镜
    Set_sensor.SensorManager(
        world, display_manager, 'RGBCamera',
        carla.Transform(carla.Location(x=0.6, y=1, z=0.9), carla.Rotation(yaw=+140)),
        vehicle, {}, display_pos=[0, 2], Sp_flag=[[4719, 570], [655, 415]]
    )
    # 正后视镜
    Set_sensor.SensorManager(
        world, display_manager, 'RGBCamera',
        carla.Transform(carla.Location(x=-2.2, y=0, z=1.35), carla.Rotation(yaw=+180)),
        vehicle, {'fov': '120'}, display_pos=[1, 1], Sp_flag=[[2890, 210], [650, 190]]
    )

    # 6) 回放结束判定：优先用 CFG["duration"]；否则尽力从 recorder info 推断
    if CFG["duration"] > 0.0:
        replay_sim_duration = CFG["duration"]
    else:
        total_dur = get_total_duration_from_recorder_info(client, recorder_filename)
        replay_sim_duration = None if total_dur is None else max(0.0, total_dur - CFG["start"])

    # 7) 评分记录
    score = int(SCORE_CFG["initial_score"])
    score = clamp(score, SCORE_CFG["min_score"], SCORE_CFG["max_score"])

    # 记录每次按键事件（含 sim_time、delta、score）
    score_events = []
    # 也记录一个起始点
    score_events.append(dict(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        sim_time=0.0,
        action="INIT",
        delta=0,
        score=score,
        log_file=latest_file
    ))

    # 8) 简单可视化：文字 + 进度条
    font = pygame.font.SysFont("Consolas", 40)
    small_font = pygame.font.SysFont("Consolas", 28)

    def draw_score_overlay(sim_elapsed, speed):
        # 取 surface（DisplayManager 可能在内部重建 surface，所以每帧取一次）
        surf = pygame.display.get_surface()
        if surf is None:
            return

        # 文本块背景（半透明风格：用实色矩形即可）
        overlay_rect = pygame.Rect(1520, 20, 520, 200)
        pygame.draw.rect(surf, (0, 0, 0), overlay_rect)

        title = font.render(f"Want to Takeover {score:02d}", True, (255, 255, 255))
        surf.blit(title, (1540, 35))

        hint = small_font.render("A: -1   D: +1   (0~10)", True, (255, 255, 255))
        surf.blit(hint, (1540, 85))


        # 进度条（如果能推断回放总时长）
        if replay_sim_duration is not None and replay_sim_duration > 0:
            bar_x, bar_y, bar_w, bar_h = 1520, 230, 520, 18
            pygame.draw.rect(surf, (80, 80, 80), pygame.Rect(bar_x, bar_y, bar_w, bar_h))
            p = clamp(sim_elapsed / replay_sim_duration, 0.0, 1.0)
            pygame.draw.rect(surf, (255, 255, 255), pygame.Rect(bar_x, bar_y, int(bar_w * p), bar_h))

    # 9) 主循环
    clock = pygame.time.Clock()
    fps = 60

    # 用 CARLA snapshot 的 elapsed_seconds 作为“仿真时间轴”
    first_snap = world.get_snapshot()
    t0 = first_snap.timestamp.elapsed_seconds

    running = True
    while running:
        # 事件处理（评分按键）
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == SCORE_CFG["key_minus"]:
                    new_score = clamp(score - SCORE_CFG["step"], SCORE_CFG["min_score"], SCORE_CFG["max_score"])
                    delta = new_score - score
                    if delta != 0:
                        score = new_score
                        snap = world.get_snapshot()
                        sim_elapsed = snap.timestamp.elapsed_seconds - t0
                        score_events.append(dict(
                            timestamp=datetime.now().isoformat(timespec="seconds"),
                            sim_time=float(sim_elapsed),
                            action="A",
                            delta=int(delta),
                            score=int(score),
                            log_file=latest_file
                        ))

                if event.key == SCORE_CFG["key_plus"]:
                    new_score = clamp(score + SCORE_CFG["step"], SCORE_CFG["min_score"], SCORE_CFG["max_score"])
                    delta = new_score - score
                    if delta != 0:
                        score = new_score
                        snap = world.get_snapshot()
                        sim_elapsed = snap.timestamp.elapsed_seconds - t0
                        score_events.append(dict(
                            timestamp=datetime.now().isoformat(timespec="seconds"),
                            sim_time=float(sim_elapsed),
                            action="D",
                            delta=int(delta),
                            score=int(score),
                            log_file=latest_file
                        ))

        # 渲染传感器画面
        display_manager.render(speed=get_speed(vehicle), present=False)

        # 计算当前仿真经过时间
        snap = world.get_snapshot()
        sim_elapsed = snap.timestamp.elapsed_seconds - t0

        # 评分叠加层（可视化）
        draw_score_overlay(sim_elapsed, get_speed(vehicle))

        # 刷新
        pygame.display.flip()
        clock.tick(fps)

        # 回放结束自动退出（如果能推断到总时长）
        if replay_sim_duration is not None and sim_elapsed >= replay_sim_duration:
            running = False

        # 若主车在回放结束后被销毁，也退出
        if not vehicle.is_alive:
            running = False

    # 10) 保存评分 CSV
    out_dir = Path("score_data")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"score_{Path(latest_file).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_path = out_dir / out_name

    df = pd.DataFrame(score_events)

    # 追加一个总结行（最终分）
    df_summary = pd.DataFrame([dict(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        sim_time=float(sim_elapsed),
        action="FINAL",
        delta=0,
        score=int(score),
        log_file=latest_file
    )])
    df = pd.concat([df, df_summary], ignore_index=True)

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"评分CSV已保存: {out_path}")

    pygame.quit()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.shutdown()
        pygame.quit()
        print('\ndone.')
