# 发版自动触发批量测试设计

**日期**：2026-05-27  
**状态**：待实现  
**关联**：[APK探索驱动设计](2026-05-26-apk-exploration-design.md)

---

## 背景

每次 App 发版后，希望自动在 4 台 Android + 4 台 iOS 设备上批量执行 Bitable 中标记"执行自动化"的用例，生成双端 Wiki 报告并发送飞书群通知。

---

## 完整架构

```
飞书群消息："gaotu 5.91.51 android:URL ios:URL"
        ↓ Webhook
Flask服务器（云端）验签 → 解析 → SSH触发 → 立即返回200
        ↓ nohup后台
scripts/orchestrate.py（Mac主控）
        │
        ├─ 1. 安装
        │     下载APK+IPA → 安装4台Android + 4台iOS
        │     提取版本号 → 确定 apps/{app}/{version}/
        │
        ├─ 2. 探索（仅新版本触发）
        │     检查 index.md 是否存在
        │     不存在 → 用1台Android做探索 → 生成 index.md + pages/*.md
        │     已存在 → 跳过
        │
        ├─ 3. 读Bitable
        │     过滤"执行自动化"=true的用例
        │     按设备字段分组 → 8组执行记录
        │
        ├─ 4. 并行执行（8个claude CLI）
        │     Android×4 + iOS×4 同时启动
        │     每台写 /tmp/result_{udid}.json
        │     超时90min → 强制kill
        │
        └─ 5. 汇总报告
              合并结果 → wiki_report.py Android版 + iOS版
              飞书群通知（含Wiki链接 + 通过率）
```

---

## Section 1：Flask 消息层

### 消息格式

```
{app_id} {version} android:{apk_url} ios:{ipa_url}
```

示例：
```
gaotu 5.91.51 android:https://xxx.apk ios:https://xxx.ipa
```

支持的 app_id：`gaotu` / `tutu` / `jingpin` / `gongkao` / `xinli` / `ketang`

### Flask 服务（`server/app.py`）

```
POST /webhook/feishu
  1. 验签（X-Lark-Signature）
  2. 处理 url_verification（飞书首次验证）
  3. 过滤非文本消息 / 机器人自身消息
  4. 正则解析：app_id、version、apk_url、ipa_url
  5. 解析失败 → 飞书回复格式错误提示
  6. 防重复：检查 /tmp/orchestrate_{app}_{version}.pid
             进程在跑 → 回复"已在执行中"
  7. 解析成功 → SSH触发，飞书回复"✅ 已收到，开始执行 {app} {version}"
```

### SSH 触发命令

```bash
ssh mac-host "nohup python3 /path/to/scripts/orchestrate.py \
  --app {app} \
  --version {version} \
  --apk-url {apk_url} \
  --ipa-url {ipa_url} \
  > /tmp/orchestrate_{app}_{version}.log 2>&1 &"
```

---

## Section 2：orchestrate.py 编排逻辑

### 主流程

```python
def main():
    write_pid(app, version)                          # 防重复

    download_and_install(apk_url, ipa_url, ...)      # 安装（失败→通知退出）

    if not exists(f"apps/{app}/{version}/index.md"): # 探索（新版本）
        run_exploration(app, version, android_devices[0])
        # 失败→跳过（不阻断执行）

    entries = fetch_bitable_cases(app)               # 读Bitable（重试3次）
    groups  = group_by_device(entries)               # 按设备分组

    procs   = launch_claude_per_device(groups)       # 并行启动8个claude
    results = collect_results(procs, timeout=90*60)  # 等待+超时保护

    generate_reports(app, version, results)          # Wiki报告+群通知
    cleanup_pid(app, version)
```

### 容错处理

| 场景 | 处理 |
|------|------|
| 某台设备安装失败 | 跳过该设备，其余继续 |
| 探索阶段失败 | 跳过探索，退化为纯视觉定位执行 |
| 某台 claude 超时 90min | kill 该进程，结果标记"超时未完成" |
| Bitable 读取失败 | 重试 3 次，仍失败则飞书通知并退出 |
| 结果 JSON 格式错误 | 标记该设备"结果解析失败"，不影响其他 |
| 无可执行用例 | 飞书通知"无标记用例"，退出 |

### claude 启动命令

```python
cmd = [
    "claude", "--add-dir", f"skills/{app}",
    "--add-dir", "common",
    "--print",
    build_prompt(udid, platform, cases, bitable_token, table_id)
]
proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
```

---

## Section 3：探索阶段

> 详细设计见 [APK探索驱动设计](2026-05-26-apk-exploration-design.md)

- 仅新版本首次触发，用 1 台 Android 设备执行
- 广度优先遍历，最大深度 2
- 生成 `apps/{app}/{version}/index.md` + `pages/*.md`
- 探索失败不阻断：退化为 gaotu skill 纯视觉定位（`ai_instruction`）

---

## Section 4：并行执行层

> 复用现有 `common/parallel.md`

- 每台 claude 接收：设备 UDID、平台、用例列表、Bitable token
- 执行完成写 `/tmp/result_{udid}.json`（格式同 parallel.md 规范）
- 回写 Bitable：执行结果 + 截图

---

## Section 5：报告与通知

> 复用现有 `scripts/wiki_report.py`，需将 `--account` 参数改为可选（批量执行账号不固定，传"多账号"作默认值）

```bash
# Android
python3 scripts/wiki_report.py \
  --app {app} --version {version} --platform Android \
  --time {start_time} --duration {duration} \
  --total N --passed P --failed F --rate R \
  --cases "$(合并4台Android结果)"

# iOS
python3 scripts/wiki_report.py \
  --app {app} --version {version} --platform iOS \
  ...
```

### 飞书群最终通知格式

```
📱 {app_name} {version} 自动化测试完成

Android：{passed}/{total} 通过 ({rate}%)  📄 {wiki_url}
iOS：    {passed}/{total} 通过 ({rate}%)  📄 {wiki_url}

总耗时：{duration}
```

---

## 新增文件清单

```
server/
└── app.py              # Flask Webhook 服务

scripts/
└── orchestrate.py      # Python 编排主控

config/
└── devices.yaml        # 8台设备 UDID 配置（Android×4 + iOS×4）
```

---

## Bitable 前置要求

Bitable 用例表需新增字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 执行自动化 | Checkbox | true = 参与发版自动执行 |

---

## 不在本次范围内

- 多 App 同时发版并行触发（串行执行，后续可扩展）
- 失败用例自动重试（需人工确认后触发）
- 发版通知与测试结果的 Bitable 版本关联记录
