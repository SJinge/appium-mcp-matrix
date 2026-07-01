---
name: gaotu
description: |
  高途 app 移动端自动化测试全生命周期 skill，支持 Android 和 iOS 双端。
  触发词："高途用例"、"执行测试"、"测试高途"、"gaotu test"、"用例 ID"
---

# 角色规范

本 skill 基于 **appium-expert** 角色规范运行。以下仅包含高途 app 专用执行流程。

---

# 高途 App 专用参数

| 参数 | Android 默认 | iOS 默认 |
|------|-------------|---------|
| device | `ce67d979` | 用户提供 UDID |
| packageName | `com.gaotu100.superclass` | — |
| bundleId | — | 首次使用请确认 |

> **账号策略**：不使用硬编码默认账号。登录所需手机号/密码/验证码一律**从用例中解析**——优先取用例「测试步骤」文本中明确写出的账号（如 `输入手机号12345679000`、`密码Gaotu@123`、`验证码1000`），其次取预置条件中指定的账号。用例未提供时向用户询问，**不得套用其它账号**。
>
> 元素定位规范见 [elements.md](elements.md)

---

# 执行全流程

## 第零步：收集用例信息 & 解析步骤

**在做任何设备操作之前**，先确认以下信息：

```
1. 用例来源？A. 搬山 caseId  B. 自然语言  C. 飞书 Bitable 链接  D. Monkey 测试
2. 目标平台？Android / iOS        ← 仅路径 A/B 需要询问
3. 使用哪台设备？（默认见上表）   ← 仅路径 A/B 需要询问
```

> 路径 C：平台和设备由 `EXECUTION_ENTRIES` 自动确定，无需询问第2、3项。  
> 用户消息已包含上述信息则跳过询问，直接进入解析。

按用例来源选择对应解析路径，完整规则见 [../../common/parsing.md](../../common/parsing.md)：

- **路径 A（搬山 caseId）**：`testCaseDetail(caseId)` → 解析节点树，含"预期结果"的节点为 ASSERT，其余为 ACTION
- **路径 B（自然语言）**：按换行/序号切分，以"预期："/"验证："开头的行为 ASSERT
- **路径 C（飞书 Bitable）**：从 URL 提取 `app_token + table_id`，读取记录，解析 测试步骤/验证点/预期结果/预置条件；**同时捕获每条记录的 `ID` 字段值（自增编号）作为 `case_id`，以及 `record_id`（Bitable内部标识符，格式如 `recXXXXXX`）用于执行后回写来源表**；按 `android执行设备` / `ios执行设备` 字段拆分为 `EXECUTION_ENTRIES`（每条记录最多产出 Android + iOS 两条，两字段均空则跳过）；按设备分组后参考 [../../common/parallel.md](../../common/parallel.md) 并行派发
  > ⚠️ **取记录必须按指定执行视图顺序**：search 传 `data.view_id`（gaotu = `vewJViMvTW`，见 [../../scripts/feishu_config.py](../../scripts/feishu_config.py)），**禁止传自定义 sort**。用户说的「第 N 条」= 该视图返回 `items[N-1]`。完整规则见 [../../common/parsing.md](../../common/parsing.md) 路径 C。
  > 预置条件中"进入 XX tab / 进入 app 首页"类条目**直接忽略**，不生成 PRECOND 步骤——tab 导航由模块字段统一处理（见下方 TARGET_PAGE 分析）

- **路径 D（Monkey 测试）**：询问以下参数后，按 `common/monkey.md` 执行：

  ```
  询问（有默认值的可直接回车跳过）：
  - 目标平台？Android / iOS  （默认 Android）
  - 使用哪台设备？           （默认 ce67d979）
  - 最大操作步数？           （默认 500）
  - 最大运行时长（分钟）？    （默认 30）
  ```

  确认参数后，设置以下变量并调用 `common/monkey.md`：
  - `APP_ID=gaotu`
  - `PKG=com.gaotu100.superclass`（Android）或 `PKG=<bundleId>`（iOS，首次使用请确认）
  - `ACCOUNT=12100000000`
  - `VERSION`：从以下命令提取：
    ```bash
    adb shell dumpsys package com.gaotu100.superclass | grep versionName | head -1
    ```
  - `UDID`：使用用户指定值或默认 `ce67d979`
  - `max_ops`、`max_minutes`：使用用户输入或默认值

  路径 D 不进行 TARGET_PAGE 分析，直接进入 `common/monkey.md` 初始化章节。

解析完成后分析 `TARGET_PAGE`，展示步骤列表等用户确认。

### 目标起始页分析（TARGET_PAGE）

**三级判断，优先级从高到低：**

1. **预置条件**中的起始页描述
2. 路径 C 的**模块字段**
3. **步骤关键词**（兜底）

#### 第一级：预置条件起始页 → 直接赋值 TARGET_PAGE（所有路径）

解析预置条件文字，若含明确起始页描述则直接赋值，**跳过后续两级判断**：

| 预置条件关键词（任意命中） | TARGET_PAGE |
|--------------------------|-------------|
| 课节列表、课节列表页 | 课程详情页 |
| 课节详情、课节详情页 | 课节详情页 |
| 课程详情、课程详情页 | 课程详情页 |
| 上课 tab、上课页 | 上课 tab |
| 首页、首页 tab | 首页 tab |
| 我的、我的页 | 我的页 |
| 设置页、设置 | 我的页-设置 |
| AI闪学、闪学 tab | AI闪学 tab |
| 消息、消息 tab | 消息 tab |
| 搜索页 | 搜索页 |
| 登录页、未登录 | 无需导航 |

#### 第二级：模块字段 → 直接赋值 TARGET_PAGE（仅路径 C，预置条件未命中时）

```
MODULE = Bitable 模块字段值

if MODULE == "上课":
    TARGET_PAGE = 上课 tab（进入第三级关键词细化）
elif MODULE == "闪学":
    TARGET_PAGE = AI闪学 tab
elif MODULE == "首页":
    TARGET_PAGE = 首页 tab
elif MODULE == "我的":
    TARGET_PAGE = 我的页（进入第三级关键词细化）
elif MODULE == "消息":
    TARGET_PAGE = 消息 tab
elif MODULE == "启动登录":
    TARGET_PAGE = 无需导航
```

#### 第三级：步骤关键词 → 细化 TARGET_PAGE

适用于：① 路径 A/B（无模块字段，完整跑关键词表）；② 路径 C 中模块为"上课"或"我的"时补充细化。

| 步骤关键词（任意命中） | TARGET_PAGE | 导航路径 |
|----------------------|-------------|---------|
| 直播、进教室、课节、开始上课 | 课节详情页 | 上课 tab → 我的课程 → [课程] → [课节] |
| 课程详情、课程介绍、课程服务 | 课程详情页 | 上课 tab → 我的课程 → [课程] |
| 搜索、查找课程 | 搜索页 | 上课 tab → 搜索入口 |
| 退出登录、注销 | 我的页-设置 | 底部导航 → 我的 → 设置 |
| 我的、设置、账号、个人信息 | 我的页 | 底部导航 → 我的 |
| AI闪学、闪学课、地图、课程地图 | AI闪学 tab | 底部导航 → AI闪学 tab |
| 首页、发现、订阅、圈子 | 首页 tab | 底部导航 → 首页 |
| （默认/其他）| 上课 tab | 已就绪 |

收集到：**平台类型、设备 UDID、账号、步骤列表、TARGET_PAGE**，记录在上下文。

用例数 ≥ 2 时执行预扫描（**仅路径 A/B 顺序执行**）：> 见 [../../common/prescan.md](../../common/prescan.md)

> 路径 C 跳过全局（跨设备）预扫描。改为**每设备在派发批级 subagent 之前**，对该设备全部用例做账号聚类排序 + 按 `BATCH_SIZE` 切批（见 [../../common/prescan.md](../../common/prescan.md)「切批」、[../../common/parallel.md](../../common/parallel.md)「设备内分批」）；批级 subagent 只对本批做预置条件处理。切批前必须全局排序，禁止先切后排。

---

## 设备就绪检查

> 见 [../../common/device.md](../../common/device.md)

---

---
> ⚠️ **第一步 ~ 第五步为 Session 级初始化，每次 Session 只执行一次。**  
> 用例循环中的重启/账号切换逻辑在第七步「预置条件处理」中单独处理，不得重复执行第一步 ~ 第五步。

---

## 第一步：系统权限预授权

> 见 [../../common/permission.md](../../common/permission.md)，`packageName = com.gaotu100.superclass`

---

## 第二步：检查 / 创建 Appium Session

先检查是否存在活跃 Session（`list_sessions`）：

- **已有活跃 Session** → 复用，跳过本步余下内容，直接进第三步
- **无 Session** → 按 [../../common/device.md](../../common/device.md) 模板新建，填入高途专用参数

---

## 第三步：激活高途 App

> 仅 activate，不 terminate，保留设备上已有的登录状态。  
> 若为卸载重装后首次启动，需额外处理首次启动弹窗，见 [startup.md](startup.md)。

**Android：**
```bash
adb -s <device> shell am start -n com.gaotu100.superclass/.ui.activity.SplashActivity
```
轮询等待底部 tab 出现（最多 10s）：`xpath=//*[@resource-id='com.gaotu100.superclass:id/tab_title']`  
若显示登录页（底部 tab 未出现），点关闭按钮：`id=com.gaotu100.superclass:id/login_view_close_iv`

**iOS：**
```
appium_app_lifecycle action=activate id=<bundleId>
```
轮询等待底部 tab 出现（最多 10s）：`xpath=//*[@name='上课']`  
若显示登录页（底部 tab 未出现），AI 视觉点关闭：`'×' or close button at top of login page`


---

## 第四步：批量处理启动弹窗

> 循环规则见 [../../common/screenshot.md](../../common/screenshot.md)

循环检测并关闭弹窗（最多 5 轮）：

| 弹窗/页面 | 定位方式 | 点击目标 |
|-----------|----------|----------|
| 广告 banner | AI 视觉；Android 降级 `ad_close` | 关闭/×按钮 |
| 课程卡片提示 | 截图 → AI 视觉 | `'知道了' button at bottom of popup` |
| 身份问卷第 1 题 | 截图可见「小学/初中/高中」| 点「高中」→「下一步」|
| 身份问卷后续 | 截图可见「跳过」| 点「跳过」→「确认退出」|
| 系统权限弹窗（iOS）| 截图可见"允许"/"好" | `appium_alert action=accept` |

```bash
GAOTU_SETUP_END=$(date +%s)
echo "setup 耗时：$((GAOTU_SETUP_END - GAOTU_START))s"
```

---

## 第五步：记录执行起点 & 创建截图目录

```bash
EXEC_START_TIME=$(date +%H:%M:%S)
GAOTU_CASE_START=$(date +%s)
SHOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/shots/gaotu/$(date +%Y%m%d_%H%M)_${CASE_ID:-manual}"
mkdir -p "$SHOT_DIR"
```

输出：`✓ setup 完成（session/弹窗）⏱ Xs → 开始执行…`

> 导航逻辑已移入第七步，每条用例执行前独立计算 TARGET_PAGE 并导航，支持多用例批量执行。

---

## 第七步：用例步骤执行循环

> 截图/等待规范见 [../../common/screenshot.md](../../common/screenshot.md)；元素定位见 [elements.md](elements.md)

**静默执行**：循环期间不向用户输出中间文字，结果汇入内部日志，仅在第八步报告中展示。

> ⚠️ **第八步强制执行**：无论用例通过/失败，循环结束后必须执行第八步（上传截图、写 Wiki 报告、发群消息）。ASSERT/ACTION 失败只终止当前用例的后续步骤，不得跳过第八步。

### 初始化（每条用例开始前）

在上下文中维护以下变量（非 shell 变量，由 Claude 在对话上下文中跟踪）：

```
CASE_STEPS = []          # 当前用例的步骤结果列表
CASE_PASSED = true       # 只要有 PRECOND/ACTION FAIL 就置 false
CASES_JSON = []          # 所有用例的汇总（跨用例累积）
CASE_START_TS = $(date +%s)
```

### 预置条件处理 & 导航至目标起始页（每条用例执行前）

**先处理预置条件（重启/账号），再执行导航。**

> 完整扫描逻辑见 [../../common/prescan.md](../../common/prescan.md)

**⚠️ 账号切换规则（禁止重启 App 或重建 Session）：**

当 `REQUIRED_ACCOUNT ≠ CURRENT_ACCOUNT` 时，**仅执行以下操作**：

```
1. 导航到「我的」tab
2. AI 视觉点击设置图标（hexagon settings icon button, rightmost icon in top-right corner of 我的 page）
3. 找到并点击「退出登录」
4. 轮询等待跳转到登录页（最多 5s）
5. 按 common/login.md 流程用密码登录 REQUIRED_ACCOUNT
6. CURRENT_ACCOUNT = REQUIRED_ACCOUNT
```

禁止因账号切换而：重启 App（force-stop / am start）、重建 Appium Session、重走第一步~第五步。

**⚠️ NEED_RESTART 判断：**

```
if NEED_RESTART == true:
    仅执行 App 重启（第三步逻辑），不重建 Session
    重启后重新处理弹窗（第四步逻辑）
else:
    确认 App 在前台（截图或 page_source），不重启
```

**每条用例开始前**，先根据该用例的模块/步骤重新计算 TARGET_PAGE，再执行导航。

TARGET_PAGE 计算规则同第零步（路径 C 先用模块字段，路径 A/B 走关键词表）。

**导航前先检查当前页面**：`get_page_source` 判断当前页面特征，若已在 TARGET_PAGE 对应页面则跳过导航，直接进入步骤执行。

| TARGET_PAGE | 已在目标页的判断特征 | 导航路径 |
|-------------|-------------------|---------|
| 上课 tab（默认）| 底部"上课" tab 处于选中状态，且无课程详情/课节列表层叠 | Android `tab_title[@text='上课']`；iOS `//*[@name='上课']`；坐标兜底 `(540, 2253)` |
| 课程详情页 | 页面含课程名称 + 课节列表区域 | 上课 tab → 我的课程 → 目标课程 |
| 课节详情页 | 页面含课节标题 + 进教室/进入按钮 | 课程详情页 → 目标课节 |
| 搜索页 | 顶部搜索输入框可见 | 上课 tab → 搜索入口 |
| 我的页 | 底部"我的" tab 处于选中状态 | Android `tab_title[@text='我的']`；iOS `//*[@name='我的']` |
| 我的页-设置 | 页面含"账号与安全"/"退出登录"等设置项 | 我的页 → AI 视觉 `hexagon settings icon button, rightmost icon in top-right corner of 我的 page` |
| AI闪学 tab | 底部"AI闪学" tab 处于选中状态 | Android `tab_title[@text='AI闪学']`；iOS `//*[@name='AI闪学']` |
| 首页 tab | 底部"首页" tab 处于选中状态 | Android `tab_title[@text='首页']`；iOS `//*[@name='首页']` |
| 消息 tab | 底部"消息" tab 处于选中状态 | Android `tab_title[@text='消息']`；iOS `//*[@name='消息']` |
| 无需导航 | — | 跳过，直接执行第一个步骤 |

导航完成后重置 CASE_START_TS（排除导航耗时）：
```
CASE_START_TS = $(date +%s)
```

### 执行循环

```
for 步骤N in 步骤列表:

  ━━ PRECOND ━━
  截图确认当前状态 → 符合则 pass=true
  不符合 → 尝试恢复（导航/重启/重新登录）
  恢复失败 → pass=false，CASE_PASSED=false
  → 追加到 CASE_STEPS，立即终止整个用例 → 进入收尾

  ━━ ASSERT ━━
  > 完整规范见 [../../common/assert_spec.md](../../common/assert_spec.md)

  截图前：确认页面无骨架屏/spinner/加载中，否则等待（最多5s）后再截图
  特殊：验证点标注 [TOAST] 时，ACTION 执行后立即截图（1s内），不可延迟

  截图（教室内先旋转90°）→ 压缩保存

  依次判断三个问题（缺一不可）：
    Q1（功能）：预期内容是否出现？→ func_pass
    Q2（数据）：涉及具体数值/文案时，实际内容与预期一致？→ data_pass
    Q3（UI）：见 [../../common/ui_spec.md](../../common/ui_spec.md) → ui_pass

  pass = func_pass AND data_pass AND ui_pass
  note 强制填写（不得留空）：
    格式："<实际观测内容>；数据<正常/异常>；UI<无异常 / 问题：具体描述>"
  → 追加到 CASE_STEPS

  ━━ ACTION ━━
  解析动作类型（点击/输入/滑动/等待）
  截图确认页面 → 三级降级策略定位并执行
  执行后截图：若下一步是ASSERT交给ASSERT处理；否则判断页面变化
  pass = 执行成功则 true，否则 false；失败时 CASE_PASSED=false
  每步后检测非预期弹窗，先处理再继续
  → 追加到 CASE_STEPS
```

**每步执行后追加格式：**

```python
CASE_STEPS.append({
    "text": "<步骤描述文字>",
    "type": "PRECOND" | "ACTION" | "ASSERT",
    "pass": true | false,
    # 仅 ASSERT 且有实际观测值时填写：
    "note": "<实际看到的内容>"
})
```

### 单条用例结束后组装

```python
CASE_END_TS = $(date +%s)

CASES_JSON.append({
    "name": "<用例名称>",
    "module": "<模块名>",              # 路径C：从 Bitable 模块字段读取；路径A/B：从 TARGET_PAGE 推断（见映射表）
    "case_id": <原表ID字段值>,         # 路径C：Bitable 记录的 ID 自增编号；路径A/B：留空或填0
    "source_record_id": "<record_id>", # 路径C：Bitable 内部标识符（recXXXXXX），用于回写来源表；路径A/B：留空
    "passed": CASE_PASSED,
    "duration": CASE_END_TS - CASE_START_TS,
    "steps": CASE_STEPS
})

# 重置，准备下一条用例
CASE_STEPS = []
CASE_PASSED = true
CASE_START_TS = $(date +%s)
```

**直播/进教室专用流程**（步骤含"进教室"/"开始直播"）：
```
1. 确认在课节详情页
2. AI 视觉点击进教室：
   "red oval '进教室' button on the right side of 直播核心课 row"
3. 轮询等横屏（每0.5s，最多8s）
4. 截图旋转90° → 确认进入教室（横屏视频 + 互动栏）
```

**闪学口语练习课节专用流程**（步骤含"视频进度条"/"答题"）：

> ⚠️ 进度条为 Canvas 绘制，禁止拖拽，用 2x 倍速 + +10s 代替
> ⚠️ 答题卡禁止硬编码坐标，必须 AI 视觉定位麦克风

```bash
# 获取屏幕尺寸
W=$(adb -s <UDID> shell wm size | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f1)
H=$(adb -s <UDID> shell wm size | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f2)

# 唤出控制栏 + 点倍速（连发，3秒窗口内可靠）
adb -s <UDID> shell "input tap $((W/2)) $((H*43/100)); input tap $((W*94/100)) $((H*96/100))"
```

| 控制栏按钮 | X比例 | Y比例 |
|-----------|-------|-------|
| 视频中心（唤出控制栏）| 50% | 43% |
| 倍速 | 94% | 96% |
| +10s | 73% | 96% |

重试最多3次等倍速弹窗 → xpath找到`//*[@text='2.0x']` → tap → 再+10s×10跳进度

答题循环：截图判断题型 → 朗读题用AI视觉定位麦克风 → 听音选词题xpath点A → xpath点「继续」/「完成」→ 直到`//*[@text='去分享']`出现

---

## 第八步：清理收尾

> ⚠️ **分批执行时（见 [../../common/parallel.md](../../common/parallel.md)「设备内分批」）本步骤分两档：**
> - **非最后一批**：跑完本批用例 → 执行下方「Bitable 回写（批级 upsert）」+ append 落盘 → **直接退出**，**不**退教室清理、**不** `delete_session`、**不**重启 App，返回 `CURRENT_ACCOUNT` + 本批通过/失败计数给主 agent。
> - **最后一批**（`is_last_batch=true`）：退教室 / 恢复 tab / `delete_session()` / 输出本设备**文本执行报告**。⚠️ 飞书 **Wiki 报告 & 群通知不在批级 subagent 生成**——由主 agent 在所有设备所有批完成后读 jsonl 合并、每平台一份统一生成（见 [../../common/parallel.md](../../common/parallel.md) 第5步）。
>
> 单设备不分批（用例数 ≤ BATCH_SIZE）且非并行独立执行时，等同「只有最后一批」，可在此直接走完整收尾含 Wiki 报告。

### 退出教室（若在教室内）
```
1. 截图旋转90° 确认是否横屏
2. 若横屏 → AI 视觉点击退出按钮 → 确认弹窗点"确定"
   Android降级：xpath //*[@text='确定']
   iOS降级：xpath //*[@name='确定']
3. 等 2s → 截图确认退出
```

### 恢复上课 tab & 关闭 Session
```bash
# 导航回上课 tab（参考第六步）
delete_session()
```

### 输出执行报告

```
=== 高途用例执行报告 ===
平台：<Android/iOS> | 设备：<UDID> | 账号：<phone>
执行日期：YYYYMMDD  执行时间：HH:MM:SS  总耗时：Ts（setup: Xs + 执行: Ys）

用例：<标题/来源>  ⏱ 用例耗时：Ys
执行步骤：N步 | ✓ 通过：X步 | ✗ 失败：Y步

失败步骤详情：
  步骤K [ACTION/ASSERT]: <文字>
    原因：<失败原因>
    截图：$SHOT_DIR/step_K_fail.png

ASSERT 验证截图：
  步骤J [ASSERT]: <验证点> → ✓/✗
    截图：$SHOT_DIR/step_J_assert.png
```

执行计划见 [../../common/prescan.md](../../common/prescan.md) — 在报告末尾追加"执行计划（预扫描）"区块。

### Bitable 回写（仅路径 C）

**固定常量：**

| 用途 | app_token | table_id |
|------|-----------|----------|
| 来源用例表（更新最新执行时间） | `C6X8wCdSLiAd9IkXtNFc6yO2nXg` | `tblvXqsSu7xShRJH` |
| 执行结果表 - iOS | `C6X8wCdSLiAd9IkXtNFc6yO2nXg` | `tblryYA67UjkVGwx` |
| 执行结果表 - Android | `C6X8wCdSLiAd9IkXtNFc6yO2nXg` | `tblUEp8pt5W9Cic5` |

**步骤一：上传截图**

```bash
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)"
RESULT_APP_TOKEN="C6X8wCdSLiAd9IkXtNFc6yO2nXg"
source "$SCRIPTS_DIR/upload_screenshots.sh" "$SHOT_DIR" "$RESULT_APP_TOKEN"
```

**步骤二：清空目标表 —— 仅 run 开头一次，由主 agent 执行（批级 subagent 跳过本步）**

> 分批执行时（见 [../../common/parallel.md](../../common/parallel.md)），整表清空**只在整个 run 开始、并行派发之前做一次**（Android 表 + iOS 表各一次）。批级 subagent **不执行**本步——否则后一批会把前一批清掉。批级去重改用步骤三的 upsert。
> 单设备不分批时，此清空即在唯一那批之前执行，等价于原逻辑。

清空逻辑（分页拉取 record_id → batch_delete，每批最多 500 条）：

```python
# 伪代码示意
page_token = ""
while True:
    url = f"/bitable/v1/apps/{RESULT_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records?page_size=500"
    if page_token:
        url += f"&page_token={page_token}"
    resp = GET(url)
    ids = [r["record_id"] for r in resp["data"]["items"]]
    if ids:
        POST(f"/bitable/v1/apps/{RESULT_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records/batch_delete",
             {"records": ids})
    if not resp["data"]["has_more"]:
        break
    page_token = resp["data"]["page_token"]
```

**步骤三：批级 upsert 写入执行结果（本批）**

> 分批模型下 `CASES_JSON` **只含本批用例**（≤ BATCH_SIZE 条；批与批之间已 append 落盘到 `/tmp/result_<udid>.jsonl`），不是全设备全部用例。

按平台选对应 table_id，为支持某批崩溃重跑不产生重复，**先删后建**（upsert）：先按本批 `用例ID` 删除结果表中同 ID 的旧记录，再 batch_create 本批。

```python
# ① 先删本批同 用例ID 的旧记录（upsert 的 delete 半程）
batch_ids = [c["case_id"] for c in CASES_JSON if c.get("case_id")]
if batch_ids:
    # search 结果表中 用例ID ∈ batch_ids 的记录 → batch_delete 其 record_id
    old_rids = search_result_records_by_case_ids(RESULT_TABLE_ID, batch_ids)
    if old_rids:
        POST(f"/bitable/v1/apps/{RESULT_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records/batch_delete",
             {"records": old_rids})
```

② 再 batch_create 本批。回写字段（已确认正确名称）：
- `用例ID`（Number，原表 ID 自增编号，唯一标识）
- `用例名称`（Text）
- `模块`（SingleSelect）
- `执行设备`（Text，写当前执行平台的 UDID，**不写另一平台的设备字段**）
- `执行结果`（SingleSelect：`通过` / `失败`）
- `执行详情`（Text）
- `截图`（Attachment，file_token 数组）

```python
# 伪代码示意
records = []
for case in CASES_JSON:
    records.append({
        "fields": {
            "用例ID": case["case_id"],
            "用例名称": case["name"],
            "模块": case["module"],
            "执行设备": case["device"],
            "执行结果": "通过" if case["passed"] else "失败",
            "执行详情": "\n".join(
                f"{'✓' if s['pass'] else '✗'} [{s['type']}] {s['text']}"
                + (f"\n  → {s['note']}" if s.get('note') else "")
                for s in case["steps"]
            ),
            "截图": [{"file_token": t} for t in case.get("screenshot_tokens", [])]
        }
    })
# POST /bitable/v1/apps/{RESULT_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records/batch_create
# body: {"records": records}
```

**步骤四：更新来源表"case最新执行时间"（仅执行通过的用例）**

```python
SOURCE_APP_TOKEN = "C6X8wCdSLiAd9IkXtNFc6yO2nXg"
SOURCE_TABLE_ID  = "tblvXqsSu7xShRJH"

import time
now_ms = int(time.time() * 1000)   # 飞书 DateTime 字段接受毫秒级 Unix 时间戳

passed_updates = [
    {
        "record_id": case["source_record_id"],
        "fields": {"case最新执行时间": now_ms}
    }
    for case in CASES_JSON
    if case.get("passed") and case.get("source_record_id")
]

if passed_updates:
    # 每批最多 500 条
    for i in range(0, len(passed_updates), 500):
        batch = passed_updates[i:i+500]
        # PUT /bitable/v1/apps/{SOURCE_APP_TOKEN}/tables/{SOURCE_TABLE_ID}/records/batch_update
        # body: {"records": batch}
```

### 飞书 Wiki 报告 & 群通知

```bash
# 获取 App 版本（Android）
APP_VERSION=$(adb -s <UDID> shell dumpsys package com.gaotu100.superclass \
  | grep versionName | head -1 | sed 's/.*versionName=//;s/ .*//' | tr -d '[:space:]')

# 计算耗时
GAOTU_CASE_END=$(date +%s)
EXEC_DURATION=$((GAOTU_CASE_END - GAOTU_CASE_START))
SETUP_DURATION=$((GAOTU_CASE_START - GAOTU_START))
TOTAL_DURATION="$((GAOTU_CASE_END - GAOTU_START))s（setup: ${SETUP_DURATION}s + 执行: ${EXEC_DURATION}s）"

# 统计通过/失败数（从 CASES_JSON 计算）
TOTAL=$(echo "$CASES_JSON" | python3 -c "import sys,json; c=json.load(sys.stdin); print(len(c))")
PASSED=$(echo "$CASES_JSON" | python3 -c "import sys,json; c=json.load(sys.stdin); print(sum(1 for x in c if x.get('passed')))")
FAILED=$((TOTAL - PASSED))
PASS_RATE=$((PASSED * 100 / TOTAL))

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)"
python3 "$SCRIPTS_DIR/wiki_report.py" \
  --app     "gaotu" \
  --version "$APP_VERSION" \
  --platform "$PLATFORM" \
  --device  "$DEVICE_UDID" \
  --account "$PHONE" \
  --time    "$EXEC_START_TIME" \
  --duration "$TOTAL_DURATION" \
  --total "$TOTAL" --passed "$PASSED" --failed "$FAILED" --rate "$PASS_RATE" \
  --cases "$CASES_JSON"
```

**`$CASES_JSON` 格式**（执行循环中逐条构建）：
```json
[
  {
    "name": "AI搜索-快问模式",
    "module": "闪学",
    "seq": 2,
    "passed": true,
    "duration": 120,
    "steps": [
      {"text": "进入 app 首页",       "type": "PRECOND", "pass": true},
      {"text": "点击顶部搜索框",       "type": "ACTION",  "pass": true},
      {"text": "返回结果包含 1+1=2",   "type": "ASSERT",  "pass": true,
       "note": "AI响应内容：在常规十进制中，1+1=2"}
    ]
  }
]
```

**module 取值规则：**

| 来源 | 取值方式 |
|------|---------|
| 路径 C（Bitable） | 直接读取 `模块` 字段值 |
| 路径 A（搬山） | 按 TARGET_PAGE 推断（见下表） |
| 路径 B（自然语言） | 按 TARGET_PAGE 推断（见下表） |

| TARGET_PAGE | module 值 |
|-------------|----------|
| 上课 tab / 课程详情 / 课节详情 / 直播教室 | `上课` |
| AI闪学 tab | `闪学` |
| 首页 tab | `首页` |
| 我的页 / 设置页 | `我的` |
| 消息 tab | `消息` |
| 登录页 | `启动登录` |
| 其他 / 无法推断 | `未分类` |

Wiki 输出：按模块分组，每组 H2 标题 + 各用例 H3 标题 + 步骤表格 + ASSERT 验证说明 + 末尾汇总表（含模块小计行）。

> Wiki 空间、群 chat_id 等常量已内置于 [../../scripts/wiki_report.py](../../scripts/wiki_report.py)

---

## 注意事项

- **等待策略**：禁止无条件固定 sleep，改用轮询；唯一例外：录音等待（2s）、发送确认（1s）
- **Android 登录页**：验证码登录页截图黑屏为页面跳转过渡帧（时序问题），等待 1s 重试；不是 FLAG_SECURE
- **iOS**：无 FLAG_SECURE，全程截图优先；降级用 accessibility id
- 整个前置流程目标耗时 **60 秒以内**
- 定位失败按三级降级策略（见 [elements.md](elements.md)），不要直接报错中断
- **截图必须加 `maxWidth: 800`**：Android/iOS 高分辨率设备截图超 2000px 会触发 Claude 多图限制报错，所有 `appium_screenshot` 调用均须传入 `maxWidth: 800`
- **单次对话截图不超过 10 张**：超出后新开对话，将 UDID、包名、当前执行步骤带入继续
- **上下文控制**：单条用例工具调用累计超过 50 次时，优先切换到 xpath/id 定位（见 elements.md），减少 AI 视觉重试；**单设备用例数多时按 `BATCH_SIZE=20` 分批，每批一个独立 subagent**（见 [../../common/parallel.md](../../common/parallel.md)「设备内分批」+ [../../common/prescan.md](../../common/prescan.md)「切批」）——批末回写结果表 + append 落盘后退出释放上下文，下一批带 `CURRENT_ACCOUNT` 新起、复用常驻 session 不重登
