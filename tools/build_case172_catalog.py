"""Build the traceable design catalogue from the reviewed 172-case document.

The mapping below is editorial: cases were read individually, not classified by
keyword. Source statements and limitations are retained in the coverage file.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r'F:\Soul_copy\outputs\172案例_个体化主动干预预测_2026-09-26\172案例结构化复核.json')
OUT = ROOT / 'optimization_reports' / 'case172_scenarios'

# id, name, case numbers, interaction, migration/uncertainty, acceptance intent
PATTERNS = [
 ('P01','前车渐缓，主车提前减速',[12,155], '前车平缓降速，主车根据车距连续跟随。','设置较长初始车距，作为强制动的对照。','前车降速、主车随后降速，间距保持为正。'),
 ('P02','前车明显制动，主车跟停',[7,111,132], '稳定前车制动，主车经历接近、制动、跟停。','原案例不能证明不干预必撞；本场景参数是实验设定。','前车先制动，主车减速并停在其后，无接触。'),
 ('P03','接近已停止的队尾',[30,77,90,92,96,126,157,177,196], '主车从自由行驶进入静止队列尾部。','保留队尾接近关系；不把日志中事后低TTC作为触发原因。','主车明显减速并停住，队尾保持静止。'),
 ('P04','较高车速下短时距跟车',[31,191], '较高车速和较短初始时距下，前车减速，主车及时调整。','原案例包含约72–119 km/h。本场景采用80 km/h，保留较高车速与短时距；该次测试不外推至119 km/h。','实测初速落在案例0191的72–84 km/h范围，初始时距小于0.8秒；制动后不碰撞。'),
 ('P05','队列起步后再次跟停',[3,21,195], '前车起步、主车跟上、前车再次停住。','普通起停也属于有价值的非紧急对照。','两车从静止起步，随后再次停住。'),
 ('P06','多车队列中的减速传播',[49,155,186], '队首制动，中间车与主车依次响应。','增加第三辆车是实验扩展，不声称原片段提供三车完整轨迹。','三车按顺序减速，所有相邻车间距保持为正。'),
 ('P07','慢速大型车辆前的速度适配',[129,138], '主车接近并跟随慢速大型车辆，限制可见前方空间。','本地图车辆库以箱式货车替代原工程拖挂车辆。','主车从较快速度降到前车附近速度，保持车距。'),
 ('P08','前车移开后显露慢车队列',[13,202], '前车向邻道离开，慢车显露，主车切换跟随对象。','原案例未证明突然切出致险；本设计单独操纵显露时刻。','前车完成横移，主车改跟新目标并降速。'),
 ('P09','前车转走，主车仍需独立停车',[84,185], '前车右转离开；主车在自己入口边界前停车。','使用脚本停车边界，不假定map10已有适用STOP或信号规则。','前车完成转弯，主车在边界前停住。'),
 ('P10','前车通过后，主车停车再通行',[187], '前车直行通过入口，主车独立停车，随后起步。','将前车动作与主车通行条件分开设置。','前车通过；主车停留后再通过。'),
 ('P11','主车变道后接近较慢前车',[103,115,168,198], '主车从相邻车道并入慢车后方，再跟随减速。','168支持主车变道，不能改写成蓝车强行切入。','主车横移到目标车道，再保持在慢车后方。'),
 ('P12','邻车超越但不切入',[199], '邻道车辆超越主车并减速，保持原车道。','作为切入误报的明确对照；原案例后窗短不外推结局。','邻车完成超越，横向间隔稳定，主车无强制动。'),
 ('P13','侧向车辆驶入并转为同向',[76,197], '侧向车辆经过主车前方，再进入同向道路。','只迁移可见的横向入道关系，不指定原车是掉头还是出入口驶出。','侧车转入同向，主车减速让出空间，无接触。'),
 ('P14','入口前等待一辆横向车',[29,43,101,127], '主车接近交叉口，等待一辆横向车清空后通行。','环岛样本迁移为普通交叉口入口让行。','横向车先通过冲突区，主车随后进入。'),
 ('P15','连续横向车流中的等待',[97,154,228], '多辆横向车依次通过，主车保持等待直到最后一辆清空。','车辆数量、间隔是实验参数；不作为原片段精确测量。','至少三辆横向车通过；主车等待覆盖整个序列。'),
 ('P16','起步后遇第二拨横向车',[95,158,205], '第一辆通过后主车缓行，第二辆到来时再次停车。','将片段中不同阶段拆成两次互动，不倒推初始接管原因。','主车有两次停车，中间确有前移；第二辆通过后恢复。'),
 ('P17','等待横向间隙后右转汇入',[37,114,133,149], '主车在入口减速，横向车通过后右转同向汇入。','普通让行与汇入；不按原画面灯色判定本图路权。','横车先清空，主车右转并进入正确出向车道。'),
 ('P18','左转前等待对向车',[219], '主车欲左转，对向车先直行通过，主车再转弯。','停车区会车关系迁移到有路由连接的交叉口；原案例未确认近碰撞。','对向车通过冲突区后，主车完成左转。'),
 ('P19','相邻车辆并行转弯',[107,117], '两车各沿相邻的弯曲路径行驶，保持各自空间。','原案例为并行左转；在map10双车道弯路迁移并行转向关系。','两车完成同向转弯，无轨迹交叉或碰撞。'),
 ('P20','跟车至分岔后选择不同路径',[16,165,174,201], '主车与前车接近路口后分道，前车不再是跟随目标。','高速出口或环岛出口迁移为现有交叉口分流；不复建几何。','车辆进入两个不同出口，主车不继续追踪远离目标。'),
 ('P21','弯道跟车时前车减速',[1,11,17,118,153,203,215], '两车沿弯曲路径行驶，前车减速，主车同时转向和制动。','环岛入口跟车迁移为现有弯道或转弯路线。','两车均有明显航向变化，主车降速且未驶离路径。'),
 ('P22','双向道路正常会车',[143,164,193], '车辆在各自方向车道上会车，保持横向空间。','原案例未证实对向侵入，因此保持正常会车。','相对纵向顺序反转，各自车道无接触。'),
 ('P23','路侧停放车辆旁的会车',[42,72,131,169], '停放车辆限制路侧空间，主车与对向车低速通过。','只布置车辆，不改变道路宽度；人员未横穿不编造突然冲出。','经过停放车辆并与对向车交会，无接触。'),
 ('P24','低速区域先会车再让横车',[95,219,221,229], '主车低速接近出口，先与迎面车辆交会，再停等横向车，最后转弯离开。','将停车区多车协调迁移到map10双向支路与T形口，不宣称复现停车场几何。','先完成会车，再等待横车清空，最后低速转弯。'),
 ('P25','大型车遮挡下两轮车穿行',[36,206], '主车在大型车后低速起停，两轮车从侧面向前通过。','蓝图库无公交车，使用厢式货车表达遮挡，并明确替代。','大型车与主车跟停，两轮车从主车后侧驶到前侧，无接触。'),
 ('P26','转弯后遇到后续横穿者',[78,105,222], '主车转弯后遇行人横穿，完成第二阶段让行。','初次转弯与后续横穿分别触发；不把后见行人当初始原因。','先完成转弯，再因横穿停车；行人清空后车辆恢复。'),
]

# These records contribute contextual/manual-control contrasts, not invented traffic.
QUALITY_ONLY = {6,24,40,82,85,87,128,179,218,225}

def build():
    data = SOURCE.read_bytes()
    cases = json.loads(data.decode('utf-8-sig'))
    assert len(cases) == 172
    lookup = {int(c['case_id'].rsplit('_',1)[1]): c for c in cases}
    patterns = []
    for pid,name,ids,interaction,migration,acceptance in PATTERNS:
        assert all(i in lookup for i in ids), (pid,ids)
        patterns.append(dict(id=pid,name=name,source_cases=[lookup[i]['case_id'] for i in ids],
            interaction=interaction,transfer=migration,acceptance_intent=acceptance,
            parameters_are_designed=True,status='design_specification_see_acceptance_for_test_status'))
    coverage = []
    for number,c in lookup.items():
        matches=[p['id'] for p in patterns if c['case_id'] in p['source_cases']]
        status='interaction_source' if matches else 'timing_or_measurement_audit' if number in QUALITY_ONLY else 'context_and_normal_maneuver_control'
        reason=('提供交通参与者之间的交互结构；仿真数值需单独设定。' if matches else
                '时序、标定或短窗存在明确限制，不用于设定精确触发时刻。' if number in QUALITY_ONLY else
                '以单车机动、道路约束或控制状态审计为主，不为凑交通流类型虚构其他车辆。')
        coverage.append(dict(case_id=c['case_id'],title=c['title'],patterns=matches,use=status,reason=reason,
            scene=c['scene'],summary=c['summary'],role=c['role'],prediction=c['prediction'],
            source_speed_kmh=c['pre_metrics'].get('speed_kmh'),source_dir=c.get('source_dir'),
            evidence_files=c.get('evidence_files'),quality=c.get('quality')))
    OUT.mkdir(parents=True,exist_ok=True)
    common=dict(source=str(SOURCE),source_sha256=hashlib.sha256(data).hexdigest(),case_count=172,
        methodology='逐例阅读scene、summary、role、可见线索及limitations后人工归类。26类按参与者关系、动作顺序和通行约束区分。参数为实验设计，不拟合未经标定的原始轨迹。')
    for filename,value in [('catalog.json',{**common,'patterns':patterns}),('case_coverage.json',{**common,'cases':coverage})]:
        (OUT/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(coverage),patterns=len(patterns),interaction_sources=sum(bool(c['patterns']) for c in coverage)),ensure_ascii=False))

if __name__=='__main__':build()
