# AI 辅导对话页（学瓜师）

- **层级**：depth 1
- **导航路径**：首页 → 点击顶部搜索栏（`gtui_search_bar`）
- **页面特征**：AI 助手对话界面（非传统搜索结果页）。顶部「学瓜师」介绍卡片 + 查看全部；中部欢迎语气泡；底部快捷工具 + 聊天输入框
- **截图**：`screenshots/04_ai_tutor_chat.png`

## UI 区域与关键元素

### 顶部介绍卡
- 头像 + 名称「学瓜师」+「8859人关注 | 高途一对一主...」+ `查看全部` 按钮

### 对话气泡区
- 欢迎语「欢迎回来，有什么问题要问我的吗~」+ 时间戳

### 快捷工具（`tools_recyclerview`）
| 工具 | 定位 |
|------|------|
| 搜课程/老师 | xpath `//*[@resource-id='com.gaotu100.superclass:id/tv_txt'][@text='搜课程/老师']` |
| 拍照答疑 | xpath `//*[@resource-id='com.gaotu100.superclass:id/tv_txt'][@text='拍照答疑']` |

### 底部输入栏
| 元素 | resource-id | 说明 |
|------|-------------|------|
| 拍照入口 | `iv_chat_camera` | 相机图标 |
| 文本输入框 | `chat_edit` | placeholder「课程难题学习建议，都可以问」 |
| 语音输入 | `iv_chat_audio` | 麦克风图标 |

## 可导航子页面（depth 2）
- 搜课程/老师 → 课程/老师搜索结果页
- 拍照答疑 → 相机拍照答疑
- 查看全部 → 学瓜师主页
