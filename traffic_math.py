"""不依赖 CARLA 的控车计算，速度单位均为 m/s，距离单位为 m。"""
import math

def follow_speed(cruise, lead_speed, gap, headway=1.5, min_gap=3.0, decel=4.0):
    """时间车距与制动距离双重约束；返回目标速度及紧急停车标志。"""
    if headway <= 0 or min_gap < 0 or decel <= 0:
        raise ValueError('Invalid following parameters')
    gap = max(0.0, gap)
    lead_speed = max(0.0, lead_speed)
    free_gap = max(0.0, gap - min_gap)
    braking_limit = math.sqrt(lead_speed ** 2 + 2 * decel * free_gap)
    time_limit = free_gap / headway
    return max(0.0, min(cruise, braking_limit, time_limit)), gap <= min_gap

def ramp_speed(current, target, dt, acceleration=2.5, deceleration=6.0):
    dt = max(0.0, min(dt, 0.2))
    delta = target - current
    return max(0.0, current + max(-deceleration * dt, min(acceleration * dt, delta)))

def lane_key(waypoint):
    return (waypoint.road_id, waypoint.section_id, waypoint.lane_id) if waypoint else None

def ahead_distance(origin, forward, target):
    return (target.x-origin.x)*forward.x + (target.y-origin.y)*forward.y

def smoothstep(value):
    t = max(0.0, min(1.0, value))
    return t*t*t*(10 + t*(-15 + 6*t))
