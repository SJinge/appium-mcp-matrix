# AI Monkey 测试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 6 个 App skill（/gaotu 等）的第零步菜单新增「Monkey 测试」选项，驱动 AI 随机操作 + 实时异常检测，跑完后汇总报告写入 Feishu Wiki。

**Architecture:** `common/monkey.md` 存放所有 Monkey 逻辑（参数解析、主循环、异常检测、并行、去重、回放、报告）；6 个 App skill 各自在「第零步」菜单加一个 D 选项，填入 App 专属参数后调用 `common/monkey.md`。不改动 `wiki_report.py` 和其他 common 模块。

**Tech Stack:** Appium MCP（appium_get_page_source / appium_tap / appium_screenshot / appium_back / appium_launch_app）、adb shell、Python 3（anomaly 合并去重脚本）、`scripts/wiki_report.py`

---

## 文件一览

| 文件 | 操作 | 职责 |
|------|------|------|
| `common/monkey.md` | 新增 | Monkey 全协议：参数、主循环、异常检测、崩溃恢复、并行、去重、回放、报告 |
| `.claude/skills/gaotu/SKILL.md` | 修改 | 第零步菜单加 D 选项，分支跳转 monkey.md |
| `.claude/skills/tutu/SKILL.md` | 修改 | 同上（tutu 参数） |
| `.claude/skills/jingpin/SKILL.md` | 修改 | 同上（jingpin 参数） |
| `.claude/skills/gongkao/SKILL.md` | 修改 | 同上（gongkao 参数） |
| `.claude/skills/xinli/SKILL.md` | 修改 | 同上（xinli 参数） |
| `.claude/skills/ketang/SKILL.md` | 修改 | 同上（ketang 参数） |

---

## Task 1：创建 `common/monkey.md` — 参数 + 初始化 + 主循环

**Files:**
- Create: `common/monkey.md`

- [ ] **Step 1: 创建文件，写入参数声明和初始化块**

```markdown
# Monkey 测试协议

> 由各 App skill 在选择「Monkey 测试」后调用。调用方须先完成 common/device.md Session 创建和 common/login.md 登录。

---

## 输入参数

调用方传入以下变量（均有默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_ID` | — | 必填，如 `gaotu` |
| `PKG` | — | 必填，Android packageName 或 iOS bundleId |
| `PLATFORM` | Android | `Android` 或 `iOS` |
| `UDID` | — | 设备 UDID |
| `ACCOUNT` | — | 登录账号（用于报告） |
| `VERSION` | — | App 版本号（用于报告） |
| `max_ops` | 500 | 最大操作步数 |
| `max_minutes` | 30 | 最大运行时长（分钟） |
| `anomaly_interval` | 10 | 异常检查间隔步数 |

---

## 初始化

```bash
MONKEY_DIR="$HOME/mcp_shots/${APP_ID}/monkey_$(date +%Y%m%d_%H%M)"
mkdir -p "$MONKEY_DIR"
START_TS=$(date +%s)
ops_count=0
anomaly_log="$MONKEY_DIR/anomaly_log.json"
actions_log="$MONKEY_DIR/actions_log.json"
echo "[]" > "$anomaly_log"
echo "[]" > "$actions_log"
echo "[Monkey] 初始化完成 → $MONKEY_DIR"
echo "[Monkey] 目标: max_ops=$max_ops, max_minutes=$max_minutes"
```

---

## 主循环

终止条件（先到先停）：`ops_count >= max_ops` 或 `(now - START_TS)/60 >= max_minutes`

### 每步操作流程

**Step A — 获取可交互元素**

调用 `appium_get_page_source`，从返回的 XML/JSON 中提取满足以下条件的元素：
- Android：`clickable="true"` 或 `enabled="true"` 且 `bounds` 不为空
- iOS：`enabled="true"` 且有 `name` 或 `label`

**Step B — 元素为空时的恢复策略**

```
if 元素列表为空:
  重试 appium_back，最多 3 次
  if 仍为空:
    appium_tap 底部导航栏第一个 Tab（坐标：屏幕宽/5, 屏幕高*0.95）
```

**Step C — 加权随机决策**

```
random_value = random(0, 100)
if random_value < 80:
    随机选一个元素，取 bounds 中心坐标 → appium_tap x y
elif random_value < 95:
    随机选方向（up/down/left/right）→ appium_swipe
else:
    appium_back
```

**Step D — 记录操作到 actions_log**

```bash
# 追加一条记录（Python 单行）
python3 -c "
import json, sys
log = json.load(open('$actions_log'))
log.append({'step': $ops_count, 'action': '$action', 'bounds': '$bounds', 'element_desc': '$element_desc', 'timestamp': '$(date +%H:%M:%S)'})
json.dump(log, open('$actions_log','w'), ensure_ascii=False)
"
```

**Step E — 递增计数**

```bash
ops_count=$((ops_count + 1))
```
```

- [ ] **Step 2: 自检文件内容**

读取 `common/monkey.md`，确认：
- 参数表完整（APP_ID / PKG / PLATFORM / UDID / ACCOUNT / VERSION / max_ops / max_minutes / anomaly_interval）
- 初始化 bash 块可执行
- 主循环 Step A-E 逻辑完整，无 TBD

- [ ] **Step 3: 提交**

```bash
git add common/monkey.md
git commit -m "feat: add common/monkey.md skeleton, params, init, main loop"
```

---

## Task 2：`common/monkey.md` — 异常检测 + 崩溃恢复

**Files:**
- Modify: `common/monkey.md`

- [ ] **Step 1: 在主循环章节末尾追加「每 N 步异常检测」子节**

在 `common/monkey.md` 的「主循环」章节末尾追加：

```markdown
### 每 anomaly_interval 步的异常检测

在 Step E 递增后，执行：

```bash
if [ $((ops_count % anomaly_interval)) -eq 0 ]; then
  echo "[Monkey] step $ops_count — 开始异常检测"
  # 视觉检测
  appium_screenshot → 保存到 $MONKEY_DIR/step_$(printf "%04d" $ops_count).png

  # Claude 判断截图中的异常（必须逐一检查以下四类）：
  # 1. blank_screen  — 屏幕全白或全黑，无可识别 UI
  # 2. crash         — "已停止运行"、"应用无响应" 等系统崩溃弹窗
  # 3. unexpected_dialog — 非业务逻辑触发的系统权限弹窗或未知弹窗
  # 4. error_content — 明显错误文案、Error Toast、异常空状态

  # Android 日志检测
  if [ "$PLATFORM" = "Android" ]; then
    adb -s $UDID logcat -d -t 200 | grep -E "FATAL EXCEPTION|ANR in|NullPointerException|java.lang.RuntimeException" > /tmp/monkey_logcat_tmp.txt
    # 若有匹配行 → 判定为 crash 或 anr
  fi
fi
```

发现异常时追加到 anomaly_log：

```bash
python3 -c "
import json
log = json.load(open('$anomaly_log'))
log.append({
    'step': $ops_count,
    'type': '$anomaly_type',          # crash|anr|blank_screen|error_content|unexpected_dialog
    'description': '$anomaly_desc',
    'screenshot': '$MONKEY_DIR/step_$(printf \"%04d\" $ops_count).png',
    'logcat': open('/tmp/monkey_logcat_tmp.txt').read()[:500] if '$PLATFORM'=='Android' else '',
    'timestamp': '$(date +%H:%M:%S)'
})
json.dump(log, open('$anomaly_log','w'), ensure_ascii=False)
"
echo "[Monkey] 已记录异常: $anomaly_type (step $ops_count)"
```

### 崩溃恢复（非阻塞）

检测到 `crash` 或 `anr` 类型时：

```bash
# 1. 异常已记录（上方已追加）
# 2. 强制停止 App
if [ "$PLATFORM" = "Android" ]; then
  adb -s $UDID shell am force-stop $PKG
else
  appium_terminate_app  # iOS
fi
# 3. 重新启动
appium_launch_app
# 等待启动完成（轮询，最多 10s）
# 4. 重新登录（参考 common/login.md 对应 App 的登录流程）
# 5. 继续主循环，ops_count 不重置
echo "[Monkey] App 已重启，继续循环（ops_count=$ops_count）"
```
```

- [ ] **Step 2: 自检**

确认：
- 四类异常类型枚举完整
- `logcat` grep 命令语法正确
- 崩溃恢复步骤明确引用了 `common/login.md`
- iOS 没有 logcat 分支（iOS 用视觉检测兜底）

- [ ] **Step 3: 提交**

```bash
git add common/monkey.md
git commit -m "feat: monkey.md — anomaly detection + crash recovery"
```

---

## Task 3：`common/monkey.md` — 汇总分析 + 报告生成

**Files:**
- Modify: `common/monkey.md`

- [ ] **Step 1: 追加「跑完后汇总」章节**

在 `common/monkey.md` 末尾追加：

```markdown
---

## 跑完后 AI 汇总分析

主循环结束后执行以下步骤：

### 1. 读取 anomaly_log

```bash
END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
anomalies=$(python3 -c "import json; print(len(json.load(open('$anomaly_log'))))")
echo "[Monkey] 完成 — ops=$ops_count, duration=${DURATION}s, anomalies=$anomalies"
```

### 2. AI 汇总每条异常

读取 `anomaly_log.json`，对每条记录：
- 从 `actions_log.json` 中取 `[step-3 .. step]` 的 3 步操作作为「触发路径」
- 格式化为：`tap 课程列表 → swipe down → tap 播放按钮`

### 3. 构建 cases JSON（单设备）

```python
# scripts/build_monkey_cases.py
import json, sys

anomaly_log_path = sys.argv[1]
actions_log_path = sys.argv[2]
device = sys.argv[3]
platform = sys.argv[4]

anomalies = json.load(open(anomaly_log_path))
actions = json.load(open(actions_log_path))

# 若无异常，生成一条通过用例
if not anomalies:
    cases = [{
        "name": f"Monkey Run — 无异常",
        "module": "Monkey",
        "platform": platform,
        "device": device,
        "seq": 1,
        "passed": True,
        "duration": 0,
        "steps": []
    }]
    print(json.dumps(cases, ensure_ascii=False))
    sys.exit(0)

cases = []
for i, a in enumerate(anomalies, 1):
    # 取触发前 3 步
    step = a["step"]
    prev_steps = [s for s in actions if s["step"] <= step][-3:]
    path = " → ".join(
        f"{s['action']} {s['element_desc']}" for s in prev_steps
    )
    cases.append({
        "name": f"[step {step}] {a['type']} — {a['description'][:40]}",
        "module": "Monkey",
        "platform": platform,
        "device": device,
        "seq": i,
        "passed": False,
        "duration": 0,
        "steps": [{
            "type": "ANOMALY",
            "text": a["description"],
            "pass": False,
            "note": f"触发路径: {path}"
        }]
    })

print(json.dumps(cases, ensure_ascii=False))
```

### 4. 生成报告

```bash
python3 scripts/build_monkey_cases.py \
  "$anomaly_log" "$actions_log" "$UDID" "$PLATFORM" \
  > /tmp/monkey_cases_${UDID}.json

# 计算通过/失败数
total=$(python3 -c "import json; c=json.load(open('/tmp/monkey_cases_${UDID}.json')); print(len(c))")
failed=$(python3 -c "import json; c=json.load(open('/tmp/monkey_cases_${UDID}.json')); print(sum(1 for x in c if not x['passed']))")
passed=$((total - failed))
rate=$(python3 -c "print(round($passed/$total*100))")

python3 scripts/wiki_report.py \
  --app "$APP_ID" \
  --version "$VERSION" \
  --platform "$PLATFORM" \
  --account "$ACCOUNT" \
  --time "$(date +%H:%M:%S)" \
  --duration "${DURATION}s" \
  --total "$total" \
  --passed "$passed" \
  --failed "$failed" \
  --rate "$rate" \
  --cases "$(cat /tmp/monkey_cases_${UDID}.json)"
```
```

- [ ] **Step 2: 创建 `scripts/build_monkey_cases.py`**

将上面「构建 cases JSON」的 Python 脚本写入 `scripts/build_monkey_cases.py`（内容即 Step 1 代码块中的 Python 部分）。

- [ ] **Step 3: 验证脚本可执行**

```bash
# 造一个最小测试输入
echo '[{"step":5,"type":"crash","description":"测试崩溃","screenshot":"/tmp/s.png","logcat":"","timestamp":"10:00:00"}]' > /tmp/test_anomaly.json
echo '[{"step":3,"action":"tap","element_desc":"首页","timestamp":"09:59:58"},{"step":4,"action":"swipe","element_desc":"","timestamp":"09:59:59"},{"step":5,"action":"tap","element_desc":"播放","timestamp":"10:00:00"}]' > /tmp/test_actions.json
python3 scripts/build_monkey_cases.py /tmp/test_anomaly.json /tmp/test_actions.json device123 Android
```

期望输出：一个合法 JSON 数组，包含 1 条 passed=false 的 case，name 含 "step 5"，note 含 "触发路径"。

- [ ] **Step 4: 提交**

```bash
git add common/monkey.md scripts/build_monkey_cases.py
git commit -m "feat: monkey.md — post-run analysis + report generation; add build_monkey_cases.py"
```

---

## Task 4：`common/monkey.md` — 多设备并行 + 崩溃去重 + 回放

**Files:**
- Modify: `common/monkey.md`

- [ ] **Step 1: 追加「多设备并行」章节**

在 `common/monkey.md` 报告生成章节后追加：

```markdown
---

## 多设备并行模式

当用户提供多台设备时，主 agent 并行派发 subagent，每台设备独立跑完整 Monkey 循环。

### 主 agent 职责

```bash
# 1. 确认设备列表 DEVICE_LIST = [udid_A, udid_B, ...]
# 2. 并行派发：每台设备一个 subagent，传入 UDID + APP_ID + PKG + PLATFORM + max_ops + max_minutes
# 3. 每个 subagent 完成后写：/tmp/monkey_result_<udid>.json
#    格式：[{"device":"<udid>","platform":"Android","anomalies":[...],"ops_count":500,"duration":1680}]
# 4. 主 agent 轮询等待所有结果文件
while true; do
  all_done=true
  for udid in "${DEVICE_LIST[@]}"; do
    [ -f "/tmp/monkey_result_${udid}.json" ] || { all_done=false; break; }
  done
  $all_done && break
  sleep 10
done
# 5. 合并所有异常 → 去重 → 生成统一报告
```

### 子 agent 职责

执行完整 Monkey 循环（本协议 主循环 + 汇总分析章节），最后写结果文件：

```bash
python3 -c "
import json
anomalies = json.load(open('$anomaly_log'))
result = [{'device': '$UDID', 'platform': '$PLATFORM', 'anomalies': anomalies, 'ops_count': $ops_count, 'duration': $DURATION}]
json.dump(result, open('/tmp/monkey_result_$UDID.json','w'), ensure_ascii=False)
"
python3 -c "import json,sys; json.load(open('/tmp/monkey_result_$UDID.json'))" && echo "[OK] 结果文件合法"
```
```

- [ ] **Step 2: 追加「崩溃堆栈去重」章节**

继续在 `common/monkey.md` 追加：

```markdown
---

## 崩溃堆栈去重

在主 agent 合并多台设备结果时，或单设备汇总时，执行去重：

```python
# 去重逻辑（嵌入 build_monkey_cases.py 的合并入口，或单独调用）
seen = {}
for anomaly in all_anomalies:
    logcat_key = anomaly.get("logcat", "")[:200]
    desc_key = anomaly.get("description", "")[:80]
    key = f"{anomaly['type']}|{logcat_key if logcat_key else desc_key}"
    if key not in seen:
        seen[key] = dict(anomaly)
        seen[key]["occurrences"] = 1
    else:
        seen[key]["occurrences"] += 1
deduped = list(seen.values())
```

报告中 case name 附加出现次数（当 occurrences > 1 时）：

```python
if anomaly.get("occurrences", 1) > 1:
    name = f"{name} ×{anomaly['occurrences']}台设备"
```
```

- [ ] **Step 3: 追加「Monkey 用例回放」章节**

继续追加：

```markdown
---

## Monkey 用例回放

用户在看到报告后可说：「回放 step 42 的崩溃」，此时进入回放模式。

### 触发条件

用户提及「回放」+ step 编号，且当前 `$MONKEY_DIR/actions_log.json` 存在。

### 回放步骤

```bash
TARGET_STEP=42   # 从用户指令解析
REPLAY_FROM=$((TARGET_STEP - 3))

# 1. 读取操作序列
python3 -c "
import json
actions = json.load(open('$actions_log'))
replay = [a for a in actions if $REPLAY_FROM <= a['step'] <= $TARGET_STEP]
print(json.dumps(replay, ensure_ascii=False))
" > /tmp/monkey_replay.json

# 2. 逐步执行（使用坐标，不重新做元素定位）
# 对每条 action：
#   tap   → appium_tap x y（从 bounds "[x1,y1][x2,y2]" 计算中心）
#   swipe → appium_swipe direction
#   back  → appium_back

# 3. 到达 TARGET_STEP 后截图
appium_screenshot → 保存 $MONKEY_DIR/replay_step_${TARGET_STEP}.png

# 4. Claude 判断是否复现（与原始异常类型一致？）
```

输出：「已复现 — 截图: $MONKEY_DIR/replay_step_${TARGET_STEP}.png」或「未复现」。
```

- [ ] **Step 4: 自检 monkey.md 完整性**

读取 `common/monkey.md`，确认包含以下所有章节标题：
- `## 输入参数`
- `## 初始化`
- `## 主循环`
- `### 每 anomaly_interval 步的异常检测`
- `### 崩溃恢复（非阻塞）`
- `## 跑完后 AI 汇总分析`
- `## 多设备并行模式`
- `## 崩溃堆栈去重`
- `## Monkey 用例回放`

- [ ] **Step 5: 提交**

```bash
git add common/monkey.md
git commit -m "feat: monkey.md — parallel, dedup, replay"
```

---

## Task 5：更新 `scripts/build_monkey_cases.py` — 集成去重逻辑

**Files:**
- Modify: `scripts/build_monkey_cases.py`

- [ ] **Step 1: 在脚本中加入去重逻辑**

在 `scripts/build_monkey_cases.py` 的 anomalies 读取之后、构建 cases 之前，插入去重：

```python
# 去重（同 type + logcat/description 前缀视为同一问题）
seen = {}
for anomaly in anomalies:
    logcat_key = anomaly.get("logcat", "")[:200]
    desc_key = anomaly.get("description", "")[:80]
    key = f"{anomaly['type']}|{logcat_key if logcat_key else desc_key}"
    if key not in seen:
        seen[key] = dict(anomaly)
        seen[key]["occurrences"] = 1
    else:
        seen[key]["occurrences"] += 1
anomalies = list(seen.values())
```

在生成 case name 时：

```python
occ = a.get("occurrences", 1)
occ_suffix = f" ×{occ}台设备" if occ > 1 else ""
name = f"[step {step}] {a['type']} — {a['description'][:40]}{occ_suffix}"
```

- [ ] **Step 2: 验证去重生效**

```bash
# 造两条相同崩溃的输入
echo '[
  {"step":5,"type":"crash","description":"FATAL EXCEPTION main","screenshot":"/tmp/s.png","logcat":"E AndroidRuntime: FATAL EXCEPTION: main","timestamp":"10:00:00"},
  {"step":15,"type":"crash","description":"FATAL EXCEPTION main","screenshot":"/tmp/s2.png","logcat":"E AndroidRuntime: FATAL EXCEPTION: main","timestamp":"10:01:00"}
]' > /tmp/test_anomaly_dup.json
echo '[]' > /tmp/test_actions_empty.json
python3 scripts/build_monkey_cases.py /tmp/test_anomaly_dup.json /tmp/test_actions_empty.json dev1 Android
```

期望：输出 1 条 case（去重后），name 含 `×2台设备`。

- [ ] **Step 3: 提交**

```bash
git add scripts/build_monkey_cases.py
git commit -m "feat: build_monkey_cases.py — integrate dedup logic"
```

---

## Task 6：更新 `gaotu` SKILL.md — 第零步加 Monkey 选项

**Files:**
- Modify: `.claude/skills/gaotu/SKILL.md`

- [ ] **Step 1: 在「第零步」的「收集用例信息」确认列表中加入 D 选项**

找到以下原有内容：

```
1. 用例来源？A. 搬山 caseId  B. 自然语言  C. 飞书 Bitable 链接
```

替换为：

```
1. 用例来源？A. 搬山 caseId  B. 自然语言  C. 飞书 Bitable 链接  D. Monkey 测试
```

- [ ] **Step 2: 在路径 A/B/C 解析说明之后，追加路径 D 的分支**

在「按用例来源选择对应解析路径」段落末尾追加：

```markdown
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
  - `PKG=com.gaotu100.superclass`（Android）或 `PKG=<bundleId>`（iOS）
  - `ACCOUNT=12100000000`
  - `VERSION`：从 `adb shell dumpsys package com.gaotu100.superclass | grep versionName` 提取
  - 其余参数按用户输入或默认值

  路径 D 不进行 TARGET_PAGE 分析，直接进入 `common/monkey.md` 初始化章节。
```

- [ ] **Step 3: 自检 gaotu SKILL.md**

读取文件，确认：
- 第零步问题 1 含 `D. Monkey 测试`
- 路径 D 分支包含 `APP_ID=gaotu`、`PKG=com.gaotu100.superclass`、`ACCOUNT=12100000000`
- 有 VERSION 提取命令
- 结尾明确跳转到 `common/monkey.md`

- [ ] **Step 4: 提交**

```bash
git add .claude/skills/gaotu/SKILL.md
git commit -m "feat: gaotu skill — add Monkey test option D"
```

---

## Task 7：更新其余 5 个 App skill — 加 Monkey 选项

**Files:**
- Modify: `.claude/skills/tutu/SKILL.md`
- Modify: `.claude/skills/jingpin/SKILL.md`
- Modify: `.claude/skills/gongkao/SKILL.md`
- Modify: `.claude/skills/xinli/SKILL.md`
- Modify: `.claude/skills/ketang/SKILL.md`

> 每个 skill 的修改模式与 Task 6 完全相同，只有 `APP_ID`、`PKG`、`ACCOUNT`、VERSION 提取命令的包名不同。

**各 App 专属参数表：**

| skill | APP_ID | Android PKG | VERSION 提取命令 |
|-------|--------|-------------|-----------------|
| tutu | `tutu` | `com.gaotu100.tutu` | `adb shell dumpsys package com.gaotu100.tutu \| grep versionName` |
| jingpin | `jingpin` | `com.gaotu100.jingpin` | `adb shell dumpsys package com.gaotu100.jingpin \| grep versionName` |
| gongkao | `gongkao` | `com.gaotu100.gongkao` | `adb shell dumpsys package com.gaotu100.gongkao \| grep versionName` |
| xinli | `xinli` | `com.gaotu100.xinli` | `adb shell dumpsys package com.gaotu100.xinli \| grep versionName` |
| ketang | `ketang` | `com.gaotu100.ketang` | `adb shell dumpsys package com.gaotu100.ketang \| grep versionName` |

所有 skill 的 `ACCOUNT` 默认值均为 `12100000000`（与 gaotu 相同）。

- [ ] **Step 1: 更新 tutu SKILL.md**

找到「用例来源？A. 搬山 caseId  B. 自然语言  C. 飞书 Bitable 链接」，替换为含 D 的版本。在路径说明末尾追加路径 D 分支（参考 Task 6 Step 2，替换 APP_ID=tutu、PKG=com.gaotu100.tutu）。

- [ ] **Step 2: 更新 jingpin SKILL.md**

同上，APP_ID=jingpin，PKG=com.gaotu100.jingpin。

- [ ] **Step 3: 更新 gongkao SKILL.md**

同上，APP_ID=gongkao，PKG=com.gaotu100.gongkao。

- [ ] **Step 4: 更新 xinli SKILL.md**

同上，APP_ID=xinli，PKG=com.gaotu100.xinli。

- [ ] **Step 5: 更新 ketang SKILL.md**

同上，APP_ID=ketang，PKG=com.gaotu100.ketang。

- [ ] **Step 6: 自检所有 5 个 skill**

```bash
grep -l "Monkey 测试" \
  .claude/skills/tutu/SKILL.md \
  .claude/skills/jingpin/SKILL.md \
  .claude/skills/gongkao/SKILL.md \
  .claude/skills/xinli/SKILL.md \
  .claude/skills/ketang/SKILL.md
```

期望：输出 5 个文件名（全部命中）。

- [ ] **Step 7: 提交**

```bash
git add \
  .claude/skills/tutu/SKILL.md \
  .claude/skills/jingpin/SKILL.md \
  .claude/skills/gongkao/SKILL.md \
  .claude/skills/xinli/SKILL.md \
  .claude/skills/ketang/SKILL.md
git commit -m "feat: remaining 5 app skills — add Monkey test option D"
```

---

## Task 8：端到端验证 + 收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-05-27-monkey-test-design.md`（更新状态）

- [ ] **Step 1: 验证文件齐全**

```bash
ls -la common/monkey.md scripts/build_monkey_cases.py
grep -c "Monkey 测试" \
  .claude/skills/gaotu/SKILL.md \
  .claude/skills/tutu/SKILL.md \
  .claude/skills/jingpin/SKILL.md \
  .claude/skills/gongkao/SKILL.md \
  .claude/skills/xinli/SKILL.md \
  .claude/skills/ketang/SKILL.md
```

期望：`monkey.md` 和 `build_monkey_cases.py` 存在；6 个 skill 各有 ≥1 次 `Monkey 测试` 命中。

- [ ] **Step 2: 验证 build_monkey_cases.py 零异常路径**

```bash
echo '[]' > /tmp/test_no_anomaly.json
echo '[]' > /tmp/test_no_actions.json
python3 scripts/build_monkey_cases.py /tmp/test_no_anomaly.json /tmp/test_no_actions.json dev1 iOS
```

期望：输出含 `"passed": true`、`"name": "Monkey Run — 无异常"` 的 JSON 数组。

- [ ] **Step 3: 更新 spec 状态**

将 `docs/superpowers/specs/2026-05-27-monkey-test-design.md` 第 3 行：

```
**状态**：待实现
```

改为：

```
**状态**：已实现
```

- [ ] **Step 4: 最终提交**

```bash
git add docs/superpowers/specs/2026-05-27-monkey-test-design.md
git commit -m "docs: mark monkey test spec as implemented"
```
