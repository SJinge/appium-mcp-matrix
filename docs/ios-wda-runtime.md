# iOS WDA 真实执行时怎么工作

> 面向「容易忘」的架构备忘。真实执行时 WDA 不是单个进程,是 4 层链路串起来的。
> 代码在 [scripts/ios_wda.py](../scripts/ios_wda.py)、[scripts/wda_proxy.py](../scripts/wda_proxy.py)、
> [scripts/orch_case_runtime_ios.py](../scripts/orch_case_runtime_ios.py);隧道常驻见 [deploy/launchd/README.md](../deploy/launchd/README.md)。

## 请求路径(自上而下)

```
orchestrate / 用例 runtime
   │  HTTP (urllib, W3C WebDriver 协议)
   ▼
127.0.0.1:8100  ← wda_proxy.py(Mac 本地代理)
   │  经 RSD 隧道转发
   ▼
tunneld(LaunchDaemon 常驻,registry http://127.0.0.1:49151/)
   │
   ▼
设备侧 :8100  ← WebDriverAgentRunner(xcodebuild 拉起,跑在 iPhone 上)
   │  XCUITest 私有 API
   ▼
被测 App(高途)
```

**关键心智模型:orchestrate 从不直接碰设备。** 所有操作都是通过 `127.0.0.1:{port}` 打 HTTP 给 WDA,由 WDA 用 XCUITest 驱动 App。

## 四层组件各干什么

| 层 | 是什么 | 归谁管 | 挂了怎么办 |
|----|--------|--------|-----------|
| **tunnel(隧道)** | iOS 17+ 必须的 RSD 隧道,给每个 udid 分配 tunnel-address,注册在 `:49151` | **LaunchDaemon 常驻自愈**,不归 orchestrate | 修 LaunchDaemon(见 deploy/launchd) |
| **WDA test-runner** | `xcodebuild` 把 WebDriverAgentRunner 装到设备上跑,设备侧监听端口;本身是个 HTTP 服务 | `ensure_wda_ready` 保活+自愈 | 判僵尸→杀重建 |
| **wda_proxy.py** | Mac 本地 `127.0.0.1:{port}` ↔ 设备侧端口的转发 | `ensure_wda_ready` | stale 时杀掉重起 |
| **session** | `POST /session {bundleId}` 拉起 App 返回 sessionId,后续操作走 `/session/{id}/...` | 用例 runtime | 掉了 `ensure_session()` 重建 |

### WDA 启动的两条路(`_start_wda`)
- **有 `.xctestrun` 产物** → `test-without-building` 复用已签名产物,~30-60s、**不重签**(免费证书信任不失效)。
- **没有** → 全量 `test` 构建到固定 derivedDataPath,首次要在设备上**信任一次证书**。

### 端口坑(`_device_wda_port`)
设备侧端口**不一定是 8100**,由 xctestrun 里烤进的 `USE_PORT` 决定(Appium 按 wdaLocalPort 烤成 8101/8102...)。proxy 上游必须连对,否则 Connection refused。

## 每台设备的就绪握手(`ensure_wda_ready`)

装完 App 后按序:
1. `health_check(port)` GET `/status` → 已健康就**直接复用**(最快路径);
2. 否则 `tunnel_ready(udid)` → 隧道没起直接失败(去修 LaunchDaemon);
3. `wda_running(udid)`(`pgrep xcodebuild.*id={udid}`)判进程在不在;
4. **僵尸判定**:进程在但不健康时,看构建日志 `/tmp/wda_build_{udid}.log` 时效——
   - `>150s 没动` 或 **无日志**(别处遗留的野进程) → 判僵尸,杀掉重建;
   - 还在动 → 构建/启动进行中,继续等;
5. proxy 在监听却不健康 → 判上游隧道失效,杀掉重起;
6. 轮询 health 到 timeout(180s)。

> **为什么要僵尸判定**:`xcodebuild` 进程活着 ≠ WDA 健康。runner 可能已死但进程不退(隧道断/锁屏/证书弹窗)。
> WDA test-runner 是**长命进程、没人管生命周期**(跨用例存活,免每条重起)。卡死的 runner 若不主动拆,会把设备**永久堵死**——
> 这曾是"iOS 首启无网批量失败"的真凶(prepare 建 session 60s 超时→网络权限 alert 没被接)。日志时效判僵尸就是补这个洞。

## 执行中的 session 生命周期

- 用例 runtime 持有一个 App session,`ensure_session()` 掉了会重建;
- `_create_ios_session_resilient` 包了重试 + `wda_recover=ensure_wda_ready`:执行中途 WDA 掉了会**自愈重建**再重试,而非硬失败;
- 上层拿不到 session(自愈也救不回)→ 该 iOS 设备**显式跳过**并飞书报警(不写结果表),不会伪装成"无网跑挂"。

## 首启系统 alert(高途 iOS 专项,易踩)

全新装的 App 首次联网会弹三选一系统 alert「允许"高途"使用无线数据? `无线局域网与蜂窝网络`/`仅限无线局域网`/`不允许`」,盖在隐私弹窗上。
- 点「不允许」= **连 WiFi 一起断** → App 落网络错误页 → 首个 ASSERT 失败(这才是"无网"的真相,不是设备真没网)。
- 两道防线接掉它:①预热 `prepare_ios_network_permission` 轮询到 alert 出现点「无线局域网与蜂窝网络」;②执行层 `dismiss_system_alert` 在首个 ASSERT 前再清一遍。
- 详见 memory `ios_startup_network_alert_blocker`。

## 排障速查

```bash
# 隧道注册表(每个 udid 应有 tunnel-address)
curl -s http://127.0.0.1:49151/ | python3 -m json.tool
# WDA 健康(设备侧端口经 proxy 暴露到本地)
curl -s http://127.0.0.1:8100/status
# WDA 进程 / proxy 端口
pgrep -f "xcodebuild.*id=<udid>"
lsof -ti tcp:8100
# 构建日志(判僵尸看它还在不在动)
tail -f /tmp/wda_build_<udid>.log
tail -f /tmp/wda_proxy_<udid>.log
# 手动杀僵尸 WDA
pkill -f "xcodebuild.*id=<udid>"
```
