# 11 首页搜索登录门禁

- 页面类型：首页搜索入口触发的登录门禁
- 入口：`首页 -> 搜索条`
- 截图：[11_home_search.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/11_home_search.png)

## UI 树分析

- 点击首页搜索条后，本轮未进入独立搜索页，而是进入统一手机号登录组件。
- 登录组件关键节点：
  - 标题：`手机号登录`
  - 手机号输入框：`com.gaotu100.superclass:id/account_enter_et`
  - 验证码按钮：`com.gaotu100.superclass:id/account_sign_btn`
  - 关闭按钮：`com.gaotu100.superclass:id/login_view_close_iv`
  - 协议区：`com.gaotu100.superclass:id/layout_agreement_main`

## 结论

- 当前游客态下，首页搜索入口需要登录。
- 页面本质复用 [04_login_phone.md](/Users/mac/Documents/projects/appium-mcp-matrix/pages/04_login_phone.md)，单独记录是为了保留 BFS 深度 2 入口结果。
