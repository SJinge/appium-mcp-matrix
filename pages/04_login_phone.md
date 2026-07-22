# 04 统一手机号登录

- 页面类型：统一登录组件
- 入口：首启链路、受限 Tab、登录召回入口
- 截图：[04_login_phone.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/04_login_phone.png)

## UI 树分析

- 标题：`手机号登录`，`com.gaotu100.superclass:id/postion_sign_in_tv`
- 关闭按钮：`com.gaotu100.superclass:id/login_view_close_iv`
- 国家区号：`+86`，`com.gaotu100.superclass:id/account_choose_country_tv`
- 手机号输入框：`com.gaotu100.superclass:id/account_enter_et`
- 验证码按钮：`获取验证码`，`com.gaotu100.superclass:id/account_sign_btn`，空手机号时 `enabled=false`
- 密码登录入口：`com.gaotu100.superclass:id/go_password_btn`
- 微信登录入口：`com.gaotu100.superclass:id/wechat_sign_in_iv`
- 协议勾选区域：`com.gaotu100.superclass:id/accept_login_agreement_layout`
- 协议文案：`com.gaotu100.superclass:id/login_agreement_tv`

## 结论

- 当前版本多个入口复用该登录组件。
- 本轮未输入手机号、未勾选协议、未提交登录。
