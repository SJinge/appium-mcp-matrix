# 系统权限预授权

> 执行时机：App 安装/重装后首次执行时授权。已授权设备无需重复执行（权限持久化）。  
> 授权失败为非致命错误，继续执行不中断。

## Android

通过 adb 批量授权，避免进入直播时被系统弹窗打断：

```bash
DEVICE=<device>
PKG=<packageName>

# 音视频权限（所有 Android 版本通用）
adb -s $DEVICE shell pm grant $PKG android.permission.RECORD_AUDIO
adb -s $DEVICE shell pm grant $PKG android.permission.CAMERA

# 存储权限：Android 13（API 33）起废弃了旧权限，需按版本选择
SDK=$(adb -s $DEVICE shell getprop ro.build.version.sdk | tr -d '[:space:]')
if [ "$SDK" -lt 33 ]; then
  adb -s $DEVICE shell pm grant $PKG android.permission.READ_EXTERNAL_STORAGE
  adb -s $DEVICE shell pm grant $PKG android.permission.WRITE_EXTERNAL_STORAGE
else
  adb -s $DEVICE shell pm grant $PKG android.permission.READ_MEDIA_IMAGES
  adb -s $DEVICE shell pm grant $PKG android.permission.READ_MEDIA_VIDEO
fi
```

> **何时需要执行**：App 卸载重装后必须执行；同一安装未重装可跳过（权限不会自动重置）。  
> 卸载重装流程见 [app.md](app.md)，其末尾有调用本步骤的提示。

## iOS

默认不执行外部预授权。iOS 没有类似 Android `pm grant` 的稳定本地网络权限命令，
执行链路在安装和 WDA ready 后会先做一次网络权限预热：创建临时 WDA session 启动 App，
轮询系统 alert 并处理网络类权限弹窗，然后关闭临时 session 和 App。预热失败时跳过该
iOS 设备，避免 App 在无网络权限的异常状态下继续跑用例。

预热处理规则：

- 弹出“发送通知” → 点“允许”
- 弹出“使用无线数据” → 点“无线局域网与蜂窝网络”
- 弹出“无线局域网”/“本地网络”/“网络权限” → 点“允许”
- 未弹出 → 视为已授权或当前版本未触发弹窗，继续执行

如果弹窗预热未完成，会再尝试系统设置兜底：

`设置 -> App -> 高途 -> 无线数据 -> 无线局域网与蜂窝数据`

兜底成功后重新启动 App 做一次预热确认；仍失败才跳过设备。

如本机环境提供可靠的 iOS 权限工具，可显式配置：

```bash
export ORCH_IOS_NETWORK_PERMISSION_CMD='<cmd> -u {udid} grant-network {bundle_id}'
```

未配置 `ORCH_IOS_NETWORK_PERMISSION_CMD` 时，编排会跳过外部命令，仍执行 WDA 预热。
