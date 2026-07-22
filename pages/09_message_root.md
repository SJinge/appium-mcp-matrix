# 09 消息登录门禁

- 页面类型：受限 Tab 登录门禁
- 入口：底部 Tab `消息`
- 截图：[09_message_root.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/09_message_root.png)

## UI 树分析

- 本轮点击 `消息` 后直接进入统一手机号登录组件。
- 标题：`手机号登录`
- 国家区号：`+86`
- 手机号输入框：`请输入您的手机号`
- 验证码按钮：`获取验证码`
- 关闭按钮：`com.gaotu100.superclass:id/login_view_close_iv`

## 深度 2

- `消息` 根入口即登录门禁，本轮未发现独立消息空态页。

## 结论

- 当前游客态 `消息` 不开放独立内容，收敛到登录。
