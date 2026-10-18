"""UE read-only asset registry survey. Does not load the map or save assets."""
import unreal,json,collections
from pathlib import Path
out=Path(r'E:\Scene_package\Scene_HYX\optimization_reports\map10_survey')
registry=unreal.AssetRegistryHelpers.get_asset_registry()
registry.scan_paths_synchronous(['/Game/package/Maps/map10','/Game/package/Static'],force_rescan=True)
assets=list(registry.get_assets_by_path('/Game/package/Maps/map10',recursive=True) or [])
assets+= [a for a in registry.get_assets_by_path('/Game/package/Static',recursive=True) if '/map10/' in str(a.object_path)]
rows=[]
for a in assets:
    row={'name':str(a.asset_name),'class':str(a.asset_class),'path':str(a.object_path)}
    for tag in ['SourceFile','SourceFilePath','SourceFileTimestamp','AssetImportData','NumTriangles','NumVertices','Materials','CollisionPrims']:
        try:
            v=a.get_tag_value(tag)
            if v:row[tag]=str(v)
        except Exception:pass
    rows.append(row)
(out/'assets.json').write_text(json.dumps({'counts':dict(collections.Counter(r['class'] for r in rows)),'assets':rows},ensure_ascii=False,indent=2),encoding='utf-8')
unreal.log('MAP10_REGISTRY_SURVEY_COMPLETE')
