# -*- coding: utf-8 -*-
"""
ZenTao API 适配（优先 MySQL 直连；兼容 API 模式）：
- apilogin_url(account): 返回 index.php 免密登录 URL（更稳）
- user_exists(account): 查 zt_user（未删除）
- create_user(account, fields): 幂等创建用户（visions=rnd）
- find_account_by_realname(name): 唯一匹配返回账号
- ensure_user_groups(account, groups): 把用户加入指定组（按组名）
- add_user_to_project(project_id, account, role): 加入项目团队
"""
import time, hashlib
import os, time, hashlib, requests, pymysql
from typing import Dict, Any, Optional, List
from config import (
    ZENTAO_BASE, ZENTAO_CREATE_MODE,
    MYSQL_HOST, MYSQL_PORT, MYSQL_DB, MYSQL_USER, MYSQL_PASS, MYSQL_TABLE_PREFIX,
    ZENTAO_APP_CODE, ZENTAO_APP_KEY, ZENTAO_ADMIN_TOKEN,
    ZENTAO_TOKEN_AUTO_LOGIN, ZENTAO_ADMIN_ACCOUNT, ZENTAO_ADMIN_PASSWORD, ZENTAO_TOKEN_URL,
)

def _db():
    return pymysql.connect(
        host=MYSQL_HOST, port=int(MYSQL_PORT), user=MYSQL_USER, password=MYSQL_PASS,
        database=MYSQL_DB, charset="utf8mb4", autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
def _tbl(name: str) -> str: return f"{MYSQL_TABLE_PREFIX}{name}"

# ---- 登录 URL（index.php 更稳，不额外做存在校验） ----
def apilogin_url(account: str) -> str:
    """使用带签名的 api.php 免密登录"""
    ts = str(int(time.time()))
    token = hashlib.md5((ZENTAO_APP_CODE + ZENTAO_APP_KEY + ts).encode()).hexdigest()
    return (f"{ZENTAO_BASE}/api.php?m=user&f=apilogin"
            f"&account={account}&code={ZENTAO_APP_CODE}&time={ts}&token={token}")

# ---- 用户是否存在 ----
def user_exists(account: str) -> bool:
    if ZENTAO_CREATE_MODE == "api":
        return _get_user_api(account)
    sql = f"SELECT id FROM {_tbl('user')} WHERE account=%s AND deleted='0' LIMIT 1"
    with _db() as conn, conn.cursor() as cur:
        cur.execute(sql, (account,))
        return cur.fetchone() is not None

# ---- 创建用户（MySQL 幂等） ----
def create_user(account: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    if ZENTAO_CREATE_MODE == "api":
        return _create_user_api(account, fields)
    realname = fields.get("realname") or account
    role     = fields.get("role") or "pm"
    dept     = int(fields.get("dept") or 0)
    visions  = fields.get("visions") or "rnd"
    sql = (f"INSERT IGNORE INTO {_tbl('user')} "
           f"(dept,account,realname,role,visions,deleted) VALUES (%s,%s,%s,%s,%s,'0')")
    with _db() as conn, conn.cursor() as cur:
        cur.execute(sql, (dept, account, realname, role, visions))
    return {"ok": True, "detail": "inserted", "mode": "mysql"}

# ---- 按真实姓名唯一匹配账号  ----
def find_account_by_realname(realname: str) -> str:
    if not realname or ZENTAO_CREATE_MODE != "mysql":
        return ""
    sql = f"SELECT account FROM {_tbl('user')} WHERE realname=%s AND deleted='0'"
    with _db() as conn, conn.cursor() as cur:
        cur.execute(sql, (realname,))
        rows = cur.fetchall()
        return rows[0]["account"] if rows and len(rows) == 1 else ""

# ---- 加组 ----
def ensure_user_groups(account: str, groups: List[str]):
    if not groups: return
    with _db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {_tbl('user')} WHERE account=%s AND deleted='0' LIMIT 1", (account,))
        u = cur.fetchone()
        if not u: return
        uid = u["id"]
        fmt = ",".join(["%s"] * len(groups))
        cur.execute(f"SELECT id FROM {_tbl('group')} WHERE `name` IN ({fmt})", groups)
        gids = [r["id"] for r in (cur.fetchall() or [])]
        for gid in gids:
            cur.execute(f"INSERT IGNORE INTO {_tbl('usergroup')}(`user`,`group`) VALUES(%s,%s)", (uid, gid))

# ---- 入项目 ----
def add_user_to_project(project_id: int, account: str, role: str = "pm"):
    if not project_id: return
    with _db() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT IGNORE INTO {_tbl('team')}(`root`,`type`,`account`,`role`,`join`,`days`) "
            f"VALUES (%s,'project',%s,%s,NOW(),36500)",
            (project_id, account, role)
        )

# --------- API 模式（默认Mysql模式） ---------
_cached_token: Optional[str] = None
def _login_and_get_token() -> Optional[str]:
    acct = os.getenv("ZENTAO_ADMIN_ACCOUNT", ZENTAO_ADMIN_ACCOUNT or "")
    pwd  = os.getenv("ZENTAO_ADMIN_PASSWORD", ZENTAO_ADMIN_PASSWORD or "")
    if not (acct and pwd and ZENTAO_TOKEN_URL): return None
    try:
        r = requests.post(ZENTAO_TOKEN_URL, json={"account": acct, "password": pwd}, timeout=8)
        j = r.json() if r.headers.get("Content-Type","").startswith("application/json") else {}
        tok = (j or {}).get("token")
        if r.status_code in (200,201) and tok:
            global _cached_token
            _cached_token = tok
            os.environ["ZENTAO_ADMIN_TOKEN"] = tok
            return tok
    except Exception:
        pass
    return None
def _admin_token() -> str:
    global _cached_token
    if _cached_token: return _cached_token
    tok = os.getenv("ZENTAO_ADMIN_TOKEN", "") or (ZENTAO_ADMIN_TOKEN if ZENTAO_ADMIN_TOKEN and not ZENTAO_ADMIN_TOKEN.startswith("YOUR_") else "")
    if tok:
        _cached_token = tok; return tok
    if ZENTAO_TOKEN_AUTO_LOGIN: return _login_and_get_token() or ""
    return ""
def _auth_headers(): tok = _admin_token(); return {"Token": tok} if tok else {}
def _create_user_api(account: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{ZENTAO_BASE}/api.php/v1/users"
    payload = {"account": account}; payload.update(fields or {})
    payload.setdefault("gender", "m"); payload.setdefault("password", "LlmY!2025")
    def call():
        r = requests.post(url, headers=_auth_headers(), json=payload, timeout=10)
        ct = r.headers.get("Content-Type",""); data = r.json() if ct.startswith("application/json") else {"text": r.text}
        return r.status_code, data
    code, data = call()
    if code in (401,403) and ZENTAO_TOKEN_AUTO_LOGIN:
        if _login_and_get_token(): code, data = call()
    return {"ok": code in (200,201), "detail": data, "mode": "api"}
def _get_user_api(account: str) -> bool:
    url = f"{ZENTAO_BASE}/api.php/v1/users/{account}"
    def call(): return requests.get(url, headers=_auth_headers(), timeout=8).status_code
    code = call()
    if code in (401,403) and ZENTAO_TOKEN_AUTO_LOGIN:
        if _login_and_get_token(): code = call()
    return code == 200

