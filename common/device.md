# 设备就绪检查

> 执行时机：用例解析完成后、第一步操作前。发现问题立即告知用户，不静默跳过。

## Android

```bash
# 1. 设备连接
adb devices
# 含 <udid>  device → 继续；unauthorized → 提示允许USB调试；不在列表 → 停止

# 2. 驱动
appium driver list --installed
# 含 uiautomator2 → 继续；否则提示安装

# 3. APK
ls /opt/homebrew/lib/node_modules/appium-mcp/node_modules/appium-uiautomator2-driver/node_modules/appium-uiautomator2-server/apks/
# 文件存在 → 继续；否则记录警告
```

检查通过后记录开始时间：
```bash
GAOTU_START=$(date +%s)
```

## iOS

```bash
tidevice list   # 推荐
# 或 xcrun xctrace list devices 2>/dev/null | grep -E "iPhone|iPad"
# UDID 在列表 → 继续；否则停止

appium driver list --installed
# 含 xcuitest → 继续；否则提示安装

# WDA：模拟器用 prepare_ios_simulator；真机确认已签名安装
```

## Session 创建

**Android capabilities：**
```json
{
  "appium:udid": "<device>",
  "appium:noReset": true,
  "appium:autoGrantPermissions": true,
  "appium:skipServerInstallation": true,
  "appium:uiautomator2ServerInstallTimeout": 120000,
  "appium:adbExecTimeout": 120000
}
```

Session 失败时手动安装 APK 再重试：
```bash
adb -s <device> install -r <apks_dir>/appium-uiautomator2-server-v9.11.1.apk
adb -s <device> install -r <apks_dir>/appium-uiautomator2-server-debug-androidTest.apk
```

**iOS capabilities：**
```json
{
  "platformName": "iOS",
  "appium:automationName": "XCUITest",
  "appium:udid": "<udid>",
  "appium:bundleId": "<bundleId>",
  "appium:noReset": true,
  "appium:autoAcceptAlerts": true,
  "appium:wdaLaunchTimeout": 120000,
  "appium:wdaConnectionTimeout": 120000
}
```

> 当前 iOS 真机默认不要手工传 `appium:webDriverAgentUrl`。
> 已验证 `appium-mcp/create_session` 直建会话可正常接管设备；强制走自定义 `webDriverAgentUrl`
> 反而可能命中不稳定的本地 proxy，出现 `ECONNREFUSED`。

## iOS 真机排障记录

### 本次实际遇到的问题

1. 设备重启后，`Apple Development: jinge.shi@icloud.com` 的设备侧信任会失效。
   现象：
   - `xcodebuild test` 失败
   - `/tmp/wda_build_<udid>.log` 出现：
     `Unable to launch com.shijinge.WebDriverAgentRunner.xctrunner because it has an invalid code signature, inadequate entitlements or its profile has not been explicitly trusted by the user`

2. 只看 `tidevice list` 在线不够，Xcode 侧还可能是 `unpaired`。
   现象：
   - `tidevice list` 能看到设备
   - `xcodebuild -showdestinations` 里设备是 `Ineligible destination`
   - 提示 `Pair with the device in the Xcode Devices Window`

3. 自建 `WDA + wda_proxy + appium:webDriverAgentUrl=http://127.0.0.1:<port>` 通路不稳定。
   现象：
   - `WebDriverAgentRunner-Runner` 日志显示已经开始跑测试
   - 但 `create_session` 仍报 `ECONNREFUSED 127.0.0.1:8100`
   - `scripts/wda_proxy.py` 上游持续报 `upstream connect failed: [Errno 61] Connection refused`

4. `tunneld` 注册表里的 `tunnel-port` 可以连通，但不能简单假设 `[{tunnel-address}]:8100` 一定可达。
   现象：
   - `tunnel-address + tunnel-port` 能建 TCP 连接
   - `tunnel-address + 8100` 直接 `Connection refused`

### 已验证可跑通的方式

1. 设备侧准备：
   - 手机保持解锁
   - `设置 -> 通用 -> VPN 与设备管理` 中手动信任 `Apple Development: jinge.shi@icloud.com`
   - 若 Xcode 报 `unpaired`，在 `Xcode -> Window -> Devices and Simulators` 中重新配对
   - 确认设备 `Developer Mode` 已开启

2. WDA 就绪验证：
   - 运行 `ios_wda.ensure_wda_ready(...)` 可把两台设备的 WDA 拉起到 ready
   - 本次实测：
     - `iPhone 12 -> :8100 ready`
     - `iPhone 13 -> :8101 ready`

3. 真正可用的建会话方式：
   - iOS 真机不要手工传 `appium:webDriverAgentUrl`
   - 直接调用 `appium-mcp/select_device -> create_session`
   - capabilities 仅保留：
     - `appium:udid`
     - `appium:bundleId`
     - 以及常规 `XCUITest` 配置
   - 本次已在 `iPhone 12`、`iPhone 13` 上实测：
     - `create_session` 成功
     - `appium_screenshot` 成功
     - `delete_session` 成功

4. 结论：
   - 当前 iOS 真机链路可用方案：`设备信任 + 直接 create_session`
   - 当前不推荐方案：`手工传 webDriverAgentUrl + 依赖 scripts/wda_proxy.py`
