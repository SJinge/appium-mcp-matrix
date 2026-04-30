# 高途矩阵 Appium-MCP 自动化测试框架 — 项目实施方案

**文档版本：** v1.0  
**编制日期：** 2026-04-30  
**项目目录：** `appium-mcp-matrix`

---

## 一、项目背景

高途集团旗下共有 6 款面向不同用户群体的矩阵 App（高途、途途课堂、高途高中、高途公职、高途心理、高途素养）。各 App 在功能模块、UI 交互、直播课堂等核心场景需要持续的质量验证。

传统自动化测试方案依赖固定脚本，面临以下痛点：

1. **维护成本高**：页面结构每次迭代后 xpath/resource-id 失效，需逐一修复脚本。
2. **多 App 重复建设**：6 款 App 的登录、弹窗、权限等逻辑高度相似，缺乏统一抽象。
3. **用例接入门槛高**：测试人员需要编写代码才能接入用例，无法直接复用已有文档或测试管理系统的用例。
4. **结果闭环缺失**：执行截图、测试结论需人工整理上传，效率低下。

本项目以 **Claude Code + Appium MCP** 为核心，构建 AI 驱动的移动端自动化测试框架，解决上述问题。

---

## 二、项目目标

| 目标 | 验收标准 |
|------|---------|
| 支持 6 款矩阵 App 的自动化测试 | 各 App 均有独立 skill 及元素库，可独立执行 |
| 支持 Android / iOS 双端 | capabilities 模板、驱动、权限策略均已覆盖双端 |
| 多路用例接入 | 搬山 caseId / 自然语言 / 飞书 Bitable 三路均可触发执行 |
| AI 视觉元素定位，降低维护成本 | 首选截图 + ai\_instruction，三级降级兜底，不依赖固定脚本 |
| 测试结果自动闭环 | 截图上传飞书 → Bitable 三字段回写 → Wiki 报告生成 → 群通知 |
| 前置流程 60 秒内完成 | 权限授权 → Session → 登录 → 弹窗 → 导航全流程目标 ≤60s |

---

## 三、已实现功能清单

### 3.1 公共模块（`common/`）

| 模块 | 文件 | 功能 |
|------|------|------|
| 设备就绪检查 | `common/device.md` | Android adb 检查 / iOS tidevice 检查；Session capabilities 模板（双端） |
| 通用登录 | `common/login.md` | 验证码登录、密码登录、微信登录；双端元素定位；协议勾选、广告弹窗处理 |
| 用例解析 | `common/parsing.md` | 路径A 搬山 caseId 节点树解析；路径B 自然语言切分；路径C 飞书 Bitable 完整字段解析（预置条件/测试步骤/验证点/预期结果/设备字段） |
| 截图与等待 | `common/screenshot.md` | maxWidth=800 统一规范；分步骤类型保存策略；轮询等待替代固定 sleep；弹窗处理循环（最多5轮）；AI 视觉定位规范 |
| 权限预授权 | `common/permission.md` | Android adb 批量授权麦克风/摄像头/存储；iOS autoAcceptAlerts 处理 |
| 公共元素库 | `common/elements/login.md` | 登录页 Android resource-id 映射（含 {pkg} 占位符，6 App 通用） |
| 公共元素库 | `common/elements/dialog.md` | 通用弹窗元素定位 |

### 3.2 App 专用 Skill（`.claude/skills/`）

| App | SKILL.md | elements.md | 状态 |
|-----|----------|-------------|------|
| 高途（gaotu） | 完整 8 步执行流程 | 完整（含 AI视觉高频元素、底部导航、上课/闪学/首页/直播/消息/我的/搜索各页面） | **完整实现** |
| 途途课堂（tutu） | 已创建 | 已创建 | 框架就绪 |
| 高途高中（jingpin） | 已创建 | 已创建 | 框架就绪 |
| 高途公职（gongkao） | 已创建 | 已创建 | 框架就绪 |
| 高途心理（xinli） | 已创建 | 已创建 | 框架就绪 |
| 高途素养（ketang） | 已创建 | 已创建 | 框架就绪 |
| Appium 排障专家 | appium-expert/SKILL.md | — | **完整实现** |

### 3.3 高途 App 执行流程（8步闭环）

| 步骤 | 内容 |
|------|------|
| 第零步 | 用例来源确认 → 三路解析 → TARGET_PAGE 分析 → 展示步骤列表等用户确认 |
| 设备检查 | adb devices / tidevice list → 驱动验证 → APK 检查 |
| 第一步 | adb 批量权限预授权（Android）|
| 第二步 | 创建 Appium Session（双端 capabilities）|
| 第三步 | 重启 App（force-stop → am start / terminate → activate）|
| 第四步 | 检测登录状态 → 按需执行密码登录 |
| 第五步 | 批量关闭登录后弹窗（协议/青少年模式/广告/身份问卷）最多 5 轮 |
| 第六步 | 根据 TARGET_PAGE 自动导航（上课/AI闪学/首页/我的/搜索）|
| 第七步 | 循环执行 PRECOND → ACTION → ASSERT；静默执行，汇总至 CASES_JSON |
| 第八步 | 退出教室 → 关闭 Session → 输出报告 → Bitable 回写 → Wiki 推送 → IM 通知 |

### 3.4 报告与结果闭环脚本（`scripts/`）

| 脚本 | 功能 |
|------|------|
| `wiki_report.py` | 在飞书 Wiki 指定空间创建报告文档（标题/执行信息/用例步骤表格/ASSERT验证说明/汇总表）；发送 IM 群通知；支持表格模式（CASES_JSON）和纯文本兼容模式 |
| `upload_screenshots.sh` | 批量上传本地截图目录至飞书多维表格，返回 file_token 数组供 Bitable 回写 |
| `feishu_config.py` | 飞书凭证常量集中管理（APP_ID / APP_SECRET / SPACE_ID / PARENT_NODE / GROUP_CHAT_ID）|

### 3.5 上下文管理与 token 优化

- 截图分流：AI视觉定位截图不进入 Claude 上下文，ASSERT 截图用后即丢弃
- 执行循环静默输出，中间状态不向用户输出冗余文字
- 长日志只提炼关键摘要，不完整嵌入会话

---

## 四、系统架构说明

```
┌─────────────────────────────────────────────────────────────────┐
│                        用例输入层                                 │
│   搬山 caseId │ 自然语言步骤 │ 飞书 Bitable 链接（推荐，支持回写）  │
└───────────────────────┬─────────────────────────────────────────┘
                        │ 统一解析为 PRECOND / ACTION / ASSERT 步骤列表
┌───────────────────────▼─────────────────────────────────────────┐
│                   Claude Code + Skill 执行引擎                    │
│                                                                   │
│  ┌──────────────────────┐   ┌─────────────────────────────────┐  │
│  │    公共模块 common/    │   │     App Skill (.claude/skills/) │  │
│  │  device / login      │   │  gaotu / tutu / jingpin / ...   │  │
│  │  parsing / screenshot│   │  SKILL.md + elements.md         │  │
│  │  permission          │   │                                 │  │
│  └──────────────────────┘   └─────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────────┘
                        │ MCP 工具调用
┌───────────────────────▼─────────────────────────────────────────┐
│                      Appium MCP Server                           │
│                                                                   │
│  appium_screenshot  appium_find_element(ai_instruction)          │
│  appium_gesture     appium_set_value    appium_get_page_source    │
│  create_session     delete_session      appium_app_lifecycle      │
└──────────┬──────────────────────────────────────┬───────────────┘
           │ Android                               │ iOS
    ┌──────▼──────┐                        ┌──────▼──────┐
    │ UiAutomator2│                        │  XCUITest   │
    │   Driver    │                        │   Driver    │
    └──────┬──────┘                        └──────┬──────┘
           │ adb                                  │ tidevice / WDA
    ┌──────▼──────┐                        ┌──────▼──────┐
    │ Android 设备 │                        │  iOS 设备    │
    └─────────────┘                        └─────────────┘

                    ┌─────────────────────────────────┐
                    │         结果输出层                │
                    │  ~/mcp_shots/ 本地截图            │
                    │  Bitable 三字段回写               │
                    │  飞书 Wiki 报告（自动创建）         │
                    │  IM 群通知                        │
                    └─────────────────────────────────┘
```

**元素定位三级降级策略：**

```
第一级  截图 + AI 视觉（ai_instruction 自然语言描述）
    ↓ 截图黑屏（FLAG_SECURE）或 AI 视觉失败
第二级  page source + resource-id / xpath / accessibility id
    ↓ 仍找不到
第三级  坐标硬点击（仅用于已知固定布局，记录日志）
```

---

## 五、技术栈

| 组件 | 版本要求 | 用途 |
|------|---------|------|
| Claude Code CLI | 最新版 | AI 驱动执行引擎，解析用例、规划步骤、调用 MCP 工具 |
| appium-mcp | npm 全局安装 | Appium MCP Server，暴露 Appium 操作为 MCP 工具 |
| Appium | ≥ 2.x | 移动端自动化核心框架 |
| appium-uiautomator2-driver | 最新版 | Android 自动化驱动 |
| appium-xcuitest-driver | 最新版 | iOS 自动化驱动 |
| Qwen3-VL（AI 视觉模型） | qwen3-vl-235b-a22b-instruct | AI 视觉元素定位，由 appium-mcp 调用阿里云 DashScope API |
| Android SDK / adb | 已配置 ANDROID_HOME | Android 设备通信、权限授权、App 启停 |
| tidevice | ≥ 0.9 | iOS 真机设备管理（推荐，免 Xcode） |
| WebDriverAgent (WDA) | 随 xcuitest 驱动 | iOS 自动化桥接层 |
| Python 3 | ≥ 3.8 | Wiki 报告脚本（仅用标准库，无第三方依赖） |
| macOS sips | 系统内置 | 直播横屏截图旋转 90° |
| 飞书开放平台 | — | Bitable 数据读写/回写、Wiki 创建、IM 消息发送（可选） |
| @larksuiteoapi/lark-mcp | npx 运行 | 飞书 MCP Server，提供飞书 API 能力 |

---

## 六、部署与运行方式

### 6.1 环境安装

```bash
# 1. 安装 Appium 及驱动
npm install -g appium
appium driver install uiautomator2
appium driver install xcuitest

# 2. 安装 appium-mcp
npm install -g appium-mcp

# 3. 确认 Android 设备就绪
adb devices        # 期望：<udid>  device

# 4. 确认 iOS 设备就绪（真机）
tidevice list
```

### 6.2 配置 Claude Code MCP

在 `~/.claude/settings.json`（用户全局）注册两个 MCP Server：

```json
{
  "mcpServers": {
    "appium-mcp": {
      "command": "appium-mcp",
      "args": [],
      "env": {
        "NO_UI": "true",
        "SCREENSHOT_QUALITY": "50",
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

### 6.3 配置飞书凭证（可选，报告推送用）

```python
# scripts/feishu_config.py
APP_ID        = "your-feishu-app-id"
APP_SECRET    = "your-feishu-app-secret"
SPACE_ID      = "..."   # Wiki 空间 ID
PARENT_NODE   = "..."   # Wiki 父节点 token
GROUP_CHAT_ID = "..."   # 通知群 chat_id
```

```bash
# ~/.zshrc — 供 upload_screenshots.sh 使用
export FEISHU_APP_ID="your-feishu-app-id"
export FEISHU_APP_SECRET="your-feishu-app-secret"
```

### 6.4 启动测试会话

**方式一（推荐）：`start.sh`**

```bash
./start.sh gaotu     # 启动高途 App 测试会话
./start.sh tutu      # 启动途途课堂测试会话
```

脚本自动将对应 App skill 目录和 `common/` 注入 Claude Code 上下文。

**方式二：slash command**

```bash
ln -s "$(pwd)/.claude/skills/gaotu" ~/.claude/skills/gaotu
# 在任意 Claude Code 会话中输入 /gaotu 触发
```

### 6.5 执行测试用例

**推荐方式：飞书 Bitable 链接**（执行结果、备注、截图自动回写至原记录）

```
执行飞书表格用例：https://xxx.feishu.cn/wiki/xxxxx?table=tblxxxxxxxx
```

其他触发方式：

```
# 搬山平台用例 ID
执行高途用例 caseId=12345，Android 设备 ce67d979

# 自然语言步骤
高途用例：
1. 进入上课 tab
2. 点击我的课程
3. 预期：课程列表正常展示
```

### 6.6 查看测试结果

| 结果类型 | 位置 |
|---------|------|
| 本地截图 | `~/mcp_shots/gaotu/YYYYMMDD_HHMM_<caseId>/` |
| 终端执行报告 | Claude Code 对话输出（第八步） |
| 飞书 Wiki 报告 | 自动创建至配置的 Wiki 空间 |
| Bitable 回写 | 原用例记录的「执行结果」/「备注/执行详情」/「截图」字段（仅飞书 Bitable 路径）|
| IM 群通知 | 配置的飞书群 |

---

## 七、项目总结

### 7.1 核心价值

本项目通过 **Claude Code + Appium MCP + AI 视觉** 的组合，将传统基于脚本的移动端自动化测试升级为 **AI 驱动的对话式自动化测试**，核心价值体现在：

1. **抗 UI 变化能力强**：AI 视觉定位首选自然语言描述元素，而非依赖 xpath 路径或 resource-id 字符串，页面迭代不影响大部分用例的执行。

2. **零代码用例接入**：测试人员可直接从搬山平台、飞书表格或自然语言触发自动化执行，无需编写任何代码。推荐使用飞书 Bitable 用例，支持执行结果、备注、截图自动回写，实现完整闭环。

3. **6 App 统一维护**：登录、弹窗、权限、截图等跨 App 通用逻辑集中于 `common/` 模块，各 App skill 只维护差异部分，扩展成本极低。

4. **结果全自动闭环**：从执行截图 → 飞书上传 → Bitable 回写 → Wiki 报告 → 群通知，全链路自动化，消除人工整理环节。

### 7.2 已知局限与后续方向

| 局限 | 说明 | 建议方向 |
|------|------|---------|
| iOS bundleId 未完整补全 | 5 款非高途 App 的 iOS bundleId 标注为 TBD | 首次真机测试时补充 |
| 5 款 App skill 为框架状态 | tutu/jingpin/gongkao/xinli/ketang 的 elements.md 需补充专属元素 | 按需填充各 App 高频操作元素 |
| AI 视觉依赖外部 API | 阿里云 DashScope 不可用时退化为 xpath 模式 | 可配置备用视觉模型或本地模型 |

### 7.3 项目规模统计

| 指标 | 数值 |
|------|------|
| 支持 App 数量 | 6 款 |
| 支持平台 | Android + iOS |
| 公共模块文件数 | 7 个 |
| App Skill 数量 | 7 个（含 appium-expert）|
| 元素定位文件数 | 6 个 |
| 报告脚本文件数 | 3 个 |
| 用例解析路径数 | 3 路 |
| 执行步骤类型数 | 3 种（PRECOND / ACTION / ASSERT）|

---

*本文档基于 `appium-mcp-matrix` 项目现有实现生成，日期：2026-04-30。*
