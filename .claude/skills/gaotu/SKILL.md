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
| phone | `12100000000` | 同左 |
| password | `Gaotu@1234` | 同左 |

> 元素定位规范见 [elements.md](elements.md)

---

# 执行全流程

## 第零步：收集用例信息 & 解析步骤

**在做任何设备操作之前**，先确认以下信息：

```
1. 用例来源？A. 搬山 caseId  B. 自然语言  C. 飞书 Bitable 链接
2. 目标平台？Android / iOS
3. 使用哪台设备？（默认见上表）
4. 登录账号？（默认见上表）
```

> 用户消息已包含上述信息则跳过询问，直接进入解析。

按用例来源选择对应解析路径，完整规则见 [../../common/parsing.md](../../common/parsing.md)：

- **路径 A（搬山 caseId）**：`testCaseDetail(caseId)` → 解析节点树，含"预期结果"的节点为 ASSERT，其余为 ACTION
- **路径 B（自然语言）**：按换行/序号切分，以"预期："/"验证："开头的行为 ASSERT
- **路径 C（飞书 Bitable）**：从 URL 提取 `app_token + table_id`，读取记录，解析 测试步骤/验证点/预期结果/预置条件，提取 `DEVICE_CANDIDATES`；记录 `BITABLE_APP_TOKEN / TABLE_ID / RECORD_ID` 供第八步回写

解析完成后根据步骤关键词分析 `TARGET_PAGE`（规则见下表），展示步骤列表等用户确认。

### 目标起始页分析（TARGET_PAGE）

| 步骤关键词（任意命中） | 目标起始页 | 导航路径 |
|----------------------|-----------|---------|
| 直播、进教室、课节、开始上课 | 课节详情页 | 上课 tab → 我的课程 → [课程] → [课节] |
| 课程详情、课程介绍、课程服务 | 课程详情页 | 上课 tab → 我的课程 → [课程] |
| 搜索、查找课程 | 搜索页 | 上课 tab → 搜索入口 |
| 我的、设置、账号、个人信息 | 我的页 | 底部导航 → 我的 |
| 退出登录、注销 | 我的页-设置 | 底部导航 → 我的 → 设置 |
| AI闪学、闪学课、地图、课程地图 | AI闪学 tab | 底部导航 → AI闪学 tab |
| 首页、发现、订阅、圈子 | 首页 tab | 底部导航 → 首页 |
| （默认/其他）| 上课 tab | 已就绪 |

收集到：**平台类型、设备 UDID、账号、步骤列表、TARGET_PAGE**，记录在上下文。

---

## 设备就绪检查

> 见 [../../common/device.md](../../common/device.md)

---

## 第一步：系统权限预授权

> 见 [../../common/permission.md](../../common/permission.md)，`packageName = com.gaotu100.superclass`

---

## 第二步：创建 Appium Session

> capabilities 模板见 [../../common/device.md](../../common/device.md)，填入高途专用参数

---

## 第三步：重启高途 App

**Android：**
```bash
adb -s <device> shell am force-stop com.gaotu100.superclass
adb -s <device> shell am start -n com.gaotu100.superclass/.ui.activity.SplashActivity
```
轮询等待（最多 10s）：`xpath=//*[@text='手机号登录']` 或底部 tab 出现

**iOS：**
```
appium_app_lifecycle action=terminate id=<bundleId>
appium_app_lifecycle action=activate  id=<bundleId>
```
轮询等待（最多 10s）：`xpath=//*[@name='手机号登录']`

---

## 第四步：处理登录

`appium_get_page_source` 判断状态：

- **已登录**（底部 tab 可见）→ 跳到第五步
- **需要登录** → 见 [../../common/login.md](../../common/login.md)
  > 调用参数：`app_id=gaotu`，`platform=<平台>`，`method=password`，`phone=<账号>`，`password=<密码>`

轮询底部 tab 出现（最多 8s）确认登录成功。

---

## 第五步：批量处理登录后弹窗

> 循环规则见 [../../common/screenshot.md](../../common/screenshot.md)

循环检测并关闭弹窗（最多 5 轮）：

| 弹窗/页面 | 定位方式 | 点击目标 |
|-----------|----------|----------|
| 用户协议/隐私政策 | 截图 → AI 视觉 | `'同意' button at bottom-right of dialog` |
| 青少年模式弹窗 | 截图 → AI 视觉 | `'已满18岁' button` |
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

## 第六步：导航至目标起始页

根据第零步分析出的 `TARGET_PAGE` 执行导航（详细降级策略见 [elements.md](elements.md)）：

| TARGET_PAGE | 导航路径 |
|-------------|---------|
| 上课 tab（默认）| Android `tab_title[@text='上课']`；iOS `//*[@name='上课']`；坐标兜底 `(540, 2253)` |
| 课程详情页 | 上课 tab → 我的课程 → 目标课程 |
| 课节详情页 | 课程详情页 → 目标课节 |
| 搜索页 | 上课 tab → 搜索入口 |
| 我的页 | AI 视觉点击最右侧底部 tab |
| AI闪学 tab | AI 视觉点击底部 AI闪学 tab |

导航完成后记录执行开始时间，创建截图目录：
```bash
EXEC_START_TIME=$(date +%H:%M:%S)
GAOTU_CASE_START=$(date +%s)
SHOT_DIR="$HOME/mcp_shots/gaotu/$(date +%Y%m%d_%H%M)_${CASE_ID:-manual}"
mkdir -p "$SHOT_DIR"
```

输出：`✓ setup 完成（权限/session/登录/弹窗/导航至 <TARGET_PAGE>）⏱ Xs → 开始执行…`

---

## 第七步：用例步骤执行循环

> 截图/等待规范见 [../../common/screenshot.md](../../common/screenshot.md)；元素定位见 [elements.md](elements.md)

**静默执行**：循环期间不向用户输出中间文字，结果汇入内部日志，仅在第八步报告中展示。

### 初始化（每条用例开始前）

在上下文中维护以下变量（非 shell 变量，由 Claude 在对话上下文中跟踪）：

```
CASE_STEPS = []          # 当前用例的步骤结果列表
CASE_PASSED = true       # 只要有 PRECOND/ACTION FAIL 就置 false
CASES_JSON = []          # 所有用例的汇总（跨用例累积）
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
  截图（教室内先旋转90°）→ 压缩保存
  视觉检查是否符合预期文字描述 → pass=true/false（不中断）
  note = 实际观测到的内容（简短描述，作为验证说明）
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
    "name": "<用例编号> <用例名称>",   # 如 "用例2 AI搜索-快问模式"
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

### Bitable 回写（仅路径 C）

```bash
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)"
source "$SCRIPTS_DIR/upload_screenshots.sh" "$SHOT_DIR" "$BITABLE_APP_TOKEN"
```

调用 `bitable_v1_appTableRecord_update` 回写三个字段：`执行结果`（通过/失败）、`备注/执行详情`、`截图`（file_token 数组）。

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
    "name": "用例2 AI搜索-快问模式",
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

Wiki 输出：每条用例标题 + 步骤表格（步骤|类型|结果）+ ASSERT 验证说明 + 末尾汇总表。

> Wiki 空间、群 chat_id 等常量已内置于 [../../scripts/wiki_report.py](../../scripts/wiki_report.py)

---

## 注意事项

- **等待策略**：禁止无条件固定 sleep，改用轮询；唯一例外：录音等待（2s）、发送确认（1s）
- **Android 登录页**：验证码登录页因 FLAG_SECURE 截图黑屏，只能用 page source + resource-id
- **iOS**：无 FLAG_SECURE，全程截图优先；降级用 accessibility id
- 整个前置流程目标耗时 **60 秒以内**
- 定位失败按三级降级策略（见 [elements.md](elements.md)），不要直接报错中断
- **截图必须加 `maxWidth: 800`**：Android/iOS 高分辨率设备截图超 2000px 会触发 Claude 多图限制报错，所有 `appium_screenshot` 调用均须传入 `maxWidth: 800`
- **单次对话截图不超过 10 张**：超出后新开对话，将 UDID、包名、当前执行步骤带入继续
