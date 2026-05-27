# AI Monkey 测试设计

**日期**：2026-05-27  
**状态**：待实现

---

## 背景

现有框架只支持预定义用例执行。Monkey 测试通过随机操作发现崩溃、白屏、ANR 等稳定性问题，与用例测试互补。

---

## 目标

1. 用户调用 `/gaotu`（或其他 App skill）时，菜单新增「Monkey 测试」选项
2. AI 驱动随机操作：每步获取当前页面可交互元素，随机选择并执行
3. 执行期间每 10 步做一次异常检测（截图视觉 + logcat）
4. 跑完后 AI 汇总异常，生成 Feishu Wiki 报告 + 群消息

---

## 架构

### 文件改动

| 文件 | 类型 | 说明 |
|------|------|------|
| `common/monkey.md` | 新增 | Monkey 核心执行协议，所有 App 共用 |
| `.claude/skills/gaotu/SKILL.md` | 修改 | 菜单加入 Monkey 测试选项，分支调用 common/monkey.md |
| `.claude/skills/tutu/SKILL.md` | 修改 | 同上 |
| `.claude/skills/jingpin/SKILL.md` | 修改 | 同上 |
| `.claude/skills/gongkao/SKILL.md` | 修改 | 同上 |
| `.claude/skills/xinli/SKILL.md` | 修改 | 同上 |
| `.claude/skills/ketang/SKILL.md` | 修改 | 同上 |

### 数据流

```
用户: /gaotu → 选择「Monkey 测试」→ 输入参数（可选）
  ↓
common/device.md → 设备检查 + Session 创建
common/login.md  → App 启动 + 登录
  ↓
common/monkey.md 主循环
  每步: get_page_source → 随机元素/手势 → 执行
  每10步: screenshot → AI 视觉检测 + adb logcat
  崩溃: 记录 → 重启 App → 继续循环
  ↓
anomaly_log.json（本地）
  ↓
AI 汇总分析 → cases JSON → wiki_report.py
  ↓
Feishu Wiki 报告 + 群消息
```

### 复用现有模块（不改动）

| 模块 | 复用方式 |
|------|---------|
| `common/device.md` | Session 创建 capabilities |
| `common/login.md` | 登录预置流程 |
| `common/screenshot.md` | 截图保存路径规范 |
| `scripts/wiki_report.py` | Wiki 报告生成 + 飞书群通知 |

---

## 执行参数

用户可在触发时指定，均有默认值：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_ops` | 500 | 最大操作步数 |
| `max_minutes` | 30 | 最大运行时长（分钟） |
| `anomaly_interval` | 10 | 异常检查间隔步数 |

终止条件：`ops_count >= max_ops` **或** `elapsed >= max_minutes`，先到先停。

---

## 主循环协议（common/monkey.md）

### 初始化

```bash
MONKEY_DIR="$HOME/mcp_shots/${APP_ID}/monkey_$(date +%Y%m%d_%H%M)"
mkdir -p "$MONKEY_DIR"
START_TS=$(date +%s)
ops_count=0
anomaly_log="$MONKEY_DIR/anomaly_log.json"
echo "[]" > "$anomaly_log"
```

### 每步操作

```
1. appium_get_page_source
   → 提取所有 clickable=true 或 enabled=true 的元素列表

2. 元素列表为空时的恢复策略：
   → appium_back（最多 3 次）
   → 仍空 → 点击底部导航第一个 Tab 回到首页

3. 随机决策（加权）：
   - 80%：随机选一个元素 → appium_tap（element bounds 中心坐标）
   - 15%：随机方向 swipe（上/下/左/右）
   -  5%：appium_back

4. 追加操作记录：
   {step, action, element_desc, timestamp}

5. ops_count++
```

### 每 anomaly_interval 步的异常检测

**视觉检测（Claude 判断）：**

调用 `appium_screenshot`，Claude 判断以下四类异常：

| 类型 | 判断依据 |
|------|---------|
| `blank_screen` | 屏幕全白或全黑，无可识别 UI |
| `crash` | "已停止运行"、"应用无响应"等系统崩溃弹窗 |
| `unexpected_dialog` | 非业务逻辑触发的系统权限弹窗或未知弹窗 |
| `error_content` | 页面出现明显错误文案、Toast 或异常空状态 |

**日志检测（Android 专属）：**

```bash
adb -s <udid> logcat -d -t 200 | grep -E "FATAL EXCEPTION|ANR in|NullPointerException|java.lang.RuntimeException"
```

### 崩溃恢复（非阻塞）

```
检测到 crash / ANR →
  1. 追加到 anomaly_log.json（含截图路径、logcat 片段）
  2. adb shell am force-stop <packageName>  （Android）
     或 appium_terminate_app              （iOS）
  3. appium_launch_app → 等待启动完成
  4. 执行登录流程（common/login.md）
  5. 继续主循环，ops_count 不重置
```

---

## 异常记录格式

`anomaly_log.json` 为 JSON 数组，每条记录：

```json
{
  "step": 42,
  "type": "crash",
  "description": "检测到 FATAL EXCEPTION，App 进程退出",
  "screenshot": "/Users/.../monkey_20260527_1430/step_042.png",
  "logcat": "E AndroidRuntime: FATAL EXCEPTION: main\n...",
  "timestamp": "14:32:11"
}
```

`type` 枚举：`crash` | `anr` | `blank_screen` | `error_content` | `unexpected_dialog`

---

## 跑完后 AI 汇总分析

1. 读取 `anomaly_log.json`
2. 按 `type` 聚合统计
3. 对每条异常，提取前 3 步操作记录作为「触发路径」
4. 构建 cases JSON（每条异常 = 一个失败用例，零异常 = 一个通过用例）

**cases JSON 结构（对接 wiki_report.py）：**

每条异常 = 一个 case（对应 Wiki 表格一行）；零异常时生成一条 passed case。

```json
[
  {
    "name": "[step 42] 崩溃 — FATAL EXCEPTION",
    "module": "Monkey",
    "platform": "Android",
    "device": "<udid>",
    "seq": 1,
    "passed": false,
    "duration": 0,
    "steps": [
      {
        "type": "ANOMALY",
        "text": "检测到 FATAL EXCEPTION，App 进程退出",
        "pass": false,
        "note": "触发路径: tap 课程列表 → swipe down → tap 播放按钮"
      }
    ]
  },
  {
    "name": "[step 187] 白屏 — 页面全白无 UI",
    "module": "Monkey",
    "platform": "Android",
    "device": "<udid>",
    "seq": 2,
    "passed": false,
    "duration": 0,
    "steps": [
      {
        "type": "ANOMALY",
        "text": "截图显示页面全白，无可识别 UI 元素",
        "pass": false,
        "note": "触发路径: tap 消息Tab → tap 通知项 → tap 返回"
      }
    ]
  }
]
```

零异常时：
```json
[{"name": "Monkey Run — 无异常", "module": "Monkey", "seq": 1, "passed": true, "duration": 1680, "steps": []}]
```

---

## 报告生成

`--account` 从 app skill 的登录配置（与日常用例执行相同的测试账号）读取，无需用户额外输入。

```bash
python3 scripts/wiki_report.py \
  --app <app_id> \
  --version <version> \
  --platform <Android|iOS> \
  --account <登录账号，来自 skill 配置> \
  --time <HH:MM:SS> \
  --duration "<N>s" \
  --total 1 \
  --passed <0或1> \
  --failed <0或1> \
  --rate <0或100> \
  --cases "$(cat /tmp/monkey_cases.json)"
```

Wiki 报告结构示例：

```
Monkey 测试报告 — 高途 5.91.x — Android
执行时间: 2026-05-27 14:30  |  总耗时: 28分钟  |  总步数: 500

[ 序号 | 异常类型 | 触发步骤  | 描述              | 截图 | 发生时间 ]
  1   | 崩溃     | step 42  | FATAL EXCEPTION  | 📷  | 14:32
  2   | 白屏     | step 187 | 页面全白无 UI      | 📷  | 15:01
  3   | 崩溃     | step 331 | ANR 无响应        | 📷  | 15:22
```

---

## 多设备并行

复用 `common/parallel.md` 的 subagent 模式：每台设备启动一个 subagent 独立跑 Monkey，完成后主 agent 合并 `anomaly_log.json`，去重后统一生成报告。

**分工：**

| 角色 | 职责 |
|------|------|
| 主 agent | 解析设备列表 → 并行派发 subagent → 等待结果文件 → 合并去重 → 生成报告 |
| 子 agent | 独立跑 Monkey 循环 → 写 `/tmp/monkey_result_<udid>.json` |

**结果文件格式**（与 `parallel.md` 一致）：

```json
[
  { "device": "<udid>", "platform": "Android", "anomalies": [...], "ops_count": 500, "duration": 1680 }
]
```

合并后，相同类型 + 相同触发路径的异常跨设备去重（见下节）。

---

## 崩溃堆栈去重

目的：多台设备或多次触发同一崩溃只记录一条，避免报告冗余。

**去重 key**：`type + logcat 前 3 行`（Android）或 `type + 截图语义描述`（iOS）

**去重逻辑**（在主 agent 合并阶段执行）：

```python
seen = {}
for anomaly in all_anomalies:
    key = f"{anomaly['type']}|{anomaly['logcat'][:200] if anomaly.get('logcat') else anomaly['description'][:80]}"
    if key not in seen:
        seen[key] = anomaly
        seen[key]['occurrences'] = 1
    else:
        seen[key]['occurrences'] += 1
deduped = list(seen.values())
```

报告中标注重复次数：`[step 42] 崩溃 × 3台设备`。

---

## Monkey 用例回放

**目的**：Monkey 跑出异常后，可单独重放触发该异常的操作序列，用于问题复现与确认。

**操作序列记录**（主循环中持续写入）：

```json
// actions_log.json
[
  {"step": 40, "action": "tap", "bounds": "[100,200][300,400]", "element_desc": "课程列表第一项", "timestamp": "14:32:05"},
  {"step": 41, "action": "swipe", "direction": "down", "timestamp": "14:32:06"},
  {"step": 42, "action": "tap", "bounds": "[50,600][200,650]", "element_desc": "播放按钮", "timestamp": "14:32:07"}
]
```

**回放触发**：

用户在报告中看到异常后，可说：「回放 step 42 的崩溃」

```
common/monkey.md 回放模式：
  读取 actions_log.json 中 [step-3 .. step] 的操作序列
  → 逐步执行（tap/swipe 复原坐标）
  → 到达目标步骤后截图确认是否复现
  → 输出"已复现" / "未复现"
```

回放使用坐标直接执行（`appium_tap coordinates`），不重新做元素定位。

---

## 不在本次范围内

- iOS logcat 检测（iOS 用视觉检测兜底，无 adb logcat）
