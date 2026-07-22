# 06 首页根页

- 页面类型：主站首页
- 入口：底部 Tab `首页`
- 截图：[06_home_root.png](/Users/mac/Documents/projects/appium-mcp-matrix/apps/gaotu/06_home_root.png)

## UI 树分析

- 根容器：`com.gaotu100.superclass:id/content_root`
- 主内容 ViewPager：`com.gaotu100.superclass:id/home_content`
- 首页内容滚动区：`androidx.recyclerview.widget.RecyclerView`
- 顶部背景：`com.gaotu100.superclass:id/svg_bg`
- 顶部阶段入口：`com.gaotu100.superclass:id/ll_label`，当前文案 `高一`
- 搜索条：`com.gaotu100.superclass:id/gtui_search_bar`
- 搜索提示：`找课程 搜老师 解难题`
- 咨询入口：`com.gaotu100.superclass:id/consult_icon`
- 内容区包含 `king_kong_area`、`top_module_container`、首页内容流等模块。
- 底部 Tab：`首页`、`AI闪学`、`上课`、`消息`、`我的`

## 深度 2

- 点击搜索条后，本轮进入统一手机号登录页，见 [11_home_search.md](/Users/mac/Documents/projects/appium-mcp-matrix/pages/11_home_search.md)。
- 点击阶段入口可回到学习阶段选择类页面，见 [05_stage_selector.md](/Users/mac/Documents/projects/appium-mcp-matrix/pages/05_stage_selector.md)。

## 结论

- `首页` 是当前游客态下信息最完整、最稳定的主站页。
- 当前阶段为本轮探索选择的 `高一`。
