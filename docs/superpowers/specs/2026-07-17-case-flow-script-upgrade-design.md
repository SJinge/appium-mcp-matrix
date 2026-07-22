# 完整流程脚本直切新格式设计

## 背景

当前 `apps/<app>/cases/<platform>/*.py` 由 `scripts/orchestrate.py` 在用例跑通后自动生成，但生成结果本质上是“断言回放脚本”：

- 脚本只保留 `ASSERTIONS`
- `execute(ctx)` 只调用 `assert_evidence_present`
- 运行时只拉当前设备的 `page source` 做 `id/text` 包含判断

这意味着脚本只能验证“当前页面是否已经处于目标状态”，不能主动完成：

- 前置状态准备
- 账号切换/登录
- 页面跳转与业务操作
- 已知弹窗处理
- 失败时步骤级证据采集

用户目标是直接切到“真正可执行的完整流程脚本”：飞书用例执行时既然已经能拿到真实元素和真实动作，就应基于真实轨迹直接生成可复跑脚本，而不是仅生成断言快照。

## 目标

把现有自动生成脚本体系直接升级为“完整流程脚本”体系，覆盖全部 Android 用例类型，要求：

1. 不改飞书表结构，继续复用现有自然语言用例。
2. 生成依据来自真实执行轨迹，而不是仅靠静态文本反推。
3. 新脚本本身可执行完整流程，而不是只做只读断言。
4. 同一 app / 平台 / 账号态下，脚本应尽量跨设备复用。
5. 已知固定弹窗和状态准备收敛进统一运行时，不散落到各 case 文件。

## 非目标

本次设计不包含以下内容：

- 不同时支持 Android 与 iOS 两套完整流程脚本执行器
- 不要求飞书用例立即结构化重写
- 不要求一次性把所有历史脚本全部回填重生；允许后续按真实执行逐步覆盖
- 不做“每个 case 直接生成完全自由的定制 Python 逻辑”

## 现状问题

### 1. 脚本能力过薄

当前 case 脚本形态类似：

- `META`
- `PRECONDITIONS`
- `ASSERTIONS`
- `execute(ctx)` 内遍历断言

没有动作步骤，无法单独复跑一条业务链路。

### 2. 运行时只支持只读断言

`run_case_script()` 当前只给脚本一个非常薄的 `ctx`，核心只有：

- `assert_evidence_present(verify_method, evidence)`

它没有统一的点击、输入、等待、页面路由、已知弹窗处理等能力。

### 3. 断言数据对跨设备复用不友好

当前生成逻辑会把昵称、手机号掩码、动态年级文本等直接写进 `evidence`，导致：

- 账号一变就失效
- 实验桶/灰度文案一变就失效
- 某些复合文本证据本身不可执行

### 4. 飞书自然语言并不稳定

飞书用例文本可继续作为“驱动一次真实执行”的输入，但不适合作为“完整流程脚本”的唯一真相源。更稳妥的方式是：

- 先按飞书用例真实执行
- 在执行过程中记录真实操作轨迹与真实断言证据
- 再生成脚本

## 方案概述

采用“轨迹生成 + DSL 执行器”方案：

1. 保留当前飞书驱动执行主链路。
2. 在 agent 执行每条用例时，要求结果中额外落盘完整动作轨迹。
3. 脚本生成器不再从 `ASSERT` 成功项中提取快照，而是从“完整动作轨迹 + 成功断言证据”生成 `FLOW`。
4. case 文件升级为“声明式流程脚本”。
5. 运行时提供统一的 `run_flow()` 执行引擎，实现动作、断言、状态准备、弹窗处理、失败收集。
6. `run_case_script()` 直接执行 `FLOW` 脚本；旧格式不再作为主路径。

## 新脚本格式

每个 case 文件保留 Python 容器，但核心数据从 `ASSERTIONS` 改为 `FLOW`。

示例：

```python
META = {
    "record_id": "recxxx",
    "name": "登录-密码登录",
    "module": "启动登录",
    "platform": "android",
    "generated_at": "2026-07-17 12:00:00",
}

FLOW = [
    {"type": "prepare_state", "target": "my_tab", "account": "<UNLOGIN>"},
    {"type": "handle_known_dialogs"},
    {"type": "tap", "by": "text", "value": "点击登录"},
    {"type": "assert_id", "value": "com.gaotu100.superclass:id/go_password_btn"},
    {"type": "tap", "by": "id", "value": "com.gaotu100.superclass:id/go_password_btn"},
    {"type": "input", "by": "id", "value": "com.gaotu100.superclass:id/phone_et", "text": "${account}"},
    {"type": "input", "by": "id", "value": "com.gaotu100.superclass:id/password_et", "text": "${password}", "secret": True},
    {"type": "tap", "by": "id", "value": "com.gaotu100.superclass:id/account_sign_btn"},
    {"type": "assert_text", "value": "点击登录", "negate": True},
]


def execute(ctx):
    return ctx["run_flow"](META, FLOW)
```

### 设计原则

- case 文件只声明“做什么”，不声明“怎么用 adb/appium 实现”
- 设备差异、账号切换、首启弹窗等公共逻辑统一放运行时
- 步骤必须原子化，不再把多重语义塞进一条 evidence 字符串
- 优先稳定 `id`，文本只在必要时使用

## `FLOW` 步骤类型

第一版支持以下步骤类型，足以覆盖当前大多数高途 Android 用例：

### 状态类

- `prepare_state`
  - 目标：准备到指定页面与账号态
  - 字段：`target`, `account`, `allow_relaunch`, `route_hint`

- `handle_known_dialogs`
  - 目标：统一处理固定已知弹窗
  - 默认规则：
    - 是否允许“高途”发送通知：点允许
    - 网络权限弹窗：点允许
    - 允许“高途”跟踪：点允许
    - 学习阶段弹窗：选一年级，点进入首页
    - 发现新版本：点取消

### 动作类

- `tap`
  - 字段：`by`, `value`, `fallbacks`
- `input`
  - 字段：`by`, `value`, `text`, `clear_first`, `secret`
- `back`
- `wait`
  - 字段：`seconds` 或 `until`
- `route`
  - 字段：`target`

### 断言类

- `assert_id`
- `assert_text`
- `assert_any`
- `assert_not_present`

所有断言步骤都统一支持：

- `soft_assert`
- `timeout`
- `evidence_label`

## 运行时设计

### 运行时入口

`run_case_script()` 不再只提供 `assert_evidence_present`，而是提供：

- `run_flow(meta, flow)`
- `resolve_variable(name)`
- `capture_debug_artifacts()`

其中 `run_flow()` 是唯一主入口。

### 运行时原子能力

运行时统一封装以下能力：

1. 页面抓取
   - `page_source`
   - 当前 activity / 当前页面特征

2. 元素查找
   - 按 `id`
   - 按文本
   - 候选 fallback

3. 动作执行
   - 点击
   - 输入
   - 返回
   - 等待

4. 状态准备
   - 账号切换
   - 登录/退出登录
   - 切 tab
   - 回首页
   - 必要时完成启动流程收口

5. 弹窗处理
   - 固定已知弹窗
   - 通用安全关闭策略

6. 断言取证
   - 记录命中的 selector / 文本 / 页面证据
   - 失败时附带截图与 page source

### 变量解析

脚本里允许出现变量：

- `${account}`
- `${password}`
- `${verification_code}`

变量值来源按优先级：

1. case 轨迹中记录的真实输入值
2. 账号规则推断（如矩阵 12 开头账号默认验证码 `1000`）
3. 运行时预置账号配置

## 脚本生成链路

### 旧链路

当前链路：

1. agent 执行飞书用例
2. 返回 case 结果
3. 从通过断言里提取高可信 `ASSERT`
4. 写出断言脚本

### 新链路

升级后链路：

1. agent 执行飞书用例
2. 每个动作步骤额外回传结构化轨迹
3. 每个断言步骤额外回传结构化证据
4. orchestrate 汇总动作轨迹与断言证据
5. 生成 `FLOW` 脚本
6. 后续回归优先执行 `FLOW` 脚本

### 轨迹数据结构

agent 每条结果里的 `steps` 除现有字段外，需要新增：

- `script_action`
  - 如 `tap`, `input`, `assert_text`
- `locator`
  - 如 `{"by": "id", "value": "..."}`
- `locator_fallbacks`
- `input_value`
- `page_hint`
- `route_target`

只有包含足够执行信息的动作步骤，才允许进入 `FLOW` 生成。

### 生成规则

- `PRECOND` 只作为辅助，不再直接写入脚本主体
- `ACTION` 优先从真实轨迹转为动作步骤
- `ASSERT` 优先生成原子断言，不再拼接复合 evidence
- 对 toast/snackbar 仍允许生成 `soft_assert`
- 对动态文案优先提取稳定元素，不稳定文本降级为可选断言或不生成

## 跨设备复用策略

为了让脚本尽量跨设备复用，生成器必须做“稳定性筛选”：

### 允许直接固化

- 稳定资源 id
- 稳定按钮文本
- 稳定 tab 文本
- 明确的页面入口元素

### 不直接固化

- 昵称
- 手机号掩码
- 动态推荐文案
- 年级内容区动态数据
- 依赖实验桶的展示文本

### 处理方式

- 优先 `id`
- 其次页面结构性文本
- 再其次 route/page hint
- 实在不稳定则不生成该断言，避免污染完整脚本

## 失败模型

`run_flow()` 的返回仍兼容当前结果结构：

- `record_id`
- `name`
- `module`
- `passed`
- `note`
- `steps`
- `script_source`

失败时规则：

1. 某步动作找不到元素
   - 记当前步失败
   - 记录 locator / 截图 / page source 路径
   - 整条 case fail

2. 某步断言失败
   - 按现有硬断言/软断言规则处理

3. 已知弹窗处理失败
   - 若弹窗属于固定规则，应记为真实阻断失败

4. 状态准备失败
   - 如无法切换到指定账号、无法到达目标 tab，整条 case fail

## 迁移方式

因为用户要求“直接切到新格式”，迁移策略采用“主路径直切”：

1. 生成器改为输出 `FLOW` 脚本
2. 运行时新增 `run_flow()`
3. `run_case_script()` 改为执行 `FLOW`
4. 旧 `ASSERTIONS` 生成逻辑不再作为主格式

为了降低风险，建议仍保留一个短期兼容层：

- 若脚本包含 `FLOW`，走新执行器
- 若脚本仍是旧 `ASSERTIONS`，记录 warning，并走旧只读执行器

这层兼容只作为迁移过渡，不作为长期主方案。

## 涉及文件

### 核心逻辑

- `scripts/orchestrate.py`
  - 新增 `run_flow()` 运行时
  - 扩展 `run_case_script()`
  - 改造 `generate_case_script()`
  - 扩展轨迹/断言生成逻辑

### 文档与规范

- `common/elements/dialog.md`
  - 固化已知弹窗处理规则
- `.claude/skills/gaotu/startup.md`
  - 补首启链路与学习阶段规则

### case 输出

- `apps/gaotu/cases/android/*.py`
  - 全部切换为 `FLOW` 新格式

## 测试策略

### 单测

1. `generate_case_script()` 可从结构化轨迹生成 `FLOW`
2. `run_case_script()` 遇到 `FLOW` 时走新执行器
3. `run_flow()` 能执行：
   - `prepare_state`
   - `tap`
   - `input`
   - `assert_id`
   - `assert_text`
4. 已知弹窗规则可被自动处理
5. 动态文本不会被错误固化为强断言

### 回归

至少覆盖：

- 登录-密码登录
- Tab 导航-默认选中与切换
- 首页-年级切换
- 首启链路类 case
- 含固定弹窗的 case

## 风险与取舍

### 风险 1：agent 轨迹质量不稳定

若动作轨迹不够结构化，生成器会失真。

取舍：
先明确收紧结果落盘格式，再生成脚本。

### 风险 2：运行时边界过大

若第一版试图覆盖所有复杂业务动作，执行器会膨胀。

取舍：
第一版只支持高频原子步骤，不支持过度定制逻辑。

### 风险 3：历史脚本无法一次性全量可跑

直切新格式后，旧脚本不一定都能立刻迁好。

取舍：
保留短期兼容层，但新生成与新执行统一只面向 `FLOW`。

## 结论

本次升级应以“真实执行轨迹生成完整流程脚本”为核心，不改飞书表结构，直接把脚本主格式切换为 `FLOW + run_flow()` 体系。

这样可以同时满足：

- 完整可执行
- 跨设备尽量复用
- 不要求先重构飞书表
- 后续规则统一收敛到运行时

这是比“只生成当前页断言脚本”更适合矩阵自动化长期演进的方案。
