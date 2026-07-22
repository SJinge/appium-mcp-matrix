# Webhook 守护（launchd）

让 webhook server 开机自启、崩溃自动拉起，替代手动 `flask run`。

## 安装

```bash
# 1. 软链到 LaunchAgents（用软链，改 plist 不用重新拷）
ln -sf /Users/mac/Documents/projects/appium-mcp-matrix/deploy/launchd/com.gaotu.appium-matrix.webhook.plist \
       ~/Library/LaunchAgents/com.gaotu.appium-matrix.webhook.plist

# 2. 加载并启动
launchctl load -w ~/Library/LaunchAgents/com.gaotu.appium-matrix.webhook.plist

# 3. 确认存活
curl -s localhost:10086/health
# → {"status":"ok","enabled_apps":["gaotu"],"active_runs":0}
```

## 常用

```bash
# 看运行状态
launchctl list | grep appium-matrix

# 改完 plist / 代码后重启
launchctl kickstart -k gui/$(id -u)/com.gaotu.appium-matrix.webhook

# 停止并卸载
launchctl unload -w ~/Library/LaunchAgents/com.gaotu.appium-matrix.webhook.plist
```

## 观测

- 存活：`curl localhost:10086/health`
- 在跑的 run：`curl localhost:10086/status`
- 结构化日志：`tail -f logs/webhook.log`（webhook）、`logs/orchestrate.log`（执行）
- launchd 自身输出：`logs/launchd.webhook.{out,err}.log`

## 注意

- `ProgramArguments` 里的 python 路径需指向装了 `flask`/`pyyaml` 的解释器（默认 `/usr/bin/python3`，已验证可用）。
- 路径为本机绝对路径；换机器需同步改 plist 内 4 处路径。
- `ENABLED_APPS` 在此控制执行白名单，与代码默认一致（仅 gaotu）。

## tunneld(iOS 真机 WDA 隧道,root 守护)

iOS17+ 真机自动化需 RemoteXPC 隧道,必须 root 启动。用 LaunchDaemon 常驻:

安装(一次性,需 sudo):
```bash
sudo cp deploy/launchd/com.gaotu.appium-matrix.tunneld.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist
sudo launchctl load -w /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist
```

观测:
```bash
curl -s http://127.0.0.1:49151/ | python3 -m json.tool   # tunnel 注册表
tail -f logs/launchd.tunneld.err.log
```

卸载:`sudo launchctl unload -w /Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist`

> 注:放 `/Library/LaunchDaemons`(非 `~/Library/LaunchAgents`)才以 root 运行。
> tunneld 只访问 USB 设备、不读 ~/Documents,不撞 webhook 当年的 TCC 坑。

## iOS/WDA 排障备忘

本机 2026-07-09 实测结论：

1. `tunneld` 常驻是必要条件，但不是全部。
   - registry `:49151` 里能看到设备，只能说明 tunnel 在
   - 不代表 `WDA proxy + webDriverAgentUrl` 一定可用

2. 设备重启后，开发者签名信任可能失效。
   - 现象：`xcodebuild test` 报
     `profile has not been explicitly trusted by the user`
   - 处理：
     - 手机解锁
     - `设置 -> 通用 -> VPN 与设备管理`
     - 手动信任 `Apple Development: jinge.shi@icloud.com`

3. `tidevice list` 在线不代表 Xcode 已可用。
   - 若 `xcodebuild -showdestinations` 显示 `unpaired`
   - 需到 `Xcode -> Window -> Devices and Simulators` 完成配对

4. 当前自建 `scripts/wda_proxy.py` 通路不稳定。
   - 现象：
     - `WebDriverAgentRunner-Runner` 已启动
     - 但 `create_session` 仍报 `ECONNREFUSED`
     - `/tmp/wda_proxy_<udid>.log` 持续 `upstream connect failed`
   - 结论：
     - 当前不要强制 agent 手工传 `appium:webDriverAgentUrl=http://127.0.0.1:<port>`
     - 已验证更稳的方式是让 `appium-mcp/create_session` 直接建 iOS 会话

5. 已验证可跑通的最小链路：
   - `ios_wda.ensure_wda_ready(...)` 返回 ready
   - `appium-mcp/select_device`
   - `appium-mcp/create_session`（不手工传 `webDriverAgentUrl`）
   - `appium_screenshot`
   - `delete_session`
