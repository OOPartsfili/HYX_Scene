"""Build a self-contained local index for a completed render benchmark folder."""
import argparse
import json
import statistics
from pathlib import Path
from html import escape

parser = argparse.ArgumentParser()
parser.add_argument('folder', type=Path)
args = parser.parse_args()
out = args.folder.resolve()
result = json.loads((out / 'results.json').read_text(encoding='utf-8'))
labels = {'baseline': '修改前', 'quality': 'quality · 原尺寸',
          'balanced': 'balanced · 前视 75%', 'performance': 'performance · 前视 50%'}
summary = {}
for name in labels:
    runs = [r for r in result['runs'] if r['profile'] == name]
    fps = [r['cameras']['front']['displayed_unique_fps'] for r in runs]
    summary[name] = dict(front_fps=statistics.mean(fps), minimum=min(fps), maximum=max(fps),
        server_fps=statistics.mean(r['server_fps'] for r in runs),
        received_fps=statistics.mean(r['cameras']['front']['received_fps'] for r in runs),
        mirror_fps=statistics.mean(r['cameras']['left']['displayed_unique_fps'] for r in runs),
        display_fps=statistics.mean(r['display_fps'] for r in runs))
(out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
gain = (summary['quality']['front_fps'] / summary['baseline']['front_fps'] - 1) * 100
rows = ''.join(f'<tr><th>{labels[k]}</th><td>{v["front_fps"]:.1f}</td><td>{v["minimum"]:.1f}–{v["maximum"]:.1f}</td><td>{v["received_fps"]:.1f}</td><td>{v["mirror_fps"]:.1f}</td><td>{v["display_fps"]:.1f}</td><td>{v["server_fps"]:.1f}</td></tr>' for k, v in summary.items())
best = max(summary, key=lambda k: summary[k]['front_fps'])
html = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>map10 实机复测：画面与速度</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf2f4;color:#19313b;font:16px/1.8 'Microsoft YaHei',sans-serif}main{max-width:1400px;margin:auto;padding:32px 26px}h1{font-size:38px;line-height:1.35}h2{font-size:24px}section{background:white;border:1px solid #d5e1e5;border-radius:12px;padding:24px;margin:22px 0}.tag{color:#087f70;font-weight:bold}.muted,small{color:#60727b}select,button{font:inherit;padding:7px 12px;border:1px solid #bccdd3;border-radius:5px;background:white}input{width:260px;accent-color:#087f70}.tools{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:16px 0}.image{position:relative;aspect-ratio:5740/1010;background:#152a35;overflow:hidden}.image img{position:absolute;width:100%;height:100%;inset:0}.image #after{clip-path:inset(0 50% 0 0)}#line{position:absolute;left:50%;height:100%;border-left:2px solid white}.labels,.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair canvas{width:100%;height:auto;border:1px solid #d5e1e5}.metric{font-size:36px;font-weight:bold;color:#087f70}.notice{border-left:4px solid #c89b36;background:#fff8e8;padding:16px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap}td,th{text-align:left;border-bottom:1px solid #d5e1e5;padding:10px}thead{background:#edf4f5}a{color:#087f70}code{overflow-wrap:anywhere}pre{white-space:pre-wrap}li{margin:6px 0}@media(max-width:750px){main{padding:15px}.pair{grid-template-columns:1fr}h1{font-size:28px}}
</style><main><header><div class="tag">MAP10 / 本次实机复测 / @DATE</div><h1>修改前后，画面与速度一起看。</h1><p>同一位置、同一天气、同一组 5 辆车，四路 CARLA RGB 相机。每档两轮，每轮预热 8 秒、计时 30 秒；第二轮反向测试，截图保存不计入测速。</p><div class="metric">quality @GAIN% <small>前视新画面速度变化</small></div><p>原版 @BASE FPS → quality @QUALITY FPS。当前最快：<b>@BEST</b>。</p></header>
<section><h2>01 · 同位置画面对照</h2><p>拖动分界线比较；切换档位查看降低采样尺寸的影响。全景按屏幕缩小显示，细节区来自原图裁切。</p><div class="tools"><select id="profile" aria-label="优化档位"><option value="quality">quality · 原尺寸</option><option value="balanced">balanced · 前视 75%</option><option value="performance">performance · 前视 50%</option></select><input id="split" type="range" min="0" max="100" value="50" aria-label="画面对照分界线"></div><div class="labels"><b id="label">左：quality 修改后</b><b style="text-align:right">右：修改前</b></div><div class="image"><img id="before" src="baseline_composite.png" alt="修改前真实驾驶画面"><img id="after" src="quality_composite.png" alt="修改后真实驾驶画面"><div id="line"></div></div><p><a href="baseline_composite.png" target="_blank">修改前原图</a> · <a id="after-link" href="quality_composite.png" target="_blank">修改后原图</a> · <a id="native" href="quality_front_native.png" target="_blank">当前档相机原生图</a></p><div class="tools"><label>放大区域 <select id="detail"><option value="front">前车与路面</option><option value="left">左后视镜</option><option value="right">右后视镜</option></select></label></div><div class="pair"><div>修改前<canvas id="crop-before" width="1000" height="500"></canvas></div><div>修改后<canvas id="crop-after" width="1000" height="500"></canvas></div><p>quality 保留 5740×1010 前视采样尺寸，后视镜采样上限降至 30 Hz；左右后视镜改为水平镜像。性能收益包含减少镜面更新负载，并非完全相同采样设置下的纯代码加速。balanced 前视为 4305×758，performance 为 2870×505，再缩放回原显示尺寸。地图建筑、材质和天气沿用当前场景。</p><p class="muted">静止截图无法验证运动模糊改善。异步渲染的抗锯齿与天空细节可能随时间变化，不能将所有像素差异都归因于代码修改。</p></section>
<section><h2>02 · 两轮实测速度</h2><div class="scroll"><table><thead><tr><th>配置</th><th>前视新画面 FPS</th><th>两轮范围</th><th>前视接收 FPS</th><th>左镜新画面 FPS</th><th>窗口刷新 FPS</th><th>世界 tick/s</th></tr></thead><tbody>@ROWS</tbody></table></div><p class="notice">判断实际流畅度请看“前视新画面 FPS”。窗口刷新包含重复画面；世界 tick/s 也不等于相机 FPS。performance 主动将前视限制为 30 Hz、后视镜限制为 15 Hz。降低分辨率会增加 CPU 放大成本，因此档位名称不保证本机实际更快。</p><details><summary>方法、适用范围与原始记录</summary><ul><li>地图：@MAP。CARLA 客户端 @CLIENT，服务器 @SERVER；UE 编辑器运行，异步世界，天气未修改。</li><li>原版：optimization_backup/20261001/Set_sensor.py；优化版：当前 Set_sensor.py。原版仅增加与新版一致的 Arial 字体兼容回退，保留每帧创建字体的逻辑。</li><li>窗口上限 60 Hz。新画面统计实际 blit 的不同 Surface；不是显示器物理刷新率或输入到显示的延迟。</li><li>静态五车、四相机工作负载，两轮短时重复。不能外推为任意地图、车流或正式实验的帧率。</li><li>清理状态：@CLEANUP。</li></ul><a href="results.json">逐轮结果与相机属性</a> · <a href="summary.json">本页汇总 JSON</a><pre>@WEATHER</pre></details></section>
<section><h2>03 · 行驶画面参考</h2><p><a href="../../map10_comparison.html#motion">打开已有同路线行驶对照视频</a>。该页视频与速度数据来自较早测试，不属于本次复测；当前天气画面以本页截图为准。</p></section></main><script>
const before=document.getElementById('before'),after=document.getElementById('after');
function crop(){const boxes={front:[2400,280,1000,500],left:[700,580,670,420],right:[4719,570,655,415]};const box=boxes[document.getElementById('detail').value];for(const [im,id] of [[before,'crop-before'],[after,'crop-after']]){const c=document.getElementById(id);c.height=Math.round(1000*box[3]/box[2]);if(im.complete&&im.naturalWidth)c.getContext('2d').drawImage(im,...box,0,0,c.width,c.height)}}
before.onload=crop;after.onload=crop;document.getElementById('detail').onchange=crop;crop();
document.getElementById('split').oninput=e=>{after.style.clipPath=`inset(0 ${100-e.target.value}% 0 0)`;document.getElementById('line').style.left=e.target.value+'%'};
document.getElementById('profile').onchange=e=>{const p=e.target.value;after.src=p+'_composite.png';document.getElementById('label').textContent='左：'+p+' 修改后';document.getElementById('after-link').href=after.src;document.getElementById('native').href=p+'_front_native.png'};
</script></html>'''
values = {'DATE': result['started'], 'GAIN': f'{gain:+.1f}', 'BASE': f'{summary["baseline"]["front_fps"]:.1f}',
          'QUALITY': f'{summary["quality"]["front_fps"]:.1f}', 'BEST': labels[best], 'ROWS': rows,
          'MAP': result['map'], 'CLIENT': result['client_version'], 'SERVER': result['server_version'],
          'WEATHER': result['weather'], 'CLEANUP': '所有测试车辆已销毁' if all(x.get('destroyed') for x in result.get('cleanup', [])) and result.get('cleanup') else '需检查 results.json'}
for key, value in values.items():
    html = html.replace('@' + key, value if key == 'ROWS' else escape(str(value)))
if all((out / f'{p}_motion.mp4').exists() for p in ('baseline', 'quality')):
    start = html.index('<section><h2>03 ·')
    end = html.index('</section>', start) + len('</section>')
    html = html[:start] + '''<section><h2>03 · 本次同路线行驶对照</h2><p>原版与 quality：相同直线路线、50 km/h 位移速度、12 秒。为对齐视点关闭了车辆物理；这是画质演示，不能用于控车或碰撞真实性验收。</p><div class="tools"><button id="play-both">从头同步播放</button><button id="pause-both">同时暂停</button></div><p>修改前</p><video id="vb" controls muted playsinline preload="metadata" style="width:100%" src="baseline_motion.mp4"></video><p>quality 修改后</p><video id="va" controls muted playsinline preload="metadata" style="width:100%" src="quality_motion.mp4"></video><p class="muted">视频统一缩放为 1920×338、封装为 24 FPS；录制和编码在测速之后进行。视频帧率不能代表实测新画面速度。异步相机和采样延迟使两段不能保证逐帧视点完全一致。</p><a href="motion_results.json">视频采集条件与清理记录</a></section><script>const vb=document.getElementById('vb'),va=document.getElementById('va');document.getElementById('play-both').onclick=async()=>{vb.currentTime=va.currentTime=0;await Promise.allSettled([vb.play(),va.play()])};document.getElementById('pause-both').onclick=()=>{vb.pause();va.pause()};vb.ontimeupdate=()=>{if(!vb.paused&&!va.paused&&Math.abs(vb.currentTime-va.currentTime)>.2)va.currentTime=vb.currentTime};</script>''' + html[end:]
(out / 'index.html').write_text(html, encoding='utf-8')
print(json.dumps({'report': str(out / 'index.html'), 'gain_percent': gain, 'summary': summary}, ensure_ascii=False, indent=2))
