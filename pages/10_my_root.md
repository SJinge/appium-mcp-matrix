# 10 我的根页

- 页面类型：`我的` Tab 游客根页
- 入口：底部 Tab `我的`
- 截图：[10_my_root.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/10_my_root.png)

## UI 树分析

- Tab 内容容器：`com.gaotu100.superclass:id/mine_framelayout`
- 主体滚动区：`android.widget.ScrollView`
- 顶部登录入口 content-desc：`点击登录, 欢迎来到高途`
- 可见文案：
  - `点击登录`
  - `欢迎来到高途`
  - `我的动态`
  - `专题中心`
- 右上角存在两个可点击图标入口，UI 树未暴露稳定文案。
- 底部 Tab 保持可见，`我的` 为 selected。

## 深度 2

- 点击顶部 `点击登录` 会进入统一手机号登录页，复用 [04_login_phone.md](/Users/mac/Documents/projects/appium-mcp-matrix/pages/04_login_phone.md)。

## 结论

- 与 `上课`、`消息` 不同，本轮 `我的` 有独立游客根页。
- 大部分个人能力仍需要登录后使用。
