# 多设备并行执行

> 每台设备一个 subagent 并行执行，完成后按平台合并出两份报告（Android + iOS）。

---

## 流程

### 1. 从 EXECUTION_ENTRIES 按设备分组

解析完成后（见 [parsing.md](parsing.md) 第5步），`EXECUTION_ENTRIES` 已包含每条执行记录的 `platform` + `device`。

按 `device` 分组：

```
DEVICE_GROUPS = {
  "udid_A": {"platform": "Android", "entries": [用例1, 用例3]},
  "udid_B": {"platform": "Android", "entries": [用例2, 用例4]},
  "udid_C": {"platform": "iOS",     "entries": [用例1, 用例3]},
  "udid_D": {"platform": "iOS",     "entries": [用例2, 用例4]},
}
```

空设备的记录在解析阶段已被标注「无设备，未执行」，不进入分组。

### 2. 每台设备派发一个 subagent

所有 subagent 同时启动，传入：
- 设备 UDID 和平台
- 该设备的用例列表
- `BITABLE_APP_TOKEN`（从 URL 解析的原始值，逐字传入 prompt，禁止让 subagent 自行推断）
- `TABLE_ID` 和各用例的 `RECORD_ID`（同上，逐字传入）

### 3. 各 subagent 写临时文件

每个 subagent 执行完成后：

```bash
echo '$CASES_JSON' > /tmp/result_<udid>.json
```

**结果文件格式强制规范（必须严格遵守）：**

```json
[
  {
    "name": "用例1 xxx",
    "platform": "Android",
    "device": "udid_A",
    "module": "上课",
    "seq": 1,
    "passed": true,
    "duration": 90,
    "steps": [
      {"type": "ACTION", "text": "点击登录按钮", "pass": true},
      {"type": "ASSERT", "text": "进入课程详情页", "pass": true,
       "verify_method": "id", "evidence": "com.gaotu100.superclass:id/course_detail_title",
       "confidence": "high"},
      {"type": "ASSERT", "text": "显示购买成功", "pass": false,
       "verify_method": "text", "evidence": "实际文案：网络异常", "confidence": "high",
       "note": "未出现成功文案"}
    ],
    "screenshots": ["/Users/.../mcp_shots/gaotu/xxx/case1_assert.png"]
  }
]
```

- 文件内容必须是 **JSON 数组**（`[{...}]`），不得包裹在对象中（禁止 `{"cases":[...]}` 格式）
- 每条用例必须包含 `device` 和 `platform` 字段，供主 agent 合并时区分
- 每个 `step` 含 `type`(PRECOND/ACTION/ASSERT) / `text` / `pass`(bool)；失败步另填 `note`(原因)
- **ASSERT 步必须额外含**（取证契约，见 [locator.md](locator.md)「ASSERT 取证链」）：
  - `verify_method`：`id`(元素取证) / `text`(文本属性取证) / `vision`(视觉兜底)
  - `evidence`：判定依据——`id`/`text` 填命中的 selector 或真实文本，`vision` 填截图本地路径
  - `confidence`：`high`(id/text 取证) / `low`(vision 主观判定，报告中标注需人工复核)
- `verify_method=vision` 且引用元素 id 不在真相源 `elements.truth.json` 的，视为未验证，不得记 `pass: true`
- `screenshots`：该用例所有截图的本地**绝对路径**数组（主流程会上传到结果表附件字段）；无截图填 `[]`
- 写文件后立即用 `python3 -c "import json,sys; json.load(open('/tmp/result_<udid>.json'))"` 验证 JSON 合法性

### 4. 等待所有 subagent 完成

主 agent 轮询临时文件是否全部写入，再合并：

```bash
EXPECTED_UDIDS=("udid_A" "udid_B" "udid_C")   # 替换为实际设备列表

echo "[INFO] 等待所有 subagent 完成..."
while true; do
  all_done=true
  for udid in "${EXPECTED_UDIDS[@]}"; do
    [ -f "/tmp/result_${udid}.json" ] || { all_done=false; break; }
  done
  $all_done && break
  sleep 10
done
echo "[INFO] 所有设备执行完毕，开始合并报告"
```

### 5. 按平台合并 + 生成报告

```bash
# 合并 Android
python3 -c "
import json, glob
cases = []
for f in sorted(glob.glob('/tmp/result_*.json')):
    data = json.load(open(f))
    android = [c for c in data if c.get('platform','').lower() == 'android']
    cases.extend(android)
print(json.dumps(cases, ensure_ascii=False))
" > /tmp/cases_android.json

# 合并 iOS
python3 -c "
import json, glob
cases = []
for f in sorted(glob.glob('/tmp/result_*.json')):
    data = json.load(open(f))
    ios = [c for c in data if c.get('platform','').lower() == 'ios']
    cases.extend(ios)
print(json.dumps(cases, ensure_ascii=False))
" > /tmp/cases_ios.json

# Android 报告
python3 scripts/wiki_report.py \
  --app gaotu --version <version> --platform Android \
  --time <start_time> --duration <duration> \
  --total <N> --passed <P> --failed <F> --rate <R> \
  --cases "$(cat /tmp/cases_android.json)"

# iOS 报告
python3 scripts/wiki_report.py \
  --app gaotu --version <version> --platform iOS \
  --time <start_time> --duration <duration> \
  --total <N> --passed <P> --failed <F> --rate <R> \
  --cases "$(cat /tmp/cases_ios.json)"
```

> `--device` 无需传，脚本自动从 cases 的 `device` 字段提取并在汇总表中展示。

---

## cases 必填字段

每条用例须包含 `device` 和 `platform`，供合并时区分：

```json
{
  "name": "用例1 xxx",
  "platform": "Android",
  "device": "udid_A",
  "module": "上课",
  "passed": true,
  "duration": 90,
  "steps": [...]
}
```

---

## 注意事项

- 各设备需同时连接，每台有独立 Appium session
- 总耗时 ≈ 所有 subagent 中最慢的一台
- 临时文件执行完后清理：`rm /tmp/result_*.json /tmp/cases_android.json /tmp/cases_ios.json`
