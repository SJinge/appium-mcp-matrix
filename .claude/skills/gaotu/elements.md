# 高途 App 元素定位规范

> 供 `gaotu` skill 引用。公共登录元素见 [../../common/elements/login.md](../../common/elements/login.md)，公共弹窗元素见 [../../common/elements/dialog.md](../../common/elements/dialog.md)。

包名：`com.gaotu100.superclass`

---

## 页面特征识别

| 页面 | 特征标志 |
|------|----------|
| 首页（发现子tab） | 顶部子 tab 栏含「发现」「我的订阅」「圈子」，发现子 tab 默认选中 |
| 消息 tab | 顶部标题「消息」，下方为消息列表 |
| 上课 tab（首页） | 顶部标题"上课"，下方有"今日学习推荐"和"我的课程" |
| AI闪学 tab | 底部 tab "AI闪学"选中状态 |
| 课程详情页 | 顶部课程名称，课节列表，有"课程"和"服务"两个 tab |
| 课节详情页 | 标题含"第X节"或课节名，"学习任务"区域含"直播核心课" |
| 直播教室 | 横屏，视频区域 + 互动栏 + 聊天区 |
| 登录页 | "手机号登录"标题，输入框，"获取验证码"按钮 |
| 我的页 | 顶部头像 + 手机号，下方列表含"我的订单"、"设置"等 |
| 搜索页 | 顶部搜索框，下方热门/历史搜索 |
| 短视频流播放页 | 全屏竖屏视频，右侧点赞/评论/收藏数字列，底部"说点什么..."输入框 |

---

## AI 视觉定位规范

### 规则一：先截图确认页面，再定位目标元素

```
Step 1: appium_screenshot maxWidth=800 → 确认当前页面特征（见上表）
Step 2: 根据确认的页面，用精确描述定位目标元素
```

### 规则二：ai_instruction 三要素

描述须包含 **元素外观 + 位置 + 上下文**：

```
# 差
"进教室 button"

# 好
"red oval '进教室' button on the right side of the 直播核心课 row"
```

### 规则三：截图分辨率统一 maxWidth=800

**Android 登录页截图**：若截图黑屏，先等待 1s 再重试（可能是页面跳转中的过渡帧，而非 FLAG_SECURE）；单独测试可正常截图。  
**iOS**：无 FLAG_SECURE，全程截图可用。

### 规则三-B：教室页（横屏）截图旋转 90°

```bash
sips -r 90 /path/to/screenshot.png   # macOS 内置，无需安装
```

判断依据：截图中视频区域出现在竖向图侧面（内容横躺）时旋转。适用于进入教室后所有截图。

### 规则四：三级降级策略

```
第一级：截图 + AI 视觉定位（ai_instruction）
    目标文字可见时优先，无需 page source
    ↓ 截图失败（FLAG_SECURE）或 AI 视觉失败
第二级：page source + 属性定位
    Android：resource-id 优先，xpath //*[@text='目标'] 次之
    iOS：accessibility id 优先，xpath //*[@name='目标'] 次之
    ↓ 仍找不到
第三级：坐标硬点击（兜底）
    仅用于已知固定布局（如底部 tab），记录日志说明
```

**⚠️ 跨 app 场景**（如分享到微信联系人选择页）：session 绑定高途 app，切换到其他 app 后 xpath/accessibility id 必然失败，直接跳第一级 AI 视觉，不走降级。

### 规则五：定位前等待页面稳定

```
方法 A（推荐）：轮询等待目标页面特征元素出现
  Android: appium_find_element xpath=//*[@text='今日学习推荐']  超时 10s
  iOS:     appium_find_element xpath=//*[@name='今日学习推荐']  超时 10s

方法 B（兜底）：仅在无法轮询时使用
  普通页面跳转：sleep 0.5s
  直播页面加载：sleep 1s
  app 冷启动：  sleep 1s
```

标准轮询间隔：0.3s；直播进入教室：0.5s，超时 8s；冷启动首屏：0.5s，超时 6s

---

## 高频元素 ai_instruction

| 元素 | ai_instruction |
|------|----------------|
| 进教室按钮 | `red oval '进教室' button on the right side of 直播核心课 row` |
| 直播核心课行 | `'直播核心课' text with small red label above it, on left side of learning task card` |
| 课节列表项 | `lesson item numbered '1.' with title text and date below, in course list` |
| 上课 tab | `'上课' bottom navigation tab with icon above text, third tab from left` |
| 我的 tab | `'我的' bottom navigation tab with icon above text, rightmost tab` |
| AI闪学 tab | `'AI闪学' bottom navigation tab with icon above text` |
| 关闭/知道了 | `'知道了' or '关闭' button at bottom of overlay popup` |
| 同意按钮 | `red '同意' button on the right side of dialog bottom button row` |
| 继续登录按钮 | Android: `xpath=//*[@text='继续登录']`（多设备登录冲突弹窗，非 AI 视觉） |
| 我的课程区域 | `'我的课程' section header with arrow on right, below 今日学习推荐` |
| 我的页-扫一扫 | `scan QR code icon button, square with rounded corners, second from right in top-right header of 我的 page` |
| 我的页-设置 | `hexagon settings icon button, rightmost icon in top-right corner of 我的 page` |
| 退出教室-确定 | `red '确定' button on the right side of '确定退出教室?' dialog（横屏）` |
| 退出教室-取消 | `blue '取消' button on the left side of '确定退出教室?' dialog（横屏）` |
| 朗读麦克风 | `microphone button for voice recording in speaking exercise` |

---

## 底部导航 Tab

### Android

| 元素名 | strategy | selector | 备注 |
|--------|---------|---------|------|
| 首页 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='首页']` | |
| AI闪学 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='AI闪学']` | |
| 上课 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='上课']` | 精确匹配 |
| 消息 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='消息']` | |
| 我的 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='我的']` | |

**坐标兜底（仅 1080p 设备，其他分辨率需重测）：**

| Tab | 坐标 |
|-----|------|
| 上课 | (540, 2253) |

### iOS

| 元素名 | strategy | selector |
|--------|---------|---------|
| 上课 tab | xpath | `//*[@name='上课']` |
| 我的 tab | xpath | `//*[@name='我的']` |

---

## 上课首页

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 今日学习推荐 | xpath | `//*[@text='今日学习推荐']` |
| 我的课程 | xpath | `//*[@text='我的课程']` |
| 课程表入口 | xpath | `//*[@text='课程表']` |

### iOS

| 元素名 | strategy | selector |
|--------|---------|---------|
| 今日学习推荐 | xpath | `//*[@name='今日学习推荐']` |
| 我的课程 | xpath | `//*[@name='我的课程']` |
| 课程表入口 | xpath | `//*[@name='课程表']` |
| 今天按钮（课程表日历） | xpath | `//*[@name='今天']` |
| 返回按钮（通用页面） | tap 坐标 | `x=28, y=57`（比 xpath 更可靠） |
| 课程表-具体日期格子 | xpath | `//*[@name='YYYY年M月D日']`（如 `2026年5月26日`） |

**课程表日历翻页（iOS）：**

iOS 日历区域的左右 swipe 手势经常无效，改用以下方式：

```
# 方法一：直接 tap 目标日期格子（推荐）
appium_find_element strategy=xpath selector=//*[@name='2026年5月28日']
→ tap 该元素

# 方法二：W3C 精确 swipe（在日历组件内）
appium_perform_actions actions=[{
  "type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"},
  "actions": [
    {"type": "pointerMove", "duration": 0, "x": 700, "y": 400},
    {"type": "pointerDown", "button": 0},
    {"type": "pointerMove", "duration": 400, "x": 100, "y": 400},
    {"type": "pointerUp", "button": 0}
  ]
}]
# x 从右向左（700→100）= 翻至下一周/月；从左向右（100→700）= 返回上一周/月
```

---

## 课程详情页 / 课节详情页

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 直播核心课标题 | xpath | `//*[@text='直播核心课']` |
| 学习任务区域 | xpath | `//*[@text='学习任务']` |
| 学习资料金刚位 | xpath | `//*[@text='学习资料']` |
| 缓存课程金刚位 | xpath | `//*[@text='缓存课程']` |

### iOS

| 元素名 | strategy | selector | 备注 |
|--------|---------|---------|------|
| 直播核心课标题 | xpath | `//*[@name='直播核心课']` | |
| 学习任务区域 | xpath | `//*[@name='学习任务']` | |
| 学习资料金刚位 | xpath | `//*[@name='学习资料']` | 返回 `undefined` 时改用坐标 `(55, 218)` |
| 返回按钮 | tap 坐标 | `x=28, y=57` | xpath `//XCUIElementTypeButton[@name='返回']` 常返回 undefined，坐标更可靠 |

**导航路径：**
```
上课首页 → 我的课程 → 目标课程（课程详情页）→ 目标课节（课节详情页）→ 进教室
```

| 页面跳转 | 轮询目标（Android） | 超时 |
|---------|------------------|------|
| 进入课程详情 | `//*[@text='直播核心课']` | 5s |
| 进入课节详情 | `//*[@text='学习任务']` | 5s |

---

## 学习资料列表页

### iOS / Android 通用（按文件名匹配）

| 元素名 | strategy | selector |
|--------|---------|---------|
| mp4 文件 | xpath | `//*[contains(@name,'mp4') or contains(@name,'MP4')]` / `//*[contains(@text,'mp4')]` |
| MP3 文件 | xpath | `//*[contains(@name,'MP3') or contains(@name,'mp3')]` / `//*[contains(@text,'MP3')]` |
| PDF 文件 | xpath | `//*[contains(@name,'.pdf') or contains(@name,'.PDF')]` / `//*[contains(@text,'.pdf')]` |
| JPG 文件 | xpath | `//*[contains(@name,'.jpg') or contains(@name,'.JPG')]` / `//*[contains(@text,'.jpg')]` |

### 平台行为差异

| 平台 | 点击 mp4 的预期行为 |
|------|----------------|
| Android | App 内视频播放器打开（与 iOS 一致）；若弹出「跳转至微信」确认框属异常，应标记 FAIL |
| iOS | App 内全屏横屏视频播放器，需主动退出 |

### iOS 视频播放器退出（mp4 全屏横屏）

> 视频播放器有两层覆盖：controls overlay（含 `flow back`，y=-48 屏幕外）和始终可见的导航 overlay（含 `nav back white`）。

**推荐方式（稳定）：**

```
appium_find_element strategy=xpath selector=//*[@name='nav back white']
→ appium_gesture action=tap elementUUID=<uuid>
```

- `nav back white`：始终可见，位于横屏坐标 x=57, y=20，size 36×36
- `flow back`（旧文档描述）在 controls overlay 层，y=-48 屏幕外，**不可用**

**⚠️ 不要使用坐标 (45, 30) 或唤出控制栏的方案，nav back white 直接 tap 更可靠。**

---

## 直播教室（横屏）

> 进入教室后截图旋转 90°，见规则三-B

### AI视觉（旋转后）

| 元素名 | ai_instruction |
|--------|---------------|
| 退出按钮 | `exit or back button at top-left of landscape classroom` |
| 退出确认-确定 | `red '确定' button on the right side of '确定退出教室?' dialog` |
| 退出确认-取消 | `blue '取消' button on the left side of '确定退出教室?' dialog` |
| 聊天输入框 | `chat input field at bottom of classroom` |
| 发送按钮 | `'发送' button on the right side of chat input` |
| 举手按钮 | `raise hand icon button in classroom toolbar` |

### Android 降级

| 元素名 | xpath |
|--------|-------|
| 退出确认-确定 | `//*[@text='确定']` |
| 退出确认-取消 | `//*[@text='取消']` |

### iOS 降级

| 元素名 | xpath |
|--------|-------|
| 退出确认-确定 | `//*[@name='确定']` |
| 退出确认-取消 | `//*[@name='取消']` |

---

## 闪学口语课节专用

> ⚠️ 进度条为 Canvas 绘制，禁止拖拽，用 2x 倍速 + +10s 代替  
> ⚠️ 麦克风按钮禁止硬编码坐标，必须 AI 视觉定位

### 控制栏（百分比坐标）

```bash
W=$(adb -s <UDID> shell wm size | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f1)
H=$(adb -s <UDID> shell wm size | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f2)
# 唤出控制栏 + 点倍速（3秒窗口内连发）
adb -s <UDID> shell "input tap $((W/2)) $((H*43/100)); input tap $((W*94/100)) $((H*96/100))"
```

| 按钮 | X比例 | Y比例 |
|------|-------|-------|
| 视频中心（唤出控制栏） | 50% | 43% |
| 倍速 | 94% | 96% |
| +10s | 73% | 96% |

### 答题元素

| 元素名 | 定位方式 | selector |
|--------|---------|---------|
| 2.0x 倍速选项 | xpath | `//*[@text='2.0x']` |
| 听音选词-A | xpath | `//*[@text='A']` |
| 继续 | xpath | `//*[@text='继续']` |
| 完成 | xpath | `//*[@text='完成']` |
| 去分享（结束标志） | xpath | `//*[@text='去分享']` |

---

## 我的页 / 设置页

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 扫一扫 | `scan QR code icon button, square with rounded corners, second from right in top-right header of 我的 page` |
| 设置 | `hexagon settings icon button, rightmost icon in top-right corner of 我的 page` |
| 头像 | `circular avatar image at top of 我的 page` |

### Android

| 元素名 | xpath |
|--------|-------|
| 设置入口 | `//*[@text='设置']` |
| 我的订单 | `//*[@text='我的订单']` |
| 退出登录 | `//*[@text='退出登录']` |
| 清除缓存 | `//*[@text='清除缓存']` |

### iOS

| 元素名 | xpath |
|--------|-------|
| 设置入口 | `//*[@name='设置']` |
| 我的订单 | `//*[@name='我的订单']` |
| 退出登录 | `//*[@name='退出登录']` |

---

## 搜索页

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 搜索框 | `search input field with placeholder text at top of search page` |
| 热门搜索项 | `hot search keyword item in the search page` |

---

## Android resource-id 汇总

> 登录页元素见 [../../common/elements/login.md](../../common/elements/login.md)

| 元素 | resource-id |
|------|-------------|
| 底部 tab 标题 | `com.gaotu100.superclass:id/tab_title` |
| 广告关闭按钮 | `com.gaotu100.superclass:id/ad_close` |
| 协议确认按钮 | `com.gaotu100.superclass:id/customer_dialog_ok` |
| 首页年级阶段选择 | `com.gaotu100.superclass:id/ll_label` |
| 首页客服入口 | `com.gaotu100.superclass:id/consult_icon` |
| 首页AI搜索入口 | `com.gaotu100.superclass:id/gtui_search_bar` |
| 首页子tab栏容器 | `com.gaotu100.superclass:id/home_tabbar` |
| 首页今日推荐标题 | `com.gaotu100.superclass:id/section_title` |
| 首页换一换按钮 | `com.gaotu100.superclass:id/section_more_title` |
| 首页内容列表 | `com.gaotu100.superclass:id/list_view` |
| 首页帖子标题 | `com.gaotu100.superclass:id/tv_title` |
| 首页作者名 | `com.gaotu100.superclass:id/tv_user_name` |
| 首页点赞数 | `com.gaotu100.superclass:id/tv_like_count` |
| 首页内容封面图 | `com.gaotu100.superclass:id/cover_iv` |
| 消息页顶部标题 | `com.gaotu100.superclass:id/headbar_left_text` |
| 消息页快捷入口容器 | `com.gaotu100.superclass:id/top_message_list` |
| 消息列表容器 | `com.gaotu100.superclass:id/mymessageactivity_message_listview` |
| 消息项标题 | `com.gaotu100.superclass:id/messageitemview_message_title` |
| 消息项描述 | `com.gaotu100.superclass:id/messageitemview_message_des` |
| 消息项时间 | `com.gaotu100.superclass:id/messageitemview_message_time` |
| 消息项头像 | `com.gaotu100.superclass:id/messageitemview_message_avatar` |
| 消息未读角标 | `com.gaotu100.superclass:id/messageitemview_message_count` |
| 消息快捷入口标题 | `com.gaotu100.superclass:id/message_title` |

---

## iOS 定位说明

iOS 无 resource-id，降级时优先用 `accessibility id`（对应 accessibilityIdentifier/label），其次 `-ios predicate string` 按 label/value 匹配，最后 xpath `//*[@name='目标']`。

---

## 消息 Tab

### 页面特征
底部「消息」tab 选中，顶部标题区显示「消息」文字，下方分两区：顶部横向快捷入口（赞与收藏、评论互动、新增关注），下方为消息列表（系统通知、AI小途、活动消息等各类型消息项）。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 消息列表第一项 | `first message item in message list` |
| 系统通知项 | `system notification item in message list` |

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 页面顶部标题「消息」 | id | `com.gaotu100.superclass:id/headbar_left_text` |
| 顶部快捷入口容器 | id | `com.gaotu100.superclass:id/top_message_list` |
| 消息列表容器 | id | `com.gaotu100.superclass:id/mymessageactivity_message_listview` |
| 单条消息项标题 | id | `com.gaotu100.superclass:id/messageitemview_message_title` |
| 单条消息项描述 | id | `com.gaotu100.superclass:id/messageitemview_message_des` |
| 单条消息项时间 | id | `com.gaotu100.superclass:id/messageitemview_message_time` |
| 单条消息项头像 | id | `com.gaotu100.superclass:id/messageitemview_message_avatar` |
| 未读消息角标数字 | id | `com.gaotu100.superclass:id/messageitemview_message_count` |
| 快捷入口标题（赞与收藏等） | id | `com.gaotu100.superclass:id/message_title` |

---

## AI闪学 Tab 页内

### 页面特征
页面分四个区块：
1. **顶部页头**：左侧「AI闪学」Logo 图（ImageView），中部连胜天数徽章（可点击），右上无按钮
2. **我的闪学课程**：横向滚动课程卡片列表，每张卡片含课程名、节数/进度、「有更新」标签、「当前学到：课节N」；右上角「我的全部AI闪学」入口
3. **学习工具**：2×2 宫格，四个工具卡片：句句背单词、刷题、资料、真题
4. **限时活动**：横幅 Banner（可点击）
5. **闪学课程推荐**：课程卡片列表（底部，需下滑）

> ⚠️ 页面内容区（除底部 tab 外）无 resource-id，均为 React Native ViewGroup，需使用 AI视觉或 content-desc xpath 定位。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 连胜天数徽章 | `streak badge showing number of consecutive learning days at top of AI闪学 page` |
| 我的全部AI闪学入口 | `'我的全部AI闪学' link button at top-right of 我的闪学课程 section` |
| 课程卡片（第一张） | `first course card in 我的闪学课程 horizontal list, showing course name and progress` |
| 句句背单词工具 | `'句句背单词' tool card in 学习工具 grid, top-left` |
| 刷题工具 | `'刷题' tool card in 学习工具 grid, top-right` |
| 资料工具 | `'资料' tool card in 学习工具 grid, bottom-left` |
| 真题工具 | `'真题' tool card in 学习工具 grid, bottom-right` |
| 限时活动 Banner | `promotional banner in 限时活动 section` |

### Android（content-desc xpath）

> 内容区无 resource-id，用 `content-desc` 属性定位可点击元素。

| 元素名 | strategy | selector | 备注 |
|--------|---------|---------|------|
| 连胜天数徽章 | xpath | `//*[contains(@content-desc,'天连胜')]` | 格式：`N, N, 天连胜` |
| 我的全部AI闪学 | xpath | `//*[@content-desc='我的全部AI闪学']` | 右上角跳转入口 |
| 课程卡片（按课名） | xpath | `//*[contains(@content-desc,'当前学到')]` | 每张卡片包含进度文本 |
| 句句背单词 | xpath | `//*[contains(@content-desc,'句句背单词')]` | |
| 刷题 | xpath | `//*[contains(@content-desc,'刷题')]` | |
| 资料 | xpath | `//*[contains(@content-desc,'资料')]` | |
| 真题 | xpath | `//*[contains(@content-desc,'真题')]` | |
| 页面文字（无id） | xpath | `//*[@text='我的闪学课程']` | 页面特征元素，确认已到AI闪学页 |
| 学习工具区域 | xpath | `//*[@text='学习工具']` | 页面特征元素 |

| 页面跳转 | 轮询目标（Android） | 超时 |
|---------|------------------|------|
| 进入AI闪学 tab | `//*[@text='我的闪学课程']` | 8s |

---

## 首页

### 页面特征
顶部子 tab 栏含「我的订阅」「发现」「圈子」，发现为默认选中状态。子 tab 栏容器 resource-id: `com.gaotu100.superclass:id/home_tabbar`。选中状态元素使用 `select_text`，未选中使用 `unselect_text`，建议用 `@text` xpath 定位以避免状态依赖。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 发现子 tab | `'发现' tab selected in top tab bar of home page` |
| 我的订阅子 tab | `'我的订阅' tab in top tab bar of home page` |
| 圈子子 tab | `'圈子' tab in top tab bar of home page` |
| 年级阶段选择 | `grade/level selector button with text and dropdown arrow at top-left of home page` |
| 客服入口 | `headphone/customer service icon button at top-right of home page` |
| AI搜索入口 | `rounded search bar with mascot on left and '辅导' label on right, below top bar` |
| 金刚区图标（按文字定位） | `icon with label '数学' (or other subject) in the category grid section` |
| 活动广告卡片（左） | `left activity banner card with title and button in the home discovery feed` |
| 活动广告卡片（右） | `right activity banner card with title and button in the home discovery feed` |

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 发现子 tab | xpath | `//*[@text='发现']` |
| 我的订阅子 tab | xpath | `//*[@text='我的订阅']` |
| 圈子子 tab | xpath | `//*[@text='圈子']` |
| 子 tab 栏容器 | id | `com.gaotu100.superclass:id/home_tabbar` |
| 年级阶段选择按钮（左上角） | id | `com.gaotu100.superclass:id/ll_label` |
| 客服入口（右上角） | id | `com.gaotu100.superclass:id/consult_icon` |
| AI搜索入口 | id | `com.gaotu100.superclass:id/gtui_search_bar` |

### 发现页内容区（Android）

> ⚠️ 金刚区和活动资源位均为 B 端动态配置，图标文字和活动内容随后台配置变化，定位时以 AI 视觉为主，xpath `@text` 为辅。

| 元素名 | strategy | selector | 备注 |
|--------|---------|---------|------|
| 今日推荐标题 | xpath | `//*[@resource-id='com.gaotu100.superclass:id/section_title'][@text='今日推荐']` | 页面特征元素 |
| 换一换按钮 | id | `com.gaotu100.superclass:id/section_more_title` | |
| 金刚区图标（按品类文字） | xpath | `//*[@text='数学']`（或具体品类名） | B端配置，共10个；上行5个+下行5个 |
| 活动广告卡片（左/右） | ai_instruction | `left/right activity banner card with title and button in the home discovery feed` | B端配置，内容动态 |
| 帖子/内容标题 | id | `com.gaotu100.superclass:id/tv_title` | 列表内多个 |
| 作者名 | id | `com.gaotu100.superclass:id/tv_user_name` | |
| 点赞数 | id | `com.gaotu100.superclass:id/tv_like_count` | |
| 内容封面图 | id | `com.gaotu100.superclass:id/cover_iv` | |
| 内容列表 | id | `com.gaotu100.superclass:id/list_view` | RecyclerView |

| 页面跳转 | 轮询目标（Android） | 超时 |
|---------|------------------|------|
| 进入首页发现 tab | `//*[@text='发现']` | 5s |

---

## 发现-短视频流播放页

### 页面特征

全屏竖屏视频播放器（类抖音短视频流）：
- 右侧纵向排列：点赞数、评论数（···）、收藏数
- 底部：作者头像 + 名称 + 「关注」按钮 + 视频标题/描述文字
- 最底部：「说点什么...」评论输入框

**入口路径：** 首页 → 发现 tab → 今日推荐 → 点击任意视频卡片（`cover_iv` 或 `tv_title`）

### 滑动操作规范

| 操作 | 手势 | Appium 调用 |
|------|------|------------|
| 切换下一个视频 | 上滑 | `appium_gesture action=swipe direction=up speed=normal` |
| 切换上一个视频 | 下滑 | `appium_gesture action=swipe direction=down speed=normal` |

> ⚠️ 页面无标准 resource-id，元素定位全程使用 AI 视觉。

### AI视觉

| 元素 | ai_instruction |
|------|----------------|
| 点赞按钮 | `heart/like icon button on the right side of short video player` |
| 关注按钮 | `'关注' follow button below author avatar at bottom of short video player` |
| 评论输入框 | `'说点什么...' comment input bar at the very bottom of short video player` |
| 返回按钮 | `back arrow button at top-left of short video player` |
