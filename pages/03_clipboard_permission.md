# 03 剪切板授权

- 页面类型：高途自定义授权弹窗
- 入口：系统通知权限处理后出现
- 截图：[03_clipboard_permission.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/03_clipboard_permission.png)

## UI 树分析

- 标题：`提示`，`com.gaotu100.superclass:id/custom_dialog_title`
- 说明：`com.gaotu100.superclass:id/custom_dialog_message`
- 说明内容：请求读取剪切板，用于识别邀请、活动或归因信息，并提示可在 `我的-设置-通用` 关闭或打开
- 操作按钮：
  - `拒绝`：`com.gaotu100.superclass:id/customer_dialog_cancel`
  - `同意`：`com.gaotu100.superclass:id/customer_dialog_ok`

## 结论

- 这是业务侧自定义弹窗，不是 Android 系统权限弹窗。
- 本轮选择 `拒绝` 后进入统一手机号登录页。
