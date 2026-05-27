# App 安装 / 卸载 / 版本确认

> 适用场景：测试前需要安装指定版本、清理旧数据后重装，或确认当前安装版本。

---

## Android

### Appium MCP（需已有 session）

**1. 下载 APK（后台执行，同时可创建 session）**

```bash
curl -L -o /tmp/<app>_<version>.apk "<下载链接>"
ls -lh /tmp/<app>_<version>.apk   # 确认文件完整（正常 100MB+）
```

**2. 卸载旧版本**

```
appium_app_lifecycle action=uninstall id=<packageName>
```

**3. 安装新版本**

```
appium_app_lifecycle action=install path=/tmp/<app>_<version>.apk
```

> APK 约 200-300MB，建议 `run_in_background` 下载，同时并行创建 session。  
> 安装完成后首次启动会触发首次启动弹窗，处理流程见 [startup.md](startup.md)。


---

## iOS

> `appium_app_lifecycle install` 在 iOS 真机上不稳定，改用 tidevice。

### 前提：tidevice 依赖

```bash
# tidevice 需要 pyOpenSSL 和 pyasn1（Homebrew Python 3.11）
pip3.11 install pyOpenSSL pyasn1
```

### 步骤

```bash
UDID="<device_udid>"
BUNDLE_ID="<bundleId>"        # 例：com.gaotu100.superclass
IPA_URL="<ipa_download_url>"
IPA_PATH="$HOME/Downloads/<app_name>.ipa"

# 1. 确认设备已连接（手机需解锁并点「信任此电脑」）
tidevice list
# 列表中出现 UDID + ConnectionType.USB → 继续；否则停止

# 2. 确认当前安装版本（可选）
tidevice -u "$UDID" applist | grep "$BUNDLE_ID"

# 3. 下载 IPA
curl -L -o "$IPA_PATH" "$IPA_URL"

# 4. 卸载旧版本
tidevice -u "$UDID" uninstall "$BUNDLE_ID"
# 输出 Complete → 继续

# 5. 安装新 IPA
tidevice -u "$UDID" install "$IPA_PATH"
# 输出 Complete → 继续

# 6. 验证
tidevice -u "$UDID" applist | grep "$BUNDLE_ID"
```

### 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `tidevice list` 为空，但 USB 已插 | 设备未解锁或未信任 | 解锁手机 → 点「信任此电脑」→ 重试 |
| `MuxReplyCode.BadDevice` | 同上 | 同上 |
| `ValueError: Invalid version` in pair | pyOpenSSL 版本 API 变动（不影响已配对设备） | 忽略，直接执行 install/uninstall |
| `xcrun devicectl` 显示 unavailable | iOS 17+ CoreDevice 协议 | 改用 tidevice |
