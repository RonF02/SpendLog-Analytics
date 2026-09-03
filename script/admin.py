# -*- coding: utf-8 -*-
"""管理员功能：用户管理、密码管理。

从 auth.py 中独立出来的管理员逻辑，与账户认证（auth.py）单向依赖：
- auth.py 提供哈希、会话等底层能力
- admin.py 负责用户列表 / 重置密码 / 禁用启用 / 删除用户 / 修改密码
"""
import hmac
import os
from datetime import datetime

from auth import _hash_password, invalidate_sessions
from db import get_accounts_conn, get_user_conn, delete_user_db, get_user_db_path


def _record_count(uid):
    """统计指定用户业务库的记录数（库不存在返回 0）。"""
    try:
        conn = get_user_conn(uid)
        n = conn.execute("SELECT COUNT(*) AS c FROM records").fetchone()["c"]
        conn.close()
        return n
    except Exception:
        return 0


def _db_size(uid):
    """指定用户业务库文件在磁盘上的占用字节数（库不存在返回 0）。"""
    try:
        return os.path.getsize(get_user_db_path(uid))
    except OSError:
        return 0


def list_users():
    """返回所有用户及统计数据（供管理员查看）。"""
    conn = get_accounts_conn()
    rows = conn.execute(
        "SELECT id, username, created_at, is_admin, is_active FROM accounts ORDER BY id").fetchall()
    conn.close()
    return [{
        "id": r["id"],
        "username": r["username"],
        "is_admin": bool(r["is_admin"]),
        "is_active": bool(r["is_active"]),
        "created_at": r["created_at"],
        "record_count": _record_count(r["id"]),
        "db_size": _db_size(r["id"]),
    } for r in rows]


def change_password(uid, old_password, new_password, keep_token=None):
    """修改自己的密码（校验原密码）。成功仅保留当前会话。"""
    if not new_password or len(new_password) < 6:
        return None, "新密码长度至少 6 位"
    conn = get_accounts_conn()
    row = conn.execute(
        "SELECT password_hash, salt FROM accounts WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        return None, "账号不存在"
    _, h = _hash_password(old_password, row["salt"])
    if not hmac.compare_digest(h, row["password_hash"]):
        conn.close()
        return None, "原密码错误"
    salt, h = _hash_password(new_password)
    conn.execute("UPDATE accounts SET password_hash=?, salt=? WHERE id=?", (h, salt, uid))
    conn.commit()
    conn.close()
    invalidate_sessions(uid, keep_token)
    return True, None


def admin_reset_password(target_uid, new_password):
    """管理员重置指定用户密码，并使其所有会话失效。"""
    if target_uid == 0:
        return None, "不能重置内置管理员密码，请使用修改密码功能"
    if not new_password or len(new_password) < 6:
        return None, "新密码长度至少 6 位"
    conn = get_accounts_conn()
    if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (target_uid,)).fetchone():
        conn.close()
        return None, "用户不存在"
    salt, h = _hash_password(new_password)
    conn.execute("UPDATE accounts SET password_hash=?, salt=? WHERE id=?",
                 (h, salt, target_uid))
    conn.commit()
    conn.close()
    invalidate_sessions(target_uid)
    return True, None


def set_user_disabled(target_uid, disabled):
    """禁用/启用用户（对应 is_active）。禁用时使其会话失效；不能操作内置管理员。"""
    if target_uid == 0:
        return None, "不能操作内置管理员账号"
    conn = get_accounts_conn()
    if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (target_uid,)).fetchone():
        conn.close()
        return None, "用户不存在"
    conn.execute("UPDATE accounts SET is_active=? WHERE id=?",
                 (0 if disabled else 1, target_uid))
    conn.commit()
    conn.close()
    if disabled:
        invalidate_sessions(target_uid)
    return True, None


def delete_user(target_uid):
    """删除用户及其业务库。不能删除内置管理员。"""
    if target_uid == 0:
        return None, "不能删除内置管理员账号"
    conn = get_accounts_conn()
    conn.execute("DELETE FROM sessions WHERE user_id=?", (target_uid,))
    cur = conn.execute("DELETE FROM accounts WHERE id=?", (target_uid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return None, "用户不存在"
    delete_user_db(target_uid)
    return True, None


def list_sessions():
    """管理员视角：列出全部用户的当前有效登录会话，以用户为主维度分组。"""
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_accounts_conn()
    rows = conn.execute(
        "SELECT s.token, s.expires_at, s.created_at, s.user_agent, "
        "a.id AS user_id, a.username "
        "FROM sessions s JOIN accounts a ON a.id=s.user_id "
        "WHERE s.expires_at>? ORDER BY a.username, s.created_at DESC",
        (now,)).fetchall()
    conn.close()
    groups = {}
    for r in rows:
        g = groups.setdefault(r["username"], {"user_id": r["user_id"], "username": r["username"], "sessions": []})
        g["sessions"].append({
            "token": r["token"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "user_agent": r["user_agent"],
        })
    return list(groups.values())


def force_logout_session(token, current_token=None):
    """管理员强制下线任意会话（按 token 全局删除）。不能下线自己当前的会话。"""
    token = str(token or "").strip()
    if not token:
        return None, "缺少会话标识"
    if token == str(current_token or "").strip():
        return None, "不能下线当前正在使用的会话"
    conn = get_accounts_conn()
    cur = conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return None, "会话不存在或已过期"
    return True, None