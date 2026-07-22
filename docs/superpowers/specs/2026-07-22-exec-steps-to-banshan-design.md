# 执行步骤沉淀为半山(Banshan)自动化用例 — 设计对齐

- 日期：2026-07-22
- 状态：草稿 / 待对齐
- 作者：shijinge + Claude

## 1. 目标

在 App 自动化执行的过程中，把 **每一步操作** 连同 **操作元素的定位信息** 实时记录成一条 **半山(Banshan)用例**。使得：

1. 人可以看到 AI 的完整执行步骤；
2. 下次回归时可以**直接复用这些步骤和元素定位**，不再依赖 AI 指导即可完成该用例的回归。

> 注意：本次**只做"记录成半山用例"**。读取半山用例并驱动设备重放的"执行器"**不在本次范围**。
> 与既有的《用例脚本固化设计》**无关**，是独立一套，不参考、不复用。

## 2. 范围

- ✅ 执行过程中逐步记录：操作类型 + 参数 + 元素定位 → 写入半山用例节点。
- ✅ 失败步骤标记。
- ❌ 不做重放执行器。
- ❌ 不改造 CI / orchestrate 链路（本次为手动示范验证）。

## 3. 执行主体（决策 A）

**本次由 Claude 手动执行一遍做示范**：用 appium-mcp 亲自操作设备，每完成一步就写入半山。

**前置条件（重要）**：
- 目标安卓设备同一时刻只能被一个 appium session 占用。
- 当前存在后台 orchestrate run(`gaotu_5.92.00_android`)正占用唯一设备(`26KUT24202013751`)。
- **示范开始前必须先腾出设备**：停止该后台 run，或等其结束。（不擅自停，由人确认）

## 4. 每步记录规范（核心）

每完成一个 appium 操作，记录为一个步骤节点，包含两块信息：

### 4.1 操作
- `action`：click / input / swipe / scroll / launch / assert / back / wait …
- `value`：操作参数（如输入的文本、滑动方向）
- 步骤描述：自然语言，如"点击底部【我的】Tab"

### 4.2 元素定位（关键 — 为下次直接复用）

执行时把当前操作元素固化成确定性定位，按 **稳定性优先级** 记录：

1. `resource-id`（Android `resource-id`）— 最优
2. `text` / `content-desc`（accessibility id）
3. 稳定 `xpath`
4. 坐标（兜底，标注 `unstable: true`）

**用 `ai_instruction`(视觉)定位的元素**：找到后立刻 `get_element_attribute` 反查上述属性并存下确定性定位，使该步骤下次不再需要 AI。

> 反查失败（无 id/text）时，记录 xpath 或坐标兜底，并标注不稳定，供人工后续加固。

## 5. 半山用例结构（决策 C）

- **一条被执行的测试用例 = 一条半山 case**。
- `createByMcp` 建 case → 根节点为用例标题。
- 每一步 = 一个子步骤节点（`addNode` 逐步 / `batchAddNode` 批量）：
  - `text`：步骤描述
  - `note`：结构化 JSON，形如
    ```json
    {"action":"click","strategy":"id","selector":"com.gaotu100.superclass:id/xxx",
     "value":null,"fallback":{"xpath":"...","xy":[x,y],"unstable":false},
     "assert":null}
    ```
  - `resource` 标签：`执行步骤` / `预期结果`(ASSERT)
  - ASSERT 步骤：`note` 里带 `assert` 字段（期望 text/id），遵循项目 ASSERT 取证规范（有 id/text 时靠取证而非肉眼）。

## 6. 失败与重复执行（决策 D）

- **某步失败**：该步节点 `addNode` 时设 `progress=5`(失败)；后续步骤停止或按需标记。
  - ⚠️ 语义坑：`addNode.progress`=1成功/5失败/9阻塞/4不执行；`tagNode.progress`=1失败/5阻塞/9成功/4忽略（相反）。统一用 `addNode.progress`。
- **同一用例重复执行**：**每次新建一条 case**（不覆盖），便于对比历史执行。

## 7. 半山接口清单（已核实）

| 接口 | 用途 | 关键参数 |
|---|---|---|
| `createByMcp` | 建用例 | 必填 `creator`(邮箱前缀)、`productLineName`(迭代组名)、`title`；可选 `teamId`(迭代组id)、`description`、`channel`(默认1) |
| `addNode` | 加单步节点 | 必填 `caseId`、`text`、`modifier`；可选 `parentNodeId`、`note`、`resource`、`progress`、`priority` |
| `batchAddNode` | 批量加节点树 | 必填 `caseId`、`nodeTreeList`、`modifier` |
| `tagNode` | 标节点结果 | 需 `recordId`(执行记录id) — 本方案不用 |

## 8. 落点与命名

- `creator` / `modifier`：`<待提供：你的邮箱前缀>`
- `teamId`：`<待提供>`
- `productLineName`：`<待提供：迭代组名>`（接口必填，即使给了 teamId 仍需）
- `title` 建议：`高途 5.92.00 - <用例名> 自动化步骤 (2026-07-22)`

## 9. 待对齐 / 开放问题

- [ ] B1：`creator`(邮箱前缀) = ?
- [ ] B2：`teamId` = ? 且 `productLineName`(迭代组名) = ?
- [ ] A1：示范执行**哪一条用例**？（给一个具体用例，如某条 bitable 用例编号 / 或"启动→登录→进入某页"这种短流程）
- [ ] A2：示范前如何腾设备——停当前后台 run，还是等它结束？
- [ ] 5a：`note` 用上面这个 JSON schema 是否 OK？字段要不要增减？
