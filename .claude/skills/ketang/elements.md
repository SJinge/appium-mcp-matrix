# 高途素养 App 元素定位规范

> 供 `ketang` skill 引用。公共登录元素见 [../../common/elements/login.md](../../common/elements/login.md)，公共弹窗元素见 [../../common/elements/dialog.md](../../common/elements/dialog.md)。

包名：`com.gaotu100.ketang`

---

## 页面特征识别

| 页面 | 特征标志 |
|------|----------|
| 首页 tab | 底部 tab 选中，下方课程/内容推荐列表 |
| 课程详情页 | 顶部课程名称，课节列表 |
| 课节详情页 | 课节名称，学习任务区域 |
| 直播教室 | 横屏，视频区域 + 互动栏 |
| 登录页 | "手机号登录"标题，输入框，"获取验证码"按钮 |
| 我的页 | 顶部头像 + 手机号，下方功能列表 |

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

**Android 登录页**：验证码页因 FLAG_SECURE 截图黑屏，只能用 page source + resource-id；切换到密码登录页后恢复正常。  
**iOS**：无 FLAG_SECURE，全程截图可用。

### 规则四：三级降级策略

```
第一级：截图 + AI 视觉定位（ai_instruction）
    ↓ 截图失败（FLAG_SECURE）或 AI 视觉失败
第二级：page source + 属性定位
    Android：resource-id 优先，xpath //*[@text='目标'] 次之
    iOS：accessibility id 优先，xpath //*[@name='目标'] 次之
    ↓ 仍找不到
第三级：坐标硬点击（兜底）
    仅用于已知固定布局（如底部 tab），记录日志说明
```

### 规则五：定位前等待页面稳定

```
方法 A（推荐）：轮询等待目标页面特征元素出现，超时 10s
方法 B（兜底）：普通页面跳转 sleep 0.5s，直播页面加载 sleep 1s
```

---

## 高频元素 ai_instruction

| 元素 | ai_instruction |
|------|----------------|
| 关闭/知道了 | `'知道了' or '关闭' button at bottom of overlay popup` |
| 同意按钮 | `red '同意' button on the right side of dialog bottom button row` |
| 我的 tab | `'我的' bottom navigation tab with icon above text, rightmost tab` |

---

## 底部导航 Tab

### Android

| 元素名 | strategy | selector |
|--------|---------|---------|
| 上课 tab | xpath | `//*[@resource-id='com.gaotu100.ketang:id/tab_title'][@text='上课']` |
| 我的 tab | xpath | `//*[@resource-id='com.gaotu100.ketang:id/tab_title'][@text='我的']` |

### iOS

| 元素名 | strategy | selector |
|--------|---------|---------|
| 上课 tab | xpath | `//*[@name='上课']` |
| 我的 tab | xpath | `//*[@name='我的']` |

---

## Android resource-id 汇总

> 登录页元素见 [../../common/elements/login.md](../../common/elements/login.md)

| 元素 | resource-id |
|------|-------------|
| 底部 tab 标题 | `com.gaotu100.ketang:id/tab_title` |
| 广告关闭按钮 | `com.gaotu100.ketang:id/ad_close` |
| 协议确认按钮 | `com.gaotu100.ketang:id/customer_dialog_ok` |

---

## iOS 定位说明

iOS 无 resource-id，降级时优先用 `accessibility id`，其次 `-ios predicate string`，最后 xpath `//*[@name='目标']`。
