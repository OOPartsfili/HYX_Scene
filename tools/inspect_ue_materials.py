"""Read-only UE Python commandlet: inspect imported map10 material graphs."""
import unreal
import json
from pathlib import Path

out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\visual_study')
out.mkdir(parents=True,exist_ok=True)
results=[]
lib=unreal.MaterialEditingLibrary
for name in ['Asphalt1_Road']:
    path='/Game/package/Maps/map10/'+name
    material=unreal.load_asset(path)
    if not material:continue
    row={'asset':path,'class':material.get_class().get_name()}
    task=unreal.AssetExportTask()
    task.object=material;task.filename=str(out/(name+'.t3d'))
    task.exporter=unreal.ObjectExporterT3D();task.automated=True;task.prompt=False;task.replace_identical=True
    try:row['text_exported']=unreal.Exporter.run_asset_export_task(task)
    except Exception as e:row['text_export_error']=str(e)
    for group in ('scalar','vector','texture'):
        try:row[group+'_parameters']=[str(v) for v in getattr(lib,'get_'+group+'_parameter_names')(material)]
        except Exception as e:row[group+'_error']=str(e)
    try:
        row['used_textures']=[t.get_path_name() for t in lib.get_used_textures(material)]
        row['expressions']=[]
        for node in material.get_editor_property('expressions'):
            item={'class':node.get_class().get_name()}
            for key in ('parameter_name','texture','r','constant','const_coordinate'):
                try:
                    value=node.get_editor_property(key)
                    item[key]=value.get_path_name() if isinstance(value,unreal.Object) else str(value)
                except Exception:pass
            row['expressions'].append(item)
        row['inputs']={}
        for key in ('base_color','normal','roughness','specular','metallic'):
            try:row['inputs'][key]=str(material.get_editor_property(key))
            except Exception as e:row['inputs'][key]=str(e)
    except Exception as e:row['graph_error']=str(e)
    results.append(row)
(out/'materials.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
unreal.log('HYX read-only material inspection complete')
