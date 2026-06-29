# 首页 Tab（发现）

- **层级**：depth 0（底部 Tab）
- **导航路径**：底部导航 → 首页
- **页面特征**：顶部年级/地区选择 + 搜索栏 + 客服入口；下方横向子 Tab 栏（关注 / 推荐 / 圈子），默认选中「推荐」；金刚区品类宫格；活动课程卡片瀑布流；底部「小灶课」继续学习胶囊
- **截图**：`screenshots/01_home_faxian.png`
- **底部 Tab 文案**：`首页` / `AI闪学` / `上课` / `消息` / `我的`（resource-id `tab_title`）

## UI 区域与关键元素

### 顶部头部
| 元素 | resource-id | 说明 |
|------|-------------|------|
| 年级阶段选择 | `com.gaotu100.superclass:id/ll_label` | 文案「二年级」(`tv_label`)，地区「揭阳」(`tv_child`)，可点 |
| 搜索栏 | `com.gaotu100.superclass:id/gtui_search_bar` | placeholder「找课程 搜老师 解难题」(`textView1`)，可点 → 搜索页 |
| 客服入口 | `com.gaotu100.superclass:id/consult_icon` | 右上角耳机图标，可点 |

### 子 Tab 栏（`subject_tab`）
| 子 Tab | 选中态 resource-id | 备注 |
|--------|--------------------|------|
| 关注 | `unselect_text` text=关注 | 未选中 |
| 推荐 | `select_text` text=推荐 | 默认选中 |
| 圈子 | `unselect_text` text=圈子 + `red_dot` 角标 | 未选中，有红点 |

> 注：旧文档记为「我的订阅/发现/圈子」，5.91.80 实测为「关注/推荐/圈子」。

### 金刚区品类宫格（`king_kong_area` / `extra_menu_item`）
品类文案（`extra_menu_text`）共 10+ 项，B 端动态配置：
小学初中、家庭教育、英语速成、研学游学、高中、青少素养、考研、公职、财会考试、心理咨询师。
另含「浏览设置」(`tv_teenager` 青少年模式入口) + `iv_teenager` 图标。

### 内容瀑布流（`simple_pull_rv_recycler_view`）
活动/课程卡片（`FrameLayout` 列表项），每张含：
| 元素 | resource-id |
|------|-------------|
| 报名人数 | `tv_deps_top`（如「800+人报名」「1万+人报名」「5万+人报名」） |
| 标题 | `tv_title`（如「直播课 专注力父母训练营」「体验课 高途英语单词带背体验课GT」） |
| 价格 | `tv_price`（如「限时免费」「¥1」） |
| 报名按钮 | `tv_small_enroll` + `tv_content`text=立即报名 |

### 底部继续学习胶囊（`fl_task_remind_capsule`）
| 元素 | resource-id |
|------|-------------|
| 标签 | `capsule_tag`（如「数学」） |
| 标题 | `capsule_title`（如「小灶课」） |
| 副标题 | `capsule_sub_title`（如「B课程中心gps1.5-线上回归B北京市」） |
| 继续学习按钮 | `capsule_button_title` |
| 关闭 | `capsule_close` |

## 可导航子页面（depth 1）
- 关注 子 Tab → `pages/02_home_guanzhu.md`
- 圈子 子 Tab → `pages/03_home_quanzi.md`
- 搜索页（点搜索栏）→ `pages/04_search.md`
- 课程卡片 → 课程详情/报名页（动态内容）
- 年级阶段选择弹层 / 客服会话 / 浏览设置（青少年模式）
