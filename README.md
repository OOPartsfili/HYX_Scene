# HYX Scene Studio

基于 CARLA 0.9.15 的本机场景编辑器：车辆路线和速度时间轴、行为预设、主车手动接管，以及固定实际轨迹的光照和天气对照。

## 启动

需要 Python 3.10、CARLA 0.9.15 服务端，以及原项目的自定义 map10。地图和 UE 工程资产不包含在本仓库中。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-studio.txt
.\.venv\Scripts\python.exe -m scene_studio.server
```

先在 CARLA / UE 编辑器打开 map10 并点击 Play，再访问 **http://127.0.0.1:8877/**。也可以双击 `Start-SceneStudio.cmd`；优先使用项目 `.venv`。

默认 CARLA 地址 `127.0.0.1:2000`。编辑器服务仅允许本机访问，运行期间由工作进程统一推进固定步长仿真。停止后恢复原天气与世界设置，只清理自身创建的参与者。

## 使用与维护手册

- [用户手册](docs/user-manual.md)：含 13 张带编号的真实操作截图，先按五步图解完成第一次录制，再学习车辆与路线、时间轴、接管、环境对照、数据核验和排错。网页图片可点击放大。
- [开发维护手册](docs/developer-maintenance-manual.md)：架构、接口、数据格式、时钟与控制权、回归验证、故障恢复和智能体接手步骤。

编辑器的“使用说明”打开[用户手册阅读版](scene_studio/web/guide.html)，同页可切换到[开发维护阅读版](scene_studio/web/maintenance.html)。服务启动后分别访问 `/static/guide.html` 与 `/static/maintenance.html`。阅读版有章节目录、移动端布局和打印样式，无需联网。

两份 Markdown 是正文来源。修改后安装可选文档依赖 `requirements-docs.txt`，执行 `python tools/build_manuals.py` 生成网页，再执行 `python tools/build_manuals.py --check` 检查一致性；不要直接修改生成网页。

## 导出可直接运行的 Python 场景

在编辑器“文件”菜单选择 **导出可运行 .py**，选择 10、20、40 或 60 Hz，下载的文件包含当前尚未保存的场景和输入设备设置。CARLA 打开对应地图并进入 Play 后，用 Python 3.10 运行它：

```powershell
python .\HYX_场景编号_60Hz.py
```

该脚本直接连接本机 CARLA，不需要编辑器网页或 Flask 服务；仍依赖本仓库的 `scene_studio` 代码与安装好的依赖。移动项目后可用 `--project-root E:\你的项目目录` 指定代码位置。本机 `.py` 双击默认打开 VS Code，可在其中点击“运行 Python 文件”。默认显示实时相机窗口，M 接管、R 恢复自动、W/S/A/D 驾驶、空格制动、Q 或 Esc 结束；自动运行可加 `--no-window`。

每次运行写到 `studio_data/runs/py_.../`。车辆状态见 `telemetry.csv`，逐帧轨迹见 `trajectory.jsonl`，事件见 `events.json`，窗口驾驶输入见 `driver_input.csv`，完整性见 `take.json`；不采集眼动。固定轨迹环境场景还需要原基准运行目录。60 Hz 已通过短时车辆状态和相机窗口测试，不能视为显示、输入和眼动均已达到 60 Hz。

## 两种工作方式

### 运动编排

1. 从场景库选择“时间轴示例 · 加速与变道”，或新建场景。
2. 在三维道路视图中布置车辆、绘制路线；主车和背景车均可应用匀速、起停、急刹、切入、超车、跟车或静止预设。
3. 底部时间轴支持片段拖动、拉伸与时间吸附。右侧编辑目标速度、车道方向、跟车目标、反应时间和车距。
4. 编辑器“预演”计算路线与速度估计；“运行并录制”使用 CARLA 物理控制，记录实际轨迹。

### 固定轨迹的环境调整

1. 完成一次运动录制后，在“轨迹录制库”选择基准。
2. 车辆、路线、速度和时间轴锁定，服务端校验运动字段哈希。
3. 调整太阳角度、云量、雾、雨量、湿润、曝光与相机参数，重新播放。
4. 重放时关闭车辆物理，逐帧批量提交录制位置与姿态。相同时间的截图可用于视觉 A/B 对照。

这是一种位置重放，不能作为不同天气下轮胎、摩擦和碰撞的物理复算。map10 部分导入材质与天空蓝图对湿润、雨天参数支持有限；本仓库未重建地图材质。

## 手动驾驶

运行或重放中按 **M** 接管，**W/S** 油门与制动、**A/D** 转向、**空格**全制动，**R**恢复自动。浏览器需保持焦点。手动控制优先于时间轴；超过约 0.35 秒无有效输入时制动并保持手动控制权。

固定轨迹重放中接管会恢复主车物理并标记 `manual_override`；背景车继续重放。恢复自动不会把主车传送回原位置，也不会清除偏离标记。

“输入 ⚙”可配置浏览器 Gamepad API 手柄/方向盘，包括转向轴、死区与踏板轴标定。开发机器无实物手柄/方向盘，硬件兼容性未实测；不含力反馈支持。原项目 Logitech 等硬件脚本依赖本地 SDK，不是编辑器启动依赖。

## 数据与代码

| 位置 | 内容 |
|---|---|
| `scene_studio/web/` | 本地前端、Three.js 与使用说明 |
| `scene_studio/engine.py` | 固定步长运行、控制权仲裁、物理驾驶与重放 |
| `scene_studio/timeline.py` | 行为预设、片段求值、输入序号与看门狗 |
| `scene_studio/planning.py` | 道路路线规划与估计预演 |
| `scene_studio/recording.py` | 每帧记录、完整性校验与按实际时间索引的基准重放 |
| `scene_studio/templates/` | 随代码附带的场景；首次启动复制到本地场景库 |
| `studio_data/scenes/` | 本机保存的场景 JSON |
| `studio_data/runs/<id>/` | 实际轨迹、telemetry CSV、事件、截图与运行配置 |

运行数据、被试数据、缓存、录制媒体和本地历史不会上传。分享环境场景时需同时分享其基准运行目录中的 `take.json` 与 `trajectory.jsonl`，单独场景 JSON 不包含轨迹。

每次新运行还保存 `run_manifest.json`：CARLA/Python 版本、地图与代码指纹、场景指纹、步长和种子。新录制包含轨迹校验和；旧录制可读取，但无法追溯检测所有历史数值修改。`take.json` 中 `complete` 表示该记录段正常关闭，`covers_scene_duration` 才表示覆盖计划全程，提前停止的试次应单独判断有效性。

当前种子仅被保存，尚未驱动条件随机抽样。仿真事件时间、传感器采样时间和被试看见画面的现实时间含义不同；当前没有测量完整的显示与输入延迟，不能直接用仿真时间差报告毫秒级人的反应时。目标速度与实际速度也需要按实验使用的车型独立校准。

## 验证

离线测试：

```powershell
python -m unittest discover -s tests -v
node tests/frontend_audit.mjs
```

在空闲 map10、编辑器服务已启动时执行实机验收（会创建并清理测试车辆）：

```powershell
python tools/test_studio_v2_live.py
python tools/test_studio_replay_edges.py
python tools/test_studio_presets_live.py
```

第一项验证实际录制/重放的逐帧姿态与速度、手动优先级、背景车一致性、输入中断制动和旧输入拒绝。第二项重复检查不同光照的重放一致性，并验证暂停时接管保留速度。第三项逐一验证七种行为预设的速度、横向运动与碰撞记录。结果写入本地 `optimization_reports/studio_v2/`。

编辑器预演不模拟动态跟车、条件触发和碰撞。旧 Scene 条件事件模板保留，新的物理控制不保证旧试次轨迹完全一致。正式实验需另行核验风险显现时刻、车距和接管时序。

本轮代码审核报告位于 `optimization_reports/code_audit_20261010/index.html`。对指定编辑器端口依次运行上述三组实机测试可使用 `python tools/test_audit_live.py --port 8877`；测试期间须让 CARLA 空闲，不能与另一个推进仿真的客户端同时运行。通过结果只覆盖报告中列出的配置与断言，不代表任意地图、车型和参数均已验证。

## 172 案例交通交互场景库

`optimization_reports/case172_scenarios/index.html` 包含 26 类场景的设计依据、逐秒实测截图、速度曲线和当前版本验收结果。`coverage.html` 保留全部 172 例的用途及解释限制。

在空闲的 map10 中，可双击 `Run-Case172.cmd` 运行前车制动示例，或执行：

```powershell
python tools/run_case172.py --ids P02 P13
python tools/run_case172.py --all
```

场景已安装到 `studio_data/scenes/`，在场景编辑器中选择 `P01 ·` 至 `P26 ·` 即可运行、编辑和手动接管。生成器可重新编译路线并安装；不会更改地图：

```powershell
python tools/build_case172_scenes.py --install
python tools/audit_case172_delivery.py
python tools/build_case172_report.py
```

场景使用物理控制；预热和初速初始化完成后才开始实验时钟。原案例中的时刻、车距和致因未充分标定，因此保留交通交互结构，另行设定仿真参数。环岛、停车场等几何替代方式逐项注明。主车是读取仿真状态的基准控制器，未模拟原案例中的辅助驾驶产品。

运行目录 `studio_data/runs/case172_*/` 保存 `scene.json`、`trajectory.jsonl`、`telemetry.csv`、`events.json`、`verification.json` 及世界恢复记录。改参或改代码后，应重新运行；历史通过结果不会替代当前配置的验收。

## 许可

项目沿用 [Apache-2.0](LICENSE)。CARLA agents 源文件保留其 MIT 版权标注；Three.js 与 controls 使用 [MIT](scene_studio/web/vendor/THREE-LICENSE.txt)。
