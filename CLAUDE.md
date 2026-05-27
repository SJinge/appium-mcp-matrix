# 高途矩阵 Appium-MCP 自动化项目

## 项目概览

6个高途矩阵App的移动端自动化测试，支持 Android / iOS 双端。

| app_id  | App名称   | Android packageName          |
|---------|----------|------------------------------|
| gaotu   | 高途      | com.gaotu100.superclass      |
| tutu    | 途途课堂  | com.gaotu100.tutu            |
| jingpin | 高途高中  | com.gaotu100.jingpin         |
| gongkao | 高途公职  | com.gaotu100.gongkao         |
| xinli   | 高途心理  | com.gaotu100.xinli           |
| ketang  | 高途素养  | com.gaotu100.ketang          |

## 目录结构

```
common/
├── elements/        # 跨App公共元素（{pkg}占位）
│   ├── login.md     # 登录页元素
│   └── dialog.md    # 通用弹窗元素
├── app.md           # App 安装/卸载流程
├── device.md        # 设备就绪检查 & Session capabilities
├── login.md         # 登录 skill 执行逻辑
├── parallel.md      # 多设备并行执行 & 结果文件格式规范 & 报告合并
├── parsing.md       # 用例解析规则（含 Bitable 路径C）
├── permission.md    # 系统权限预授权
├── prescan.md       # 多用例预扫描 & 执行计划优化
├── screenshot.md    # 截图/等待/弹窗规范
└── startup.md       # 首次启动弹窗（各App独立，见各skill目录）
scripts/
├── feishu_config.py # 飞书常量（APP_ID/SECRET/SPACE_ID等）
├── upload_screenshots.sh
└── wiki_report.py
.claude/skills/
├── appium-expert/
│   └── SKILL.md     # Appium 通用排障（设备/Session/元素定位/MCP）
└── gaotu/
    ├── SKILL.md     # 高途执行全流程
    ├── elements.md  # 高途专属元素 & AI视觉定位规范
    └── startup.md   # 高途首次启动弹窗序列
```

## 上下文管理规则

### 约束规则
1. 自动精简历史冗余信息，只保留当前任务核心上下文。
2. 不主动回溯无关历史对话，不重复复述过往内容。
3. 长日志、大代码、配置文本不完整嵌入会话，只提炼关键摘要。
4. 单次只聚焦当前单一问题，不主动延伸衍生无关内容。
5. 自动截断无效历史铺垫，只保留必要指令与关键参数。
6. 多步骤任务按阶段分步执行，不把全流程一次性塞入上下文。
7. 不主动加载无关项目文件、不自动读取冗余目录文件。
8. 图片只提取关键信息，不保留原图冗余像素与完整原始数据。

### 截图规则
1. **元素定位**（点击目标）使用 `appium_find_element strategy=ai_instruction`，截图由 Appium MCP 内部发给外部视觉模型处理，不进入 Claude 上下文。
2. **ASSERT 页面验证**需调用 `appium_screenshot` 让 Claude 判断页面状态，截图此时进入上下文；判断完毕立即丢弃，不在后续步骤中重复引用。
3. 截图同时保存到本地 `$SHOT_DIR`，上传飞书和 Wiki 报告均读取磁盘文件，不通过上下文传递图片数据。
4. 非必要不截图：ACTION 执行后若下一步是 ASSERT，交给 ASSERT 统一截图，不重复截同一页面。
5. 单次对话截图不超过 10 张；超出后新开对话，将当前步骤上下文带入继续。

---

## 飞书 MCP 调用规则

飞书 MCP 工具调用一律不传 `useUAT`（或显式传 `useUAT: false`），始终使用 tenant_access_token（应用权限）。

---

## 每次对话开始时必须读取以下文件

<common-files>
Read these files before doing anything else:
- common/elements/login.md
- common/elements/dialog.md
- common/screenshot.md
- common/device.md
</common-files>

执行具体 App 的测试时，额外读取对应 skill 的 elements.md：
- 高途：.claude/skills/gaotu/elements.md

遇到 Appium 环境/设备/Session/元素定位问题时，使用 `appium-expert` skill（.claude/skills/appium-expert/SKILL.md）。
