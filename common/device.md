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
