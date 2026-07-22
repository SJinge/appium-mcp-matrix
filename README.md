# appium-mcp-matrix

> 基于 **Claude Code + Appium MCP** 的高途矩阵 6 款 App 移动端 AI 驱动自动化测试框架，支持 Android / iOS 双端，用例来源覆盖搬山平台、自然语言、飞书多维表格，测试结果自动回写 Bitable 并推送飞书 Wiki 报告。

---

## 功能特性

- **AI 视觉元素定位**：优先截图 + `ai_instruction` 自然语言描述定位，三级降级（AI → resource-id/xpath → 坐标兜底），无惧页面结构变化
- **三路用例接入**：搬山 caseId 节点树解析 / 自然语言步骤 / 飞书 Bitable 表格，统一转为 `ACTION / ASSERT / PRECOND` 步骤列表
- **多设备并行执行**：Bitable 路径按设备字段自动拆分执行条目，每台设备派发独立 subagent 并行跑，完成后按平台合并为 Android / iOS 两份报告
- **执行计划优化（预扫描）**：多条用例自动按账号聚合排序，减少登录切换和 App 重启次数
- **App 安装/卸载**：支持 Appium MCP 安装指定版本 APK，卸载重装后自动处理首次启动弹窗序列
- **6 App 公共模块复用**：登录、弹窗处理、权限授权、截图等策略集中维护，各 App skill 只管差异
- **结果闭环**：截图并行上传飞书 → 按平台写入独立结果表（iOS / Android 各一张，batch_create）→ Wiki 报告生成 → IM 群通知
- **Android / iOS 双端支持**：capabilities 模板、权限预授权（含 Android 13+ 适配）、WDA 启动均已抽象为公共规范

---

## 技术栈 / 环境依赖

| 组件 | 版本要求 | 用途 |
|------|---------|------|
| Claude Code CLI | 最新版 | AI 驱动执行引擎 |
| appium-mcp | 已 npm 全局安装 | Appium MCP Server |
| Appium | ≥ 2.x | 移动端自动化核心 |
| appium-uiautomator2-driver | 最新版 | Android 驱动 |
| appium-xcuitest-driver | 最新版 | iOS 驱动 |
| Android SDK / adb | 已配置环境变量 | Android 设备通信 |
| tidevice | ≥ 0.9 | iOS 真机管理 |
| Python 3 | ≥ 3.8 | 报告脚本（仅用标准库） |
| macOS sips | 系统内置 | 横屏截图旋转 |
| 飞书应用机器人 | — | Bitable 回写、Wiki 报告、IM 通知（可选） |

---

## 安装部署步骤

### 1. 安装 Appium 及驱动

```bash
npm install -g appium
appium driver install uiautomator2
appium driver install xcuitest
```

### 2. 安装 appium-mcp

```bash
npm install -g appium-mcp
```

### 3. 配置 Claude Code MCP

在 Claude Code **全局**设置（`~/.claude/settings.json`）中注册两个 MCP Server：

```json
{
  "mcpServers": {
    "appium-mcp": {
      "command": "appium-mcp",
      "args": [],
      "env": {
        "NO_UI": "true",
        "SCREENSHOT_QUALITY": "50",
        "CACHE_TTL": "300000",
        "LOG_LEVEL": "warn",
        "ANDROID_HOME": "/your/local/android/sdk",
        "AI_VISION_API_KEY": "your-api-key",
        "AI_VISION_API_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "AI_VISION_MODEL": "qwen3-vl-235b-a22b-instruct"
      }
    },
    "feishu": {
      "command": "npx",
      "args": ["-y", "@larksuiteoapi/lark-mcp", "mcp"],
      "env": {
        "APP_ID": "your-feishu-app-id",
        "APP_SECRET": "your-feishu-app-secret"
      }
    }
  }
}
```

> 注意：是 `~/.claude/settings.json`（用户全局），不是项目目录下的 `.claude/settings.json`。

**关键字段说明：**

| 字段 | 所属 | 说明 |
|------|------|------|
| `ANDROID_HOME` | appium-mcp | 本地 Android SDK 路径，如 `/Users/yourname/Library/Android/sdk` |
| `AI_VISION_API_KEY` | appium-mcp | AI 视觉模型 API Key，不配则 AI 视觉定位退化为 xpath/resource-id |
| `AI_VISION_API_BASE_URL` | appium-mcp | 视觉模型接口地址 |
| `AI_VISION_MODEL` | appium-mcp | 视觉模型名称，默认 `qwen3-vl-235b-a22b-instruct` |
| `APP_ID` / `APP_SECRET` | feishu | 飞书机器人凭证，**与下方第 5 步中三处填写的是同一套值** |

### 4. 克隆项目

```bash
git clone <repo-url> appium-mcp-matrix
cd appium-mcp-matrix
```

### 5. 配置飞书凭证（可选，报告推送用）

飞书机器人的 `APP_ID` / `APP_SECRET` 在项目中有三处引用，填同一套值：

**① 编辑 `scripts/feishu_config.py`**（供 `wiki_report.py` 创建 Wiki、发送群消息）：

```python
APP_ID        = "your-feishu-app-id"
APP_SECRET    = "your-feishu-app-secret"
SPACE_ID      = "..."   # Wiki 空间 ID，联系团队获取
PARENT_NODE   = "..."   # Wiki 父节点 token，联系团队获取
GROUP_CHAT_ID = "..."   # 通知群 chat_id，联系团队获取
```

**② 设置环境变量**（供 `upload_screenshots.sh` 上传截图到 Bitable），建议写入 `~/.zshrc`：

```bash
export FEISHU_APP_ID="your-feishu-app-id"
export FEISHU_APP_SECRET="your-feishu-app-secret"
```

**③ MCP 配置中的 `APP_ID` / `APP_SECRET`**（第 3 步已填，无需重复操作）。

### 6. Android 设备准备

```bash
# 确认设备连接
adb devices
# 预期输出：<udid>  device

# 确认驱动就绪
appium driver list --installed
```

### 7. iOS 设备准备

```bash
# 真机
tidevice list

# 模拟器：在 Claude Code 中调用
# appium_skills platform=ios driver=xcuitest → prepare_ios_simulator
```

---

## 使用教程 / 快速上手

### 触发执行

手工调试时，可在 Claude Code 项目目录中输入 `/gaotu` 触发 skill，再输入用例指令：

**方式 A：搬山 caseId**

```
执行高途用例 caseId=12345，Android 设备 ce67d979
```

**方式 B：自然语言步骤**

```
高途用例：
1. 进入上课 tab
2. 点击我的课程
3. 预期：课程列表正常展示
```

**方式 C：飞书 Bitable 链接（支持多设备并行）**

```
执行飞书表格用例：https://xxx.feishu.cn/wiki/xxxxx?table=tblxxxxxxxx
```

> `/gaotu` 主要用于手工调试/探索。当前自动执行主链路是：webhook → `scripts/orchestrate.py` → `codex`/`claude` subagent。自动编排不依赖手工输入 slash skill。

Bitable 表格中每条用例当前依赖以下字段参与自动编排：
- `编号`：执行顺序主键；拉回后按 `编号` 稳定排序
- `所属页面`：执行展示/报告中的页面归属
- `状态组`：设备内切批主键之一
- `android执行设备` / `ios执行设备`：按设备拆分执行条目

多台设备并行跑，最终生成 Android 和 iOS 两份独立报告。

### 执行流程概览

**顺序执行（路径 A / B）：**

```
第零步  解析用例 & 确认步骤列表（≥2条时执行预扫描排序）
  ↓
设备就绪检查（adb devices / tidevice list）
  ↓
第一步  adb 预授权权限（麦克风/摄像头，Android 13+ 适配存储权限）
  ↓
第二步  创建 Appium Session
  ↓
第三步  重启 App（首次安装后处理协议/青少年守护弹窗）
  ↓
第四步  检测登录状态 → 按需登录（密码登录，自动检测当前页面）
  ↓
第五步  批量关闭登录后弹窗（最多 5 轮）
  ↓
第六步  记录执行起点 & 创建截图目录
  ↓
第七步  循环执行 PRECOND → ACTION → ASSERT 步骤
  ↓
第八步  清理收尾 → 执行报告 → Bitable 回写 → Wiki 推送
```

**并行执行（路径 C Bitable）：**

```
第零步  解析 Bitable → 生成 EXECUTION_ENTRIES（按设备拆分）
  ↓
按 `编号` 全局排序 → 按 device 字段分组
  ↓
每台设备内按 `(状态组, 账号)` 切批
  说明：`状态组=启动弹窗` 为特例，每条用例单独一批、逐条重装恢复首启态
  ↓
每台设备派发一个 subagent（同时启动）
  ↓
各 subagent 独立完成第一~第八步 → 每跑完一条即增量 append 到 /tmp/result_<udid>.jsonl（JSONL，抗中途崩溃）
  ↓
主 agent 轮询等待所有 subagent 完成
  ↓
按平台合并 → batch_create 到 iOS/Android 独立结果表 → Android 报告 + iOS 报告（wiki_report.py × 2）
```

### 执行器配置（webhook / orchestrate）

并行执行时，单设备 subagent 的 CLI runner 由环境变量 `ORCH_AGENT_CLI` 控制：

- `codex`：默认值；不依赖 Claude 的 `--add-dir`，由 orchestrator 在 prompt 中注入共享执行上下文；同时会显式关闭 `feishu` / `feishu-docx-blocks` / `Banshan` 等无关 MCP，仅保留执行必需的 `appium-mcp`
- `claude`：保留现有 `.claude/skills/<app>` + `common/` 注入方式

单设备执行日志统一写到 `/tmp/agent_<udid>.log`，供 orchestrator 崩溃 tail 与排障复用。

当前设备内真实分批规则：
- 先按 `编号` 稳定排序
- 再按 `(状态组, 账号)` 切批
- 同一 `(状态组, 账号)` 桶内继续按 `BATCH_SIZE=20` 限制拆分
- `状态组=启动弹窗` 不承接现场，强制每条单独一批

### 常用参数默认值（高途 App）

| 参数 | 默认值 |
|------|--------|
| Android device | `ce67d979` |
| packageName | `com.gaotu100.superclass` |
| phone | `12100000000` |
| password | `Gaotu@1234` |

> 需要修改默认值时，编辑 `.claude/skills/gaotu/SKILL.md` 顶部的参数表格。

---

## 目录结构

```
appium-mcp-matrix/
├── CLAUDE.md                          # Claude Code 项目指令（上下文规则）
│
├── common/                            # 跨 App 公共模块
│   ├── elements/
│   │   ├── login.md                   # 登录页公共元素（{pkg} 占位符）
│   │   └── dialog.md                  # 通用弹窗元素
│   ├── app.md                         # App 安装/卸载流程
│   ├── device.md                      # 设备就绪检查 & Session capabilities 模板
│   ├── login.md                       # 通用登录 skill（验证码/密码）
│   ├── parallel.md                    # 多设备并行执行 & 报告合并
│   ├── parsing.md                     # 用例解析规则（搬山/自然语言/Bitable）
│   ├── permission.md                  # Android adb 权限预授权（含 Android 13+ 适配）
│   ├── prescan.md                     # 多用例预扫描 & 执行计划优化
│   ├── screenshot.md                  # 截图规范、等待策略、弹窗处理循环
│   └── startup.md                     # 首次启动弹窗说明（各 App 见对应 skill 目录）
│
├── .claude/skills/
│   ├── appium-expert/
│   │   └── SKILL.md                   # Appium 通用排障（设备/Session/元素定位/MCP）
│   └── gaotu/
│       ├── SKILL.md                   # 高途完整执行流程（第零~第八步）
│       ├── elements.md                # 高途专属元素定位 & AI 视觉规范
│       └── startup.md                 # 高途首次启动弹窗序列（协议 → 青少年守护）
│
└── scripts/
    ├── feishu_config.py               # 飞书应用凭证常量（APP_ID/APP_SECRET/SPACE_ID 等）
    ├── upload_screenshots.sh          # 截图并行上传飞书 Bitable
    └── wiki_report.py                 # 生成 Wiki 报告 & 发送群通知（支持多设备汇总表）
```

### 新增 App 的扩展方式

1. 在 `.claude/skills/` 下新建目录，如 `.claude/skills/tutu/`
2. 复制 `.claude/skills/gaotu/SKILL.md` 并修改包名、默认参数
3. 新建 `.claude/skills/tutu/elements.md` 补充该 App 专属元素
4. 如有首次启动弹窗，新建 `.claude/skills/tutu/startup.md`
5. 在 Claude Code 中输入 `/tutu` 触发

---

## 支持的 App

| app_id | App 名称 | Android packageName |
|--------|---------|---------------------|
| gaotu | 高途 | `com.gaotu100.superclass` |
| tutu | 途途课堂 | `com.gaotu100.tutu` |
| jingpin | 高途高中 | `com.gaotu100.jingpin` |
| gongkao | 高途公职 | `com.gaotu100.gongkao` |
| xinli | 高途心理 | `com.gaotu100.xinli` |
| ketang | 高途素养 | `com.gaotu100.ketang` |

---

## 常见问题 FAQ

**Q: `adb devices` 显示 `unauthorized`，无法连接设备？**

在 Android 设备上点击"允许 USB 调试"弹窗，或在开发者选项中撤销 USB 调试授权后重新授权。

---

**Q: Session 创建失败，报 UiAutomator2 安装超时？**

手动推送 APK 后重试：

```bash
APK_DIR=/opt/homebrew/lib/node_modules/appium-mcp/node_modules/appium-uiautomator2-driver/node_modules/appium-uiautomator2-server/apks
adb -s <device> install -r $APK_DIR/appium-uiautomator2-server-v9.11.1.apk
adb -s <device> install -r $APK_DIR/appium-uiautomator2-server-debug-androidTest.apk
```

---

**Q: 登录页截图全黑，看不到任何内容？**

页面跳转过渡帧导致的时序问题（非 `FLAG_SECURE`）。解决方法：等待 1s 后重试截图，通常即可恢复；确实拍到黑帧时改用 `appium_get_page_source` + `resource-id` 定位元素。

---

**Q: 截图分辨率过高导致报错？**

所有 `appium_screenshot` 调用必须加 `maxWidth=800` 参数：

```
appium_screenshot maxWidth=800
```

Android/iOS 高分辨率设备原图超 2000px 会触发 Claude 多图限制。

---

**Q: 单次对话截图超过 10 张怎么处理？**

新开一个 Claude Code 对话，将以下上下文带入继续：当前设备 UDID、包名、已执行步骤编号、剩余步骤列表。

---

**Q: AI 视觉定位失败，元素找不到？**

按三级降级策略处理：
1. 优化 `ai_instruction` 描述，确保包含**外观 + 位置 + 上下文**三要素
2. 降级到 `xpath=//*[@text='目标文字']` 或 `resource-id`
3. 最终兜底：使用已知固定布局坐标（需记录日志说明）

---

**Q: 直播教室截图内容横躺，方向不对？**

进入教室后 App 自动横屏，截图需旋转 90°：

```bash
sips -r 90 /path/to/screenshot.png
```

---

**Q: 并行执行时，主 agent 如何知道所有设备跑完了？**

每个设备 subagent 每跑完一条用例即增量 append 到 `/tmp/result_<udid>.jsonl`（JSONL，一行一条）。文件从首条起就存在，故判完成不靠"文件是否存在"，而以进程退出为准（见 `orchestrate.py:collect_results`）：进程退出后读回已落盘的行——即使中途 429/崩溃，已跑完的用例也照常合并进报告与结果表。详见 `common/parallel.md`。

---

**Q: 执行结果写到哪里，如何与原用例表区分？**

执行结果不回写原用例表，而是按平台写入两张独立结果表（batch_create，每次执行追加新记录）：

| 平台 | 结果表 |
|------|--------|
| iOS | `tblryYA67UjkVGwx`（app_token: `C6X8wCdSLiAd9IkXtNFc6yO2nXg`） |
| Android | `tblUEp8pt5W9Cic5`（同上 app_token） |

每条记录写入：`用例名称` / `执行结果` / `执行详情` / `截图`。

---

**Q: 如何跳过 Bitable 回写，只看本地报告？**

不传飞书 Bitable 链接（使用路径 A 或路径 B 接入用例），第八步会跳过回写，仅输出终端执行报告和本地截图目录 `~/mcp_shots/`。
