# 首次启动弹窗流程（高途专属）

适用场景：**全新安装或卸载重装后首次启动**，弹窗按固定顺序出现，无需截图判断，直接顺序点击。

---

## 弹窗序列（固定顺序）

```
启动 App → 用户协议弹窗 → 青少年守护弹窗 → 正常启动流程（登录/首页）
```

---

## 快速执行脚本

### 1. 重启 App

```bash
adb -s <UDID> shell am force-stop com.gaotu100.superclass
adb -s <UDID> shell am start -n com.gaotu100.superclass/.ui.activity.SplashActivity
```

> 启动后直接等弹窗，无需 sleep。

### 2. 用户协议弹窗

| 字段 | 值 |
|------|----|
| 特征 | 「同意」「不同意」两个按钮，底部横排 |
| 定位 | AI 视觉 |
| ai_instruction | `red '同意' button on the right side of dialog bottom button row` |
| 降级 | `xpath //*[@text='同意']` |

点击后立刻出现下一个弹窗，不需要等待。

### 3. 青少年守护弹窗

| 字段 | 值 |
|------|----|
| 特征 | 标题「青少年守护」，「未满14岁」「已满14岁」两个按钮 |
| 定位 | AI 视觉 |
| ai_instruction | `'已满14岁' button on the right side of teenager protection dialog bottom button row` |
| 降级 | `xpath //*[@text='已满14岁']` |

点击后进入正常启动流程（闪屏 → 登录页或首页）。

---

## 注意事项

- 两个弹窗**只在首次启动时出现**，重启 App 但不卸载则不会再出现
- 如果已登录账号，跳过弹窗后直接进首页；未登录则进登录页
- 协议弹窗因 FLAG_SECURE 截图可能黑屏，但 AI 视觉定位不受影响
- 整个弹窗处理流程预期耗时 **< 10s**

---

## 验证：弹窗已处理完毕

```
轮询等待（超时 8s）：
  Android: //*[@resource-id='com.gaotu100.superclass:id/tab_title']   ← 底部 tab 出现
  或:       //*[@text='手机号登录']                                      ← 登录页出现
```
