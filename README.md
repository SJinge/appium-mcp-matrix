# appium-mcp-matrix

> 基于 **Claude Code + Appium MCP** 的高途矩阵 6 款 App 移动端 AI 驱动自动化测试框架，支持 Android / iOS 双端，用例来源覆盖搬山平台、自然语言、飞书多维表格，测试结果自动回写 Bitable 并推送飞书 Wiki 报告。

---

## 功能特性

- **AI 视觉元素定位**：优先截图 + `ai_instruction` 自然语言描述定位，三级降级（AI → resource-id/xpath → 坐标兜底），无惧页面结构变化
- **三路用例接入**：搬山 caseId 节点树解析 / 自然语言步骤 / 飞书 Bitable 表格，统一转为 `ACTION / ASSERT / PRECOND` 步骤列表
- **6 App 公共模块复用**：登录、弹窗处理、权限授权、截图等策略集中维护，各 App skill 只管差异
- **结果闭环**：截图自动上传飞书 → Bitable 三字段回写（执行结果 / 备注 / 截图）→ Wiki 报告生成 → IM 群通知
- **Android / iOS 双端支持**：capabilities 模板、权限预授权、WDA 启动均已抽象为公共规范

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
| tidevice | ≥ 0.9 | iOS 设备管理（推荐） |
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

在 Claude Code **全局**设置（`~/.claude/settings.json`）中同时注册两个 MCP Server：

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
| `AI_VISION_API_KEY` | appium-mcp | AI 视觉模型 API Key，不配则 AI 视觉定位不可用，退化为 xpath/resource-id |
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

### 启动方式

**方式一：`start.sh`（推荐）**

```bash
./start.sh gaotu
```

将 `skills/gaotu/` 和 `common/` 目录注入上下文，启动 Claude Code 交互对话。进入对话后直接输入用例指令即可触发执行。

> 每次只能启动一个 App 的会话。同时测试多个 App 需开多个终端分别执行。

**方式二：`/gaotu` slash command**

将 `skills/gaotu/` 目录软链到 `~/.claude/skills/`：

```bash
ln -s "$(pwd)/skills/gaotu" ~/.claude/skills/gaotu
```

之后在任意 Claude Code 会话中输入 `/gaotu` 即可触发。

> 注意：此方式下 `common/` 目录未注入，skill 中引用的公共文件（`parsing.md` 等）需要 Claude 从项目路径读取，建议在项目目录内启动 Claude Code 会话。

### 执行测试用例

在 Claude Code 对话中，支持以下触发方式：

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

**方式 C：飞书 Bitable 链接**

```
执行飞书表格用例：https://xxx.feishu.cn/wiki/xxxxx?table=tblxxxxxxxx
```

### 执行流程概览

```
第零步  解析用例 & 确认步骤列表
  ↓
设备就绪检查（adb devices / tidevice list）
  ↓
第一步  adb 预授权麦克风/摄像头/存储权限
  ↓
第二步  创建 Appium Session
  ↓
第三步  重启 App（force-stop → am start）
  ↓
第四步  检测登录状态 → 按需登录
  ↓
第五步  批量关闭登录后弹窗（最多 5 轮）
  ↓
第六步  导航至目标起始页（依据关键词自动判断）
  ↓
第七步  循环执行 PRECOND → ACTION → ASSERT 步骤
  ↓
第八步  清理收尾 → 执行报告 → Bitable 回写 → Wiki 推送
```

### 常用参数默认值（高途 App）

| 参数 | 默认值 |
|------|--------|
| Android device | `ce67d979` |
| packageName | `com.gaotu100.superclass` |
| phone | `12100000000` |
| password | `Gaotu@1234` |

> 需要修改默认设备或账号时，编辑 `skills/gaotu/SKILL.md` 顶部的参数表格。

---

## 目录结构

```
appium-mcp-matrix/
├── start.sh                       # 启动入口，注入指定 App skill 上下文
├── CLAUDE.md                      # Claude Code 项目指令（上下文规则）
│
├── common/                        # 跨 App 公共模块
│   ├── device.md                  # 设备就绪检查 & Session capabilities 模板
│   ├── login.md                   # 通用登录 skill（验证码/密码/微信）
│   ├── parsing.md                 # 用例解析规则（搬山/自然语言/Bitable）
│   ├── permission.md              # Android adb 权限预授权
│   ├── screenshot.md              # 截图规范、等待策略、弹窗处理循环
│   └── elements/
│       ├── login.md               # 登录页公共元素（{pkg} 占位符）
│       └── dialog.md              # 通用弹窗元素
│
├── skills/
│   └── gaotu/                     # 高途 App 专用 skill
│       ├── SKILL.md               # 完整执行流程（第零~第八步）
│       ├── elements.md            # 高途专属元素定位 & AI 视觉规范
│       └── evals/
│           └── evals.json         # skill 评估用例
│
└── scripts/
    ├── feishu_config.py           # 飞书应用凭证常量（APP_ID/APP_SECRET/SPACE_ID 等）
    ├── upload_screenshots.sh      # 截图批量上传飞书 Bitable
    └── wiki_report.py             # 生成 Wiki 报告 & 发送群通知
```

### 新增 App 的扩展方式

1. 在 `skills/` 下新建目录，如 `skills/tutu/`
2. 复制 `skills/gaotu/SKILL.md` 并修改包名、默认参数
3. 新建 `skills/tutu/elements.md` 补充该 App 专属元素
4. 执行：`./start.sh tutu`

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

Android 登录页启用了 `FLAG_SECURE`，截图强制黑屏。解决方法：跳过截图，改用 `appium_get_page_source` + `resource-id` 定位元素；切换到密码登录页后恢复正常截图。

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

**Q: 如何跳过 Bitable 回写，只看本地报告？**

不传飞书 Bitable 链接（使用路径 A 或路径 B 接入用例），第八步会跳过回写，仅输出终端执行报告和本地截图目录 `~/mcp_shots/`。
