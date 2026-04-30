# 高途 Android 元素补全设计文档

**日期：** 2026-04-30  
**范围：** `skills/gaotu/elements.md` + `common/parsing.md` → `skills/gaotu/SKILL.md`

---

## 背景

当前 `elements.md` 存在两个问题：
1. 「发现 tab | 底部 tab」条目错误——发现是首页内子 tab，不是底部导航项
2. 首页、消息 tab、AI闪学页内元素完全缺失，遇到这些页面的用例会卡住

`common/parsing.md` 中的 TARGET_PAGE 映射表包含「AI闪学」「上课 tab」等高途专属概念，放在 common 层会误导其他 App。

---

## 目标

连接真机，逐页截图 + page source，补全 Android 元素文档。

---

## 变更范围

### 1. `skills/gaotu/elements.md`

**修正：**
- 删除「发现 tab | 底部 tab '发现'选中状态」错误条目

**补充底部导航：**
- 首页 tab（selector 待真机确认）
- 消息 tab（selector 待真机确认）

**新增页面章节：**

| 页面 | 补充内容 |
|------|---------|
| 首页 | 页面特征、子 tab 切换（发现/我的订阅/圈子）元素 |
| 消息 tab | 页面特征、消息列表、通知项常用元素 |
| AI闪学页内 | 学习地图、课节入口、进度相关元素 |

每个页面补充格式：页面特征识别 → AI视觉 ai_instruction → Android xpath/resource-id

### 2. `skills/gaotu/SKILL.md`

**新增：** 第零步末尾补 TARGET_PAGE 映射表（从 `common/parsing.md` 移入），加「首页」导航映射。

### 3. `common/parsing.md`

**删除：** TARGET_PAGE 映射表（迁移到 gaotu SKILL.md 后移除，避免其他 App 误用）。

---

## 操作步骤

1. 检查 adb 设备连接
2. 创建 Appium Session
3. 逐页操作：截图 → page source → 提取元素 → 写入文档
   - 首页（发现子 tab）
   - 首页切换到我的订阅子 tab
   - 首页切换到圈子子 tab
   - 消息 tab
   - AI闪学 tab 页内
4. 更新 elements.md
5. 迁移 TARGET_PAGE 映射表
6. 关闭 Session

---

## 验收标准

- elements.md 中每个新增页面均有：页面特征识别条目 + 至少一条 AI视觉 ai_instruction + Android xpath/resource-id
- TARGET_PAGE 表只存在于 `skills/gaotu/SKILL.md`，`common/parsing.md` 中已删除
- 错误的「发现 tab」底部导航条目已删除
