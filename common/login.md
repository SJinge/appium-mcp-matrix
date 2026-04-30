---
name: common-login
description: 高途矩阵6个App通用登录skill，支持验证码登录、密码登录、微信登录，双端（Android/iOS）
---

# Common Login Skill

## App 包名映射

| app_id  | App名称   | Android packageName          | iOS bundleId |
|---------|----------|------------------------------|--------------|
| gaotu   | 高途      | com.gaotu100.superclass      | TBD |
| tutu    | 途途课堂  | com.gaotu100.tutu            | TBD |
| jingpin | 高途高中  | com.gaotu100.jingpin         | TBD |
| gongkao | 高途公职  | com.gaotu100.gongkao         | TBD |
| xinli   | 高途心理  | com.gaotu100.xinli           | TBD |
| ketang  | 高途素养  | com.gaotu100.ketang          | TBD |

## 入参

- `app_id`：目标 App（见上表），默认 `gaotu`
- `platform`：`android` | `ios`
- `method`：`sms`（验证码）| `password`（密码）| `wechat`（微信）
- `phone`：手机号（sms / password 必填）
- `password`：密码（method=password 必填）
- `sms_code`：验证码（method=sms 时，若无法自动获取则人工传入）

## Android 元素定位

> `{pkg}` = 对应 app_id 的 packageName

| 元素 | 定位方式 | selector |
|------|----------|----------|
| 手机号输入框（验证码页） | id | `{pkg}:id/account_enter_et`（password=false） |
| 手机号输入框（密码页） | xpath | `//*[@resource-id='{pkg}:id/password_login_phone_et']//*[@resource-id='{pkg}:id/account_enter_et']` |
| 密码输入框 | xpath | `//*[@resource-id='{pkg}:id/password_login_password_et']//*[@resource-id='{pkg}:id/account_enter_et']` |
| 主操作按钮 | id | `{pkg}:id/account_sign_btn` |
| 切换密码登录 | id | `{pkg}:id/go_password_btn` |
| 微信登录按钮 | id | `{pkg}:id/wechat_sign_in_iv` |
| 协议勾选框 | id | `{pkg}:id/accept_login_agreement_layout` |
| 关闭按钮（验证码页） | id | `{pkg}:id/login_view_close_iv` |
| 返回按钮（密码页） | id | `{pkg}:id/login_view_back_iv` |

## iOS 元素定位

> iOS 使用 accessibility id 或 `-ios predicate string`，待截图补充后填入

| 元素 | 定位方式 | selector |
|------|----------|----------|
| 手机号输入框 | accessibility id | TBD |
| 密码输入框 | accessibility id | TBD |
| 主操作按钮 | accessibility id | TBD |
| 切换密码登录 | accessibility id | TBD |
| 微信登录按钮 | accessibility id | TBD |
| 协议勾选框 | accessibility id | TBD |

## 执行流程

### 前置：处理协议弹窗

每次登录前检查协议勾选框是否存在且未勾选，若存在则先勾选。
```
1. 尝试找 accept_login_agreement_layout
2. 若存在且未选中 → tap
3. 若不存在 → 跳过
```

### 分支一：验证码登录（method=sms）

```
1. 确认当前在验证码登录页（postion_sign_in_tv text="手机号登录"）
2. 处理协议勾选
3. 清空并输入手机号 → account_enter_et（password=false）
4. tap account_sign_btn（text="获取验证码"）
5. 等待验证码输入框出现（或由调用方传入 sms_code）
6. 输入验证码
7. tap 确认按钮
8. 等待登录成功（见成功判断）
```

### 分支二：密码登录（method=password）

```
1. 确认当前在验证码登录页
2. tap go_password_btn 切换到密码登录页
3. 等待页面切换（postion_sign_in_tv text="密码登录"）
4. 清空并输入手机号 → password_login_phone_et 下的 account_enter_et
5. 清空并输入密码 → password_login_password_et 下的 account_enter_et
6. tap account_sign_btn（text="登录"）
7. 等待登录成功（见成功判断）
```

### 分支三：微信登录（method=wechat）

```
1. 确认当前在验证码登录页
2. 处理协议勾选
3. tap wechat_sign_in_iv
4. 等待微信授权页面出现
5. tap 授权确认按钮（微信侧，需单独处理）
6. 等待回调并登录成功（见成功判断）
```

## 成功判断

登录成功后 App 会跳转首页，通过以下任一元素确认：
- Android：`{pkg}:id/tab_title` 可见
- iOS：TBD（待补充首页标志元素）

超时时间建议：10秒

## 失败处理

| 场景 | 处理方式 |
|------|----------|
| 协议弹窗未处理导致登录失败 | 重新勾选协议后重试 |
| 验证码超时 | 抛出错误，提示重新获取 |
| 密码错误 | 抛出错误，返回错误文本 |
| 广告弹窗遮挡 | 查找 `{pkg}:id/ad_close` 并关闭后继续 |

## 调用示例

```
# 验证码登录高途App
使用 common-login，app_id=gaotu，platform=android，method=sms，phone=13800138000

# 密码登录高途App
使用 common-login，app_id=gaotu，platform=android，method=password，phone=13800138000，password=xxx123

# 微信登录
使用 common-login，app_id=gaotu，platform=android，method=wechat
```
