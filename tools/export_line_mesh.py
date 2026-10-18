import unreal,json
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix')
mesh=unreal.load_asset('/Game/package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node')
t=unreal.AssetExportTask();t.object=mesh;t.filename=str(out/'markings_original.fbx');t.exporter=unreal.StaticMeshExporterFBX();t.automated=True;t.prompt=False;t.replace_identical=True
o=unreal.FbxExportOption();o.set_editor_property('ascii',True);o.set_editor_property('collision',False);o.set_editor_property('level_of_detail',False);t.options=o
data={'exported':unreal.Exporter.run_asset_export_task(t),'bounds':str(mesh.get_bounds()),'lods':mesh.get_num_lods(),'uv_channels':unreal.EditorStaticMeshLibrary.get_num_uv_channels(mesh,0)}
(out/'export.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
