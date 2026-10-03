"""七个实验场景共用的环境和背景车设置。"""
import os
from background_traffic import BackgroundTraffic
from optimization_config import ROOT
import scene_runtime as runtime

class Environment:
    def __init__(self, client, ego):
        self.client, self.world = client, ego.get_world()
        self.weather = None
        runtime.register(self, 'restore')
        preset = os.environ.get('HYX_WEATHER', 'keep')
        if preset != 'keep':
            self.weather = self.world.get_weather()
            weather = self.world.get_weather()
            weather.sun_altitude_angle = 45 if preset == 'clear' else 35
            weather.cloudiness = 20 if preset == 'clear' else 70
            weather.precipitation = 0
            weather.precipitation_deposits = 0
            weather.wetness = 0
            weather.fog_density = 0 if preset == 'clear' else 2
            weather.wind_intensity = 10
            self.world.set_weather(weather)
        settings = self.world.get_settings()
        if settings.no_rendering_mode:
            raise RuntimeError('CARLA no_rendering_mode is enabled; RGB experiment needs rendering')
        # 现有实验依赖实时输入，不暗中启用同步模式，也不抢占其他客户端的 tick。
        runtime.metadata(map=self.world.get_map().name, client_version=client.get_client_version(),
            server_version=client.get_server_version(), render_profile=os.environ.get('HYX_RENDER_PROFILE','quality'),
            weather=preset, synchronous_mode=settings.synchronous_mode,
            fixed_delta_seconds=settings.fixed_delta_seconds)
        for folder in ('carla_data', 'log_data', 'optimization_reports'):
            (ROOT / folder).mkdir(exist_ok=True)
        self.traffic = BackgroundTraffic(client, ego, count=int(os.environ.get('HYX_BACKGROUND_COUNT','0')),
            seed=int(os.environ.get('HYX_SEED','42')), hybrid=os.environ.get('HYX_HYBRID','0') == '1')

    def restore(self):
        try:
            self.client.stop_recorder()
        finally:
            if self.weather is not None:
                self.world.set_weather(self.weather)

def setup_scene(client, ego):
    return Environment(client, ego)
