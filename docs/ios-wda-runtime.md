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

## TeamID 配置 & WDA 编译安装到设备(换机 / 换证书必读)

### TeamID 在哪配、用哪个

WDA 用哪个 Apple 开发者团队签名,决定证书稳不稳。配置两处,`devices.yaml` 每设备覆盖优先于默认:
- [config/devices.yaml](../config/devices.yaml) 每台 iOS 的 `wda.team`(实际生效值);
- [scripts/orch_config.py](../scripts/orch_config.py) `DEFAULT_WDA_TEAM`(未配 `wda.team` 的新设备继承)。

`team` 传给 `xcodebuild` 的 `DEVELOPMENT_TEAM=`,配合 `CODE_SIGN_STYLE=Automatic`+`-allowProvisioningUpdates` 自动签名。本项目两个可选团队(**team id = 证书 subject 的 OU 字段**,不是括号里那串):

| team id | 归属 | 证书名 | 有效期 | 适合 |
|---------|------|--------|--------|------|
| `LU2B796CHV` | Guangzhou Gaotu **组织付费** | `Apple Development: 金鸽 石 (TV3FCP39YB)` | **1 年** | ✅ headless CI(当前用这个) |
| `5YX44746D6` | jinge.shi@icloud.com **个人免费** | `Apple Development: jinge.shi@icloud.com (F54B58M263)` | **7 天** | 仅临时调试 |

**为什么用组织团队**:个人免费证书 7 天到期,每次过期/重签,设备端「VPN与设备管理」的信任就失效,headless CI 会周期性因"未信任"挂;组织付费证书 1 年有效,信任一次扛很久。

查某张证书属于哪个 team:
```bash
security find-identity -v -p codesigning                       # 列所有可签名身份
security find-certificate -c "Apple Development: 金鸽 石 (TV3FCP39YB)" -p login.keychain-db \
  | openssl x509 -noout -subject                               # 看 OU=<team id>
```

### WDA 怎么编译并装到设备(`_start_wda` 全量构建路径)

`ensure_wda_ready` 在没有 `.xctestrun` 产物时走全量构建,命令等价于:
```bash
xcodebuild test \
  -project <appium-webdriveragent>/WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination "id=<udid>" \
  -derivedDataPath /tmp/wda_derived/<udid> \
  -allowProvisioningUpdates CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM=LU2B796CHV \
  PRODUCT_BUNDLE_IDENTIFIER=com.shijinge.WebDriverAgentRunner \
  'WARNING_CFLAGS=$(inherited) -Wno-poison-system-directories'
```
`xcodebuild test` 一步做完:**编译 → 自动签名(拉/装 provisioning profile)→ 安装到设备 → 启动 runner**(设备侧监听 8100,日志出现 `ServerURLHere->http://<设备IP>:8100<-ServerURLHere` 即起来了)。runner 是常驻长命进程,之后 `test-without-building` 复用。WDA 源码目录由 `_resolve_wda_dir()` 探测(可 `ORCH_WDA_DIR` 覆盖)。

**全量 clean build 的三层坑(换机 / 换团队必踩,按 build log 关键字逐层定位)**:

1. `include location '/usr/local/include' is unsafe for cross-compilation`(**poison,交叉编译不安全路径**)
   WDA 的 `IOSSettings.xcconfig` 开了 `-Weverything` + `GCC_TREAT_WARNINGS_AS_ERRORS=YES`,clang 对 pbxproj `HEADER_SEARCH_PATHS` 注入的 `-I /usr/local/include` 报 `-Wpoison-system-directories`,warning 当 error 直接挂(**与该目录是否真实存在无关**)。
   ⚠️ `CLANG_WARN_POISON_SYSTEM_DIRECTORIES=NO` **无效**——被排在其后的 `-Weverything` 重新打开。
   ✅ 传 `'WARNING_CFLAGS=$(inherited) -Wno-poison-system-directories'`(追加在 -Weverything 之后精准关这一条,不降整体严格度)。已固化进 [scripts/ios_wda.py](../scripts/ios_wda.py)。

2. `Apple Development: xxx (XXXXXXXXXX): ambiguous`(**codesign 身份歧义**)
   钥匙串有**两张同名证书**(常见:一张已吊销 `CSSMERR_TP_CERT_REVOKED` 没清)→ codesign 按名字选不出唯一身份 → "Embed app icon into Runner.app" 脚本非零退出 → `** TEST INTERRUPTED **`。
   ✅ 按 SHA-1 删掉吊销那张:`security delete-certificate -Z <吊销证书SHA-1> login.keychain-db`(SHA-1 从 `security find-identity -v -p codesigning` 取)。

3. `does not match installed application's application-identifier; rejecting upgrade`(**跨团队升级被拒**)
   换签名团队后 app-id 前缀变了(如 `5YX44746D6.` → `LU2B796CHV.`),iOS 不允许把已装的包"升级"成另一团队的包。
   ✅ 先卸旧的再装:`xcrun devicectl device uninstall app --device <udid> com.shijinge.WebDriverAgentRunner.xctrunner`,然后重跑构建。

> 组织团队(LU2B796CHV)证书在**当前主力设备已被信任**,卸旧重装后 runner 直接起,无需再手点信任。换到没信任过组织账号的新设备时,仍需在设备上手动信任一次(见下「换机前置」第 2 条)。

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

## 换机前置:DeviceSupport(build 能跑 ≠ 真机能跑)

新 Mac 上 WDA 起不来,最常见不是 SDK/签名,而是 **Xcode 缺设备 iOS 版本的 DeviceSupport**。

**关键结论:能不能跑真机,取决于该 Xcode 的 DeviceSupport 目录里有没有设备对应 iOS 版本的符号文件,跟 Xcode 版本号无关。**
- 安装"iOS 平台组件"(`xcodebuild -downloadPlatform iOS`)只解决 **build**(编译 SDK),不等于能在真机上 **run**。
- 设备 iOS 比 Xcode 出厂支持的还新时(如 Xcode 16.4 出厂最高 iOS 18.5、设备 18.7.8),`xcodebuild test` 会报找不到 device support,WDA 起不来。

主力机(这台)是 **Xcode 15.3**——原生根本没有 iOS 18——却能跑 18.7.8 真机,就是因为手动往它 DeviceSupport 塞了对应文件:

```
~/Library/Developer/Xcode/iOS DeviceSupport/
  iPhone13,2 18.7.8 (22H352)   ← iPhone 12
  iPhone14,5 18.7.8 (22H352)   ← iPhone 13
```

设备系统 = **iOS 18.7.8 / build 22H352**。搭新机不必降级 Xcode,把这两个目录整个拷到新机同路径即可:

```bash
mkdir -p ~/Library/Developer/Xcode/iOS\ DeviceSupport/
scp -r ~/Library/Developer/Xcode/iOS\ DeviceSupport/iPhone1{3,4}*\ 18.7.8\ \(22H352\) \
       <newmac>:'~/Library/Developer/Xcode/iOS DeviceSupport/'
# 新机确认 + 若 Xcode 不认"型号 版本 (build)"命名,复制一份改成"版本 (build)":
#   cd ~/Library/Developer/Xcode/iOS\ DeviceSupport/ && cp -r "iPhone13,2 18.7.8 (22H352)" "18.7.8 (22H352)"
# 拷完重启 Xcode 再跑 WDA
```

DeviceSupport 之外,真机跑 WDA 还需三样齐全(缺一起不来):
1. 设备**开发者模式**开启(设置→隐私与安全性→开发者模式,iOS16+);
2. 「VPN与设备管理」信任签名用的开发者证书(高途组织 team,自动签名),全程解锁;
3. **tunnel** 常驻(iOS17+,`:49151` registry 有该 udid 的 tunnel-address)。

> 详见 memory `ios_realdevice_wda_setup`。

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
