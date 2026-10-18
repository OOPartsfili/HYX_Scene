import unreal,json,traceback
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix')
result={}
try:
    task=unreal.AssetImportTask()
    task.filename=str(out/'markings_fixed.fbx')
    task.destination_path='/Game/package/Maps/map10_LineFix'
    task.destination_name='Markings_Verified_Scale1'
    task.automated=True;task.replace_existing=True;task.replace_existing_settings=True;task.save=False
    opts=unreal.FbxImportUI()
    opts.import_mesh=True;opts.import_materials=False;opts.import_textures=False
    opts.import_as_skeletal=False;opts.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH
    opts.automated_import_should_detect_type=False
    data=opts.static_mesh_import_data
    data.combine_meshes=True;data.auto_generate_collision=False
    data.generate_lightmap_u_vs=False
    data.normal_import_method=unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS
    data.convert_scene=True;data.convert_scene_unit=False
    data.import_uniform_scale=1.0;data.import_translation=unreal.Vector(0,0,0);data.import_rotation=unreal.Rotator(0,0,0)
    task.options=opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    result['paths']=list(task.imported_object_paths)
    mesh=unreal.load_asset(task.imported_object_paths[0])
    for i,n in enumerate(['LaneMarking1_Marking','LaneMarkingYellow1_Marking']):
        mesh.set_material(i,unreal.load_asset('/Game/package/Maps/map10/'+n))
    result['bounds']=str(mesh.get_bounds());result['materials']=[str(s.material_interface) for s in mesh.static_materials]
    exp=unreal.AssetExportTask();exp.object=mesh;exp.filename=str(out/'markings_staged.fbx');exp.exporter=unreal.StaticMeshExporterFBX()
    exp.automated=True;exp.prompt=False;exp.replace_identical=True
    eo=unreal.FbxExportOption();eo.ascii=True;eo.collision=False;eo.level_of_detail=False;exp.options=eo
    result['exported']=unreal.Exporter.run_asset_export_task(exp)
except Exception:
    result['error']=traceback.format_exc()
(out/'stage_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
