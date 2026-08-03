#!/usr/bin/env bash
# iOS 真机 WDA 执行链路体检(纯只读,不含 sudo/不改任何状态)。
# 逐项确认: venv+pymobiledevice3 → 设备连接 → tunneld 隧道注册表 → WDA 端口 → xcodebuild 进程。
# 任何一环红了都给出定位提示。换机/venv 丢失/iOS 触发挂 WDA 时先跑这个。
#
#   bash scripts/ios_preflight.sh
#
# 退出码: 全绿=0; 有致命缺失(venv/pymobiledevice3/tunneld)=1。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$HOME/.wda-venv"
PMD3="$VENV/bin/pymobiledevice3"
PLIST_SRC="$ROOT/deploy/launchd/com.gaotu.appium-matrix.tunneld.plist"
PLIST_DST="/Library/LaunchDaemons/com.gaotu.appium-matrix.tunneld.plist"
LABEL="com.gaotu.appium-matrix.tunneld"
REGISTRY="http://127.0.0.1:49151"
SYS_PY="/usr/bin/python3"

fatal=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
hint() { printf "      → %s\n" "$1"; }
section() { printf "\n\033[1m%s\033[0m\n" "$1"; }

# 从 config/devices.yaml 读 iOS 设备(udid<空格>port,每行一台)
read_ios_devices() {
  "$SYS_PY" - "$ROOT/config/devices.yaml" <<'PY' 2>/dev/null
import sys, yaml
try:
    cfg = yaml.safe_load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
def walk(node):
    out = []
    if isinstance(node, dict):
        if "ios" in node and isinstance(node["ios"], list):
            for d in node["ios"]:
                if isinstance(d, dict) and d.get("udid"):
                    out.append((d["udid"], str((d.get("wda") or {}).get("port", 8100))))
        for v in node.values():
            out += walk(v)
    elif isinstance(node, list):
        for v in node:
            out += walk(v)
    return out
seen = set()
for udid, port in walk(cfg):
    if udid not in seen:
        seen.add(udid)
        print(udid, port)
PY
}

# ---------- 1. venv + pymobiledevice3 ----------
section "1. venv + pymobiledevice3"
if [ -x "$PMD3" ]; then
  ver="$("$PMD3" version 2>/dev/null | tail -1)"
  ok "pymobiledevice3 已装: $ver ($PMD3)"
else
  bad "缺 pymobiledevice3: $PMD3 不存在"
  hint "$SYS_PY -m venv ~/.wda-venv && ~/.wda-venv/bin/pip install -U pip pymobiledevice3"
  fatal=1
fi

# ---------- 2. 设备连接(usbmux) ----------
section "2. USB 设备连接"
usb=""
if [ -x "$PMD3" ]; then
  usb="$("$PMD3" usbmux list 2>/dev/null)"
  if [ -n "$usb" ]; then
    ok "usbmux 有设备响应"
  else
    bad "usbmux list 无设备 — 数据线/信任/解锁 任一异常"
    hint "插紧数据线、解锁屏幕、弹「信任此电脑」点信任后重跑"
  fi
else
  warn "跳过(pymobiledevice3 未装)"
fi

# ---------- 3. tunneld LaunchDaemon + 隧道注册表 ----------
section "3. tunneld 隧道(:49151)"
if [ -f "$PLIST_DST" ]; then
  ok "LaunchDaemon 已放置: $PLIST_DST"
else
  bad "LaunchDaemon 未安装到 /Library/LaunchDaemons"
  hint "sudo cp $PLIST_SRC /Library/LaunchDaemons/"
  hint "sudo chown root:wheel $PLIST_DST && sudo launchctl load -w $PLIST_DST"
  fatal=1
fi
if launchctl list 2>/dev/null | grep -q "$LABEL" || sudo -n launchctl list 2>/dev/null | grep -q "$LABEL"; then
  ok "tunneld 守护已加载($LABEL)"
else
  warn "launchctl 未见 $LABEL(可能需 sudo 才查得到,或确未加载)"
fi
reg="$(curl -s --max-time 3 "$REGISTRY/" 2>/dev/null)"
if [ -n "$reg" ]; then
  ok "隧道注册表 $REGISTRY 有响应"
else
  bad "注册表 $REGISTRY 无响应 — tunneld 没跑起来"
  hint "看日志: tail -n 40 $ROOT/logs/launchd.tunneld.err.log"
  fatal=1
fi

# ---------- 4. 逐设备: 隧道地址 + WDA 端口 + xcodebuild ----------
section "4. 逐设备 WDA 状态"
devs="$(read_ios_devices)"
if [ -z "$devs" ]; then
  warn "config/devices.yaml 未解析到 iOS 设备"
else
  while read -r udid port; do
    [ -z "$udid" ] && continue
    printf "  \033[1m%s\033[0m (WDA :%s)\n" "$udid" "$port"
    # 4a 隧道地址
    if [ -n "$reg" ] && printf "%s" "$reg" | grep -q "$udid"; then
      printf "    "; ok "隧道已分配 tunnel-address"
    else
      printf "    "; bad "注册表无此 udid 的隧道 — 设备没进隧道"
      printf "        "; hint "确认设备已信任; 重启守护: sudo launchctl kickstart -k system/$LABEL"
    fi
    # 4b WDA proxy 端口 /status
    st="$(curl -s --max-time 3 "http://127.0.0.1:$port/status" 2>/dev/null)"
    if printf "%s" "$st" | grep -q '"state"'; then
      printf "    "; ok "WDA :$port /status 健康"
    else
      printf "    "; warn "WDA :$port 无健康响应(执行时 orchestrate 会自愈重建,预检期正常)"
    fi
    # 4c xcodebuild WDA 进程
    if pgrep -f "xcodebuild.*$udid" >/dev/null 2>&1; then
      printf "    "; ok "xcodebuild WDA 进程在跑"
    else
      printf "    "; warn "无 xcodebuild WDA 进程(未执行时正常; 执行中缺则查构建日志)"
      printf "        "; hint "tail -f /tmp/wda_build_$udid.log"
    fi
  done <<< "$devs"
fi

# ---------- 总结 ----------
section "总结"
if [ "$fatal" -eq 0 ]; then
  ok "关键环节齐备,可触发 iOS 执行"
  exit 0
else
  bad "存在致命缺失(见上方 ✗),补齐后再触发 iOS"
  exit 1
fi
