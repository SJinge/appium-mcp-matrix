# 截图与等待规范

## 截图规则

- 统一使用 `appium_screenshot maxWidth=800`
- 直播教室内横屏截图需旋转：`sips -r 90 <路径>`
- 压缩保存：`sips -Z 600 <原图> --out <目标路径>`

## 截图保存策略（节省 token）

| 步骤类型 | 保存时机 |
|---------|---------|
| PRECOND | 仅失败时保存 |
| ACTION  | 仅失败时保存；若下一步是 ASSERT 则交给 ASSERT 处理 |
| ASSERT  | 无论成功/失败均保存 |

截图目录：
```bash
SHOT_DIR="$HOME/mcp_shots/${APP_ID:-app}/$(date +%Y%m%d_%H%M)_${CASE_ID:-manual}"
mkdir -p "$SHOT_DIR"
```

## 等待策略

- **禁止**无条件固定 sleep，改用轮询等目标条件出现
- 轮询间隔：0.3s；普通页面超时 3s；直播加载超时 8s
- 截图本身约 0.5s，弹窗循环无需额外 sleep
- 唯一可保留固定 sleep 的场景：录音等待（2s）、发送动作确认（1s）

## 弹窗处理循环（通用）

最多 5 轮，每轮：
1. 截图
2. 判断是否有弹窗（含"同意"/"知道了"/"允许"/"关闭"等）
3. 有 → AI 视觉定位点击；失败再降级 xpath/resource-id（Android）或 accessibility id（iOS）
4. 本轮无弹窗特征 → 退出循环

## AI 视觉定位规范

- 所有 ai_instruction 描述须包含：元素外观 + 位置 + 上下文
- 示例：`"red oval '进教室' button on the right side of 直播核心课 row"`
- 降级顺序：AI 视觉 → xpath → resource-id（Android）/ accessibility id（iOS）→ 坐标兜底
