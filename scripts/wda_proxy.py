#!/usr/bin/env python3
"""IPv4 127.0.0.1:{port} -> device tunnel IPv6 [addr]:{device-port} TCP proxy.
Auto-discovers the tunnel address from pymobiledevice3 tunneld registry (:49151).
Usage: wda_proxy.py --udid <udid> --port 8100 [--device-port 8100] [--registry http://127.0.0.1:49151/]

device-port 是 WDA 在设备侧实际监听的端口。默认 8100,但复用已有构建产物时该端口由
xctestrun 里烤进的 USE_PORT 决定(不同构建可能是 8101/8102...),须由调用方显式传入。
"""
import argparse, socket, select, sys, json, urllib.request, time

DEFAULT_DEVICE_PORT = 8100


def discover_tunnel_host(registry: str, udid: str):
    with urllib.request.urlopen(registry, timeout=5) as r:
        data = json.load(r)
    entry = data.get(udid) or data.get(udid.replace("-", ""))
    if isinstance(entry, list):
        entry = entry[0] if entry else None
    if isinstance(entry, dict):
        return entry.get("tunnel-address") or entry.get("address")
    return None


def _pipe(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [])
            if a in r:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
            if b in r:
                d = b.recv(65536)
                if not d:
                    break
                a.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def serve(udid: str, port: int, registry: str, device_port: int = DEFAULT_DEVICE_PORT):
    import threading
    host = None
    for _ in range(30):
        try:
            host = discover_tunnel_host(registry, udid)
        except Exception as e:
            print(f"registry not ready: {e}", file=sys.stderr)
        if host:
            break
        time.sleep(1)
    if not host:
        print("ERROR: could not discover tunnel host from registry "
              f"{registry} (is tunneld running?)", file=sys.stderr)
        sys.exit(1)
    print(f"tunnel host = {host}; proxy 127.0.0.1:{port} -> [{host}]:{device_port}")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)
    while True:
        cli, _ = srv.accept()
        try:
            info = socket.getaddrinfo(host, device_port, socket.AF_INET6, socket.SOCK_STREAM)
            fam, typ, proto, _, addr = info[0]
            up = socket.socket(fam, typ, proto)
            up.connect(addr)
        except OSError as e:
            print(f"upstream connect failed: {e}", file=sys.stderr)
            cli.close()
            continue
        threading.Thread(target=_pipe, args=(cli, up), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--udid", required=True)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--device-port", type=int, default=DEFAULT_DEVICE_PORT)
    ap.add_argument("--registry", default="http://127.0.0.1:49151/")
    args = ap.parse_args()
    serve(args.udid, args.port, args.registry, args.device_port)


if __name__ == "__main__":
    main()
