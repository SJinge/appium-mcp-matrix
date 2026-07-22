# 05 学习阶段选择

- 页面类型：学习阶段选择页
- 入口：关闭统一手机号登录页后出现；首页顶部阶段入口也可回到同类页面
- 截图：[05_stage_selector.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/05_stage_selector.png)

## UI 树分析

- 页面由 React Native 容器承载：`com.gaotu100.superclass:id/reactNativeFragment`
- 标题文案：`嗨，让我们了解一下你吧!`
- 副标题：`选择你的学习阶段`
- 提示：`在校学生请选择9月升入的年级`
- 可滚动阶段区：`android.widget.ScrollView`
- 可见分组：`小学`、`初中`、`高中`、`大学`、`成人`
- 可见阶段示例：`一年级`、`二年级`、`三年级`、`初一`、`高一`、`研究生`、`工作/备考`
- 底部按钮：`进入首页`

## 结论

- 未选择阶段时点击 `进入首页` 不跳转。
- 本轮选择 `高一` 后进入主站首页。
