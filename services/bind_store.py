# -*- coding: utf-8 -*-
"""
账号绑定存储：ding_uid -> zentao_account
"""
import json, os, threading
_PATH = "bindings.json"
_LOCK = threading.Lock()

def get_all():
    if not os.path.exists(_PATH):
        return {}
    with _LOCK, open(_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f) or {}
        except Exception:
            return {}

def save_all(data: dict):
    with _LOCK, open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get(ding_uid: str) -> str:
    return get_all().get(ding_uid, "")

def put(ding_uid: str, account: str):
    data = get_all()
    data[ding_uid] = account
    save_all(data)
