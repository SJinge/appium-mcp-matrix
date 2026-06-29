# 用例解析规范

> 本文件供 `gaotu` skill 引用，包含：三条用例解析路径（搬山 caseId / 自然语言 / 飞书 Bitable）、步骤分类规则、目标起始页分析映射。

---

## 解析路径 A：搬山 caseId

```
1. 调用 testCaseDetail(caseId) 获取用例结构
2. 从返回的 caseContent（JSON 字符串）解析节点树，按以下规则分类每个节点：
   - 节点 resource 含 "预期结果" 或文字以"预期："/"期望："开头 → 类型 = ASSERT
   - 其余节点 → 类型 = ACTION
3. 整理为带类型的步骤列表：
   步骤1 [ACTION]: <文字>
   步骤2 [ACTION]: <文字>
   步骤3 [ASSERT]: <预期文字>
   …
4. 展示给用户确认（"解析到 N 步（其中 M 个验证点），是否继续？"）
```

---

## 解析路径 B：自然语言 / 直接描述

```
1. 读取用户提供的文本
2. 按换行/序号切分，识别验证点：
   - 行以"预期："/"期望："/"验证："/"检查："开头 → 类型 = ASSERT
   - 其余行 → 类型 = ACTION
3. 若文本无明确步骤（一句话描述），生成推断步骤并展示（含推断的 ASSERT 节点）
4. 等用户确认或修改后继续
```

---

## 解析路径 C：飞书多维表格（Bitable）

**表格字段结构（已确认）**：

| 字段名 | 类型 | 用途 |
|--------|------|------|
| 用例编号 | Number | 用例 ID |
| 模块 | SingleSelect | 启动登录/首页/闪学/上课/我的/消息 |
| 用例名称 | Text | 用例标题 |
| 预置条件 | Text | 前置说明（不作为执行步骤） |
| 测试步骤 | Text | ACTION 步骤（含编号，\n 分隔） |
| 预期结果 | Text | 整体预期（作为最终 ASSERT） |
| 验证点 | Text | 具体验证点（作为 ASSERT，可选） |
| Android设备 | Text | 执行用 Android 设备序列号（如 `ce67d979`） |
| ios设备 | Text | 执行用 iOS 设备 UDID |
| 执行结果 | SingleSelect | 回写：`通过` / `失败` |
| 备注/执行详情 | Text | 回写：失败原因或执行摘要 |
| 截图 | Attachment | 回写：附件（当前暂不支持上传） |
| 父记录 | SingleLink | 层级关系（忽略，不影响执行） |

> 设备字段名以实际表格列名为准（已确认：`Android设备` / `ios设备`）。若不存在调用 `bitable_v1_appTableField_list` 确认。

**文本字段格式**：值为数组 `[{text: "...", type: "text"}, …]`，解析时拼接所有 text 值。

---

**从 URL 提取 token**：

```
支持两种 URL 格式：
  ① Wiki 内嵌：https://<domain>.feishu.cn/wiki/<wiki_token>?table=<table_id>&view=<view_id>
     → app_token = wiki_token（直接用于 bitable API，已验证可行）
     → table_id  = URL 中 table= 参数值
  ② 独立 Base：https://<domain>.feishu.cn/base/<app_token>?table=<table_id>
     → app_token = /base/ 后的部分
     → table_id  = URL 中 table= 参数值

  若 URL 无 table= 参数 → 调用 bitable_v1_appTable_list 列出表格让用户选择
```

**读取并解析记录**：

> ⚠️ **用例执行顺序 = 指定视图顺序（强制规则）**
>
> 用户所说的「第 N 条用例」一律指**该 app 指定执行视图返回顺序的第 N 条**（从 1 开始），
> 不是默认搜索顺序、不是 ID 顺序、不是表格物理行号。各 app 的执行视图 `view_id` 见
> [../scripts/feishu_config.py](../scripts/feishu_config.py) `BITABLE_CONFIGS["<app>"]["view_id"]`
> （如 gaotu = `vewJViMvTW`，已筛选并按 ID 升序）。
>
> 取记录时**必须**：
> 1. `bitable_v1_appTableRecord_search` 的 `data` 里**传 `view_id`** —— 视图自带筛选+排序，
>    只有带 view_id 返回的顺序才与用户在飞书里看到的视图顺序一致。
> 2. **禁止再传 `data.sort` 或任何自定义排序** —— 自定义 sort 会覆盖视图排序、并可能拉回视图筛选外的记录，
>    导致「第 N 条」对不上（曾因此把 82 条视图拉成 232 条全表、顺序全乱）。
> 3. 按返回的 `items` **原始数组下标**定位第 N 条（`items[N-1]`），不要本地再排序。

```
1. 调用 bitable_v1_appTableRecord_search(app_token, table_id, page_size=500,
       data={"view_id": "<该 app 的执行视图 view_id>"})   # 不传 sort
   按视图顺序读取记录（每条记录 = 一个完整用例；返回 items 顺序即视图顺序）

2. 定位用户要执行的用例：
   - 用户说「第 N 条」「第 N、M 条」→ 取 items[N-1]、items[M-1]（数组下标即视图顺序）
   - 用户未指定 → 展示用例列表（ID + 用例名称，按视图顺序编号）让用户选择，支持多选
   → 只处理选中记录，其余忽略

3. 对选中记录解析步骤：
   ① 解析 测试步骤 字段：
      - 拼接所有 text 值得到完整文本
      - 按 \n 分割，过滤空行
      - 识别编号行（以 "1、" "1，" "1." "step1" 等开头）→ 每行一个 ACTION
      - 无编号时整段作为一个 ACTION
   ② 解析 验证点 字段（若非空）：
      - 拼接文本 → 追加为 ASSERT 步骤
   ③ 解析 预期结果 字段：
      - 若 验证点 为空 → 作为最终 ASSERT 步骤
      - 若 验证点 有值 → 作为补充 ASSERT（拼在验证点之后）
   ④ 解析 预置条件 字段，追加为步骤列表**最前面**，类型 = [PRECOND]：
      - 拼接所有 text 值，按 \n 分割，过滤空行
      - 每行作为一个前置检查/执行项
      - 常见映射：
        | 预置条件文字 | 路径 C 执行动作 | 路径 A/B 执行动作 |
        |------------|--------------|----------------|
        | 进入 app 首页 / 首页 / 进入 XX tab | **忽略**（模块字段已处理 tab 导航） | ASSERT 当前在目标 tab，不符则导航过去 |
        | 重启 App：否 | 仅确认 app 在前台运行 | 同左 |
        | 重启 App：是 | 执行重启（等同于第三步） | 同左 |
        | 账号：1210xxxxx | ASSERT 登录账号匹配，不符则重新登录 | 同左 |
        | 账号有已购课程 / 其他数据条件 | 记录为前置说明，执行时截图确认 | 同左 |

4. 构建最终步骤列表（顺序）：
   [PRECOND] 步骤P1: <预置条件行1>
   [PRECOND] 步骤P2: <预置条件行2>
   …
   [ACTION]  步骤1:  <测试步骤第1行>
   [ACTION]  步骤2:  <测试步骤第2行>
   …
   [ASSERT]  步骤N:  <验证点>
   [ASSERT]  步骤N+1: <预期结果>

5. 提取设备字段，生成执行记录列表：

   ① 读取每条记录的 `Android设备` 和 `ios设备` 字段值
      - 若字段名不存在 → 调用 bitable_v1_appTableField_list 确认实际字段名后重试

   ② 按以下规则生成执行记录（EXECUTION_ENTRIES）：

   | Android设备 | ios设备 | 处理方式 |
   |------------|--------|---------|
   | 有值 | 有值 | 拆成两条：Android 一条 + iOS 一条 |
   | 有值 | 空 | 生成一条 Android 执行记录 |
   | 空 | 有值 | 生成一条 iOS 执行记录 |
   | 空 | 空 | 跳过，标注「无设备，未执行」 |

   ③ 每条执行记录结构：
   ```json
   {
     "record_id": "<bitable_record_id>",
     "name": "<用例编号> <用例名称>",
     "platform": "Android" 或 "iOS",
     "device": "<设备序列号或UDID>",
     "module": "<模块字段值>",
     "steps": [...]
   }
   ```

6. 记录上下文变量（供后续步骤使用）：
   BITABLE_APP_TOKEN  = <app_token>
   BITABLE_TABLE_ID   = <table_id>
   BITABLE_RECORD_IDS = [<所有选中记录的 record_id>]
   EXECUTION_ENTRIES  = [<生成的执行记录列表>]

7. 将解析结果返回给 skill 执行层：
   - EXECUTION_ENTRIES（执行记录列表，含平台/设备/步骤）
   - BITABLE_APP_TOKEN / TABLE_ID / RECORD_IDS
```
