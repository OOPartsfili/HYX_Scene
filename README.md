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

完整图文式说明：[使用说明](scene_studio/web/guide.html)。启动服务后访问 `/static/guide.html` 可直接阅读。

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
| `scene_studio/recording.py` | 每帧记录与按帧索引的基准重放 |
| `scene_studio/templates/` | 随代码附带的场景；首次启动复制到本地场景库 |
| `studio_data/scenes/` | 本机保存的场景 JSON |
| `studio_data/runs/<id>/` | 实际轨迹、telemetry CSV、事件、截图与运行配置 |

运行数据、被试数据、缓存、录制媒体和本地历史不会上传。分享环境场景时需同时分享其基准运行目录中的 `take.json` 与 `trajectory.jsonl`，单独场景 JSON 不包含轨迹。

## 验证

离线测试：

```powershell
python -m unittest discover -s tests -v
```

在空闲 map10、编辑器服务已启动时执行实机验收（会创建并清理测试车辆）：

```powershell
python tools/test_studio_v2_live.py
python tools/test_studio_replay_edges.py
python tools/test_studio_presets_live.py
```

第一项验证实际录制/重放的逐帧姿态与速度、手动优先级、背景车一致性、输入中断制动和旧输入拒绝。第二项重复检查不同光照的重放一致性，并验证暂停时接管保留速度。第三项逐一验证七种行为预设的速度、横向运动与碰撞记录。结果写入本地 `optimization_reports/studio_v2/`。

编辑器预演不模拟动态跟车、条件触发和碰撞。旧 Scene 条件事件模板保留，新的物理控制不保证旧试次轨迹完全一致。正式实验需另行核验风险显现时刻、车距和接管时序。

## 许可

项目沿用 [Apache-2.0](LICENSE)。CARLA agents 源文件保留其 MIT 版权标注；Three.js 与 controls 使用 [MIT](scene_studio/web/vendor/THREE-LICENSE.txt)。
