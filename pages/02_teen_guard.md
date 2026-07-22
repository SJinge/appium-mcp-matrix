# 02 青少年守护

- 页面类型：首启年龄确认弹窗
- 入口：隐私协议点击 `同意` 后出现
- 截图：[02_teen_guard.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/02_teen_guard.png)

## UI 树分析

- 卡片容器：`com.gaotu100.superclass:id/cardLayout`
- 标题：`青少年守护`，`com.gaotu100.superclass:id/tvTitle`
- 说明：`com.gaotu100.superclass:id/tvMessage`
- 顶部图：`com.gaotu100.superclass:id/top_icon`
- 操作按钮：
  - `未满14岁`：`com.gaotu100.superclass:id/tvCancel`
  - `已满14岁`：`com.gaotu100.superclass:id/tvConfirm`

## 结论

- 这是进入主站前的年龄确认拦截。
- 本轮点击 `已满14岁` 后进入系统通知权限申请。
