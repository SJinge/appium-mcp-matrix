# 元素定位链(真相源 + 缓存优先)

> 供各 App skill 引用。执行 ACTION/ASSERT 定位目标元素时的**统一优先级链**。
> 核心转变:`strategy=id` 优先,AI 视觉降级为兜底。元素定位的成本从「执行期每步识别」
> 沉淀为「首次解析 + 永久缓存」。背景见记忆 [[project_element_truth_source]]。

---

## 前置:确定当前版本

会话开始时取一次,后续复用(缓存/真相源都按版本隔离):

```bash
adb -s <UDID> shell dumpsys package com.gaotu100.superclass | grep -m1 versionName
# → VERSION=5.91.80
```

依赖文件(由发版流程产出,见 scripts/scan_apk_ids.py / scan_source_ids.py):
- `apps/{app_id}/{VERSION}/elements.truth.json`   【Android】元素 id 全集(真相源)
- `apps/{app_id}/{VERSION}/elements.enriched.json` 【Android】带页面归属(可选)
- `apps/{app_id}/{VERSION}/elements.ios.json`      【iOS】运行时探索真相源(见下方 iOS 分支)
- `apps/{app_id}/{VERSION}/locator_cache.json`     步骤→selector 缓存(跨平台,自动累积)

> ⚠️ **平台差异**:Android 真相源是静态扫 APK 的 resource-id 全集(strategy=id);iOS 无 resource-id、
> 也无可扫的静态来源(已证伪,见记忆 project_element_truth_source),真相源只能靠**运行时探索**累积,
> 定位策略是 `accessibility id` / `-ios class chain` 而非 id。下方第 1 档按平台分流。

---

## 定位优先级链

对每个要定位的目标元素,**从上往下**,命中即停:

### 第 0 档 · 缓存命中(0 AI / 0 截图 / 0 page_source)

```bash
python3 scripts/locator_cache.py get --app-id {app_id} --version {VERSION} \
    --step "<步骤里的元素意图,如 点击登录按钮>" [--page <已知页面类>]
```
- exit 0 + 返回 `{selector, strategy}` → 直接 `appium_find_element strategy=<strategy> selector=<selector>` 执行,**本档结束**。
- exit 1(`{}`)→ 未命中,进第 1 档。

> 第二轮起绝大多数步骤都在这一档命中,不产生任何视觉/上下文开销。

### 第 1 档 · 真相源解析 + 写回缓存(仅首次/未命中时)

#### Android 分支(resource-id 真相源)

1. `appium_get_page_source` 抓当前页 —— **每页只抓一次**,同页多个待定位元素复用这一份,抓完即从上下文丢弃。
2. 从 page source 提取当前页真实 `resource-id` 集。
3. 与 `elements.truth.json` 的 `ids` 取**交集**(只认真相源里存在的 id,过滤脏 id)。
4. 按语义匹配目标:id 名(如 `account_sign_btn` ↔「登录按钮」)、邻近 text/content-desc;`elements.enriched.json` 的 module/page 归属辅助消歧。
5. 命中 → 用 `strategy=id` 执行 → 写回缓存:
   ```bash
   python3 scripts/locator_cache.py put --app-id {app_id} --version {VERSION} \
       --step "<同第0档的步骤意图>" [--page <页面类>] \
       --selector "com.gaotu100.superclass:id/<id>" --strategy id [--module <模块>]
   # put 默认校验 id 是否在真相源里,不在会拒绝(防止缓存脏 id)
   ```
6. page source 里无匹配真实 id(React Native / Compose / WebView / 动态页)→ 进第 2 档。

#### iOS 分支(运行时探索真相源)

> iOS 无 resource-id,真相源靠运行时 page_source 抽取累积。

1. `appium_get_page_source` 抓当前页 → 存成临时 xml。
2. 抽最优 locator + 累积到 iOS 真相源(同时得到本页全部可定位元素):
   ```bash
   python3 scripts/ios_locator_extract.py merge --app-id {app_id} --version {VERSION} \
       --page "<当前页>" --xml /tmp/ios_page.xml
   # 优先级:accessibility id(name 整页唯一)→ -ios class chain(type+name 唯一)→ needs_vision
   ```
3. 从输出里按语义匹配目标元素,取其 `strategy`+`selector` 执行。
4. 命中 → 写回缓存(iOS selector 非 id,需 `--no-verify` 跳过真相源 id 校验):
   ```bash
   python3 scripts/locator_cache.py put --app-id {app_id} --version {VERSION} \
       --step "<步骤意图>" --page "<页面>" \
       --selector "<name 或 class chain>" --strategy "accessibility id" --no-verify
   ```
5. 目标 `strategy=needs_vision`(纯图标/无 name/label)→ 进第 2 档。

### 第 2 档 · AI 视觉(ai_instruction)

无 resource-id 的页面(闪学 RN、短视频流、教室等)走这里。规范见各 App `elements.md` 的「AI 视觉定位规范」。AI 视觉结果**不写回 id 缓存**(无稳定 id 可缓存)。

### 第 3 档 · page source 属性兜底

text/content-desc 的 xpath:`//*[@text='目标']`、`//*[contains(@content-desc,'目标')]`。用于有文字但无稳定 id 的动态内容。

### 第 4 档 · 坐标兜底

仅已知固定布局(如底部 tab),记录日志说明。各 App `elements.md` 规则四原三级降级即第 2~4 档。

---

## ASSERT 取证链(判定可信度)

> 上面的定位链解决「点哪」;本段解决「判对没」。核心:ASSERT **默认怀疑**——
> 不靠主观看图说话,而是用真相源取得**可验证事实**再判定。把「我觉得这页对了」
> 换成「我用真实 id/文本在 UI 树里找到了证明这条断言的元素」。

### 判定优先级链(从上往下,命中即停)

#### 第 1 档 · id 取证(确定性,高可信)

断言指向某元素存在/某页已进入时:

1. 用定位链拿到目标 selector(优先 `strategy=id`,命中 `elements.truth.json`)。
2. `appium_find_element` 找到 → 断言**成立**;找不到 → 断言**不成立**。
3. **页面类断言**(如「进入课程详情页」):查 `elements.enriched.json` 取该页**签名元素 id**,
   确认其在当前 page source 出现,即可确定性判定「已在目标页」。页面标识来自源码扫描的页面归属,
   无需写进用例表。
4. 记 `verify_method="id"`,`evidence` 填命中的 selector,`confidence="high"`。

#### 第 2 档 · 文本/属性取证(确定性,高可信)

断言指向具体文案(如「显示购买成功」「余额为 ¥0」)时:

1. `appium_get_text` / `get_element_attribute` 取真实值。
2. 与断言预期**相等/包含**比对成立才判通过。
3. 记 `verify_method="text"`,`evidence` 填取到的真实文本,`confidence="high"`。

#### 第 3 档 · 视觉判定(主观,低可信,仅兜底)

仅当目标无 id、无可取文本(纯图标 / RN / 短视频流 / 教室画面)时,才 `appium_screenshot` 让 Claude 判断。

- 记 `verify_method="vision"`,`evidence` 填截图本地路径,`confidence="low"`。
- 低可信结果在报告里单独标注,需人工复核(见 parallel.md 字段规范)。

### 反幻觉校验(强制)

声称「看到 / 找到」的元素 id **必须存在于 `elements.truth.json`**。引用了真相源里不存在的 id 来证明通过,
这条 ASSERT 一律判**可疑/无效**(等同未验证),不得记 pass。
(同 `locator_cache.py put` 的真相源校验:不在真相源即拒绝。)

### 断言轮询(消 flaky,只读,生产安全)

ASSERT **判失败前**,在同一页面内 `appium_get_page_source` 短轮询(默认 3 次 × 2s)等动画/网络/弹窗稳定后再终判。

- ⚠️ 这是**重新查询页面**(只读),**不是重试用例**。
- **生产环境严禁重放 ACTION**(点击/提交/下单)做重试——会重复写线上数据。轮询只刷新 UI 树读取,无副作用。

---

## 发版后:继承上一版缓存(增量)

新版本目录首跑会全 miss。发版流程在 `scan_apk_ids` 出 `elements.diff.json` 后,执行一次继承:

```bash
python3 scripts/locator_cache.py seed-from-diff --app-id {app_id} --from <旧版本> --to <新版本>
# id 仍在新真相源 → 继承(标记待复验);id 已删除/改名 → 丢弃,只这些要重新解析
```

通常两周发版只动几个页面,90%+ 缓存可继承,只有变更页面回到第 1 档重学。

---

## 与上下文规则的关系

- 第 0 档不进上下文(CLI 只回小 JSON)。
- 第 1 档 page source 进上下文,但**每页一次、用完即丢、可一次解析多个元素**,且只在首次/版本变更时付出。
- 第 2 档 AI 视觉截图由外部视觉模型处理,不进 Claude 上下文(同 CLAUDE.md 截图规则①)。
