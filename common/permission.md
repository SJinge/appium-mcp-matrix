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

跳过此步。权限通过 session capability `autoAcceptAlerts: true` 处理，或在弹窗出现时 AI 视觉点击"允许"。
