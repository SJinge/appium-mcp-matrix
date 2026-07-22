# 01 隐私协议

- 页面类型：首启隐私协议弹窗
- 入口：首次启动高途 App
- 截图：[01_privacy_agreement.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/01_privacy_agreement.png)

## UI 树分析

- 根包名：`com.gaotu100.superclass`
- 协议正文：`com.gaotu100.superclass:id/tvMessage`
- 主操作：`同意`，父节点 `com.gaotu100.superclass:id/tvConfirm`
- 次操作：`不同意`，父节点 `com.gaotu100.superclass:id/tvCancel`
- 正文包含《高途用户服务协议》《高途隐私政策》《儿童隐私保护声明》等链接文本。

## 结论

- 首启必须处理该弹窗才能继续。
- 本轮点击 `同意` 后进入青少年守护弹窗。
