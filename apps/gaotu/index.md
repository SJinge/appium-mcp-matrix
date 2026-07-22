# gaotu App 5.91.93 遍历索引

## 本次采集

- App：高途 `com.gaotu100.superclass`
- 版本：`5.91.93`
- 设备：`26KUT24202013751`（Android，`1224x2776`）
- 采集时间：`2026-07-20 14:14:53 CST`
- 遍历策略：游客态，广度优先遍历 Tab 和稳定子页面，最大深度 `2`
- UI 树来源：`appium_get_page_source`
- 截图来源：`adb exec-out screencap -p`

## 设备检查

- `adb devices`：目标设备 `26KUT24202013751 device`
- `appium driver list --installed`：`uiautomator2@7.1.2` 已安装
- UiAutomator2 server APK：`appium-uiautomator2-server-v9.11.1.apk` 和 `appium-uiautomator2-server-debug-androidTest.apk` 存在
- `dumpsys package com.gaotu100.superclass`：`versionName=5.91.93`
- 启动 Activity：`.ui.activity.SplashActivity`

## 进入主站前置链路

本轮实际顺序：

1. `隐私协议`
2. `青少年守护`
3. `系统通知权限`
4. `剪切板授权`
5. `统一手机号登录`
6. `学习阶段选择`
7. 选择 `高一` 后进入主站首页

## BFS 结果

- `首页`：游客可浏览；顶部有阶段入口、搜索条、咨询入口，主体为内容流，底部 5 个 Tab 可见。
- `AI闪学`：游客可浏览；顶部有连胜/任务入口，主体为闪学内容，底部固定登录召回条。
- `上课`：当前游客态点击 Tab 后直接进入统一手机号登录页。
- `消息`：当前游客态点击 Tab 后直接进入统一手机号登录页。
- `我的`：当前游客态有独立根页，展示 `点击登录`、权益/功能入口和设置类入口。

## 深度 2 结果

- `首页 -> 搜索条`：本轮触发统一手机号登录页，未进入独立搜索页。
- `首页 -> 阶段入口`：阶段入口在 UI 树中为 `ll_label`，当前值 `高一`；阶段选择页见 `05_stage_selector`。
- `AI闪学 -> 立即登录~`：复用统一手机号登录页。
- `上课`：根入口即登录门禁，无更深独立子页。
- `消息`：根入口即登录门禁，无更深独立子页。
- `我的 -> 点击登录`：复用统一手机号登录页。

## 注意事项

- 原生 `uiautomator dump` 在该设备上仍会被系统杀掉，本轮 UI 树分析使用 Appium source。
- `08_class_root.png`、`09_message_root.png`、`11_home_search.png` 均为统一手机号登录页截图，因为这些入口本轮实际收敛到登录门禁。
- 本轮选择 `高一` 仅用于进入游客态主站，不代表业务推荐阶段。

## 页面文档

- [00 系统通知权限](/Users/mac/Documents/projects/appium-mcp-matrix/pages/00_permission_notifications.md)
- [01 隐私协议](/Users/mac/Documents/projects/appium-mcp-matrix/pages/01_privacy_agreement.md)
- [02 青少年守护](/Users/mac/Documents/projects/appium-mcp-matrix/pages/02_teen_guard.md)
- [03 剪切板授权](/Users/mac/Documents/projects/appium-mcp-matrix/pages/03_clipboard_permission.md)
- [04 统一手机号登录](/Users/mac/Documents/projects/appium-mcp-matrix/pages/04_login_phone.md)
- [05 学习阶段选择](/Users/mac/Documents/projects/appium-mcp-matrix/pages/05_stage_selector.md)
- [06 首页根页](/Users/mac/Documents/projects/appium-mcp-matrix/pages/06_home_root.md)
- [07 AI闪学根页](/Users/mac/Documents/projects/appium-mcp-matrix/pages/07_ai_root.md)
- [08 上课登录门禁](/Users/mac/Documents/projects/appium-mcp-matrix/pages/08_class_root.md)
- [09 消息登录门禁](/Users/mac/Documents/projects/appium-mcp-matrix/pages/09_message_root.md)
- [10 我的根页](/Users/mac/Documents/projects/appium-mcp-matrix/pages/10_my_root.md)
- [11 首页搜索登录门禁](/Users/mac/Documents/projects/appium-mcp-matrix/pages/11_home_search.md)
