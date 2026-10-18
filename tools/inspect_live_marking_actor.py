import unreal,json
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix')
rows=[]
for world in unreal.EditorLevelLibrary.get_pie_worlds(False):
 for actor in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.StaticMeshActor):
  comp=actor.static_mesh_component;mesh=comp.static_mesh
  if mesh and 'map10_Roads_Marking' in mesh.get_name():rows.append({'world':world.get_path_name(),'actor':actor.get_path_name(),'transform':str(actor.get_actor_transform()),'materials':[comp.get_material(i).get_path_name() for i in range(comp.get_num_materials())]})
(out/'live_marking_actors.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
