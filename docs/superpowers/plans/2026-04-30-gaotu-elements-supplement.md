# 高途 Android 元素补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 `skills/gaotu/elements.md` 中缺失的首页、消息 tab、AI闪学页内元素，修正错误条目，并将 TARGET_PAGE 映射表从 `common/parsing.md` 迁移到 `skills/gaotu/SKILL.md`。

**Architecture:** 连接真机，逐页截图 + page source 提取 resource-id/xpath，按现有 elements.md 格式写入。TARGET_PAGE 表整体搬迁，不改内容逻辑。

**Tech Stack:** Appium MCP (appium-uiautomator2)、adb、Android 设备 ce67d979

---

### Task 1: 设备就绪 & 创建 Session

**Files:**
- 参考: `common/device.md`

- [ ] **Step 1: 检查设备连接**

```bash
adb devices
```
预期：`ce67d979  device`（或其他已连接设备序列号）

- [ ] **Step 2: 确认 uiautomator2 驱动已安装**

```bash
appium driver list --installed
```
预期：列表中包含 `uiautomator2`

- [ ] **Step 3: 创建 Appium Session**

调用 `create_session`，capabilities：
```json
{
  "platformName": "Android",
  "appium:udid": "ce67d979",
  "appium:automationName": "uiautomator2",
  "appium:packageName": "com.gaotu100.superclass",
  "appium:noReset": true,
  "appium:autoGrantPermissions": true,
  "appium:skipServerInstallation": true
}
```

- [ ] **Step 4: 确认 App 在前台（上课 tab 可见）**

```
appium_find_element strategy=xpath selector=//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='上课']
```
若找到则继续；若在登录页则先登录（密码登录，账号 12100000000 / Gaotu@1234）。

---

### Task 2: 补全底部导航 Tab 元素

**Files:**
- Modify: `skills/gaotu/elements.md` — 底部导航 Tab 章节

- [ ] **Step 1: 截图确认底部 5 个 tab 的外观**

```
appium_screenshot maxWidth=800
```

- [ ] **Step 2: 获取底部 tab 完整 page source**

```
appium_get_page_source
```
在 XML 中找所有 `resource-id` 含 `tab_title` 或 `tab` 的节点，记录每个 tab 的 text 属性值（首页/上课/AI闪学/消息/我的）。

- [ ] **Step 3: 更新 elements.md 底部导航章节**

删除错误条目：
```
| 发现 tab | 底部 tab "发现"选中状态 |
```

在「底部导航 Tab - Android」表格补充：
```markdown
| 首页 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='首页']` | 填入真实 text 值 |
| 消息 tab | xpath | `//*[@resource-id='com.gaotu100.superclass:id/tab_title'][@text='消息']` | 填入真实 text 值 |
```
（text 值以 page source 实际值为准，可能是「首页」「消息」或其他）

同步更新「页面特征识别」表格，补充：
```markdown
| 首页（发现子tab） | 顶部子 tab 栏含「发现」「我的订阅」「圈子」，发现子 tab 默认选中 |
| 消息 tab | 顶部标题「消息」，下方消息列表 |
```

---

### Task 3: 首页元素（发现 / 我的订阅 / 圈子）

**Files:**
- Modify: `skills/gaotu/elements.md` — 新增「首页」章节

- [ ] **Step 1: 导航到首页 tab**

```
appium_gesture action=tap elementUUID=<首页 tab UUID>
```
等待首页加载：轮询 `xpath=//*[@text='发现']` 或 `[@text='我的订阅']` 出现，超时 5s。

- [ ] **Step 2: 截图 + page source（发现子 tab）**

```
appium_screenshot maxWidth=800
appium_get_page_source
```
记录：
- 子 tab 栏的 resource-id
- 「发现」子 tab 的选中/未选中 selector
- 内容区特征元素（帖子列表、关注按钮等）

- [ ] **Step 3: 切换到「我的订阅」子 tab，截图 + page source**

```
appium_find_element strategy=xpath selector=//*[@text='我的订阅']
appium_gesture action=tap elementUUID=<UUID>
appium_screenshot maxWidth=800
appium_get_page_source
```
记录「我的订阅」子 tab selector。

- [ ] **Step 4: 切换到「圈子」子 tab，截图 + page source**

```
appium_find_element strategy=xpath selector=//*[@text='圈子']
appium_gesture action=tap elementUUID=<UUID>
appium_screenshot maxWidth=800
appium_get_page_source
```
记录「圈子」子 tab selector。

- [ ] **Step 5: 写入 elements.md 新章节**

在 `skills/gaotu/elements.md` 末尾（我的页/设置页之后）新增：

```markdown
## 首页

### 页面特征
顶部子 tab 栏含「发现」「我的订阅」「圈子」，发现为默认选中状态。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 发现子 tab | `'发现' tab selected in top tab bar of home page` |
| 我的订阅子 tab | `'我的订阅' tab in top tab bar of home page` |
| 圈子子 tab | `'圈子' tab in top tab bar of home page` |

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 发现子 tab | xpath | （填入真实值） |
| 我的订阅子 tab | xpath | （填入真实值） |
| 圈子子 tab | xpath | （填入真实值） |
```
（所有 selector 填入 Step 2-4 记录的真实值）

---

### Task 4: 消息 Tab 元素

**Files:**
- Modify: `skills/gaotu/elements.md` — 新增「消息 tab」章节

- [ ] **Step 1: 导航到消息 tab**

```
appium_gesture action=tap elementUUID=<消息 tab UUID>
```
等待加载：轮询 `xpath=//*[@text='消息']`（标题）出现，超时 5s。

- [ ] **Step 2: 截图 + page source**

```
appium_screenshot maxWidth=800
appium_get_page_source
```
记录：顶部标题、消息列表容器、单条消息项的 resource-id。

- [ ] **Step 3: 写入 elements.md 新章节**

```markdown
## 消息 Tab

### 页面特征
顶部标题「消息」，下方为消息列表。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 消息列表第一项 | `first message item in message list` |

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 页面标题 | xpath | （填入真实值） |
| 消息列表容器 | xpath/id | （填入真实值） |
```

---

### Task 5: AI闪学页内元素

**Files:**
- Modify: `skills/gaotu/elements.md` — 扩充「AI闪学 tab」章节

- [ ] **Step 1: 导航到 AI闪学 tab**

```
appium_gesture action=tap elementUUID=<AI闪学 tab UUID>
```
等待加载：轮询 `xpath=//*[@text='AI闪学']` 或学习地图特征元素出现，超时 8s。

- [ ] **Step 2: 截图 + page source（AI闪学主页）**

```
appium_screenshot maxWidth=800
appium_get_page_source
```
记录：学习地图容器、课节入口按钮、进度条/里程碑等关键元素的 resource-id。

- [ ] **Step 3: 写入 elements.md**

在现有「AI闪学 tab」相关条目之后扩充：

```markdown
## AI闪学 Tab 页内

### 页面特征
学习地图可滚动，含课节节点（圆形图标+课节名），顶部含进度信息。

### AI视觉

| 元素名 | ai_instruction |
|--------|---------------|
| 学习地图课节节点 | `circular lesson node with title text in AI learning map` |
| 开始学习按钮 | `'开始学习' or '继续学习' button on AI learning map page` |

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 学习地图容器 | id/xpath | （填入真实值） |
| 课节节点 | xpath | （填入真实值） |
```

---

### Task 6: 迁移 TARGET_PAGE 映射表

**Files:**
- Modify: `skills/gaotu/SKILL.md` — 第零步末尾
- Modify: `common/parsing.md` — 删除 TARGET_PAGE 章节

- [ ] **Step 1: 从 `common/parsing.md` 复制 TARGET_PAGE 表**

找到「分析目标起始页」章节（约第 142-154 行），复制整段内容。

- [ ] **Step 2: 粘贴到 `skills/gaotu/SKILL.md` 第零步末尾**

在第零步「收集到：…记录在上下文。」之前插入，补充「首页 tab」映射：

```markdown
| 首页、发现、订阅、圈子 | 首页 tab | 底部导航 → 首页 |
```

- [ ] **Step 3: 删除 `common/parsing.md` 中的 TARGET_PAGE 章节**

删除「## 分析目标起始页」及其下方的完整表格。

---

### Task 7: 关闭 Session & 验收

- [ ] **Step 1: 关闭 Appium Session**

```
delete_session()
```

- [ ] **Step 2: 核查 elements.md**

确认以下各项均已完成：
- [ ] 「发现 tab | 底部 tab」错误条目已删除
- [ ] 底部导航补充了「首页 tab」「消息 tab」
- [ ] 新增「首页」章节，含 3 个子 tab 的 AI视觉 + Android selector
- [ ] 新增「消息 Tab」章节
- [ ] 扩充「AI闪学 Tab 页内」章节
- [ ] 所有占位「（填入真实值）」已替换为真实 selector

- [ ] **Step 3: 核查 SKILL.md 和 parsing.md**

- [ ] TARGET_PAGE 表已在 `skills/gaotu/SKILL.md` 第零步内
- [ ] `common/parsing.md` 中 TARGET_PAGE 章节已删除
- [ ] 「首页」导航映射已加入 TARGET_PAGE 表
