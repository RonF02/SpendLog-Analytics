# -*- coding: utf-8 -*-
"""数据库基建骨架（阶段 0）。

阶段 0 仅保留跨阶段复用的通用基建，业务库结构（星型模型建表 / 默认 seed）将在阶段 1 实现。

- data/accounts.db   用户账号与登录会话（账户库，沿用旧版结构）
- data/{uid}.db      每个用户的业务库（星型模型，按用户 id 命名）
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（本文件位于 script/）
DATA_DIR = os.path.join(BASE_DIR, "data")
ACCOUNTS_DB = os.path.join(DATA_DIR, "accounts.db")


def get_conn(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str  # 统一按 UTF-8 处理文本，支持中文用户名
    conn.execute("PRAGMA encoding='UTF-8';")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_accounts_conn():
    """账户库连接（users + sessions）。"""
    return get_conn(ACCOUNTS_DB)


def user_db_path(uid):
    """指定用户的业务库文件路径：data/{uid}.db"""
    return os.path.join(DATA_DIR, "{}.db".format(uid))


def delete_user_db(uid):
    """删除指定用户业务库文件（不存在则忽略）。"""
    path = user_db_path(uid)
    if os.path.exists(path):
        os.remove(path)


def get_user_conn(uid):
    """指定用户业务库连接。"""
    return get_conn(user_db_path(uid))