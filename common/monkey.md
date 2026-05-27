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

每步开始时记录当前时间戳（用于终止条件判断）：
```bash
now=$(date +%s)
```
若 `$((now - START_TS))` 超过 `$((max_minutes * 60))` 秒，退出循环。

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

执行完成后设置变量，供 Step D 记录：
- tap 操作：action="tap"，bounds 取元素的 bounds 值，element_desc 取元素的 content-desc 或 text 属性（若为空则用 resource-id）
- swipe 操作：action="swipe"，bounds=""，element_desc="swipe_${direction}"
- back 操作：action="back"，bounds=""，element_desc=""

**Step D — 记录操作到 actions_log**

```bash
ACTION="$action" BOUNDS="$bounds" ELEM="$element_desc" STEP="$ops_count" \
python3 -c "
import json, os
log = json.load(open('$actions_log'))
log.append({
    'step': int(os.environ['STEP']),
    'action': os.environ['ACTION'],
    'bounds': os.environ['BOUNDS'],
    'element_desc': os.environ['ELEM'],
    'timestamp': '$(date +%H:%M:%S)'
})
json.dump(log, open('$actions_log', 'w'), ensure_ascii=False)
"
```

**Step E — 递增计数**

```bash
ops_count=$((ops_count + 1))
```

---

## 每 anomaly_interval 步的异常检测

在每步 Step E 递增后执行：

```bash
if [ $((ops_count % anomaly_interval)) -eq 0 ]; then
  echo "[Monkey] step $ops_count — 开始异常检测"
  SHOT_PATH="$MONKEY_DIR/step_$(printf '%04d' $ops_count).png"
fi
```

当 `ops_count % anomaly_interval == 0` 时，调用 `appium_screenshot`，将截图保存到 `$SHOT_PATH`。

### 视觉检测（Claude 判断）

逐一检查以下四类异常：

| 类型 | 判断依据 |
|------|---------|
| `blank_screen` | 屏幕全白或全黑，无可识别 UI |
| `crash` | "已停止运行"、"应用无响应" 等系统崩溃弹窗 |
| `unexpected_dialog` | 非业务逻辑触发的系统权限弹窗或未知弹窗 |
| `error_content` | 明显错误文案、Error Toast、异常空状态 |

### 日志检测（Android 专属）

```bash
if [ "$PLATFORM" = "Android" ]; then
  adb -s "$UDID" logcat -d -t 200 \
    | grep -E "FATAL EXCEPTION|ANR in|NullPointerException|java.lang.RuntimeException" \
    > /tmp/monkey_logcat_tmp.txt 2>/dev/null || true
  # 若 /tmp/monkey_logcat_tmp.txt 非空 → 判定为 crash 或 anr
fi
```

### 发现异常时追加到 anomaly_log

```bash
python3 -c "
import json, os
log = json.load(open('$anomaly_log'))
log.append({
    'step': int(os.environ['STEP']),
    'type': os.environ['ATYPE'],
    'description': os.environ['ADESC'],
    'screenshot': os.environ['ASHOT'],
    'logcat': open('/tmp/monkey_logcat_tmp.txt').read()[:500] if os.environ.get('PLATFORM') == 'Android' else '',
    'timestamp': '$(date +%H:%M:%S)'
})
json.dump(log, open('$anomaly_log', 'w'), ensure_ascii=False)
" STEP="$ops_count" ATYPE="$anomaly_type" ADESC="$anomaly_desc" ASHOT="$SHOT_PATH" PLATFORM="$PLATFORM"
echo "[Monkey] 已记录异常: $anomaly_type (step $ops_count)"
```

其中 `$anomaly_type` 和 `$anomaly_desc` 由 Claude 根据截图和 logcat 内容确定后赋值。

---

## 崩溃恢复（非阻塞）

检测到 `crash` 或 `anr` 类型异常时，在记录完异常后执行以下恢复流程，**不中断主循环，ops_count 不重置**：

```bash
echo "[Monkey] 检测到 $anomaly_type，开始恢复流程"

# 1. 强制停止 App
if [ "$PLATFORM" = "Android" ]; then
  adb -s "$UDID" shell am force-stop "$PKG"
else
  # iOS：调用 appium_terminate_app
  echo "[Monkey] iOS: 调用 appium_terminate_app 终止 $PKG"
fi

# 2. 重新启动 App
echo "[Monkey] 重新启动 App..."
# 调用 appium_launch_app，等待启动完成（最长 10s）

# 3. 重新登录
# 按 common/login.md 对应 App 的登录流程执行登录
echo "[Monkey] 执行登录流程（common/login.md）"

# 4. 继续主循环
echo "[Monkey] 恢复完成，继续主循环（ops_count=$ops_count）"
```
