#!/bin/bash
# 上传截图目录内所有 PNG 到飞书多维表格，返回 ATTACHMENTS JSON 数组字符串。
#
# Usage:
#   source upload_screenshots.sh <SHOT_DIR> <BITABLE_APP_TOKEN>
#   echo "$ATTACHMENTS"   # "[{"file_token":"...","name":"..."}, ...]"
#
# Env (required):
#   FEISHU_APP_ID     飞书应用 App ID
#   FEISHU_APP_SECRET 飞书应用 App Secret

GAOTU_SHOT_DIR="${1:?Usage: $0 <SHOT_DIR> <BITABLE_APP_TOKEN>}"
BITABLE_APP_TOKEN="${2:?Usage: $0 <SHOT_DIR> <BITABLE_APP_TOKEN>}"

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 获取 tenant_access_token（复用 feishu_config.py 常量）
FS_TOKEN=$(python3 - <<EOF
import sys, json, urllib.request
sys.path.insert(0, '$_SCRIPT_DIR')
from feishu_config import APP_ID, APP_SECRET
data = json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode()
req = urllib.request.Request(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    data=data, headers={'Content-Type': 'application/json'}, method='POST')
print(json.load(urllib.request.urlopen(req))['tenant_access_token'])
EOF
)

# 解析 parent_node：若传入的是知识库 wiki 节点 token，需换成真实 bitable obj_token。
# bitable 记录 API 兼容 wiki token，但 medias/upload_all 的 parent_node 只认 obj_token，
# 否则报 1061044 parent node not exist。
# 优先从 feishu_config.RESULT_TABLES 读已配置的 obj_token（零 API 调用）；
# 未配置则回退到 wiki get_node 动态解析；非 wiki 节点（已是 obj_token）原样返回。
REAL_PARENT_NODE=$(python3 - <<EOF
import sys, json, urllib.request
sys.path.insert(0, '$_SCRIPT_DIR')
node = "$BITABLE_APP_TOKEN"
# 1) 配置优先：RESULT_TABLES 中 app_token 命中则直接用其 obj_token
try:
    from feishu_config import RESULT_TABLES
    for cfg in RESULT_TABLES.values():
        if cfg.get("app_token") == node and cfg.get("obj_token"):
            print(cfg["obj_token"]); sys.exit(0)
except Exception:
    pass
# 2) 回退：wiki get_node 动态解析
tok = "$FS_TOKEN"
url = f'https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={node}&obj_type=wiki'
try:
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'})
    d = json.load(urllib.request.urlopen(req))
    obj = d.get('data', {}).get('node', {}).get('obj_token') if d.get('code') == 0 else None
    print(obj or node)
except Exception:
    print(node)
EOF
)
[ "$REAL_PARENT_NODE" != "$BITABLE_APP_TOKEN" ] && \
  echo "[INFO] wiki 节点 token 已解析为 bitable obj_token: $REAL_PARENT_NODE" >&2

TMPDIR_TOKENS=$(mktemp -d)

_upload_one() {
  local F="$1"
  local FNAME FSIZE TOKEN
  FNAME=$(basename "$F")
  FSIZE=$(stat -f%z "$F" 2>/dev/null || stat -c%s "$F")
  TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all" \
    -H "Authorization: Bearer $FS_TOKEN" \
    -F "file_name=$FNAME" \
    -F "parent_type=bitable_file" \
    -F "parent_node=$REAL_PARENT_NODE" \
    -F "size=$FSIZE" \
    -F "file=@$F" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['file_token']) if d.get('code')==0 else print('')")
  [ -n "$TOKEN" ] && echo "{\"file_token\":\"$TOKEN\",\"name\":\"$FNAME\"}" \
    > "$TMPDIR_TOKENS/$FNAME.json"
}

# 并行上传所有截图
for F in "$GAOTU_SHOT_DIR"/*.png; do
  [ -f "$F" ] || continue
  _upload_one "$F" &
done
wait  # 等待所有上传完成

# 收集结果
FILE_TOKENS=()
for J in "$TMPDIR_TOKENS"/*.json; do
  [ -f "$J" ] && FILE_TOKENS+=("$(cat "$J")")
done
rm -rf "$TMPDIR_TOKENS"

ATTACHMENTS="[$(IFS=,; echo "${FILE_TOKENS[*]}")]"
echo "[INFO] 上传完成，共 ${#FILE_TOKENS[@]} 张截图" >&2
