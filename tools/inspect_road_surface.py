import unreal,json
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix')
rows=[]
for world in unreal.EditorLevelLibrary.get_pie_worlds(False):
 for a in unreal.GameplayStatics.get_all_actors_of_class(world,unreal.StaticMeshActor):
  mesh=a.static_mesh_component.static_mesh
  if mesh and 'map10_Roads' in mesh.get_name():
   rows.append({'actor':a.get_name(),'mesh':mesh.get_path_name(),'bounds':str(mesh.get_bounds()),'materials':[str(m.material_interface) for m in mesh.static_materials]})
   if 'Roads_Road' in mesh.get_name() or 'Roads_Lane' in mesh.get_name():
    task=unreal.AssetExportTask();task.object=mesh;task.filename=str(out/(mesh.get_name()+'.fbx'));task.exporter=unreal.StaticMeshExporterFBX();task.automated=True;task.prompt=False;task.replace_identical=True
    opt=unreal.FbxExportOption();opt.ascii=True;opt.collision=False;opt.level_of_detail=False;task.options=opt
    rows[-1]['exported']=unreal.Exporter.run_asset_export_task(task)
(out/'road_surface_inspect.json').write_text(json.dumps(rows,indent=2))
