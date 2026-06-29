# 我的 Tab

- **层级**：depth 0（底部 Tab）
- **导航路径**：底部导航 → 我的
- **页面特征**：React Native 页面（`ScrollView`）。顶部用户卡（头像/昵称/手机号/学币签到）+ 快捷入口横排 + 学习服务宫格 + 用户服务宫格 + 专题中心
- **截图**：`screenshots/10_profile.png`

## UI 区域与关键元素

### 顶部用户卡
| 元素 | 定位 | 说明 |
|------|------|------|
| 用户卡 | content-desc=`姐姐大家, 121****0001` | 头像 + 昵称 + 手机号(脱敏)，可点进个人主页 |
| 昵称 | `text=姐姐大家` | |
| 手机号 | `text=121****0001` | |
| 学币签到 | 右上角红色按钮 `学币签到` | 截图右上 |
| 设置入口 | AI 视觉 `hexagon settings icon button, rightmost icon in top-right corner of 我的 page` | 退出登录入口（gear/六边形图标，无稳定 id）|

### 快捷入口（横排）
| 入口 | 定位 |
|------|------|
| 我的动态 | content-desc=`我的动态` |
| 我的订单 | content-desc=`我的订单` |
| 学币商城 | content-desc=`学币商城` |
| 购物车 | content-desc=`购物车` |

### 学习服务（宫格）
| 入口 | 定位 |
|------|------|
| 缓存课程 | content-desc=`缓存课程` |
| 我的课程 | content-desc=`我的课程` |
| 课程评价 | content-desc=`课程评价` |
| 我的预约 | content-desc=`我的预约` |
| 教辅图书 | content-desc=`教辅图书` |
| 优惠券 | content-desc=`优惠券` |

### 用户服务（宫格 / `HorizontalScrollView`）
| 入口 | 定位 |
|------|------|
| 帮助中心 | content-desc=`帮助中心` |
| 意见反馈 | content-desc=`意见反馈` |
| 学考资料 | content-desc=`学考资料` |
| 社区公约 | content-desc=`社区公约` |
| 中奖记录 | content-desc=`中奖记录` |
| 讲义物流 | content-desc=`讲义物流` |
| 我的关注 | content-desc=`我的关注` |
| 个性装扮 | content-desc=`个性装扮` |
| 我的硬件 | content-desc=`我的硬件` |
| 教师资质 | content-desc=`教师资质` |

### 专题中心
- 区块标题 `text=专题中心`，下方为动态运营内容（需下滑加载）。

## 可导航子页面（depth 1）
- 用户卡 → 个人主页
- 设置图标 → 设置页（含「退出登录」，账号切换入口，见 gaotu skill 账号切换流程）
- 我的动态 / 我的订单 / 学币商城 / 购物车 → 各对应页
- 缓存课程 / 我的课程 / 课程评价 / 我的预约 / 教辅图书 / 优惠券 → 学习服务子页
- 帮助中心 / 意见反馈 / 学考资料 / 社区公约 / 中奖记录 / 讲义物流 / 我的关注 / 个性装扮 / 我的硬件 / 教师资质 → 用户服务子页
