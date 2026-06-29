APP_ID        = "cli_a85cf7f3137a500b"
APP_SECRET    = "udumglgyKwVmDjWKf0E25fuLKpCsYw2y"
SPACE_ID      = "7531056966526681116"
PARENT_NODE   = "UflIw2u4aiKfSVkxEOAcc5Mnn6e"
GROUP_CHAT_ID = "oc_aad4f334d463251e56c2f5495f60027e"

BITABLE_CONFIGS = {
    "gaotu": {
        "app_token": "RLDEbjYG7aiKwBsu9gOcadmlnvc",
        "table_id":  "tblvXqsSu7xShRJH",
        "view_id":   "vewJViMvTW",  # 执行用指定视图，按 ID 升序；search 必须带此 view_id 才与用户视图顺序一致
    },
    "tutu": {
        "app_token": "",
        "table_id":  "",
    },
    "jingpin": {
        "app_token": "",
        "table_id":  "",
    },
    "gongkao": {
        "app_token": "",
        "table_id":  "",
    },
    "xinli": {
        "app_token": "",
        "table_id":  "",
    },
    "ketang": {
        "app_token": "",
        "table_id":  "",
    },
}

# 执行结果表（按平台分离，执行完 batch_create 写入，不回写原用例表）
#   app_token：知识库 wiki 节点 token，用于 bitable 记录 API（search/create/update，兼容 wiki token）
#   obj_token：真实 bitable obj_token，用于 medias/upload_all 上传截图的 parent_node
#             （wiki token 上传会报 1061044 parent node not exist；obj_token 由
#              wiki_v2 get_node 解析得到，与该 app 用例表 app_token 同属一个 bitable 文件）
RESULT_TABLES = {
    "gaotu": {
        "app_token": "C6X8wCdSLiAd9IkXtNFc6yO2nXg",
        "obj_token": "RLDEbjYG7aiKwBsu9gOcadmlnvc",
        "android":   "tblUEp8pt5W9Cic5",
        "ios":       "tblryYA67UjkVGwx",
    },
}
