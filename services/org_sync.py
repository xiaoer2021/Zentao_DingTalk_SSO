# -*- coding: utf-8 -*-
"""
组织架构同步与用户字段构建
"""
from typing import Dict, Any
from . import dingtalk_api, zentao_api
from mapping import ACCOUNT_MAP, USER_FIELD_MAP, DEPT_MAP

def _build_user_fields(d_user: Dict[str, Any]) -> Dict[str, Any]:
    """根据钉钉用户信息构造禅道用户字段"""
    fields = {}
    # 姓名映射
    if "name" in USER_FIELD_MAP:
        fields["realname"] = d_user.get("name")
    # 部门映射
    raw_dept = d_user.get("departmentId") or d_user.get("deptId")
    if raw_dept in DEPT_MAP:
        fields["dept"] = DEPT_MAP[raw_dept]
    return fields

def ensure_user_exists(d_user: Dict[str, Any]) -> str:
    """确保用户存在，不存在则创建"""
    account = ACCOUNT_MAP.get(d_user.get("userId")) or d_user.get("userId") or d_user.get("name")
    if not zentao_api.user_exists(account):
        fields = _build_user_fields(d_user)
        fields["role"] = "pm"  # 全员 PM
        zentao_api.create_user(account, fields)
    return account

def full_sync(access_token: str) -> int:
    """全量同步组织架构"""
    users = dingtalk_api.list_users(access_token)
    cnt = 0
    for u in users:
        ensure_user_exists(u)
        cnt += 1
    return cnt
