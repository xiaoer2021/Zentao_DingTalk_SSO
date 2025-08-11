# -*- coding: utf-8 -*-
"""
DingTalk ⇄ ZenTao SSO 网关
- PC 一键：/dingtalk/login → 授权 → callback(J|...) → 由网关中继 Cookie 后直进首页
- 扫码：   /dingtalk/qrcode → 授权 → callback(Q|ticket) → 仅显示“成功，可关闭”，PC 端可轮询 /dingtalk/status
- 健康：   /health
"""
from flask import Flask, request, redirect, render_template, send_file, Response, jsonify, make_response
import logging, urllib.parse, qrcode, os, time, uuid, json, re, requests
from io import BytesIO

# ---------- 配置 ----------
import config as _cfg
from services import zentao_api
from services.bind_store import get as bind_get, put as bind_put
import mapping as _map

DT_APP_KEY  = getattr(_cfg, "DT_APP_KEY", "")
ZENTAO_BASE = getattr(_cfg, "ZENTAO_BASE", "http://localhost")

ACCOUNT_STRATEGY                 = getattr(_cfg, "ACCOUNT_STRATEGY", "ding_userid")
BIND_BY_REALNAME_ON_FIRST_LOGIN  = getattr(_cfg, "BIND_BY_REALNAME_ON_FIRST_LOGIN", False)
DEFAULT_DEPT_ID                  = getattr(_cfg, "DEFAULT_DEPT_ID", 0)          
ALLOW_AUTO_CREATE_BY_NAME        = getattr(_cfg, "ALLOW_AUTO_CREATE_BY_NAME", True)

DEFAULT_GROUPS          = getattr(_cfg, "DEFAULT_GROUPS", ["pm"])
AUTO_JOIN_PROJECT_ID    = getattr(_cfg, "AUTO_JOIN_PROJECT_ID", 0)
AUTO_JOIN_PROJECT_ROLE  = getattr(_cfg, "AUTO_JOIN_PROJECT_ROLE", "pm")

ACCOUNT_MAP = getattr(_map, "ACCOUNT_MAP", {})
DEPT_MAP    = getattr(_map,  "DEPT_MAP", {})

# ---------- 日志 ----------
LOG_PATH  = getattr(_cfg, "LOG_FILE", "/var/log/dingtalk_login.log") or "/var/log/dingtalk_login.log"
LOG_LEVEL = getattr(_cfg, "LOG_LEVEL", "INFO")
_log_dir = os.path.dirname(LOG_PATH)
if _log_dir:
    os.makedirs(_log_dir, exist_ok=True)
try:
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, "a").close()
except Exception:
    LOG_PATH = "/tmp/dingtalk_login.log"
handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
logging.basicConfig(level=getattr(logging, (LOG_LEVEL or "INFO").upper(), logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(message)s",
                    handlers=handlers)

app = Flask(__name__)

# ---------- 票据（扫码轮询可选） ----------
TICKET_FILE = "/tmp/dt_tickets.json"
def _load_tickets():
    try:
        with open(TICKET_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {}
def _save_tickets(data: dict):
    tmp = TICKET_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f)
    os.replace(tmp, TICKET_FILE)
def ticket_new(return_url: str) -> str:
    data = _load_tickets(); t = uuid.uuid4().hex
    data[t] = {"ok": False, "created": int(time.time()), "return": return_url}
    _save_tickets(data); return t
def ticket_ok(t: str, account: str, redirect_url: str):
    data = _load_tickets()
    if t in data:
        data[t].update({"ok": True, "account": account, "redirect": redirect_url, "ts": int(time.time())})
        _save_tickets(data)
def ticket_get(t: str):
    return _load_tickets().get(t)

# ---------- 工具 ----------
def _norm_return() -> str:
    return request.args.get("return") or request.referrer or "/"

def _normalize_account(display_name: str, fallback: str) -> str:
    if not display_name: return fallback
    s = re.sub(r'[^a-zA-Z0-9_]', '', display_name).lower()[:30]
    return s if len(s) >= 3 else fallback

def build_auth_url(return_url: str, state: str = "", src: str = "jump") -> str:
    """state: J|<空>（一键） or Q|<ticket>（扫码）"""
    prefixed_state = f"{'J' if src=='jump' else 'Q'}|{state or ''}"
    redirect_uri = f"{ZENTAO_BASE}/dingtalk/callback"
    return (
        "https://login.dingtalk.com/oauth2/auth?"
        f"client_id={DT_APP_KEY}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        "&response_type=code&scope=openid"
        f"&state={urllib.parse.quote(prefixed_state)}"
        f"&prompt=consent"
        f"&return_url={urllib.parse.quote(return_url)}"
    )

def _ensure_account_from_dingtalk(code: str) -> str:
    """从 code 换取用户并确保在禅道存在；必要时创建并配权。"""
    from services import dingtalk_api
    access_token = dingtalk_api.get_user_access_token(code)
    if not access_token:
        raise RuntimeError("获取 accessToken 失败")

    user = dingtalk_api.get_user_me(access_token)
    ding_uid = user.get("userId") or user.get("openId")
    if not ding_uid:
        raise RuntimeError(f"获取钉钉用户信息失败：{user}")
    display_name = (user.get("name") or user.get("nick") or "").strip()

    account = ACCOUNT_MAP.get(ding_uid) or bind_get(ding_uid)
    if not account and BIND_BY_REALNAME_ON_FIRST_LOGIN and hasattr(zentao_api, "find_account_by_realname"):
        if display_name:
            matched = zentao_api.find_account_by_realname(display_name)
            if matched:
                account = matched
                bind_put(ding_uid, account)

    if not account:
        account = ding_uid if ACCOUNT_STRATEGY == "ding_userid" else _normalize_account(display_name, ding_uid)

    logging.info(f"[sso] will login/create account={account}  ding_uid={ding_uid}  display={display_name!r}")

    if not zentao_api.user_exists(account):
        if not ALLOW_AUTO_CREATE_BY_NAME and not bind_get(ding_uid):
            raise PermissionError("账号未映射且未允许自动创建")

        # 组装字段
        raw_dept = user.get("departmentId") or user.get("deptId")
        fields = {
            "realname": display_name or account,
            "role": "pm",
            "dept": DEPT_MAP.get(raw_dept, DEFAULT_DEPT_ID),
            "visions": "rnd"
        }
        ret = zentao_api.create_user(account, fields)
        logging.info(f"create_user({account}) => {ret}")
        if not ret or not ret.get("ok"):
            raise RuntimeError(f"创建用户失败：{ret}")
        bind_put(ding_uid, account)

    # 统一配权（若实现）
    try:
        zentao_api.ensure_user_groups(account, DEFAULT_GROUPS)
        if AUTO_JOIN_PROJECT_ID:
            zentao_api.add_user_to_project(AUTO_JOIN_PROJECT_ID, account, role=AUTO_JOIN_PROJECT_ROLE)
    except Exception as e:
        logging.warning("post provision failed: %s", e)

    return account

def _apilogin_url(account: str) -> str:
    url = zentao_api.apilogin_url(account)  # index.php?m=user&f=apilogin...
    connector = "&" if "?" in url else "?"
    return f"{url}{connector}referer=%2F"  # 防止回到受限页再跳登录

def _relay_apilogin_cookies(apilogin_url: str, final_return: str = "/"):
    """
    先访问禅道首页拿会话，再调用 apilogin，最后把 cookie 写回浏览器并 302。
    同时透传用户真实 IP/UA，避免会话失效。
    """
    try:
        from urllib.parse import urlparse
        xff = request.headers.get("X-Forwarded-For", "")
        client_ip = (xff.split(",")[0].strip() if xff else request.remote_addr) or "127.0.0.1"
        ua = request.headers.get("User-Agent", "Mozilla/5.0")
        host = urlparse(apilogin_url).netloc

        headers = {
            "Host": host,
            "X-Real-IP": client_ip,
            "X-Forwarded-For": client_ip,
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Connection": "close",
        }

        s = requests.Session()
        # 1) 预热首页
        s.get(f"{_cfg.ZENTAO_BASE}/", timeout=8, allow_redirects=True, headers=headers)
        # 2) apilogin（允许跟随，拿最终 cookie）
        r = s.get(apilogin_url, timeout=8, allow_redirects=True, headers=headers)

        # 日志 cookie
        try:
            logging.info("relay cookies got: %s", ",".join([c.name for c in s.cookies]))
        except Exception:
            pass

        # 3) 写回浏览器
        resp = make_response(redirect(final_return or "/", code=302))
        for c in s.cookies:
            resp.set_cookie(c.name, c.value, path="/", httponly=True, secure=False, samesite="Lax")

        # 兜底透传 Set-Cookie
        try:
            raw_list = r.raw.headers.get_all("Set-Cookie")
            for sc in raw_list or []:
                resp.headers.add("Set-Cookie", sc)
        except Exception:
            pass

        return resp
    except Exception:
        logging.exception("relay apilogin failed")
        return redirect(final_return or "/", code=302)

# ---------- 路由 ----------
@app.get("/")
def home():
    return Response(
        "DingTalk ⇄ ZenTao SSO 运行中。<br>"
        "PC 一键授权：/dingtalk/login<br>"
        "（可选）二维码：/dingtalk/qrcode<br>"
        "（可选）票据：/dingtalk/newticket, /dingtalk/status?ticket=xxx",
        mimetype="text/html"
    )

@app.get("/dingtalk/login")
def dingtalk_login():
    ret = _norm_return()
    return redirect(build_auth_url(ret, state="", src="jump"), code=302)

@app.get("/dingtalk/qrcode")
def dingtalk_qrcode():
    ret = _norm_return()
    t = request.args.get("ticket") or ticket_new(ret)
    auth_url = build_auth_url(ret, state=t, src="qr")
    img = qrcode.make(auth_url)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    resp.headers["X-DT-Ticket"] = t
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.get("/dingtalk/newticket")
def dingtalk_newticket():
    ret = _norm_return()
    t = ticket_new(ret)
    return jsonify({"ticket": t, "return": ret})

@app.get("/dingtalk/status")
def dingtalk_status():
    t = request.args.get("ticket", "")
    info = ticket_get(t) or {}
    if info.get("ok"):
        return jsonify({"ok": True, "redirect": info.get("redirect", "/")})
    return jsonify({"ok": False})

@app.get("/dingtalk/callback")
def dingtalk_callback():
    code  = request.args.get("code")
    state = request.args.get("state", "")  # J|... or Q|ticket
    if not code:
        return render_template("error.html", message="缺少 code"), 400

    src_flag, _, tail = state.partition('|')
    is_jump = (src_flag == 'J'); ticket = tail or ""

    try:
        account = _ensure_account_from_dingtalk(code)
    except PermissionError as e:
        return render_template("error.html", message=str(e)), 403
    except Exception as e:
        logging.exception("callback error")
        return render_template("error.html", message=str(e)), 500

    apilogin = _apilogin_url(account)

    if is_jump:
        logging.info(f"pc-jump login -> {account} | apilogin={apilogin}")
        final_return = request.args.get("return") or "/"
        return _relay_apilogin_cookies(apilogin, final_return=final_return)

    # 扫码：仅标票据 + 成功页面（尝试自动关闭）
    if ticket:
        try:
            ticket_ok(ticket, account, apilogin)
        except Exception:
            pass

    SUCCESS_HTML = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权成功</title>
<div style="font:16px/1.6 system-ui;padding:28px">
  <h2>授权成功</h2>
  <p>您可以关闭此页面，回到电脑端继续。</p>
  <p style="color:#64748b">若未自动关闭，请手动返回钉钉。</p>
  <button id="closeBtn" style="padding:10px 14px;margin-top:12px;border-radius:10px;border:1px solid #e5e7eb">关闭</button>
</div>
<script>
(function(){
  function tryClose(){ try{ if(window.dd){ dd.biz.navigation.close({}); } else { window.close(); } }catch(e){} }
  var s=document.createElement('script'); s.src='https://g.alicdn.com/dingding/open-develop/1.9.0/dingtalk.js';
  s.onload=function(){ tryClose(); setTimeout(tryClose, 800); };
  document.head.appendChild(s);
  setTimeout(tryClose, 2000);
  document.getElementById('closeBtn').onclick=tryClose;
})();
</script>"""
    return Response(SUCCESS_HTML, status=200, headers={"Cache-Control": "no-store"})

@app.get("/health")
def health():
    return "ok", 200

@app.route("/error")
def error():
    return render_template("error.html")

# 全量同步
@app.get("/dingtalk/sync")
def full_sync():
    from services import dingtalk_api, org_sync
    code = request.args.get("code")
    if not code: return "缺少授权码 code（?code=）", 400
    access_token = dingtalk_api.get_user_access_token(code)
    if not access_token: return "获取 accessToken 失败", 500
    n = org_sync.full_sync(access_token)
    return f"全量同步完成，共处理 {n} 个用户"

# 事件
@app.post("/dingtalk/event")
def dingtalk_event():
    try:
        data = request.get_json(force=True, silent=True) or {}
        logging.info(f"event received: {data}")
        return {"code": 0, "msg": "ok"}
    except Exception as e:
        logging.exception("event error")
        return {"code": 1, "msg": str(e)}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, debug=True)

