# -*- coding: utf-8 -*-
# config.py

"""配置中心："""
# 钉钉应用信息
DT_APP_KEY = "xxxx"
DT_APP_SECRET = "xxxxxxxxxxx"

# 禅道信息
ZENTAO_BASE = "http://zentao.xxxx.cn"  # 禅道地址（http）
ZENTAO_APP_CODE = "DingTalk_Logi"  # 禅道应用代号
ZENTAO_APP_KEY = "xxxxxxxx"  # 禅道应用密钥

# API Token
ZENTAO_CREATE_MODE = "mysql"
ZENTAO_ADMIN_TOKEN = "TOKEN"

# ——自动登录获取 Token——
ZENTAO_TOKEN_AUTO_LOGIN = True            # 开启自动登录取 Token
# 账号密码均通过环境变量配置，下方配置占位
ZENTAO_ADMIN_ACCOUNT = "admin"            # 管理员账号
ZENTAO_ADMIN_PASSWORD = "password"   # 管理员密码

# 环境变量优先：ZENTAO_ADMIN_TOKEN / ZENTAO_ADMIN_ACCOUNT / ZENTAO_ADMIN_PASSWORD
# Token 登录接口（不同版本一般相同）
ZENTAO_TOKEN_URL = f"{ZENTAO_BASE}/api.php/v1/tokens"

# MySQL 模式连接信息
MYSQL_HOST = "172.18.0.2"
MYSQL_PORT = 3306
MYSQL_DB = "zentao"
MYSQL_USER = "root"
MYSQL_PASS = "xxxxxx"
MYSQL_TABLE_PREFIX = "zt_"


# 账号生成策略：ding_userid 或 realname
ACCOUNT_STRATEGY = "ding_userid"
BIND_BY_REALNAME_ON_FIRST_LOGIN = True
ALLOW_AUTO_CREATE_BY_NAME = True

# 默认部门、密码
DEFAULT_GROUPS = ["pm"]
AUTO_JOIN_PROJECT_ID = 0         
AUTO_JOIN_PROJECT_ROLE = "pm"
DEFAULT_DEPT_ID = 0
DEFAULT_PASSWORD = "123456"

# 日志
LOG_FILE = "/var/log/dingtalk_login.log"
LOG_LEVEL = "DEBUG"
