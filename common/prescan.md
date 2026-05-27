# 预扫描 & 执行计划

> 供各 App skill 引用。在开始任何设备操作之前，对多条用例的预置条件进行扫描，生成优化后的执行顺序，减少账号切换和 App 重启次数。

---

## 触发条件

用例数 ≥ 2 时执行预扫描；单条用例跳过，直接进入设备操作。

---

## 扫描逻辑

```
for 每条用例:
    REQUIRED_ACCOUNT = 预置条件中"账号：XXXX"的值
                       预置条件含"无需登录"/"未登录" → "无需登录"（特殊值）
                       无账号要求 → 取当前默认账号（DEFAULT_ACCOUNT）
    NEED_RESTART     = 预置条件含"重启App：是" → true，否则 false
```

---

## 排序规则

按以下优先级对用例重新排序，生成 `EXEC_PLAN`：

| 优先级 | 排序键 | 规则 |
|--------|--------|------|
| 1（主键）| REQUIRED_ACCOUNT | `"无需登录"` 排最前；其余按账号聚在一起，减少切换次数 |
| 2（次键）| NEED_RESTART | 同账号内，`false` 排前，`true` 排后 |

> "无需登录"用例排最前，避免从已登录状态切换到未登录状态时多余的退出操作。

---

## 上下文变量

```
EXEC_PLAN = [
  {
    "case_name":        "用例1 ...",
    "original_index":   1,          # 原始顺序（报告展示用）
    "exec_index":       1,          # 实际执行顺序
    "required_account": "12100000000",
    "need_restart":     false
  },
  ...
]

ACCOUNT_SWITCH_COUNT = 账号种类数 - 1   # 预计切换次数
RESTART_COUNT        = NEED_RESTART=true 的用例数
CURRENT_ACCOUNT      = ""               # 执行时实时跟踪，初始为空
```

> 执行顺序按 `EXEC_PLAN` 的 `exec_index` 走，报告仍按原始用例名（`case_name`）展示。

---

## 每条用例执行前的预置条件处理

在导航至目标页之前，按以下顺序处理预置条件：

### 1. 重启 App

| 预置条件 | 执行动作 |
|---------|---------|
| `NEED_RESTART = true` | 执行重启（同第三步逻辑），完成后继续 |
| `NEED_RESTART = false` 或无 | 仅确认 App 在前台（截图/page source），不重启 |

### 2. 账号处理

```
if REQUIRED_ACCOUNT == "无需登录":
    跳过所有登录操作，不改变 CURRENT_ACCOUNT

elif REQUIRED_ACCOUNT == CURRENT_ACCOUNT:
    账号一致，跳过

else:
    # ⚠️ 账号切换：禁止重启 App，禁止重建 Appium Session
    # 仅执行：退出登录 → 重新登录
    退出当前账号（导航到「我的」→ 设置 → 退出登录）
    执行登录流程（见 common/login.md），使用 REQUIRED_ACCOUNT
    CURRENT_ACCOUNT = REQUIRED_ACCOUNT
```

### 3. 数据类预置条件

"账号有已购课程"等数据条件：截图确认，记录为 PRECOND pass/fail，不触发任何操作。

---

## 执行计划写入报告

在第八步执行报告末尾追加：

```
执行计划（预扫描）：
共 N 条用例 | 账号切换 ACCOUNT_SWITCH_COUNT 次 | 重启 RESTART_COUNT 次

原始顺序 → 执行顺序：
  用例1（原序1）→ 执行序1  账号: 12100000000  重启: 否
  用例2（原序2）→ 执行序3  账号: 12188888888  重启: 否
  用例3（原序3）→ 执行序2  账号: 12100000000  重启: 是
  ...
```
