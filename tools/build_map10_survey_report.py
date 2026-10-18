"""Build a local photographic atlas and reproducible route catalogue."""
import json,html,hashlib
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'optimization_reports/map10_survey'
survey=json.loads((OUT/'survey.json').read_text(encoding='utf-8'))
camera=json.loads((OUT/'camera_regions.json').read_text(encoding='utf-8'))
valid=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
assets=json.loads((OUT/'assets.json').read_text(encoding='utf-8'))
extra=json.loads((OUT/'extra_checks.json').read_text(encoding='utf-8'))
meta={
 'A_elevated':('高架主线','优先','双向八车道，路面 Z≈8.74 m；两侧有高层住宅，跨过地面路网。','跟车、前车急刹、邻车切入、连续变道。','路线位于 road 15 中段；不安排驶往地面道路。'),
 'B_merge':('高架收窄区','优先','road 29 到 28，从每方向五车道收窄为四车道。','车道结束并入、侧后方来车、合流冲突。','已额外查通 lane −5 到 road 28 / lane −4；运行时仍需设计让行和并入时序。'),
 'C_arterial':('城市主干道','优先','双向六车道，连续多层楼房、沿街店面、人行道与中央绿化带。','城市跟车、遮挡显现、公交/货车遮挡、行人横穿。','首选城市背景；行人运动须另查人行导航与碰撞。'),
 'D_crossroads':('城市 T 形路口','优先','road 2 经 junction 160 接 road 3，侧向连接宽幅 road 20。','路口横向来车、转弯让行、建筑遮挡。','本次连续路线验证的是直行穿越；每条转弯路线与信号控制应单独核验。'),
 'E_residential':('低层住宅街景','优先','双向六车道，两侧独立住宅、庭院入口和树木。','住宅区遮挡、路侧驶出、儿童/行人出现。','背景是住宅区，但道路本身较宽；不宜描述成窄小区巷道。'),
 'F_local':('双向两车道支路','备选','每方向一条车道，路边背景稀疏、视野开阔。','会车、路侧障碍、低干扰控制实验。','lane_change=NONE；不把跨中心线当作普通同向变道。'),
 'G_wide':('宽幅多车道道路','备选','每方向五条可驾驶车道，中央分隔和行道树明显。','多车交互、连续变道、横向间距控制。','街景较空旷；适合控制变量，不优先用于密集城区背景。'),
 'H_long':('长直测试道路','备选','road 8 约 1.98 km，双向四车道，行道树和远处建筑。','稳定跟驰、制动距离、长时间匀速、速度变化。','这里给出中段 600 m；全路段并非闭环，路线必须在边界前结束。'),
 'I_curve':('高架双车道弯道','优先','road 24 约 494 m，两条同向车道，有护栏并连接高架主线。','弯道跟随、曲率影响、汇入主线。','这段弯道 Z 基本恒定，没有下到地面的坡道；已查通到 road 29 的额外路线。')}
regions=[]
for cam in camera:
    key=cam['id'];title,priority,description,use,limit=meta[key];v=valid['regions'][key]
    regions.append(dict(id=key,name=title,priority=priority,map=survey['map'],xodr_sha256=survey['xodr_sha256'],description=description,use=use,limit=limit,reference_camera=cam,start=v['start'],end=v['end'],continuous_m=v['continuous_m'],road_sequence=v['road_sequence'],path=v['path'],validation={'type':'read-only waypoint traversal + existing planner + sampled collision raycasts; no vehicle dynamics run','router_points':v['router_points'],'router_end_error_m':v['router_end_error_m'],'surface_samples':len(v['surface_checks'])}))
(OUT/'regions.json').write_text(json.dumps({'map':survey['map'],'units':'CARLA metres and degrees; start.z is lane surface, not vehicle spawn clearance','xodr_sha256':survey['xodr_sha256'],'regions':regions},ensure_ascii=False,indent=2),encoding='utf-8')
fig,ax=plt.subplots(figsize=(14,10))
for b in survey['approximate_boxes']:ax.add_patch(plt.Rectangle((b['x']-b['ex'],b['y']-b['ey']),2*b['ex'],2*b['ey'],color='#dce2e7',alpha=.7))
ps=survey['waypoints'];ax.scatter([p['x'] for p in ps],[p['y'] for p in ps],c=['#de903e' if p['z']>5 else '#466ba9' for p in ps],s=2)
for r in regions:
    p=r['reference_camera'];ax.scatter([p['x']],[p['y']],c='#172e43',s=170,zorder=10);ax.text(p['x'],p['y'],r['id'][0],color='white',ha='center',va='center',weight='bold',fontsize=10,zorder=11)
ax.set_aspect('equal');ax.invert_yaxis();ax.set_xlabel('CARLA X (m)');ax.set_ylabel('CARLA Y (m; positive downward)');ax.set_title('map10 region atlas | Blue: ground roads / Orange: elevated roads\nGrey: approximate structure footprints, not verified semantic building labels');fig.tight_layout();fig.savefig(OUT/'region_atlas.png',dpi=125);plt.close(fig)
esc=html.escape
cards=[];table=[]
for r in regions:
    p=r['start'];cam=r['reference_camera'];name=r['name'];code=r['id'][0]
    table.append(f'<tr><td><a href="#{r["id"]}">{code} · {name}</a></td><td>{p["road"]} / {p["lane"]} / {p["s"]:.0f}</td><td>{p["x"]:.2f}, {p["y"]:.2f}, {p["z"]:.2f}</td><td>{p["yaw"]:.1f}°</td><td>{r["continuous_m"]:.0f} m</td></tr>')
    cards.append(f'''<article id="{r['id']}"><div class="cardtitle"><h3>{code} · {name}</h3><span class="tag">{r['priority']}</span></div><p>{r['description']}</p><div class="photos"><a href="{cam['street']}" target="_blank"><img src="{cam['street']}" loading="lazy" alt="{name} 路面视角"><small>路面视角 · 点击原图</small></a><a href="{cam['aerial']}" target="_blank"><img src="{cam['aerial']}" loading="lazy" alt="{name} 鸟瞰"><small>鸟瞰 · 点击原图</small></a></div><p><b>适合：</b>{r['use']}</p><p class="muted"><b>设计边界：</b>{r['limit']}</p><div class="route">已验证起点 ({p['x']:.2f}, {p['y']:.2f}, {p['z']:.2f}) · yaw {p['yaw']:.1f}°<br>road/lane/s = {p['road']} / {p['lane']} / {p['s']:.0f} · 连续 {r['continuous_m']:.0f} m · 道路序列 {' → '.join(map(str,r['road_sequence']))}</div></article>''')
editing='''<section id="editing"><h2>map10 还能编辑吗？可以，分两种工作。</h2>
<p>当前是可编辑的 UE 工程，地图资产仍在；原始导入 FBX、OpenDRIVE 和 RoadRunner 元数据也找到了。<b>街景和材质可在 UE 中调整；车道几何需要与道路语义同步修改。</b></p>
<table><thead><tr><th>想改什么</th><th>实际要改的内容</th><th>车辆控制的影响</th></tr></thead><tbody>
<tr><td>楼房、树、路灯、材质、光照</td><td>UE 场景 Actor / StaticMesh / Material</td><td>保持道路和碰撞净空时，通常无需改 XODR；新遮挡/障碍会改变感知和可行驶空间。</td></tr>
<tr><td>停车车辆、施工锥桶、道路障碍</td><td>场景物体及碰撞；必要时调整行人导航</td><td>waypoint 仍会经过原车道。不能期待所有自定义 PID 控制器自动绕行，应显式设计停车/换道。</td></tr>
<tr><td>实线/虚线、转向箭头、限速、可变道规则</td><td>可见标线/标志 + XODR roadMark / laneChange / speed 等</td><td>只改贴图会导致画面规则与规划规则不同；交通灯还需 UE Actor 与道路控制关系核验。</td></tr>
<tr><td>车道宽度、数量、方向、道路位置/高度/曲率、路口连接</td><td>FBX 道路几何 + XODR 道路/车道拓扑一起更新，再导入</td><td>重建 TM；行人区域改变时重建 Nav；重新检查 spawn、信号、路线、旧坐标和录制轨迹。</td></tr>
</tbody></table>
<h3>你说的“waypoint 文件”对应什么？</h3><p>在检查的 map10 目录和当前代码工程内，没有发现以 waypoint 命名的地图数据文件。真正决定 <code>get_waypoint()</code>、<code>next()</code> 和道路路径规划的是 <b>OpenDrive/map10.xodr</b>。Waypoint 是 CARLA 根据这些道路数据提供的对象。另一个容易混淆的是 <b>TM/map10.bin</b>：它保存 Traffic Manager 使用的 waypoint 缓存。<b>Nav/map10.bin</b> 则用于行人导航，不负责车辆车道中心线。若你记得的是其他文件名，还应对照具体文件再判断。</p>
<div class="chain">FBX / UE 网格 → 可见路面、标线与碰撞<br>XODR → Waypoint / 道路拓扑 → 路径规划 → 车辆控制<br>XODR → TM/map10.bin → Traffic Manager<br>最终场景可步行几何 → Nav/map10.bin → 行人 AI</div>
<h3>这张地图实际的资产组织</h3><ul>
<li>Maps/map10：337 个 Material、968 个 Texture2D、1 个 World。</li>
<li>Static 下的 map10：2,969 个 StaticMesh，其中 Road 1、RoadLine 1、SideWalk 3、Terrain 2,964。建筑等背景也可能归在 Terrain 路径。</li>
<li>主要路面是 <code>map10_Roads_Road_Layer0Node</code>，标线是另一个合并网格。不能把它们当成逐车道可拖动的 spline；直接移动网格不会改 waypoint。</li>
<li>路面材质和网格是引用资源：只复制 .umap 仍可能共享它们。做变体时，需一并复制将修改的依赖资产或另名重新导入。</li>
</ul>
<h3>已找到的源数据</h3><p class="path">D:\\carla\\carla\\Import\\STORE\\map10</p><ul>
<li>map10.fbx（26.65 MB）：其 MD5 与 UE 路面网格保存的导入源 MD5 完全一致。</li>
<li>map10.xodr（2.24 MB）：SHA-256 与当前 Content 中 XODR 完全一致；运行中的地图 XML 规范化后也一致。</li>
<li>map10.rrdata.xml：RoadRunner 导出元数据；还有 map10.geojson。</li>
<li>在已检查的 STORE 范围未找到 .rrscene / .rrproj / .rmap，不能保证原始 RoadRunner 工程仍在。FBX 和 rrdata.xml 不等价于完整可参数化编辑工程。可从 XODR 导入道路后编辑，并复用/重建街景。</li></ul>
<h3>建议的实际编辑流程</h3><ol>
<li>以新名称创建变体，例如 map10_variant，连同待改网格/材质保存独立副本。</li>
<li>只改街景：在 UE 编辑对应物体并检查碰撞净空。改道路：优先在道路编辑器中导入 XODR，同步导出新的 FBX 与同名 XODR，保持坐标、比例、道路与车道 ID 的变更记录。</li>
<li>沿 CARLA 导入流程生成新的 TM 缓存；行人区域或障碍改变后生成 Nav。核验出生点、交通灯 Actor 与道路关系。</li>
<li>重新加载变体地图并重新获取 carla.Map。当前 Studio 的地图/规划缓存有按地图名称复用的逻辑；仅替换同名文件并刷新网页不足以保证更新，需重启服务并重建路线。</li>
<li>旧录制轨迹存的是世界坐标，运动哈希没有包含 XODR 指纹。道路变更后重新录制，不把旧轨迹默认视为有效。后续编辑支持应加入地图指纹校验。</li>
<li>验证 waypoint 与路面重合、车道方向和可变道属性、每条实验路线连通、碰撞、信号和实际车辆运动，再确认可用。</li></ol>
</section>'''
limitations='''<section id="findings"><h2>已经确认的边界</h2><div class="notice"><b>高架与地面目前不能作为一条连续导航路线混用。</b>拓扑查询得到一个地面分量、一个高架分量和孤立的 road 267；高架 road 15 到城市 road 3 的现有规划器查询也失败。高架弯道处 Z 基本恒定，不能把它当作接地匝道。</div>
<ul><li><b>road 267 需修复后再用：</b>它长约 31.5 m，属于 junction 257；道路级 link 指向 road 32 和 15，但 lane 1 没有 predecessor/successor lane link，当前查询中处于孤立分量。本次推荐路线避开它。</li>
<li><b>方向同样决定可达性：</b>同在地面分量不意味着所有车道对都能直达。例如城市 road 3 的向西 lane +2 可以规划到住宅 road 1 的向西 lane +2；选择向东车道后不能假定自动掉头。</li>
<li><b>路口不等于已有完善信号控制：</b>当前世界查到 3 个 traffic light Actor，但 XODR landmark 数为 0。本次没有验证信号绑定、相位或每个路口的控制。</li>
<li><b>语义标签需另查：</b>Buildings 类别的包围盒查询为 0，图中灰色轮廓来自尺寸过滤后的近似结构。实拍可以看到建筑，但不能据此保证语义分割图把它们标成 Buildings。</li>
<li><b>验证范围：</b>本次是道路/资产检查、18 张实景照片、9 条路线规划及 99 处路面射线抽查；不是 9 条路线的实车动力学测试，也不是性能基准。每处抽查均找到与 waypoint 高度接近的碰撞面，不能替代全路线碰撞或路缘检测。现有规划器返回的末端与查询目标相差约 2～4 m；区域 JSON 同时保留完整 waypoint 采样路径，若要精确停车须单独处理终点控制。</li></ul></section>'''
sources='''<section><h2>证据与复用文件</h2><p><a href="regions.json" download>区域坐标与 2 m 路径采样 JSON</a> · <a href="survey.json">完整道路调查</a> · <a href="validation.json">路线与碰撞抽查</a> · <a href="assets.json">UE 资产注册表</a> · <a href="extra_checks.json">导入源指纹与跨区域检查</a> · <a href="camera_cleanup.json">相机清理记录</a></p>
<p>坐标采用 CARLA 米、角度制，yaw=0 沿 +X，yaw=90 沿 +Y；Z 是道路表面。车辆生成需另加合适离地量并检查碰撞。UE 同一世界坐标的常用位置单位为厘米；不要混用 OpenDRIVE 的原始 Y 方向。</p>
<p>原始资产路径：<code>D:\\carla\\carla\\Unreal\\CarlaUE4\\Content\\package\\Maps\\map10</code>。本次未保存或改写地图资源，未移动现有车辆，未修改天气/步长，独立相机已销毁，原有 Actor 均在。</p>
<h3>机制依据</h3><ul><li><a href="https://carla.readthedocs.io/en/0.9.15/core_map/">CARLA 0.9.15：Maps and navigation</a></li><li><a href="https://carla.readthedocs.io/en/0.9.15/tuto_M_custom_map_overview/">CARLA 0.9.15：自定义地图与 FBX / XODR</a></li><li><a href="https://www.mathworks.com/help/roadrunner/">MathWorks：RoadRunner 道路导入与编辑</a></li></ul>
<p class="muted">另核对本机 CARLA 源码：OpenDrive.cpp、InMemoryMap.cpp、TrafficManagerLocal.cpp、NavigationMesh.cpp、Util/BuildTools/Import.py；以及本项目 planning.py、routing.py、server.py、timeline.py。客户端 0.9.15，服务器 0.9.15-dirty。</p></section>'''
doc='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>map10 · 区域图册与编辑调查</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f1f4f7;color:#193047;font:16px/1.75 'Microsoft YaHei',sans-serif}header{background:#172e43;color:white;padding:48px max(24px,calc((100vw - 1240px)/2))}header p{color:#cddae5}h1{font-size:36px;line-height:1.35;margin:12px 0}h2{font-size:27px;line-height:1.4}h3{margin:4px 0;font-size:22px}nav{display:flex;gap:20px;flex-wrap:wrap}nav a{color:#bcd9f7}main{max-width:1280px;margin:auto;padding:24px}section,article{background:white;border:1px solid #dfe6ec;border-radius:12px;padding:28px;margin:22px 0;scroll-margin-top:16px}a{color:#175b99;text-decoration:none}a:hover{text-decoration:underline}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.kpis div{background:white;border-radius:10px;padding:22px;border:1px solid #dfe6ec}.kpis b{display:block;font-size:30px}.muted,small{color:#5d7082}.atlas{width:100%;height:auto}.cardtitle{display:flex;align-items:center;justify-content:space-between}.tag{background:#e8f0f8;color:#175b99;padding:3px 13px;border-radius:30px;font-size:14px}.photos{display:grid;grid-template-columns:1fr 1fr;gap:16px}.photos img{display:block;width:100%;border-radius:8px}.photos small{display:block;padding:5px 0}.route,.chain{background:#f0f5f9;padding:15px 20px;border-radius:7px;font-family:Consolas,'Microsoft YaHei',monospace}.notice{border-left:5px solid #d6923a;background:#fff5e6;padding:16px 20px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:12px;border-bottom:1px solid #dfe6ec;vertical-align:top}th{background:#f0f5f9}li{margin:10px 0}.path,code{overflow-wrap:anywhere}.tablewrap{overflow:auto}footer{text-align:center;padding:24px;color:#718293}@media(max-width:800px){h1{font-size:28px}.kpis{grid-template-columns:1fr 1fr}.photos{grid-template-columns:1fr}main{padding:12px}section,article{padding:18px}}
</style></head><body><header><small style="color:#aac2d7">MAP10 / 实景调查 / 2026-10-03</small><h1>选择实验区域，厘清地图编辑边界</h1><p>6 个优先区域 + 3 个备选 · 路面与鸟瞰实拍 · 可复用路线坐标 · waypoint 依赖核查</p><nav><a href="#atlas">区域总览</a><a href="#regions">坐标目录</a><a href="#findings">已知限制</a><a href="#editing">编辑方式</a><a href="regions.json" download>下载区域数据</a></nav></header><main>'''
doc+='<div class="kpis"><div><b>84 / 7</b>道路 / 路口</div><div><b>9 条</b>区域连续路线</div><div><b>18 张</b>实际相机照片</div><div><b>99 处</b>路面高度抽查</div></div>'
doc+='<section id="atlas"><h2>区域总览</h2><p>优先采用 A、B、C、D、E、I；F、G、H 用作背景更简单的对照区域。橙色为高架道路，蓝色为地面道路。区域以实际 CARLA 坐标和 road/lane/s 锚定。</p><a href="region_atlas.png" target="_blank"><img class="atlas" src="region_atlas.png" alt="map10 区域总览"></a></section>'
doc+='<section id="regions"><h2>可复用起点与已验证长度</h2><p>表中是路线测试起点，照片拍摄点在同一区域内但不一定与起点相同；两者均保存在 JSON 中。长度为本次验证区间，非整个区域边界。</p><div class="tablewrap"><table><thead><tr><th>区域</th><th>road / lane / s</th><th>起点 X, Y, Z（米）</th><th>yaw</th><th>连续区间</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div></section>'
doc+=''.join(cards)+limitations+editing+sources+'</main><footer>map10 调查结果 · 原始地图保持不变 · 本地报告</footer></body></html>'
(OUT/'index.html').write_text(doc,encoding='utf-8')
print(OUT/'index.html')
