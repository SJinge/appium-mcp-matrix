# 公共登录页元素

适用范围：矩阵所有App（各App共用同一登录SDK，resource-id后缀相同）  
`{pkg}` = 对应App的packageName，完整映射见 [../../CLAUDE.md](../../CLAUDE.md)

| app_id  | packageName |
|---------|-------------|
| gaotu   | com.gaotu100.superclass |
| tutu    | com.gaotu100.tutu |
| jingpin | com.gaotu100.jingpin |
| gongkao | com.gaotu100.gongkao |
| xinli   | com.gaotu100.xinli |
| ketang  | com.gaotu100.ketang |

---

## 页面特征识别

| 页面状态 | 特征 |
|---------|------|
| 验证码登录页 | 标题"手机号登录"；主按钮text="获取验证码" |
| 密码登录页 | 标题"密码登录"；主按钮text="登录" |
| 已登录（首页） | 底部Tab可见 |

> Android 验证码登录页因 FLAG_SECURE 截图黑屏，只能用 page source + resource-id。切换到密码登录页后截图正常。  
> iOS 无 FLAG_SECURE，全程截图可见。

---

## Android 元素

### 验证码登录页

| 元素名 | resource-id | 备注 |
|--------|-------------|------|
| 手机号输入框 | `{pkg}:id/account_enter_et` | password属性=false区分手机号框 |
| 获取验证码按钮 | `{pkg}:id/account_sign_btn` | text="获取验证码" |
| 切换密码登录 | `{pkg}:id/go_password_btn` | 仅此页存在 |
| 微信登录 | `{pkg}:id/wechat_sign_in_iv` | |
| 协议勾选容器 | `{pkg}:id/accept_login_agreement_layout` | 未勾选时先tap |
| 关闭按钮 | `{pkg}:id/login_view_close_iv` | |

### 密码登录页

| 元素名 | resource-id / xpath | 备注 |
|--------|---------------------|------|
| 手机号输入框 | xpath: `//*[@resource-id='{pkg}:id/password_login_phone_et']//*[@resource-id='{pkg}:id/account_enter_et']` | 父容器限定避免歧义 |
| 密码输入框 | xpath: `//*[@resource-id='{pkg}:id/password_login_password_et']//*[@resource-id='{pkg}:id/account_enter_et']` | password属性=true |
| 登录按钮 | `{pkg}:id/account_sign_btn` | text="登录" |
| 返回按钮 | `{pkg}:id/login_view_back_iv` | 返回验证码页 |

### 协议弹窗（部分App）

| 元素名 | resource-id | 备注 |
|--------|-------------|------|
| 协议确认按钮 | `{pkg}:id/customer_dialog_ok` | 高途已确认，其余App待核实 |

---

## iOS 元素

> iOS 无 FLAG_SECURE，截图全程可用。  
> 所有元素待真机截图 + page source 补充后填入。

| 元素名 | strategy | selector | 备注 |
|--------|---------|---------|------|
| 手机号输入框 | accessibility id | TBD | |
| 密码输入框 | accessibility id | TBD | |
| 获取验证码/登录按钮 | accessibility id | TBD | |
| 切换密码登录 | accessibility id | TBD | |
| 微信登录 | accessibility id | TBD | |
| 协议勾选框 | accessibility id | TBD | |

---

## 登录成功判断

| 平台 | 判断方式 | selector |
|------|---------|---------|
| Android | 底部Tab可见 | `{pkg}:id/tab_title` |
| iOS | 底部Tab可见 | TBD |

超时：10秒
