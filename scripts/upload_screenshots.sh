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

FILE_TOKENS=()
for F in "$GAOTU_SHOT_DIR"/*.png; do
  [ -f "$F" ] || continue
  FNAME=$(basename "$F")
  FSIZE=$(stat -f%z "$F" 2>/dev/null || stat -c%s "$F")
  TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all" \
    -H "Authorization: Bearer $FS_TOKEN" \
    -F "file_name=$FNAME" \
    -F "parent_type=bitable_file" \
    -F "parent_node=$BITABLE_APP_TOKEN" \
    -F "size=$FSIZE" \
    -F "file=@$F" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['file_token']) if d.get('code')==0 else print('')")
  [ -n "$TOKEN" ] && FILE_TOKENS+=("{\"file_token\":\"$TOKEN\",\"name\":\"$FNAME\"}")
done

ATTACHMENTS="[$(IFS=,; echo "${FILE_TOKENS[*]}")]"
echo "[INFO] 上传完成，共 ${#FILE_TOKENS[@]} 张截图" >&2
