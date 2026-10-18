"""Generate a local, evidence-linked scenario design and acceptance report."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).parent))
from run_case172 import code_hashes
OUT=ROOT/'optimization_reports/case172_scenarios'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def esc(s):return html.escape(str(s))
NAMES={'ego':'主车','lead':'前车','middle':'中间车','neighbor':'邻道车','entering':'侧向驶入车','parallel':'并行车','queue':'队尾','cross':'横向车','cross2':'第二辆横向车','cross3':'第三辆横向车','oncoming':'对向车','parked':'停放车','moto':'两轮车','pedestrian':'行人'}
EVENT_NAMES={'own_stop':'到达本车停车边界时停车','own_restart':'停留8秒后起步','yield':'接近冲突区时停车','entry_clear':'驶入车清空入口后起步','follow_entering':'开始跟随驶入车','approach_stop':'接近入口时停车','cross_clear':'最后一辆横车清空后起步','first_stop':'第一次停车','first_clear':'第一辆横车通过后缓行','second_stop':'缓行4秒后再次停车','second_clear':'第二辆横车清空后通行','left_wait':'左转前停车等候','oncoming_clear':'对向车清空后左转','after_turn':'主车转弯后，行人开始横穿','pedestrian_yield':'为后续行人停车','pedestrian_clear':'行人走出主车路径后起步'}
CSS='''body{margin:0;background:#eef2f4;color:#152b38;font:16px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:32px}h1{font-size:32px;line-height:1.4}h2{margin-top:0;font-size:24px}h3{font-size:18px}p{max-width:960px}section{background:white;border:1px solid #d8e1e6;border-radius:12px;padding:26px;margin:24px 0;scroll-margin-top:20px}a{color:#0b647c}nav{display:flex;flex-wrap:wrap;gap:8px}nav a,.tag{display:inline-block;padding:4px 10px;background:#e5eef3;border-radius:5px;text-decoration:none}.pass{color:#176b4d;background:#dff3e8}.fail{color:#93411e;background:#ffeddf}.muted,small{color:#586d77}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;border-bottom:1px solid #dce4e8;padding:9px;vertical-align:top}pre{padding:16px;background:#eff4f6;overflow:auto;white-space:pre-wrap}.shots{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}figure{margin:0}img{width:100%;border-radius:6px}figcaption{font-size:13px;color:#586d77}svg{max-width:100%;height:auto}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}@media(max-width:700px){main{padding:16px}.shots{grid-template-columns:1fr}section{padding:18px}table{font-size:12px}h1{font-size:26px}}'''
def page(title,body):return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'+CSS+'</style><main>'+body+'</main></html>'
def speed_plot(frames):
    actors=list(frames[0]['actors']);duration=frames[-1]['t'];vmax=max(10,max(a['speed'] for f in frames for a in f['actors'].values()))*1.1
    colors=['#09846b','#d17a22','#7164c5','#c84368','#2074a9'];out=['<svg viewBox="0 0 1000 200" role="img" aria-label="实测速度随仿真时间变化"><rect width="1000" height="200" fill="#f6f9fb"/>']
    for i in range(4):
        y=160-i*42;out.append(f'<path d="M45 {y}H970" stroke="#d9e3e8"/><text x="3" y="{y+4}" font-size="12">{vmax*i/3:.0f}</text>')
    for i,aid in enumerate(actors):
        pts=' '.join(f'{45+f["t"]/duration*925:.1f},{160-f["actors"][aid]["speed"]/vmax*126:.1f}' for f in frames[::4] if aid in f['actors'])
        color=colors[i%len(colors)];out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/><text x="{50+i*145}" y="20" fill="{color}" font-size="13">{esc(aid)}</text>')
    out.append(f'<text x="45" y="189" font-size="12">0 s</text><text x="915" y="189" font-size="12">{duration:g} s</text><text x="400" y="189" font-size="12">仿真时间 / 速度 km/h</text></svg>');return ''.join(out)

def main():
    catalog=read(OUT/'catalog.json');coverage=read(OUT/'case_coverage.json');build=read(OUT/'build.json');current=code_hashes()
    results={};history=[]
    for p in sorted((ROOT/'studio_data/runs').glob('case172_*/verification.json')):
        r=read(p);history.append(dict(scene=r['scene'],run=r['run'],passed=r['passed']))
        source=OUT/'scenes'/(r['scene']+'.json')
        if source.exists() and r.get('scene_sha256')==hashlib.sha256(source.read_bytes()).hexdigest() and r.get('code_hashes')==current:
            results[r['scene']]=(r,p.parent)
    n=sum(r['passed'] for r,_ in results.values());total=len(catalog['patterns'])
    body=f'''<header><small>172 例 → 交通交互设计 → map10 物理实测</small><h1>CARLA 交通交互场景库</h1><p>从 172 个案例中整理 26 类交互模式。车辆沿 map10 现有道路行驶，用油门、制动和转向控制产生运动；不移动地图、不重建路口。</p><p><span class="tag {'pass' if n==total else 'fail'}">当前版本实测通过 {n} / {total}</span> <a href="coverage.html">查看全部 172 例的用途与限制</a> · <a href="acceptance.json">原始验收索引</a></p></header>
<section><h2>设计思路</h2><p>先提取“谁与谁交互、动作按什么顺序发生、主车需满足什么约束”，再给 map10 设置可运行的路线、初速、间距和触发条件。77 例提供这 26 类交互的直接或关联依据；其余 95 例保留为单车机动、道路约束或数据质量对照，未虚构其他车辆补成交通事件。</p><p>本库是案例启发的实验场景，不是原始事故或接管片段的逐帧复现。原文缺乏标定轨迹、目标身份或可靠时钟时，不照搬其毫秒时序。环岛、停车场、高速出口只迁移其交通交互关系；每个场景均注明替代方式。</p><p>主车自带基准控制器，便于直接运行和检查互动。它读取仿真状态并执行预设条件，未实现摄像头感知，也不模拟原案例中的辅助驾驶产品。接入自己的算法时，可替换主车控制或在编辑器中接管；修改后需要重新验收。</p></section>
<section><h2>怎么运行</h2><ol><li>保持 CARLA 打开 map10，结束其他正在控车的场景。</li><li>运行项目根目录的 <code>Run-Case172.cmd P02</code>，先看前车制动示例；也可使用下面的命令。</li><li>在场景编辑器里选择以 <code>P01 ·</code> 至 <code>P26 ·</code> 开头的场景，再点运行。JSON 导入也使用同一物理引擎。</li></ol><pre>python tools/build_case172_scenes.py --install
python tools/run_case172.py --ids P02
python tools/run_case172.py --all
python -m scene_studio.server</pre><p>编辑器地址：<a href="http://127.0.0.1:8877/">http://127.0.0.1:8877/</a>。每次运行保存在 <code>studio_data/runs/case172_时间_P编号/</code>，包含实际轨迹、控制量、条件触发、碰撞、截图及验收结果。运行结束后恢复世界设置，并只清理本次创建的参与者。</p></section>
<section><h2>验收口径</h2><p>每项检查完整时长、0.05 秒步长、真实物理状态、碰撞、事件触发、相机输出和资源清理，再检查本场景特有行为，例如停住、变道完成、先让行后通过。报告只承认与当前场景文件和运行代码哈希一致的结果；失败记录仍保留。</p><p>初速允许物理稳定过程产生少量偏差：限值为 1.5 km/h 与设定初速 3% 中的较大者；P04 另检查实速处于来源案例的 72–84 km/h 范围。参与者轮廓逐帧检查不重叠。行人下路缘的零冲量接触单列保留，仅当轨迹证明正常继续行走且下降不足 0.3 米时归为地面接触；其他接触仍判失败。</p><p>截图是传感器逐秒取样，标题显示实际采样时刻。速度图来自物理轨迹记录。通过仅说明本次配置和本次运行的结果，不证明任意改参都安全。车道线仅作为现有地图背景，本轮未修改 XODR；道路连接取自运行中的地图。</p><p><a href="delivery_audit.json">最终交付审查</a> · <a href="editor_acceptance.json">编辑器实际运行验收</a> · <a href="../code_audit_20261010/offline_tests.log">本轮离线回归记录</a></p></section><nav>'''
    body+=''.join(f'<a href="#{p["id"]}">{p["id"]} {esc(p["name"])}</a>' for p in catalog['patterns'])+'</nav>'
    indexed=[]
    for p in catalog['patterns']:
        pid=p['id'];sid='Case172_'+pid;scene=read(OUT/'scenes'/(sid+'.json'));meta=scene['case172'];r,folder=results.get(sid,(None,None))
        body+=f'<section id="{pid}"><h2>{esc(scene["name"])}</h2><p>{esc(meta["interaction"])}</p><p><b>迁移边界：</b>{esc(meta["transfer"])}</p><p><b>案例依据：</b>'+', '.join(f'<a href="coverage.html#{cid}">{cid[-4:]}</a>' for cid in meta['source_cases'])+'</p>'
        body+=f'<p><b>设计验收：</b>{esc(meta["acceptance_intent"])}</p><p><a href="scenes/{sid}.json">场景 JSON</a> · 仿真时长 {scene["duration"]:g} 秒</p><table><tr><th>参与者</th><th>设定初速</th><th>控制安排</th></tr>'
        for a in scene['actors']:
            desc=[]
            for c in a['clips']:
                label={'follow':'跟随 '+c.get('target',''),'speed':'速度调整至 '+str(c.get('value',''))+' km/h','brake':'制动','lane_change':'向'+('左' if c.get('direction')=='left' else '右')+'变道'}.get(c['type'],c['type'])
                desc.append(f'{c["start"]:g}–{c["start"]+c["duration"]:g} s：{label}')
            for e in scene['events']:
                if e['action'].get('actor')==a['id']:desc.append(EVENT_NAMES.get(e['id'],e['id']))
            body+=f'<tr><td>{esc(NAMES.get(a["id"],a["name"]))}</td><td>{a["speed"] if a["start_in_motion"] else 0:g} km/h</td><td>{esc("；".join(desc) or "沿指定路径行驶 / 保持停止")}</td></tr>'
        body+='</table>'
        if r and r.get('error'):
            body+='<p class="tag fail">实测运行失败</p><pre>'+esc(r['error'])+'</pre></section>'
            indexed.append(r);continue
        if r:
            body+=f'<h3 class="{"pass" if r["passed"] else "fail"}">{"实测通过" if r["passed"] else "实测未通过"} · {sum(c["passed"] for c in r["checks"])} / {len(r["checks"])} 项</h3>'
            frames=[json.loads(x) for x in (folder/'trajectory.jsonl').read_text(encoding='utf-8').splitlines()]
            body+=speed_plot(frames)
            shots=sorted(folder.glob('shot_*.jpg'))
            ev=read(folder/'events.json');release=[v for k,v in ev['fired'].items() if 'clear' in k]
            clips=[c for a in scene['actors'] for c in a['clips'] if c['type'] in ('speed','brake','lane_change')]
            critical=max(release)-.5 if release else min([c['start']+min(2,c['duration']/2) for c in clips] or [scene['duration']/2])
            chosen=list(dict.fromkeys(min(shots,key=lambda x:abs(int(x.stem.split('_')[1])/1000-t)) for t in [0,critical,scene['duration']])) if shots else []
            body+='<div class="shots">'
            assets=OUT/'images'/pid;assets.mkdir(parents=True,exist_ok=True)
            for im in shots:shutil.copy2(im,assets/im.name)
            for im in chosen:
                target=assets/im.name;shutil.copy2(im,target);t=int(im.stem.split('_')[1])/1000
                body+=f'<figure><a href="images/{pid}/{im.name}"><img loading="lazy" src="images/{pid}/{im.name}" alt="{pid} {t:g}秒实测截图"></a><figcaption>{t:g} 秒 · CARLA RGB 相机</figcaption></figure>'
            body+='</div>'
            if shots:
                gallery=[dict(src=f'images/{pid}/{im.name}',t=int(im.stem.split('_')[1])/1000) for im in shots]
                body+=f'''<details><summary>逐秒查看实测画面</summary><div class="player"><p><output>{gallery[0]['t']:g} 秒</output> · 拖动时间条查看</p><input aria-label="{pid}实测画面时间" style="width:100%" type="range" min="0" max="{len(shots)-1}" value="0" data-frames="{esc(json.dumps(gallery))}" oninput="const f=JSON.parse(this.dataset.frames)[this.value];this.parentElement.querySelector('img').src=f.src;this.parentElement.querySelector('output').value=f.t+' 秒'"><img loading="lazy" src="{gallery[0]['src']}" alt="{pid}逐秒实测画面"></div></details>'''
            body+='<details><summary>实测细节与原始记录</summary><table><tr><th>检查</th><th>结果</th><th>测量或要求</th></tr>'
            for c in r['checks']:
                detail=c['details']
                if c['name']=='资源与世界恢复':detail=dict(remaining=detail['remaining'],settings_restored=detail['before']==detail['after'])
                body+=f'<tr><td>{esc(c["name"])}</td><td>{"通过" if c["passed"] else "失败"}</td><td>{esc(json.dumps(detail,ensure_ascii=False))}</td></tr>'
            relative='../../studio_data/runs/'+folder.name
            body+=f'</table><p>运行：{folder.name}<br><a href="{relative}/verification.json">完整验收 JSON</a> · <a href="{relative}/telemetry.csv">逐帧数据</a> · <a href="{relative}/events.json">事件和碰撞</a></p></details>'
            indexed.append(r)
        else:body+='<p class="tag fail">当前版本尚待实测</p>'
        body+='</section>'
    body+=f'<footer><p>源文档 SHA-256：<code>{catalog["source_sha256"]}</code><br>运行地图 XODR SHA-256：<code>{build["xodr_sha256"]}</code></p></footer>'
    (OUT/'index.html').write_text(page('172例交通交互场景库',body),encoding='utf-8')
    body='<h1>172 例逐案用途</h1><p><a href="index.html">返回场景库</a>。保留原文的观测与限制；“未作交互来源”不等于删除案例，也不等于认定没有风险。</p>'
    for c in coverage['cases']:
        body+=f'<section id="{c["case_id"]}"><h2>{c["case_id"][-4:]} · {esc(c["title"])}</h2><p><b>用于：</b>'+('、'.join(f'<a href="index.html#{pid}">{pid}</a>' for pid in c['patterns']) or esc(c['reason']))+f'</p><p>{esc(c["summary"])}</p><p><b>可见情境：</b>{esc(c["scene"])}</p><p><b>解释限制：</b>{esc(c["prediction"]["limitations"])}</p></section>'
    (OUT/'coverage.html').write_text(page('172例逐案用途',body),encoding='utf-8')
    (OUT/'acceptance.json').write_text(json.dumps(dict(passed=n==total,current_passed=n,required=total,results=indexed,history=history,source_sha256=catalog['source_sha256'],code_hashes=current),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Current verified: {n}/{total}; report: {OUT / "index.html"}')

if __name__=='__main__':main()
