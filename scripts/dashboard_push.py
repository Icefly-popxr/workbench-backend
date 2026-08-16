#!/usr/bin/env python3
"""工作台 feeds 推送工具"""
import json
import sys
import urllib.request
import urllib.error

DASHBOARD_URL = "http://127.0.0.1:8765/api/feeds/push"

def push(category, items):
    if not items:
        return
    payload = json.dumps({"category": category, "items": items}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        DASHBOARD_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            pass
    except Exception as e:
        print(f"[dashboard_push] 推送失败（{category}）: {e}", file=sys.stderr)

if __name__ == "__main__":
    category = sys.argv[1] if len(sys.argv) > 1 else "ai"
    items = json.loads(sys.stdin.read())
    push(category, items)
