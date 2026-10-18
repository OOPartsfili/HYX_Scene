import unreal,json
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix');out.mkdir(parents=True,exist_ok=True)
mesh=unreal.load_asset('/Game/package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node')
data={'engine':unreal.SystemLibrary.get_engine_version(),'mesh_methods':[n for n in dir(mesh) if any(s in n for s in ['mesh','description','material'])],
'classes':[n for n in dir(unreal) if any(s in n for s in ['MeshDescription','ProceduralMesh','StaticMeshDescription','DynamicMesh','GeometryScript'])],
'editor_world':str(unreal.EditorLevelLibrary.get_editor_world()),'dirty_content':[p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()],'dirty_maps':[p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]}
(out/'live_editor_probe.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
