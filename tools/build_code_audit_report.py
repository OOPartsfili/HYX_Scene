"""Build the local audit summary from completed regression artifacts."""
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'optimization_reports/code_audit_20261010'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}


def current_run(rid):
    manifest = read(ROOT / 'studio_data/runs' / rid / 'run_manifest.json')
    hashes = manifest.get('code_sha256', {})
    return bool(hashes) and all((ROOT / p).is_file() and hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == v for p, v in hashes.items())


def main():
    offline = (OUT / 'offline_tests.log').read_text(encoding='utf-8-sig')
    frontend = (OUT / 'frontend_tests.log').read_text(encoding='utf-8-sig')
    offline_count = int(re.search(r'Ran (\d+) tests', offline)[1])
    frontend_count = int(re.search(r'# tests (\d+)', frontend)[1])
    core = read(OUT / 'live/runtime_acceptance.json')
    edges = read(OUT / 'live/replay_edge_acceptance.json')
    presets = read(OUT / 'live/preset_acceptance.json')
    alignment = read(OUT / 'live/all_camera_alignment.json')
    cases = read(ROOT / 'optimization_reports/case172_scenarios/delivery_audit.json')
    case_hashes = cases.get('current_code_hashes', {})
    cases_current = bool(case_hashes) and all((ROOT / p).is_file() and hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == v for p, v in case_hashes.items())
    live_ids = [core.get(k, '') for k in ('baseline', 'golden_replay', 'manual_replay')]
    live_ids += [r['run'] for r in edges.get('repeated_replays', [])]
    live_ids += [edges.get('paused_takeover', {}).get('run', '')]
    live_ids += [r['run'] for r in presets.get('results', [])]
    live_ok = bool(core.get('world_restored') and core.get('watchdog_verified') and core.get('stale_input_rejected') and edges.get('passed') and presets.get('passed'))
    live_ok = live_ok and len(live_ids) == 14 and all(current_run(r) for r in live_ids)
    live_ok = live_ok and alignment.get('passed', False) and set(alignment.get('runs', {})) == set(live_ids)
    checks = {
        'offline': {'passed': bool(re.search(r'^OK\s*$', offline, re.M)), 'count': offline_count},
        'frontend': {'passed': bool(re.search(r'^# fail 0\s*$', frontend, re.M)), 'count': frontend_count},
        'live': {'passed': live_ok, 'runs': live_ids},
        'case172': {'passed': cases_current and cases.get('passed', False), 'count': cases.get('verified_scenarios', 0) if cases_current else 0},
    }
    passed = all(v['passed'] for v in checks.values())
    summary = {'generated': datetime.now().isoformat(timespec='seconds'), 'passed': passed, 'checks': checks,
               'scope': '当前代码与 map10 指定配置；不构成零缺陷或任意实验有效性的保证',
               'editor': 'http://127.0.0.1:8879/'}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    fixes = [
        ('编辑不再被旧请求覆盖', '修复保存过程中继续修改、切换对象、预设或路线请求返回过晚等竞态；启动时固定场景快照。空数字输入不再被当成 0，Esc 取消切换会恢复选择，取消拖动会恢复原值。', '前端回归与真实浏览器草稿操作'),
        ('同一控制通道禁止冲突配置', '拒绝同一车辆、同一通道同时使用条件事件和时间轴片段；严格验证布尔值、对象形状、参与者类型和 dt。避免一套动作刚生效就被另一套静默覆盖。', '服务端与配置回归；现有 51 份场景及模板兼容性检查'),
        ('制动时继续沿路线转向', '制动片段原来提前返回零转向指令；现在保留路线控制器的转向，再覆盖纵向油门与刹车。灯光片段结束后恢复片段之前的状态。', '控制器回归；26 场景与 7 个行为预设实测'),
        ('重放检查真实记录完整性', '新录制增加轨迹校验和；检查帧序、时间、步长、参与者、有限数值与运动配置。按实际时间检索历史末帧，并区分记录正常关闭和覆盖完整试次。', '录制回归；逐帧重放实测'),
        ('截图和碰撞使用采样帧时间', '截图按真实帧号与遥测对齐，排除延迟进入正式运行的预热帧；无法映射的相机帧不伪造时间。碰撞缺失时间保留 null，界面显示帧号和“时间未映射”。', '帧时间回归；实际截图与遥测对应检查'),
        ('连续运行和异常退出可恢复', '结果保存完成后才发布“结束”，并等待已结束的工作进程退出后接续下一场；相机停止失败仍尝试销毁。遥测关闭、天气、世界设置与录制关闭分别处理，避免前一步异常跳过后续恢复。', '故障注入回归；连续实机录制、重放及资源恢复检查'),
        ('旧路线缓存自动重算', '规划器考虑条件事件可能提高的目标速度，修复路径过短；修正无路线行人与停放车辆预演。加入规划器版本，旧计划不会静默复用。', '规划与缓存回归；当前版本场景实测'),
        ('实验结果能够追溯', '每次运行保存 run_manifest.json：代码、地图、场景指纹及 CARLA/Python 版本、步长、种子；可通过运行文件接口下载。补上运动哈希遗漏的触发依赖。', '清单文件与下载路由回归；实机记录'),
    ]
    priorities = [
        ('01', '先补实验时钟与延迟测量', '记录“相机采样 → 屏幕显示 → 原始按键 → 控制应用”的时间链，输出实际运行速度、掉帧和输入延迟。当前仿真时间不能直接充当人的毫秒级反应时。'),
        ('02', '校准毕设实际使用的车型', '逐车型验收速度误差、超调、稳定时间、制动距离与横向偏差。目标加减速度限制只约束控制目标，不等于实际车辆加减速度。'),
        ('03', '加入试次管理和有效性检查', '保存被试编号、条件、重复次数、顺序和每次实际抽取的参数；输出一行一试次的数据表与剔除原因。当前 seed 仅记录，还没有控制参数随机抽样。'),
        ('04', '明确安全参数与两种实验模式', '速度上下限、连续安全参数关键帧和二维安全场仍需实现与定义。固定轨迹重放适合视觉刺激对照；接管后背景车仍沿录制轨迹运动，不能用于推断双向闭环交通响应。'),
    ]
    esc = html.escape
    state = '列出的回归全部通过' if passed else '验收尚未全部完成'
    cards = ''.join(f'<article><b>{v["count"]}</b><span>{label}</span></article>' for v, label in [(checks['offline'], 'Python 回归'), (checks['frontend'], '前端回归'), (checks['case172'], '交通场景实测')])
    cards += f'<article><b>{len(live_ids) if live_ok else "—"}</b><span>录制、重放与预设运行</span></article>'
    fix_rows = ''.join(f'<tr><th>{esc(t)}</th><td>{esc(d)}</td><td>{esc(e)}</td></tr>' for t, d, e in fixes)
    ideas = ''.join(f'<article class="priority"><span>{n}</span><div><h3>{esc(t)}</h3><p>{esc(d)}</p></div></article>' for n, t, d in priorities)
    baseline = core.get('baseline', '')
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CARLA 辅助软件 · 代码审核</title>
<style>body{{margin:0;background:#f3f6f8;color:#18333f;font:16px/1.75 "Microsoft YaHei",sans-serif}}main{{max-width:1080px;margin:auto;padding:45px 28px 70px}}h1{{font-size:34px;line-height:1.3;margin:12px 0 20px}}h2{{font-size:24px;margin:0 0 18px}}h3{{font-size:18px;margin:0 0 5px}}p{{margin:8px 0 16px}}small,.muted{{color:#58717c}}a{{color:#096b86}}.badge{{display:inline-block;padding:4px 12px;background:#deeee5;color:#25614e;border-radius:6px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}}.cards article,section{{background:white;border:1px solid #d8e3e8;border-radius:10px}}.cards article{{padding:20px}}.cards b{{display:block;font-size:34px;color:#146e7d}}.cards span{{font-size:14px}}section{{padding:26px;margin:22px 0;scroll-margin-top:20px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;border-bottom:1px solid #e2e9ed;padding:13px 8px;vertical-align:top}}th{{width:19%}}td:last-child{{width:24%;color:#58717c}}.priority{{display:flex;gap:18px;padding:18px 0;border-bottom:1px solid #e2e9ed}}.priority>span{{font-size:24px;color:#167a83;font-weight:bold}}.priority p{{margin:4px 0}}.note{{border-left:4px solid #bd8d3e;padding:12px 16px;background:#fff6e6}}nav{{display:flex;gap:16px;flex-wrap:wrap}}code{{overflow-wrap:anywhere}}@media(max-width:700px){{main{{padding:24px 15px}}h1{{font-size:27px}}section{{padding:18px}}.cards{{grid-template-columns:repeat(2,1fr)}}table{{font-size:12px}}td:last-child{{width:20%}}}}</style>
<main><header><small>代码审核 · map10 实机回归 · {esc(summary['generated'])}</small><h1>CARLA 辅助软件代码审核</h1><p class="badge">{state}</p><p>已修复编辑竞态、控制冲突、录制完整性、帧时间与退出清理等问题。通过只覆盖本报告列出的代码版本、地图和测试配置，不能证明软件绝对没有 BUG。</p><nav><a href="http://127.0.0.1:8879/">打开本轮验收的编辑器</a><a href="../case172_scenarios/index.html">查看 26 个实测场景与截图</a><a href="#research">毕设应优先补什么</a><a href="summary.json">验收索引</a></nav></header>
<div class="cards">{cards}</div>
<section><h2>这次实际修了什么</h2><table><thead><tr><th>问题</th><td>修复后的行为</td><td>验证方式</td></tr></thead><tbody>{fix_rows}</tbody></table></section>
<section><h2>测试证据与范围</h2><ul><li><a href="offline_tests.log">Python 回归日志</a>：配置、服务端、控制器、轨迹与异常恢复。日志内的注入异常用于验证失败路径，最终以测试汇总为准。</li><li><a href="frontend_tests.log">前端回归日志</a>：运行真实前端函数并模拟网络与界面依赖；另在真实浏览器验证了空数值恢复及 Esc 取消场景切换保留草稿。</li><li><a href="case172_regression.log">26 场景运行日志</a>与<a href="../case172_scenarios/delivery_audit.json">最终场景审查</a>：当前运行代码与场景指纹一致，检查轨迹、特定交互、碰撞和世界恢复。</li><li><a href="live/runtime_acceptance.json">录制/重放与接管</a>、<a href="live/replay_edge_acceptance.json">重复重放/暂停接管</a>、<a href="live/preset_acceptance.json">7 个行为预设</a>：逐帧比较姿态与速度，验证输入中断制动、旧输入拒绝、截图对齐和清理。</li><li><a href="live_tests_final.log">连续运行完整日志</a>。首次测试发现的进程退出竞态保留在<a href="live_tests.log">首次失败日志</a>中。</li></ul><p>示例运行：<code>{esc(baseline)}</code> · <a href="../../studio_data/runs/{esc(baseline)}/run_manifest.json">版本与配置清单</a></p><p class="muted">本轮没有修改地图资产或 XODR；没有实物方向盘，硬件兼容性与力反馈不在实测范围内。已启动的旧服务不会自动重新加载 Python 代码，本轮验收地址为 8879。</p></section>
<section><h2>尚未解决的一个关键精度问题</h2><p class="note">“设定了某个速度”不等于“车辆始终保持这个实速”。现有 Audi 测试中，前 3 秒目标为 20 km/h，实测为 14.42–22.84 km/h，均方根误差 2.72 km/h。当前通用控制器和起步初始化仍需车型校准，不能把通过场景行为测试写成速度精度已经达标。</p><p>数据来自既有运行 <code>20261010_155707_2f4718</code>，60 个采样点；不是本轮 26 个固定配置的验收结论。需要针对使用车型验证初始化与控制器响应。</p><p><a href="../../studio_data/runs/20261010_155707_2f4718/trajectory.jsonl">原始轨迹</a> · <a href="../../studio_data/runs/20261010_155707_2f4718/scene.json">对应配置</a></p></section>
<section id="research"><h2>更适合毕设：按这个顺序提升</h2>{ideas}<p class="muted">当前每秒保存首张可用截图，不能据此精确确定危险显现的毫秒时刻；complete=true 也不代表完成计划全程，需同时检查 covers_scene_duration 和关键研究事件。</p></section>
<footer><p>结论：当前版本可继续用于场景制作与指定配置下的仿真验证。正式人因实验前，应优先完成时钟测量、车型校准和试次有效性判定。</p></footer></main></html>'''
    (OUT / 'index.html').write_text(body, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
