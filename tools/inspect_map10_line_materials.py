"""UE read-only inspection of line material inputs and mesh material slots."""
import unreal,json
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_audit')
mesh=unreal.load_asset('/Game/package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node')
rows=[]
for name in ['LaneMarking1_Marking','LaneMarkingYellow1_Marking']:
 m=unreal.load_asset('/Game/package/Maps/map10/'+name);row={'name':name,'class':m.get_class().get_name()}
 t=unreal.AssetExportTask();t.object=m;t.filename=str(out/(name+'.t3d'));t.exporter=unreal.ObjectExporterT3D();t.automated=True;t.prompt=False;t.replace_identical=True
 row['exported']=unreal.Exporter.run_asset_export_task(t)
 row['textures']=[x.get_path_name() for x in unreal.MaterialEditingLibrary.get_used_textures(m)]
 rows.append(row)
data={'materials':rows,'slots':[{'slot':str(s.material_slot_name),'material':s.material_interface.get_path_name() if s.material_interface else None} for s in mesh.get_editor_property('static_materials')]}
(out/'line_materials.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
unreal.log('LINE_MATERIAL_INSPECTION_COMPLETE')
