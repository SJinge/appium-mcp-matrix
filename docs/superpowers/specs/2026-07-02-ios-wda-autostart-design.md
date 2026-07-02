# iOS 真机 WDA 自动化启动 —— 设计文档

- 日期:2026-07-02
- 分支:feat/auto-release-ci
- 状态:已通过 brainstorming 评审,待写实现计划

## 背景与问题

orchestrate 后台无人值守执行 iOS 真机用例时必然失败,根因两层:

1. **orchestrate 没有拉起 WDA 栈的逻辑**:iOS 流程 `install_ios` 装完 IPA 后直接 `launch_claude_per_device`,中间没有任何 tunnel / WDA / proxy 预启动。
2. **tunnel 步骤要 root 密码**:iOS 17+ 真机(实测 iphone12 / iOS 18.7.8)的 RemoteXPC 隧道必须 `sudo pymobiledevice3 remote tunneld` 以 root 启动。orchestrate 拉起的 `claude --print` 是非交互进程,输不了 sudo 密码 → 隧道起不来 → WDA 起不来 → `:8100` 空 → 建 session 等满 120s 超时失败。

额外发现的洞:`build_prompt` 与 `common/device.md` 的 iOS capabilities **都没有 `webDriverAgentUrl`**。即使 WDA 就绪挂在 `:8100`,claude 建 session 若不显式指向它,XCUITest driver 会**自行再装一个 WDA**,架空已就绪的 WDA 并触发签名。

## 目标

- iOS 真机自动化达到与 Android 同等的无人值守能力。
- 最小化 sudo 攻击面:不引入任何 `NOPASSWD` sudoers 规则。
- WDA 起不来时快速失败并精确报警,不用每条用例撞 120s 超时,不污染飞书结果表。

## 非目标

- 不改 iphone13(config UDID 与在线设备对不上,用户明确不改 config)。
- 不做 WDA 首次签名/证书的自动化(签名过期仍需人工,自愈只覆盖"已配好但进程掉了")。
- 不改 Android 链路。

## 架构:混合方案(常驻 tunnel + 按需 WDA/proxy)

四个职责隔离的组件:

| 组件 | 职责 | root | 生命周期 |
|------|------|:---:|------|
| ① tunneld LaunchDaemon | `pymobiledevice3 remote tunneld` 建 RemoteXPC 隧道 | 是 | 系统级常驻(RunAtLoad + KeepAlive 自愈) |
| ② `scripts/ios_wda.py` | `ensure_wda_ready(udid,team,bundle_id,port,timeout)` | 否 | 库函数,被 orchestrate 调用 |
| ③ WDA + proxy(由②拉起) | xcodebuild WDA(设备侧)+ TCP proxy(`127.0.0.1:{port}`→隧道 IPv6) | 否 | 后台进程,健康则复用不重起 |
| ④ orchestrate 集成 + capability 闭环 | iOS 装完后调 `ensure_wda_ready`;端口注入 prompt;device.md 固化 `webDriverAgentUrl` | 否 | —— |

只有 tunnel 需要 root,交给 LaunchDaemon 以 root 常驻 —— 既不用改 sudoers,也不用交互密码。WDA + proxy 不需要 root,由 orchestrate 按需拉起,实现无人值守。

### 数据流

```
tunneld(root 常驻) → registry :49151
      ↓
orchestrate: install_ios OK
      ↓
ensure_wda_ready(udid): curl :port/status ?
   ├─ 健康 → 复用,继续
   └─ 不健康 → 起 xcodebuild WDA + wda_proxy(读 registry 发现隧道地址)→ 轮询 :port/status ≤180s
                ├─ 就绪 → 继续
                └─ 超时/tunnel 缺失 → 判该设备环境阻断,飞书报警,不写结果表
      ↓
launch claude(prompt 带 webDriverAgentUrl=http://127.0.0.1:{port})
      ↓
claude 建 session 直接连已就绪 WDA(不再自装)
```

## 组件详细设计

### ① tunneld LaunchDaemon

`deploy/launchd/com.gaotu.appium-matrix.tunneld.plist`,照现有 webhook plist 模式:

- `Label`: `com.gaotu.appium-matrix.tunneld`
- `ProgramArguments`: `/Users/mac/.wda-venv/bin/pymobiledevice3 remote tunneld`
- `RunAtLoad: true`(开机自启)、`KeepAlive: true`(掉线自愈)
- `StandardOutPath/ErrorPath`: `logs/launchd.tunneld.{out,err}.log`

关键:放 **`/Library/LaunchDaemons`**(非 `~/Library/LaunchAgents`)且 owner root → 以 root 运行,拿到 tunneld 所需权限,无需 sudoers/交互密码。tunneld 访问的是 USB 设备、不读 `~/Documents`,不撞 webhook 当年的 TCC 坑。

一次性安装(需 sudo 一次):
```bash
sudo cp deploy/launchd/com.gaotu.appium-matrix.tunneld.plist /Library/LaunchDaemons/
sudo launchctl load -w /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist
```
`deploy/launchd/README.md` 补 tunneld 安装/排障段。

### ② `scripts/ios_wda.py`

`ensure_wda_ready(udid, team, bundle_id, port, timeout=180) -> bool`:

```
1. health_check(port): GET http://127.0.0.1:{port}/status (超时 2s)
     命中 → return True(复用,不重起)
2. 不健康 → 确认 tunnel 就绪: GET registry :49151,能发现该 udid 的 tunnel-address ?
     否 → return False,报警区分 "tunnel 未就绪,检查 tunneld daemon"
3. 起 WDA(若无存活的该设备 xcodebuild 进程):
     xcodebuild test ... -destination id={udid} \
       DEVELOPMENT_TEAM={team} PRODUCT_BUNDLE_IDENTIFIER={bundle_id}
     Popen 后台 → /tmp/wda_build_{udid}.log
4. 起 proxy(若 :port 未 LISTEN):
     python scripts/wda_proxy.py --udid {udid} --port {port}
     Popen 后台 → /tmp/wda_proxy_{udid}.log
5. 轮询 health_check(port) 每 3s,直到健康 or 超过 timeout
     健康 → return True;超时 → return False
```

进程复用判定(幂等,避免重复起/僵尸):
- WDA:按 `xcodebuild.*id={udid}` 匹配存活进程,有则不重起。
- proxy:按 `:port` 是否已 LISTEN(`lsof -ti :port`),有则不重起。
- 同一设备多次调用 `ensure_wda_ready` 安全。

### ③ WDA + proxy

`/tmp/wda_proxy.py` 从临时目录**纳入 `scripts/wda_proxy.py` 版本管理**,现写死的 UDID / port / registry 全部参数化(`--udid --port [--registry]`)。proxy 从 registry `:49151` 自动发现隧道 IPv6 地址,`127.0.0.1:{port}` → `[隧道地址]:8100` TCP 转发。

### ④ orchestrate 集成 + capability 闭环

集成点在 `_run` 的 iOS 装完之后、launch claude 之前:

```python
for d in devices["ios"]:
    if not install_ios(...):
        continue
    wda = d.get("wda", {})
    if ensure_wda_ready(d["udid"],
                        wda.get("team", DEFAULT_TEAM),
                        wda.get("bundle_id", DEFAULT_BUNDLE),
                        wda.get("port", DEFAULT_PORT)):
        d["wda_port"] = wda.get("port", DEFAULT_PORT)
        ios_ok.append(d)
    else:
        _notify(...环境阻断,不写结果...)
```

capability 闭环(两处双保险):

- `build_prompt` 增加 iOS 分支,注入实际端口:
  > 本设备 WDA 已就绪,建 session 必须带 `appium:webDriverAgentUrl=http://127.0.0.1:{wda_port}` 与 `appium:usePreinstalledWDA=true`;严禁让 driver 自行重装 WDA。
- `common/device.md` 的 iOS capabilities 固化:
  ```json
  "appium:webDriverAgentUrl": "http://127.0.0.1:8100",
  "appium:usePreinstalledWDA": true
  ```

orchestrate 传实际端口(多设备 8100/8101),device.md 给规范缺省。

## 配置:devices.yaml

每台 iOS 设备加可选 `wda` 段:

```yaml
ios:
  - udid: "00008101-001E28D436E0001E"
    name: "111的iPhone12 (iOS 18.7.8)"
    wda:
      team: "5YX44746D6"
      bundle_id: "com.shijinge.WebDriverAgentRunner"
      port: 8100
  - udid: "00008110-00180CD9348B801E"
    name: "iPhone (iOS 18.7.8)"
    wda:
      port: 8101   # 多设备并行用不同端口;team/bundle_id 缺省继承默认
```

脚本默认常量:`DEFAULT_TEAM=5YX44746D6`、`DEFAULT_BUNDLE=com.shijinge.WebDriverAgentRunner`、`DEFAULT_PORT=8100`。

## 失败处理(全走方案 A)

判该设备环境阻断 + 飞书报警 + 不写结果表,分层文案便于定位:

| 失败点 | 判定 | 报警文案 | 排障入口 |
|--------|------|---------|---------|
| tunnel 未就绪(registry 无该 udid) | return False | "tunnel 未就绪,检查 tunneld LaunchDaemon" | `logs/launchd.tunneld.err.log` |
| WDA 拉起后 180s 未健康 | return False | "WDA 编译/签名/锁屏失败" | `/tmp/wda_build_{udid}.log` |
| IPA 装失败(原有) | continue | 原逻辑 | —— |
| 全部 iOS 设备阻断 | iOS run 无就绪设备 → 早退 | 汇总报警,不进用例 | —— |

## 测试策略

- **单元(mock 掉硬件)**:`ios_wda.py` 纯逻辑 —— registry 解析、health_check 分支、进程复用判定(mock `lsof`/`pgrep`)、超时循环;`build_prompt` iOS 分支注入 `webDriverAgentUrl`;devices.yaml `wda` 段解析 + 默认值回退。
- **集成(手工验证一次)**:真机 iphone12 上 —— tunneld daemon 起好 → 跑 `ensure_wda_ready` → `curl :8100/status` 返 JSON → orchestrate 端到端触发一条 iOS 用例连上已就绪 WDA(确认没自装第二个 WDA)。
- **回归**:确认 Android 链路零改动(集成点仅在 iOS 分支内)。

## 影响的文件

- 新增 `scripts/ios_wda.py`
- 新增 `scripts/wda_proxy.py`(从 `/tmp/wda_proxy.py` 迁移 + 参数化)
- 新增 `deploy/launchd/com.gaotu.appium-matrix.tunneld.plist`
- 改 `scripts/orchestrate.py`(iOS 集成点 + `build_prompt` iOS 分支)
- 改 `config/devices.yaml`(iOS 设备 `wda` 段)
- 改 `common/device.md`(iOS capabilities 固化 `webDriverAgentUrl`/`usePreinstalledWDA`)
- 改 `deploy/launchd/README.md`(tunneld 安装/排障段)
