import re, json, os, subprocess
from typing import Optional
from flask import Flask, request, jsonify

app = Flask(__name__)

APP_IDS = {"gaotu", "tutu", "jingpin", "gongkao", "xinli", "ketang"}
_MSG_RE = re.compile(
    r'(?P<app>' + '|'.join(APP_IDS) + r')\s+'
    r'(?P<version>\d+\.\d+(?:\.\d+)?)\s+'
    r'android:(?P<apk_url>https?://\S+)\s+'
    r'ios:(?P<ipa_url>https?://\S+)',
    re.IGNORECASE
)

def parse_message(text: str) -> Optional[dict]:
    m = _MSG_RE.search(text)
    if not m:
        return None
    return {
        "app_id":  m.group("app").lower(),
        "version": m.group("version"),
        "apk_url": m.group("apk_url"),
        "ipa_url": m.group("ipa_url"),
    }
