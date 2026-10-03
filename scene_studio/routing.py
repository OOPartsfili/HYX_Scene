"""Guard the bundled legacy DAO against short/dead-end imported map lanes."""
import numpy as np
from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO

class MapDAO(GlobalRoutePlannerDAO):
    def get_topology(self):
        topology=[]
        for entry,exit in self._wmap.get_topology():
            a=entry.transform.location;b=exit.transform.location
            xyz=np.round([a.x,a.y,a.z,b.x,b.y,b.z],0)
            row={'entry':entry,'exit':exit,'entryxyz':tuple(xyz[:3]),'exitxyz':tuple(xyz[3:]),'path':[]}
            point=entry;seen={entry.id}
            while point.transform.location.distance(b)>self._sampling_resolution:
                candidates=[p for p in point.next(self._sampling_resolution) if p.id not in seen and p.road_id==entry.road_id and p.section_id==entry.section_id and p.lane_id==entry.lane_id]
                if not candidates:break
                point=min(candidates,key=lambda p:p.transform.location.distance(b))
                seen.add(point.id);row['path'].append(point)
                if len(seen)>20000:raise ValueError('道路拓扑长度异常')
            topology.append(row)
        return topology
