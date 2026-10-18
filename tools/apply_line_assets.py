"""Apply the validated FBX and RoadRunner yellow tint to backed-up source assets."""
import unreal,json,traceback
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_lane_fix')
result={}
try:
    mesh=unreal.load_asset('/Game/package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node')
    original_bounds=mesh.get_bounds()
    data=mesh.get_editor_property('asset_import_data')
    result['old_import_scale']=data.import_uniform_scale
    data.import_uniform_scale=1.0;data.import_translation=unreal.Vector(0,0,0);data.import_rotation=unreal.Rotator(0,0,0)
    data.convert_scene=True;data.convert_scene_unit=False;data.combine_meshes=True
    data.auto_generate_collision=False;data.generate_lightmap_u_vs=False
    data.normal_import_method=unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS
    task=unreal.AssetImportTask();task.filename=str(out/'markings_fixed.fbx')
    task.destination_path='/Game/package/Static/RoadLine/map10';task.destination_name=mesh.get_name()
    task.automated=True;task.replace_existing=True;task.replace_existing_settings=True;task.save=False
    opts=unreal.FbxImportUI();opts.import_mesh=True;opts.import_as_skeletal=False
    opts.import_materials=False;opts.import_textures=False;opts.automated_import_should_detect_type=False
    opts.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH;opts.static_mesh_import_data=data
    task.options=opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    result['imported']=list(task.imported_object_paths)
    mesh=unreal.load_asset('/Game/package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node')
    result['bounds']=str(mesh.get_bounds())
    assert abs(mesh.get_bounds().box_extent.x-original_bounds.box_extent.x)<.1, 'Bounds changed unexpectedly'
    for i,n in enumerate(['LaneMarking1_Marking','LaneMarkingYellow1_Marking']):mesh.set_material(i,unreal.load_asset('/Game/package/Maps/map10/'+n))
    mat=unreal.load_asset('/Game/package/Maps/map10/LaneMarkingYellow1_Marking')
    lib=unreal.MaterialEditingLibrary
    tex=unreal.find_object(mat,'MaterialExpressionTextureSample_0')
    assert tex is not None
    tint=unreal.find_object(mat,'MaterialExpressionVectorParameter_0')
    if tint is None:
        tint=lib.create_material_expression(mat,unreal.MaterialExpressionVectorParameter,240,-520)
    tint.set_editor_property('parameter_name','HYX_RoadRunnerYellow')
    tint.set_editor_property('default_value',unreal.LinearColor(1.0,0.835294,0.0,1.0))
    mul=unreal.find_object(mat,'MaterialExpressionMultiply_0')
    if mul is None:mul=lib.create_material_expression(mat,unreal.MaterialExpressionMultiply,550,-320)
    mul.set_editor_property('desc','HYX yellow tint')
    assert lib.connect_material_expressions(tex,'RGB',mul,'A')
    assert lib.connect_material_expressions(tint,'',mul,'B')
    assert lib.connect_material_property(mul,'',unreal.MaterialProperty.MP_BASE_COLOR)
    lib.recompile_material(mat)
    result['yellow_tint']=[1,.835294,0]
    result['saved']=unreal.EditorLoadingAndSavingUtils.save_packages([mesh.get_outer(),mat.get_outer()],False)
    exp=unreal.AssetExportTask();exp.object=mesh;exp.filename=str(out/'markings_applied.fbx');exp.exporter=unreal.StaticMeshExporterFBX()
    exp.automated=True;exp.prompt=False;exp.replace_identical=True
    eo=unreal.FbxExportOption();eo.ascii=True;eo.collision=False;eo.level_of_detail=False;exp.options=eo
    result['exported']=unreal.Exporter.run_asset_export_task(exp)
except Exception:
    result['error']=traceback.format_exc()
(out/'apply_assets_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
