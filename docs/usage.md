# 高途矩阵 Appium-MCP 自动化使用说明

本文档说明当前项目如何部署、触发、观测和排障。项目主链路为：

```text
轻舟触发打包 -> webhook 接收 -> 后台拉起 orchestrate -> 下载/安装 -> 设备准备 -> 读取 Bitable 用例 -> 多设备执行 -> 写结果表 -> 生成 Wiki 报告 -> 飞书群通知
```

## 1. 项目范围

本项目用于高途矩阵 App 的 Android / iOS 自动化回归，当前支持以下 app_id：

| app_id | App 名称 | Android packageName |
| --- | --- | --- |
| gaotu | 高途 | com.gaotu100.superclass |
| tutu | 途途课堂 | com.gaotu100.tutu |
| jingpin | 高途高中 | com.gaotu100.jingpin |
| gongkao | 高途公职 | com.gaotu100.gongkao |
| xinli | 高途心理 | com.gaotu100.xinli |
| ketang | 高途素养 | com.gaotu100.ketang |

当前 webhook 执行白名单由 `ENABLED_APPS` 控制，默认只自动执行 `gaotu`。其他 App 的打包消息可以被解析，但不会自动拉起执行。

## 2. 主要目录

| 路径 | 说明 |
| --- | --- |
| `server/app.py` | Flask webhook 服务，接收轻舟/飞书消息，解析 app、端、版本、下载地址，并按白名单和幂等规则触发执行 |
| `scripts/orchestrate.py` | 主编排入口，负责下载、安装、WDA、读取用例、拆批、执行、回写和报告 |
| `scripts/orch_execution.py` | 子进程执行、批次结果 JSONL、固化脚本和 agent 回退调度 |
| `scripts/orch_result_table.py` | 结果表写入逻辑 |
| `scripts/orch_reporting.py` | 汇总结果、生成 Wiki 报告、发送通知 |
| `scripts/run_status.py` | 运行状态读写，供 `/status` 查询 |
| `config/devices.yaml` | Android / iOS 设备清单和 iOS WDA 配置 |
| `common/` | 公共登录、弹窗、设备、截图、定位规范 |
| `apps/<app_id>/cases/` | 已固化的用例脚本 |
| `logs/` | 运行日志，已 gitignore |
| `runs/` | 运行状态文件，已 gitignore |

## 3. 前置环境

### 3.1 通用依赖

- macOS
- Python 3
- Git
- Appium 2.x
- `appium-mcp`
- Android SDK / adb
- iOS 真机执行需要 Xcode、tidevice、xcuitest driver、WDA 签名环境
- Codex CLI 或 Claude CLI，用作 agent 回退执行器

### 3.2 Appium 驱动

```bash
appium driver list --installed
```

需要至少包含：

- Android：`uiautomator2`
- iOS：`xcuitest`

缺少时安装：

```bash
appium driver install uiautomator2
appium driver install xcuitest
```

### 3.3 Android 设备

```bash
adb devices
```

预期设备状态为 `device`。如果是 `unauthorized`，需要在手机上允许 USB 调试。

### 3.4 iOS 设备

```bash
tidevice list
xcrun xctrace list devices
```

iOS 真机执行前需要确认：

- 手机保持解锁
- 开启 Developer Mode
- Xcode 能识别并完成配对
- `设置 -> 通用 -> VPN 与设备管理` 中信任 WDA 使用的 Apple Development 证书
- tunneld 守护已启动
- WDA 能 ready

当前项目会在安装 iOS 包后检查 WDA 和网络权限；WDA 未 ready 时会跳过该设备，不写结果表。

## 4. 配置说明

### 4.1 设备配置

设备清单在 `config/devices.yaml`：

```yaml
default:
  android:
    - udid: "26KUT24202013751"
      name: "华为 ADA-AL00"
  ios:
    - udid: "00008101-001E28D436E0001E"
      name: "iPhone"
      wda:
        team: "5YX44746D6"
        bundle_id: "com.shijinge.WebDriverAgentRunner"
        port: 8100
```

每个 App 可单独覆盖设备配置；没有覆盖时使用 `default`。

### 4.2 飞书和 Bitable 配置

飞书配置在 `scripts/feishu_config.py`，主要包括：

- 飞书应用 `APP_ID` / `APP_SECRET`
- Wiki 空间和父节点
- 群通知 `GROUP_CHAT_ID`
- 用例表 `BITABLE_CONFIGS`
- 结果表 `RESULT_TABLES`

当前执行结果写入独立结果表，不回写原用例表。

结果表由 `RESULT_TABLES` 按平台区分：

```python
RESULT_TABLES = {
    "gaotu": {
        "app_token": "...",
        "obj_token": "...",
        "android": "tbl...",
        "ios": "tbl...",
    },
}
```

### 4.3 webhook 白名单

`ENABLED_APPS` 表示允许自动执行的 App 白名单，默认值为 `gaotu`。

示例：

```bash
ENABLED_APPS=gaotu,tutu
```

如果收到的打包消息不在白名单内，webhook 只记录日志并跳过，不会启动 orchestrate。

### 4.4 agent 执行器

`orchestrate` 会在需要 agent 回退时自动拉起子进程，不需要人工手动开 Codex 会话。

可通过环境变量选择执行器：

```bash
ORCH_AGENT_CLI=codex
```

可选值：

| 值 | 说明 |
| --- | --- |
| `codex` | 默认值，使用 `codex exec --dangerously-bypass-approvals-and-sandbox ... <prompt>` 无人值守执行 |
| `claude` | 使用 `claude --print <prompt>` 执行 |

如果换电脑后子进程每次都反问，通常是该机器上的 CLI 权限、MCP 配置或无人值守参数没有生效；本项目生产链路使用 `orchestrate` 自动组装命令，不需要手工进入交互会话。

### 4.5 runner 凭据

仓库外凭据文件默认路径：

```text
~/.config/appium-matrix/runner.env
```

可通过 `ORCH_SECRETS_FILE` 覆盖。格式：

```env
ANTHROPIC_API_KEY=...
```

不要把真实凭据写进仓库。

## 5. 启动 webhook 服务

webhook 推荐使用 launchd 托管，不要手动 `flask run`。

安装：

```bash
ln -sf /Users/mac/Documents/projects/appium-mcp-matrix/deploy/launchd/com.gaotu.appium-matrix.webhook.plist \
  ~/Library/LaunchAgents/com.gaotu.appium-matrix.webhook.plist

launchctl load -w ~/Library/LaunchAgents/com.gaotu.appium-matrix.webhook.plist
```

重启：

```bash
launchctl kickstart -k gui/$(id -u)/com.gaotu.appium-matrix.webhook
```

确认存活：

```bash
curl -s localhost:10086/health
```

正常返回示例：

```json
{"status":"ok","enabled_apps":["gaotu"],"active_runs":0}
```

## 6. 自动触发执行

正常生产链路不需要手动开 Codex 或 Claude 会话：

```text
轻舟打包完成
  -> webhook 收到 template 消息
  -> 解析 appProduct / appVersion / downloadUrl
  -> 判断 ENABLED_APPS
  -> 判断是否重复触发
  -> 后台拉起 scripts/orchestrate.py
```

同一个 `app + version + platform` 默认只触发一次。幂等标记文件在 `/tmp`：

```text
/tmp/orchestrate_<app>_<version>_<platform>.triggered
```

需要重跑同一版本时，删除对应 marker 后重新触发：

```bash
rm -f /tmp/orchestrate_gaotu_5.91.92_ios.triggered
```

## 7. 手动触发执行

手动排障或本地验证时，可以直接运行 `orchestrate.py`。

Android：

```bash
python3 scripts/orchestrate.py \
  --app gaotu \
  --version 5.91.92 \
  --platform android \
  --apk-url "https://example.com/app.apk"
```

iOS：

```bash
python3 scripts/orchestrate.py \
  --app gaotu \
  --version 5.91.92 \
  --platform ios \
  --ipa-url "https://example.com/app.ipa"
```

如果不传 `--platform`，则按提供的 `--apk-url` / `--ipa-url` 决定执行哪些端。

## 8. 执行流程

### 8.1 主流程

```text
下载或复用安装包
  -> 安装到设备
  -> Android 设备准备 / iOS WDA 和网络权限准备
  -> 过滤出可执行设备
  -> Android 新版本探索建图
  -> 拉取 Bitable 用例
  -> 按设备拆分
  -> 按状态组和账号切批
  -> 每设备每批执行
  -> 增量写入 JSONL
  -> 增量写结果表
  -> 汇总多设备结果
  -> 生成 Wiki 报告
  -> 发送飞书群通知
  -> 标记执行完成
```

### 8.2 用例拆分规则

Bitable 用例读取后会先按 `编号` 稳定排序。

主要参与编排的字段：

| 字段 | 用途 |
| --- | --- |
| `编号` | 全局排序 |
| `所属页面` | 页面归属和报告展示 |
| `状态组` | 切批依据 |
| `android执行设备` | Android 设备分配 |
| `ios执行设备` | iOS 设备分配 |

设备内切批规则：

- 按 `(状态组, 账号)` 切批
- 同一桶内继续受 `BATCH_SIZE=20` 限制
- `状态组=启动弹窗` 为特例：每条用例单独一批，并逐条重装恢复首启态

### 8.3 固化脚本和 agent 回退

每条用例执行时优先使用固化脚本：

```text
有固化脚本 -> 运行固化脚本 -> 生成结果
无固化脚本或脚本不可用 -> 启动 Codex/Claude 子进程执行 -> 生成结果
```

子进程执行过程中，每跑完一条用例必须立即 append 到 JSONL，避免中途崩溃导致结果丢失。

## 9. 结果产物

### 9.1 运行状态

运行状态写入：

```text
runs/<run_id>.json
runs/history.jsonl
```

`run_id` 格式：

```text
<app>_<version>_<platform>
```

示例：

```text
gaotu_5.91.92_ios
```

### 9.2 日志

| 日志 | 说明 |
| --- | --- |
| `logs/webhook.log` | webhook 收到消息、解析、白名单、幂等触发 |
| `logs/orchestrate.log` | 主编排日志 |
| `/tmp/orchestrate_<app>_<version>_<platform>.log` | 某次后台执行的 stdout/stderr |
| `/tmp/agent_<udid>.log` | 单设备 agent 执行日志 |
| `/tmp/wda_build_<udid>.log` | iOS WDA 构建/启动日志 |
| `/tmp/wda_proxy_<udid>.log` | iOS WDA proxy 日志 |

### 9.3 JSONL 结果

执行结果按设备增量写入：

```text
/tmp/result_<udid>.jsonl
/tmp/batch_results/batch_<udid>_<batch_idx>/result_<udid>.jsonl
```

### 9.4 结果表

执行完成或批次完成后，结果写入配置的 Android / iOS 结果表。当前写入逻辑会按已有字段写入，不需要在文档或流程图中展开所有字段。

当前常见写入内容包括：

- 编号
- 执行版本
- 执行时间
- 状态组
- 执行设备
- 用例名称
- 执行结果
- 执行详情
- 截图

## 10. 观测命令

查看 webhook 存活：

```bash
curl -s localhost:10086/health
```

查看全部运行状态：

```bash
curl -s localhost:10086/status
```

查看指定 run：

```bash
curl -s "localhost:10086/status?run_id=gaotu_5.91.92_ios"
```

看 webhook 日志：

```bash
tail -f logs/webhook.log
```

看主编排日志：

```bash
tail -f logs/orchestrate.log
```

看单次后台执行日志：

```bash
tail -f /tmp/orchestrate_gaotu_5.91.92_ios.log
```

看单设备 agent 日志：

```bash
tail -f /tmp/agent_00008101-001E28D436E0001E.log
```

## 11. 常见问题

### 11.1 为什么触发轻舟后没有执行？

优先检查：

```bash
curl -s localhost:10086/health
tail -f logs/webhook.log
```

常见原因：

- webhook 没启动
- 端口不是 `10086`
- app 不在 `ENABLED_APPS`
- 同版本同端已经触发过，marker 文件存在
- 轻舟消息里缺少版本号或下载地址

### 11.2 为什么同一个版本不能再次触发？

因为 webhook 有幂等保护。同一个 `app + version + platform` 只触发一次。

删除对应 marker 后可以重跑：

```bash
rm -f /tmp/orchestrate_gaotu_5.91.92_ios.triggered
```

### 11.3 iOS WDA 没 ready 会怎样？

该设备会被跳过，并发送环境阻断通知，不写结果表。

如果所有设备都失败，整次 run 标记为 failed。

### 11.4 iOS WDA 不可用怎么排？

检查：

```bash
tidevice list
xcrun xctrace list devices
curl -s http://127.0.0.1:49151/
tail -f /tmp/wda_build_<udid>.log
tail -f /tmp/wda_proxy_<udid>.log
```

重点看：

- 手机是否解锁
- Developer Mode 是否开启
- Xcode 是否已配对
- `VPN 与设备管理` 是否信任 WDA 的 Apple Development 证书
- WDA 是否真的在设备侧监听 8100/8101

如果 tunnel registry 能看到设备，但 proxy 反复报 `Connection refused`，通常说明设备侧 WDA Runner 没有真正监听，不是 Mac 到手机网络不通。

### 11.5 换电脑后子进程每次都反问是什么原因？

通常是新电脑上的 CLI 没有处于无人值守可执行状态，例如：

- `codex exec` 版本或参数不一致
- MCP 配置缺失或权限策略不同
- 没有使用 `--dangerously-bypass-approvals-and-sandbox`
- 运行环境没有继承正确 PATH 或凭据
- Claude/Codex 登录态或 API key 配置不同

生产链路中不要手动开 Codex 会话；由 `orchestrate` 自动拉起子进程。

### 11.6 结果表字段改了怎么办？

字段回写逻辑在 `scripts/orch_result_table.py`。如果结果表新增字段，需要在该文件中补充写入字段，并为对应逻辑添加测试。

近期已支持：

- `执行版本`
- `执行时间`

## 12. 换电脑部署检查清单

换电脑执行前按下面顺序检查：

- 拉取最新代码
- 安装 Python 依赖和 Appium 驱动
- 安装并配置 `appium-mcp`
- 配置 Codex 或 Claude CLI
- 配置 `~/.config/appium-matrix/runner.env`
- 检查 `deploy/launchd/*.plist` 里的绝对路径
- 启动 webhook launchd
- 确认 `curl -s localhost:10086/health` 正常
- 确认 `ENABLED_APPS` 符合预期
- Android 执行前确认 `adb devices`
- iOS 执行前确认 tidevice、Xcode 配对、Developer Mode、证书信任、tunneld、WDA
- 检查 `config/devices.yaml` 里的设备 UDID 和 WDA 端口
- 手动跑一次 `/status` 和日志 tail，确认观测链路可用

## 13. 推荐日常操作顺序

日常发版回归：

```text
1. 确认 webhook 存活
2. 确认设备在线
3. 在轻舟触发打包
4. 观察 logs/webhook.log 是否收到消息
5. 观察 logs/orchestrate.log 和 /status
6. 等待结果表和 Wiki 报告
7. 如果失败，根据 /status phase 和日志定位是下载、安装、WDA、用例读取还是执行问题
```

手动排障：

```text
1. 明确 run_id
2. 查 /status
3. 查 logs/orchestrate.log
4. 查 /tmp/orchestrate_<run_id>.log
5. 查对应 /tmp/agent_<udid>.log
6. iOS 问题再查 WDA build/proxy 日志
7. 只在确认需要重跑时删除 .triggered marker
```
