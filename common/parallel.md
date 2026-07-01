# 多设备并行执行

> **二级编排**：外层每台设备并行；设备内把用例切成多批，**每批一个独立 subagent 串行执行**，批末增量回写结果表 + 落盘。全部完成后按平台合并出两份报告（Android + iOS）。
>
> 为什么分批：单设备用例多（100+）时，一个 subagent 在同一对话里线性跑完会导致上下文爆炸。每批换新 subagent 才能真正释放上下文——回写表 + 落盘只是批次交接手段，换进程才是目的。

---

## run 开头：清空结果表（一次）

> ⚠️ 结果表清空**只在整个 run 开始、并行派发之前，由主 agent 执行一次**（Android 表 + iOS 表各清一次）。
> 之后所有批次只做增量 append，**禁止任何 subagent 再清空整表**——否则后一批会把前一批的结果删掉。
> 清空逻辑见 [../.claude/skills/gaotu/SKILL.md](../.claude/skills/gaotu/SKILL.md)「Bitable 回写 · 步骤：清空目标表」。

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

### 2. 设备内分批 + 批级 subagent 串行派发

每台设备**不再**一个 subagent 跑全部用例，改为：

```
for each device（设备间并行）:
    1. 对该设备全部 entries 跑预扫描排序（见 prescan.md）→ 有序 EXEC_PLAN
    2. 按 BATCH_SIZE=20 顺序切批 → BATCHES（见 prescan.md「切批」）
    3. 串行派发（同设备的批必须串行，共享 session/登录态）：
         CURRENT_ACCOUNT = ""          # 首批为空
         for batch_idx, batch in enumerate(BATCHES):
             起一个新 subagent，传入下方「交接信息包」
             等其返回 → 取回 CURRENT_ACCOUNT、本批通过/失败计数
             （返回的 CURRENT_ACCOUNT 传给下一批）
```

> 不同设备的首批可同时派发，各设备之后按自己的批串行推进。
> 主 agent 上下文只持有「批次进度 + 每批精简返回（账号/通过数）」，**不持有用例步骤明细**——明细在批级 subagent 内部产生并落盘后即随进程退出释放。

**交接信息包（主 agent → 批级 subagent，逐字传入 prompt）：**

| 交接项 | 作用 |
|--------|------|
| `CURRENT_ACCOUNT`（首批为空） | 决定是否切账号；首条用例所需账号 == 此值则跳过登录 |
| UDID / 平台 / 包名 | 复用常驻 session（`list_sessions` 复用，非首批不新建） |
| 本批用例列表（全局有序的第 k 段，含 name/steps/module/case_id/record_id） | 要跑什么 |
| `BITABLE_APP_TOKEN`（URL 解析原始值，禁止 subagent 自行推断） | 回写 |
| 结果表 `table_id`（按平台选 Android/iOS 表）/ 来源表 `table_id` | 回写目标 |
| `batch_idx` / `is_last_batch`（bool） | 是否最后一批 → 决定是否收尾 `delete_session()` |
| 全局 `START_TS` | 报告耗时基准 |

### 3. 各批级 subagent：批末回写 + append 落盘

批级 subagent 执行完本批用例后：

1. **批末回写结果表**（upsert，见 SKILL.md「Bitable 回写」）：按本批 `用例ID` 删同 ID 旧记录 → batch_create 本批。**不清空整表**。
2. **append 落盘**：本批每条用例作为**一行** JSON 追加到 `/tmp/result_<udid>.jsonl`：

```bash
# 逐行追加（每行一条 case，供最终合并报告）
python3 - "$CASE_JSON" >> /tmp/result_<udid>.jsonl <<'PY'
import sys, json
print(json.dumps(json.loads(sys.argv[1]), ensure_ascii=False))
PY
```

3. **非最后一批**：不 `delete_session`、不重启 App，直接退出，返回 `CURRENT_ACCOUNT` + 本批通过/失败计数。
4. **最后一批**：执行第八步收尾（退教室 / 恢复 tab / `delete_session()`）。

**单条 case 字段规范（`/tmp/result_<udid>.jsonl` 每行一条，必须严格遵守）：**

```json
{"name": "用例1 xxx", "platform": "Android", "device": "udid_A", "module": "上课", "seq": 1, "passed": true, "duration": 90, "steps": [{"type": "ACTION", "text": "点击登录按钮", "pass": true}, {"type": "ASSERT", "text": "进入课程详情页", "pass": true, "verify_method": "id", "evidence": "com.gaotu100.superclass:id/course_detail_title", "confidence": "high"}, {"type": "ASSERT", "text": "显示购买成功", "pass": false, "verify_method": "text", "evidence": "实际文案：网络异常", "confidence": "high", "note": "未出现成功文案"}], "screenshots": ["/Users/.../case1_assert.png"]}
```

- 落盘文件是 **JSONL**：每行一条 case（单个 JSON 对象，**一行内不换行、不包裹数组**），批级 subagent 每跑完一条即 append 一行
- 每条用例必须包含 `device` 和 `platform` 字段，供主 agent 合并时区分
- 每个 `step` 含 `type`(PRECOND/ACTION/ASSERT) / `text` / `pass`(bool)；失败步另填 `note`(原因)
- **ASSERT 步必须额外含**（取证契约，见 [locator.md](locator.md)「ASSERT 取证链」）：
  - `verify_method`：`id`(元素取证) / `text`(文本属性取证) / `vision`(视觉兜底)
  - `evidence`：判定依据——`id`/`text` 填命中的 selector 或真实文本，`vision` 填截图本地路径
  - `confidence`：`high`(id/text 取证) / `low`(vision 主观判定，报告中标注需人工复核)
- `verify_method=vision` 且引用元素 id 不在真相源 `elements.truth.json` 的，视为未验证，不得记 `pass: true`
- `screenshots`：该用例所有截图的本地**绝对路径**数组（主流程会上传到结果表附件字段）；无截图填 `[]`
- 每 append 一行后立即校验该文件每行合法：`python3 -c "import json; [json.loads(l) for l in open('/tmp/result_<udid>.jsonl') if l.strip()]"`

### 4. 等待所有设备所有批完成

主 agent 是**批级 subagent 的直接派发者**，天然掌握进度：每台设备的批循环（串行 await 每批 subagent 返回）结束即该设备全部完成，所有设备的批循环都结束即可合并。

> 不再靠"轮询临时文件是否存在"判定——`result_<udid>.jsonl` 从首批起就存在且持续 append，文件存在 ≠ 该设备跑完。以主 agent 掌握的「每设备批次总数 vs 已返回批数」为准。
> 某批 subagent 崩溃/超时：主 agent 重派该批（`batch_idx` 不变），批级回写是 upsert（按用例ID 先删后建），重跑不产生重复。

### 5. 按平台合并 + 生成报告

```bash
# 合并 Android（读所有 jsonl 行，每行一条 case）
python3 -c "
import json, glob
cases = []
for f in sorted(glob.glob('/tmp/result_*.jsonl')):
    for line in open(f):
        if not line.strip(): continue
        c = json.loads(line)
        if c.get('platform','').lower() == 'android':
            cases.append(c)
print(json.dumps(cases, ensure_ascii=False))
" > /tmp/cases_android.json

# 合并 iOS
python3 -c "
import json, glob
cases = []
for f in sorted(glob.glob('/tmp/result_*.jsonl')):
    for line in open(f):
        if not line.strip(): continue
        c = json.loads(line)
        if c.get('platform','').lower() == 'ios':
            cases.append(c)
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
- **session 生命周期**：同一设备的多批共用一个常驻 session，批间**不销毁**；仅该设备最后一批收尾时 `delete_session()`。中间批次重建 session / 重启 App 会丢登录态，使 `CURRENT_ACCOUNT` 交接失效
- 总耗时 ≈ 最慢的一台设备（= 该设备所有批串行耗时之和）；设备之间并行
- 临时文件执行完后清理：`rm /tmp/result_*.jsonl /tmp/cases_android.json /tmp/cases_ios.json`
