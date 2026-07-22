# 07 AI闪学根页

- 页面类型：AI闪学 Tab 根页
- 入口：底部 Tab `AI闪学`
- 截图：[07_ai_root.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/07_ai_root.png)

## UI 树分析

- Tab 内容容器：`com.gaotu100.superclass:id/study_framelayout`
- 顶部区域包含闪学品牌图、连胜入口和右上功能入口。
- 连胜入口 content-desc：`0, 0, 天连胜`
- 主内容区为可滚动区域，包含学习内容和课程推荐。
- 页面底部有固定登录召回条：
  - 文案：`登录后可享专属学习服务~`
  - 登录按钮：`立即登录~`，`com.gaotu100.superclass:id/tv_login`

## 深度 2

- 点击 `立即登录~` 会进入统一手机号登录页，复用 [04_login_phone.md](/Users/mac/Documents/projects/appium-mcp-matrix/pages/04_login_phone.md)。

## 结论

- `AI闪学` 游客态可浏览，但关键个性化能力通过底部召回条引导登录。
