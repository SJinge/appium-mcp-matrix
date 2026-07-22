# 08 上课登录门禁

- 页面类型：受限 Tab 登录门禁
- 入口：底部 Tab `上课`
- 截图：[08_class_root.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/08_class_root.png)

## UI 树分析

- 本轮点击 `上课` 后直接进入统一手机号登录组件。
- 标题：`手机号登录`
- 输入框：`com.gaotu100.superclass:id/account_enter_et`
- 关闭按钮：`com.gaotu100.superclass:id/login_view_close_iv`
- 底部协议区：`com.gaotu100.superclass:id/layout_agreement_main`

## 深度 2

- `上课` 根入口即登录门禁，本轮未发现可独立浏览的课程空态页。

## 结论

- 当前游客态 `上课` 不开放独立内容，收敛到登录。
