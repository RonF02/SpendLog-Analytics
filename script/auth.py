# -*- coding: utf-8 -*-
"""用户账户认证：注册、登录、会话校验、退出、管理员初始化、账号删除。

- 用户账号与密码哈希存于 data/accounts.db（UTF-8 编码，支持中文用户名）
- 内置管理员：id=0，账密均为 admin，is_admin=1
- 业务数据按用户 id 分库：data/{uid}.db，注册时自动建库并播种默认种子
- 管理员功能（用户管理/密码管理）见 admin.py
密码使用 PBKDF2-HMAC-SHA256 加盐存储（标准库实现，无第三方依赖）。
登录成功签发随机 token，存入 sessions 表用于后续请求鉴权。
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from db import get_accounts_conn, init_user_db_with_seed, delete_user_db

SESSION_TTL_HOURS = 24 * 7  # token 有效期：7 天


def _hash_password(password, salt=None):
    """返回 (salt, hash)，均存为十六进制字符串。"""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return salt, digest.hex()


def _user_from_row(row):
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def ensure_admin():
    """确保内置管理员（id=0，账密 admin/admin）存在，并初始化其业务库。"""
    conn = get_accounts_conn()
    if not conn.execute("SELECT 1 FROM accounts WHERE id=0").fetchone():
        salt, h = _hash_password("admin")
        conn.execute(
            "INSERT INTO accounts (id, username, password_hash, salt, created_at, is_admin, is_active) "
            "VALUES (0,'admin',?,?,?,1,1)",
            (h, salt, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    conn.close()
    init_user_db_with_seed(0)


def _insert_account(username, password):
    """创建账号：用户名唯一性校验 + 入库 + 初始化并播种业务库。不校验口令策略。"""
    conn = get_accounts_conn()
    if conn.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
        conn.close()
        return None, "用户名已存在：{}".format(username)
    m = conn.execute("SELECT COALESCE(MAX(id),0) AS m FROM accounts").fetchone()["m"]
    uid = max(1, m + 1)  # 0 被管理员占用，普通用户从 1 开始
    salt, h = _hash_password(password)
    conn.execute(
        "INSERT INTO accounts (id, username, password_hash, salt, created_at, is_admin, is_active) "
        "VALUES (?,?,?,?,?,0,1)",
        (uid, username, h, salt, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    init_user_db_with_seed(uid)  # 创建并播种该用户独立的业务库
    return {"id": uid, "username": username, "is_admin": False}, None


def register(username, password, confirm_password):
    """自助注册新用户。成功创建其独立业务库 data/{uid}.db 并播种默认种子。"""
    username = str(username or "").strip()
    if not (3 <= len(username) <= 20):
        return None, "用户名长度需为 3-20 个字符"
    if not password:
        return None, "密码不能为空"
    if password != confirm_password:
        return None, "两次输入的密码不一致"
    if len(password) < 6:
        return None, "密码长度至少 6 位"
    return _insert_account(username, password)


def create_user(username, password):
    """管理员创建账户（普通用户，无 is_admin）。不做双次确认。"""
    username = str(username or "").strip()
    if not (3 <= len(username) <= 20):
        return None, "用户名长度需为 3-20 个字符"
    if not password or len(password) < 6:
        return None, "密码长度至少 6 位"
    return _insert_account(username, password)


def login(username, password, user_agent=None):
    """校验用户名密码，成功签发 token；user_agent 记录登录设备供会话管理区分。"""
    username = str(username or "").strip()
    conn = get_accounts_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, salt, is_admin, is_active FROM accounts WHERE username=?",
        (username,)).fetchone()
    if not row:
        conn.close()
        return None, "用户名或密码错误"
    if not row["is_active"]:
        conn.close()
        return None, "该账号已被禁用，请联系管理员"
    _, h = _hash_password(password, row["salt"])
    if not hmac.compare_digest(h, row["password_hash"]):
        conn.close()
        return None, "用户名或密码错误"
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(hours=SESSION_TTL_HOURS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at, created_at, user_agent) "
        "VALUES (?,?,?,?,?)",
        (token, row["id"], expires.isoformat(timespec="seconds"),
         now.isoformat(timespec="seconds"), (user_agent or "")[:200]))
    conn.commit()
    conn.close()
    return {"token": token, "user": _user_from_row(row)}, None


def logout(token):
    """使 token 失效。"""
    token = str(token or "").strip()
    if not token:
        return
    conn = get_accounts_conn()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def check_auth(token):
    """校验 token。有效返回用户信息 {id, username, is_admin}，否则返回 None。"""
    token = str(token or "").strip()
    if not token:
        return None
    conn = get_accounts_conn()
    row = conn.execute(
        "SELECT a.id, a.username, a.is_admin, a.is_active FROM sessions s "
        "JOIN accounts a ON a.id = s.user_id "
        "WHERE s.token=? AND s.expires_at>?",
        (token, datetime.now().isoformat(timespec="seconds"))).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        return None
    return _user_from_row(row)


def list_sessions(uid, current_token=None):
    """列出某用户当前有效（未过期）的登录会话，按签发时间倒序。"""
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_accounts_conn()
    rows = conn.execute(
        "SELECT token, expires_at, created_at, user_agent FROM sessions "
        "WHERE user_id=? AND expires_at>? ORDER BY created_at DESC",
        (uid, now)).fetchall()
    conn.close()
    current_token = str(current_token or "").strip()
    return [{
        "token": r["token"],
        "is_current": r["token"] == current_token,
        "created_at": r["created_at"],
        "expires_at": r["expires_at"],
        "user_agent": r["user_agent"],
    } for r in rows]


def revoke_session(uid, token, current_token=None):
    """强制下线指定会话。不能下线当前正在使用的会话。"""
    token = str(token or "").strip()
    if not token:
        return None, "缺少会话标识"
    if token == str(current_token or "").strip():
        return None, "不能下线当前正在使用的会话"
    conn = get_accounts_conn()
    cur = conn.execute(
        "DELETE FROM sessions WHERE token=? AND user_id=? AND expires_at>?",
        (token, uid, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return None, "会话不存在或已过期"
    return True, None


def invalidate_sessions(uid, keep_token=None):
    """删除某用户全部会话；keep_token 非空时保留该 token（改密后保持当前登录）。"""
    conn = get_accounts_conn()
    if keep_token:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (uid, keep_token))
    else:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()


def delete_account(uid):
    """普通用户删除自己的账号：清除会话与账户，并永久删除其业务库。

    前端需二次确认；内置管理员（id=0）不允许自删。
    """
    if uid == 0:
        return None, "管理员账号不可删除"
    conn = get_accounts_conn()
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    cur = conn.execute("DELETE FROM accounts WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return None, "账号不存在"
    delete_user_db(uid)
    return True, None