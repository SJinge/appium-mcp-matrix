# 高途 App UI 探索文档 · v5.91.80

- **App**：高途（gaotu）`com.gaotu100.superclass`
- **版本**：5.91.80
- **平台/设备**：Android · `26KUT24202013751`
- **遍历策略**：广度优先，最大深度 2（底部 Tab = depth 0）
- **登录状态**：复用设备既有登录态（`noReset=true`，未执行登录）；账号 `121****0001`「姐姐大家」，处于**青少年模式**
- **截图目录**：`screenshots/`

## 底部 Tab 总览

底部导航 5 个 Tab（resource-id `com.gaotu100.superclass:id/tab_title`）：`首页` / `AI闪学` / `上课` / `消息` / `我的`。Tab 栏容器 `com.gaotu100.superclass:id/home_tabbar`，默认落地页为「上课」。

| Tab | 页面文档 | 说明 |
|-----|---------|------|
| 首页 | [01_home.md](pages/01_home.md) | 发现页：搜索栏 + 横向子 Tab（关注/推荐/圈子）+ 金刚区 + 课程瀑布流 |
| 首页·子 Tab | [02_home_subtabs.md](pages/02_home_subtabs.md) | 关注/圈子（青少年浏览时长限制拦截，未深入）|
| 首页·搜索 | [04_ai_tutor.md](pages/04_ai_tutor.md) | 顶部搜索栏 → AI 辅导对话页（学瓜师）|
| AI闪学 | [05_ai_flashlearn.md](pages/05_ai_flashlearn.md) | 连胜徽章 + 热门好课 + 学习工具宫格 + 限时活动 |
| 上课 | [06_class.md](pages/06_class.md) | 今日学习推荐 + 我的课程（筛选器 + 课程卡）|
| 上课·课程详情 | [07_course_detail.md](pages/07_course_detail.md) | depth 1：课节列表 + 学习资料/考试/错题本 |
| 上课·课节详情 | [08_lesson_detail.md](pages/08_lesson_detail.md) | depth 2：学习任务时间轴（进教室/去练习）|
| 消息 | [09_message.md](pages/09_message.md) | 消息分类列表（上课提醒/系统通知/活动消息等）|
| 我的 | [10_profile.md](pages/10_profile.md) | 用户卡 + 学习服务/用户服务宫格 + 设置入口 |

## 导航树（最大 depth 2）

```
首页 (depth0)
├─ 关注 / 圈子 子Tab (depth1) — 青少年时长限制拦截
└─ 搜索栏 (depth1) → AI辅导对话页/学瓜师
AI闪学 (depth0)
├─ 热门好课卡 (depth1)
└─ 学习工具：句句背单词/听一听/创意空间/资料 (depth1)
上课 (depth0)
├─ 课程卡 (depth1) → 课程详情页
│  └─ 课节卡 (depth2) → 课节详情页（进教室/去练习）
├─ 错题本 / 课程表 (depth1)
└─ 今日学习推荐卡 (depth1)
消息 (depth0)
└─ 各消息分类 (depth1) → 消息详情列表
我的 (depth0)
├─ 设置 (depth1) → 退出登录
├─ 我的订单/学币商城/购物车 (depth1)
├─ 学习服务：缓存课程/我的课程/课程评价/我的预约/教辅图书/优惠券 (depth1)
└─ 用户服务：帮助中心/意见反馈/学考资料/讲义物流/我的关注… (depth1)
```

## 关键定位约定

- **底部 Tab**：`//android.widget.TextView[@resource-id="com.gaotu100.superclass:id/tab_title" and @text="<Tab名>"]`
- **RN 页面**（课程详情/课节详情/我的）：以 `content-desc` 为主定位；卡片含易变时间文案时用 `-android uiautomator` 的 `descriptionContains(...)` 部分匹配
- **原生页面**（消息）：以 `resource-id` 为主
- **定位降级**：AI 视觉 → xpath/resource-id → 坐标

## 探索备注

- 账号处于青少年模式，社交流（关注/圈子)触发浏览时长限制，未能深入；课程/学习类页面正常可达。
- 截图均以 `maxWidth=800` 采集（高分辨率设备超 2000px 会触发多图限制）。
- UI 树通过 `generate_locators` 采集（`uiautomator dump` 与运行中的 UiAutomator2 driver 冲突）。
