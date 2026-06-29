# 消息 Tab

- **层级**：depth 0（底部 Tab）
- **导航路径**：底部导航 → 消息
- **页面特征**：原生页面（`android.widget.ListView`）。顶部标题栏「消息」+ 消息分类列表（每行：标题 + 描述 + 时间 + 未读角标）
- **截图**：`screenshots/09_message.png`

## UI 区域与关键元素

### 顶部标题栏
| 元素 | 定位 | 说明 |
|------|------|------|
| 标题 | resource-id=`com.gaotu100.superclass:id/headbar_left_text`（text=消息）| |

### 消息列表（`mymessageactivity_message_listview`）

列表容器 resource-id=`com.gaotu100.superclass:id/mymessageactivity_message_listview`。每行 item 字段:

| 字段 | resource-id |
|------|-------------|
| 标题 | `messageitemview_message_title` |
| 描述 | `messageitemview_message_des` |
| 时间 | `messageitemview_message_time` |
| 未读角标 | `messageitemview_message_count` |
| 标签 | `messageitemview_message_tag` |
| 关闭 | `messageitemview_message_cancel` |

#### 消息分类行
| 标题 | 描述 | 时间 | 未读/标签 |
|------|------|------|----------|
| 邀好友 100% 得… | 召唤搭子抽大奖 | — | 标签「千元礼包」+ 关闭 X |
| AI小途 | 找课程 搜老师 解难题 | — | — |
| 上课提醒 | 直播课已经开始 | 2025年09月21日 19:48 | 24 |
| 系统通知 | 速看！获学币，so easy | 2025年03月19日 18:17 | 23 |
| 活动消息 | 💌 25考研党进！！ | 2024年03月08日 20:04 | 1 |
| 练习提醒 | 暂无消息 | — | — |
| 物流消息 | 暂无消息 | — | — |

## 可导航子页面（depth 1）
- 各消息分类行 → 对应消息详情列表（上课提醒/系统通知/活动消息/练习提醒/物流消息）
- AI小途 → AI 助手对话页
- 邀好友卡 → 活动落地页
