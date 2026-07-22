# Orchestrator 执行器双适配设计

**目标**

让 `scripts/orchestrate.py` 的单设备执行器支持 `claude` 与 `codex` 双适配，默认使用 `codex`，同时保留现有基于 skill 的执行能力，并补上一层 runner-neutral 的通用执行上下文，确保切换执行器时不破坏现有 webhook 到报告回写的主链路。

**现状**

当前 orchestrator 为每台设备启动一个子进程，命令写死为 `claude --print`。执行流程依赖 Claude 的 `--add-dir` 机制注入 app skill 目录和共享 `common/` 规则。当 `claude` CLI 的认证状态失效时，子进程会在产出 JSONL 结果前退出，导致 orchestrator 将设备判为失败，哪怕下载、安装、设备准备等前置步骤都已经成功。

**问题**

当前执行器选择直接写死在 `launch_claude_per_device` 中，设备执行与单一 CLI 强绑定，恢复能力受限于该 CLI 的认证健康状态。与此同时，现有执行规则又是围绕 Claude skill 机制组织的，若直接切换到 Codex，会丢失关键执行约束。我们需要一个小而稳的改动：既能让运维通过配置切换执行器，又能让两种执行器共享同一套核心测试规则，而不是分裂成两套流程。

## 需求

1. 设备执行器必须支持通过环境变量配置，便于 webhook 服务在不改代码的前提下切换 runner。
2. 默认执行器必须为 `codex`。
3. 必须支持显式回退到 `claude`。
4. `claude` 路径下，现有 skill 目录注入方式必须继续可用。
5. `codex` 路径下，必须拿到最小必要执行规则，不能依赖 Claude 专属的 `--add-dir` 机制。
6. 下列主流程必须保持不变：下载、安装、WDA 启动、用例获取、结果收集、报告生成、群通知。
7. 现有“子进程退出但无结果”的失败判定逻辑必须继续生效。
8. 测试必须覆盖默认 runner、显式回退 runner，以及共享上下文注入行为。

## 方案概述

在 `scripts/orchestrate.py` 中增加一层 runner 解析与命令构造逻辑，不再把 `claude` 写死为唯一执行器；同时增加一层“共享执行上下文”拼装逻辑，让 Claude 与 Codex 都能收到同一套最小必要规则。

执行器通过环境变量选择：

- `ORCH_AGENT_CLI=codex`：使用 Codex CLI
- `ORCH_AGENT_CLI=claude`：使用 Claude CLI
- 未设置或为空：默认使用 `codex`

执行上下文分成两层：

- **runner-neutral 共享上下文**
  由本地文件中“执行必须知道”的最小规则拼装而成，例如：
  - `CLAUDE.md` 中强制要求的 common files 约束
  - 设备准备、启动弹窗、截图规范、定位规范、结果落盘规范
  - app 专属执行流程里 Codex 也必须知道的关键规则
  这部分内容将直接进入 prompt，供两种 runner 共用。

- **runner-specific 增强层**
  - `claude`：继续追加 `--add-dir <skill_dir>` 与 `--add-dir <common_dir>`，保留现有 skill 能力
  - `codex`：不依赖 Claude skill 注入，而是直接消费共享上下文

命令层面的其他行为尽量保持不变：

- 仍以“每台设备一条 prompt”的方式执行
- 仍将 stdout/stderr 合流写入单设备日志
- 仍按 app / version / device 分组驱动子进程

## 日志命名

当前日志路径为 `/tmp/claude_<udid>.log`，它会误导排障，以为所有子进程都一定是 Claude。

建议统一改为：

- `/tmp/agent_<udid>.log`

并同步更新结果收集、异常收尾、日志 tail 等所有引用点。

## 文件级设计

### `scripts/orchestrate.py`

新增：

- runner 名称解析函数
- 按 runner 构造命令的函数
- 共享执行上下文拼装函数
- 单设备日志路径生成函数

修改：

- 将 `launch_claude_per_device` 改为 runner-neutral 的命名
- 将硬编码 `claude` 命令替换为按 runner 动态构造
- 确保最终 prompt 在 case 数据前包含共享执行上下文
- 将所有 `/tmp/claude_<udid>.log` 引用改为新的中性日志路径

保持不变：

- prompt 的核心 case 数据结构
- 子进程生命周期监控
- JSONL 增量结果读取规则
- 报告与 finalize 收尾逻辑

### `scripts/tests/test_orchestrate.py`

新增测试覆盖：

- 默认命令走 `codex`
- `ORCH_AGENT_CLI=claude` 时切换为 `claude`
- Codex 命令构造不依赖 `--add-dir`
- Claude 命令构造仍保留 skill 目录注入
- 共享执行上下文会进入 prompt
- 日志路径使用 `/tmp/agent_<udid>.log`

这些测试应 patch `subprocess.Popen`，只验证命令构造、prompt 注入和日志路由，不真实拉起 CLI。

### `README.md`

补充执行器环境变量说明，明确：

- 默认 runner 为 `codex`
- 如何显式切到 `claude`
- 两种 runner 在“skill 注入”上的差异

### `deploy/launchd/com.gaotu.appium-matrix.webhook.plist`

显式配置 `ORCH_AGENT_CLI=codex`，虽然代码默认也是 `codex`，但托管环境里写清楚更利于排障和交接。

## 错误处理

不支持的 runner 名称不能静默失败，必须在启动设备子进程前抛出清晰错误，并列出支持值。

这样可以把配置错误暴露在最靠前的位置，而不是等到后面以“命令不存在”或“无结果退出”的形式间接暴露。

## 测试策略

采用聚焦的单元测试，覆盖命令选择与上下文注入行为。

至少包括：

1. 未设置环境变量时，默认构造 `codex` 命令。
2. `ORCH_AGENT_CLI=claude` 时，构造 `claude` 命令。
3. Codex 的 prompt 中包含共享执行上下文。
4. Claude 启动命令仍包含 app skill 目录与 `common/` 注入。
5. 非法 runner 值会抛出明确异常。
6. 日志路径为 `/tmp/agent_<udid>.log`。

这次改动不要求补端到端测试，因为行为面有意限制在执行器选择、prompt 拼装和日志命名三件事上。

## 发布与回滚

1. 落地代码，默认 runner 设为 `codex`。
2. 更新 launchd 环境变量为 `ORCH_AGENT_CLI=codex`。
3. 重启 webhook 服务。
4. 用单设备做一次 Codex runner 的 smoke test。
5. 若出现问题，可将环境变量切回 `claude` 后重启，无需再次改代码。

## 风险

- Codex CLI 的参数形态可能与 Claude 不完全一致，必须在测试或本地 smoke check 中确认。
- 日志文件改名会影响崩溃 tail 逻辑，所有旧路径引用必须一起替换。
- 如果共享执行上下文遗漏了当前 Claude skill 流程中的关键规则，Codex 的执行行为可能与 Claude 漂移。因此这份共享上下文必须覆盖“最小但必要”的规则，并保持易于补充。
- 旧运行残留的 `/tmp/claude_<udid>.log` 依然会存在，但不会影响新执行流程。
