# -*- coding: utf-8 -*-
import requests
from typing import Dict, Any

BASE = "https://api.dingtalk.com/v1.0"

from config import DT_APP_KEY, DT_APP_SECRET

def get_user_access_token(auth_code: str) -> str:
    url = f"{BASE}/oauth2/userAccessToken"
    resp = requests.post(url, json={
        "clientId": DT_APP_KEY,
        "clientSecret": DT_APP_SECRET,
        "code": auth_code,
        "grantType": "authorization_code"
    }, timeout=10)
    data = resp.json()
    return data.get("accessToken", "")

def get_user_me(access_token: str) -> Dict[str, Any]:
    url = f"{BASE}/contact/users/me"
    resp = requests.get(url, headers={"x-acs-dingtalk-access-token": access_token}, timeout=10)
    return resp.json()

def list_users(access_token: str):
    url = f"{BASE}/contact/users"
    resp = requests.get(url, headers={"x-acs-dingtalk-access-token": access_token}, timeout=20)
    data = resp.json()
    return data.get("users", []) or []
