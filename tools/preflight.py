"""只读检查当前服务器、地图、入口点与摄像头属性，不生成/销毁 actor。"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from optimization_config import ROOT

def main():
    result={}
    try:
        import carla
        client=carla.Client('127.0.0.1',2000);client.set_timeout(3)
        result['client_version']=client.get_client_version()
        result['server_version']=client.get_server_version()
        world=client.get_world();m=world.get_map();settings=world.get_settings()
        result.update(map=m.name,synchronous_mode=settings.synchronous_mode,
            fixed_delta_seconds=settings.fixed_delta_seconds,no_rendering_mode=settings.no_rendering_mode,
            vehicle_count=len(world.get_actors().filter('vehicle.*')))
        result['starts']=[]
        for x,y in [(693,-637),(-850.75,-305.75),(-995,-275)]:
            location=carla.Location(x=x,y=y)
            wp=m.get_waypoint(location)
            delta_xy=((wp.transform.location.x-x)**2+(wp.transform.location.y-y)**2)**.5 if wp else None
            result['starts'].append(dict(x=x,y=y,waypoint_found=wp is not None,projection_xy_m=delta_xy))
        bp=world.get_blueprint_library().find('sensor.camera.rgb')
        result['camera_attributes']={key:bp.has_attribute(key) for key in
            ('sensor_tick','image_size_x','image_size_y','gamma','motion_blur_intensity')}
        result['connected']=True
    except Exception as exc:
        result.update(connected=False,error=str(exc))
    path=ROOT/'optimization_reports'/'preflight.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['connected'] else 1

if __name__=='__main__':sys.exit(main())
