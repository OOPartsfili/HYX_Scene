import unreal,json,traceback
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix');result={}
try:
    path='/Game/package/Static/Road/map10/map10_Roads_Road_Layer0Node'
    mesh=unreal.load_asset(path);bounds=mesh.get_bounds();body=mesh.get_editor_property('body_setup')
    result['collision_trace_before']=str(body.get_editor_property('collision_trace_flag'))
    data=mesh.get_editor_property('asset_import_data');data.import_uniform_scale=1.0
    data.import_translation=unreal.Vector(0,0,0);data.import_rotation=unreal.Rotator(0,0,0)
    data.convert_scene=True;data.convert_scene_unit=False;data.combine_meshes=True
    data.auto_generate_collision=False;data.generate_lightmap_u_vs=False
    data.normal_import_method=unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS
    task=unreal.AssetImportTask();task.filename=str(out/'road_surface_fixed.fbx');task.destination_path='/Game/package/Static/Road/map10'
    task.destination_name=mesh.get_name();task.automated=True;task.replace_existing=True;task.save=False
    opts=unreal.FbxImportUI();opts.import_mesh=True;opts.import_as_skeletal=False;opts.import_materials=False;opts.import_textures=False
    opts.automated_import_should_detect_type=False;opts.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH;opts.static_mesh_import_data=data;task.options=opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    mesh=unreal.load_asset(path);result['imported']=list(task.imported_object_paths);result['bounds']=str(mesh.get_bounds())
    assert abs(mesh.get_bounds().box_extent.x-bounds.box_extent.x)<.1
    mesh.set_material(0,unreal.load_asset('/Game/package/Maps/map10/Asphalt1_Road'))
    result['collision_trace_after']=str(mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag'))
    assert result['collision_trace_before']==result['collision_trace_after']
    result['saved']=unreal.EditorLoadingAndSavingUtils.save_packages([mesh.get_outer()],False)
    exp=unreal.AssetExportTask();exp.object=mesh;exp.filename=str(out/'road_surface_applied.fbx');exp.exporter=unreal.StaticMeshExporterFBX()
    exp.automated=True;exp.prompt=False;exp.replace_identical=True
    eo=unreal.FbxExportOption();eo.ascii=True;eo.collision=False;eo.level_of_detail=False;exp.options=eo
    result['exported']=unreal.Exporter.run_asset_export_task(exp)
except Exception:result['error']=traceback.format_exc()
(out/'apply_surface_result.json').write_text(json.dumps(result,indent=2))
