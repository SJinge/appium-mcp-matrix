# 00 系统通知权限

- 页面类型：Android 系统权限弹窗
- 入口：青少年守护确认后出现
- 截图：[00_permission_notifications.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/00_permission_notifications.png)

## UI 树分析

- 根包名：`com.android.permissioncontroller`
- 权限弹窗容器：`com.android.permissioncontroller:id/grant_dialog`
- 主文案：`是否允许“高途”发送通知？`
- 说明文案：包含横幅、锁屏、铃声等通知说明
- 操作按钮：
  - `禁止`：`com.android.permissioncontroller:id/permission_deny_button`
  - `允许`：`com.android.permissioncontroller:id/permission_allow_button`

## 结论

- 这是系统级通知权限申请，不属于高途业务页面。
- 本轮选择 `禁止` 后继续首启链路。
