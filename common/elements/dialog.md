# 公共弹窗元素

适用范围：矩阵所有App通用弹窗处理。  
`{pkg}` = 对应App的packageName，完整映射见 [../../CLAUDE.md](../../CLAUDE.md)

---

## 弹窗处理顺序

登录后批量处理，循环最多5轮，每轮截图判断一次：

1. 用户协议/隐私政策弹窗
2. 青少年模式弹窗
3. 广告 banner
4. 课程卡片/引导提示
5. 身份问卷
6. 系统权限弹窗（iOS）

---

## 各类弹窗元素

### 用户协议/隐私政策

| 元素名 | 定位方式 | selector / ai_instruction |
|--------|---------|--------------------------|
| 同意按钮 | AI视觉 | `red '同意' button on the right side of dialog bottom button row` |
| 同意按钮 | xpath（降级） | `//*[@text='同意']` (Android) / `//*[@name='同意']` (iOS) |

### 青少年模式

| 元素名 | ai_instruction |
|--------|---------------|
| 已满18岁按钮 | `'已满18岁' button in teenager mode dialog` |

### 广告 Banner

| 元素名 | 定位方式 | selector / ai_instruction | 备注 |
|--------|---------|--------------------------|------|
| 广告关闭按钮 | id（Android优先） | `{pkg}:id/ad_close` | |
| 广告关闭按钮 | AI视觉（降级） | `small '×' or '关闭' button at top-right corner of advertisement banner` | |

### 引导提示/课程卡片

| 元素名 | ai_instruction |
|--------|---------------|
| 知道了/关闭 | `'知道了' or '关闭' button at bottom of overlay popup` |

### 身份问卷（第1题）

| 元素名 | ai_instruction | 备注 |
|--------|---------------|------|
| 高中选项 | `'高中' option button in identity questionnaire` | 选高中，再点下一步 |
| 跳过（后续题） | `'跳过' button at top-right of questionnaire page` | 跳过后点「确认退出」 |

### 系统权限弹窗（iOS）

| 处理方式 | 说明 |
|---------|------|
| `appium_alert action=accept` | 允许/好 |
| AI视觉 | `'允许' or '好' button in system permission dialog` |

---

## 弹窗识别特征（截图判断）

| 弹窗类型 | 截图可见关键词 |
|---------|--------------|
| 用户协议 | "用户协议"、"隐私政策"、"同意" |
| 青少年模式 | "青少年"、"已满18岁" |
| 广告 | 右上角×或"跳过"，全屏覆盖图片 |
| 引导提示 | "知道了"、"我知道了" |
| 身份问卷 | "小学"/"初中"/"高中" 选项 |
| 系统权限 | "允许"/"好"（iOS系统弹窗样式） |
