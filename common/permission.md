# 系统权限预授权

> 执行时机：Session 创建后、App 启动前。授权失败为非致命错误，继续执行不中断。

## Android

通过 adb 批量授权，避免进入直播时被系统弹窗打断：

```bash
adb -s <device> shell pm grant <packageName> android.permission.RECORD_AUDIO
adb -s <device> shell pm grant <packageName> android.permission.CAMERA
adb -s <device> shell pm grant <packageName> android.permission.READ_EXTERNAL_STORAGE
adb -s <device> shell pm grant <packageName> android.permission.WRITE_EXTERNAL_STORAGE
```

## iOS

跳过此步。权限通过 session capability `autoAcceptAlerts: true` 处理，或在弹窗出现时 AI 视觉点击"允许"。
