# APK 探索驱动自动化测试设计

**日期**：2026-05-26  
**状态**：待实现

---

## 背景

当前框架需要人工在 Bitable 或自然语言中写好测试步骤，AI 才能执行。  
目标：用户只需提供 APK/IPA + 一句自然语言描述，AI 自动完成测试。

---

## 目标流程

```
APK/IPA 路径 → 安装 → 探索生成 App 地图 → 用户描述测试目标 → 自动执行
```

---

## 三个阶段

### 阶段 1：安装

1. 用户提供 APK/IPA 本地路径或下载链接
2. 执行 `appium_app_lifecycle install`（Android）或 `tidevice install`（iOS）
3. 提取版本号：
   - Android：`adb shell dumpsys package {pkg} | grep versionName`
   - iOS：`tidevice -u {udid} applist | grep {bundleId}`
4. 确定 catalog 目录：`apps/{app_id}/{version}/`
5. 若 `index.md` 已存在 → 跳过阶段 2，直接进入阶段 3

---

### 阶段 2：探索（生成 App 地图）

仅在以下情况触发：首次安装该版本，或用户主动要求重新探索。

#### 探索策略

- 广度优先遍历，最大深度 2
- 入口点：底部导航各 Tab（depth 0）
- 每层展开可交互元素，进入子页面（depth 1、2）

#### 单页探索步骤

1. `appium_screenshot` → 保存 `apps/{app_id}/{version}/pages/screenshots/{page}.png`
2. `appium_get_page_source` → 提取可交互元素
3. AI 归纳：页面名称、主要元素（含 xpath/accessibility_id）、可跳转入口
4. 写入 `pages/{page}.md`
5. 追加一行到 `index.md`
6. 导航回上一页，继续遍历

#### 跳过规则

| 情况 | 处理 |
|------|------|
| Webview 页面 | 记录存在，不深入 |
| 支付 / 外部跳转 | 记录存在，不触发 |
| 已访问页面 | 比对 UI 树签名去重，跳过 |
| depth > 2 | 停止，在 pages/*.md 注明"有更深层级" |

#### 文件格式

**`apps/{app_id}/{version}/index.md`**（常驻上下文，轻量）：

```markdown
| 页面名称    | 导航路径              | 文件                     | 深度 |
|-----------|---------------------|------------------------|------|
| 首页 Tab   | 启动后底栏第一项        | pages/home.md          | 0    |
| 课程详情页  | 首页 → 点击课程卡片     | pages/course_detail.md | 1    |
```

**`apps/{app_id}/{version}/pages/{page}.md`**（按需加载）：

```markdown
# 课程详情页

## 导航路径
首页 Tab → 点击任意课程卡片

## 截图
screenshots/course_detail.png

## 主要元素
- 课程标题：xpath=...
- 立即购买按钮：accessibility_id=...
- 课节列表入口：xpath=...

## 可跳转子页面
- 课节列表页：点击「查看课节」
- 支付页：点击「立即购买」（跳过，外部支付）
```

#### 目录结构

```
apps/
└── {app_id}/
    └── {version}/
        ├── index.md
        └── pages/
            ├── home.md
            ├── login.md
            ├── course_detail.md
            ├── ...
            └── screenshots/
                ├── home.png
                ├── login.png
                └── ...
```

---

### 阶段 3：执行

#### 流程

1. 读取 `index.md`（常驻上下文）
2. 根据用户自然语言描述，匹配相关页面
3. 按需 `Read` 对应 `pages/*.md`（通常 1-3 个）
4. 规划步骤（复用 `parsing.md` 路径 B 逻辑）
5. 通过 Appium MCP 执行（复用现有 gaotu skill 执行层）
6. 结果输出，可选回写 Bitable

#### 与现有框架对接

| 现有模块 | 复用方式 |
|---------|---------|
| `common/parsing.md` 路径 B | 自然语言 → ACTION/ASSERT 步骤列表 |
| `common/login.md` | 登录预置条件处理 |
| `gaotu` skill 执行层 | ACTION/ASSERT 执行逻辑 |
| `common/screenshot.md` | ASSERT 截图规范 |
| `common/app.md` | 安装/卸载流程 |

**新增唯一逻辑**：执行前读 `index.md` → 按需读 `pages/*.md` → 补充上下文，其余与现有用例执行完全一致。

---

## 上下文控制

- `index.md` 每行约 80 字符，50 页的 App 约 4000 字符，始终加载无压力
- 单页 `pages/*.md` 约 300-500 字符，执行时最多加载 3 个，合计 < 2000 字符
- 截图文件路径记录在 `pages/*.md` 中，仅 ASSERT 时按需读取，不占常驻上下文

---

## 版本管理

- 每个版本独立目录，旧版本保留不删除
- 版本号变更时执行阶段检测到 `index.md` 不存在，自动提示重新探索
- 用户也可强制触发重新探索（覆盖现有目录）

---

## 不在本次范围内

- 自动探索生成 Bitable 用例（需求不含）
- 多设备并行探索（复杂度高，后续可扩展）
- Webview 内页面深入探索（需切换 context，后续可扩展）
