# -*- coding: utf-8 -*-
"""数据库层（阶段 1）：账户库 + 按用户分库的星型模型。

- data/accounts.db   用户账号与登录会话（账户库）
- data/{uid}.db      每个用户的业务库（星型模型 + 默认 seed），按用户 id 命名

设计要点：
- 星型模型：事实表 records + 维度表 dim_category / dim_motive / dim_channel ，
  附预算表 budgets 与渠道校准表 channel_calibrations。
- 三层分类：dim_category 通过 level(1/2/3) 与 parent_id 组织层级。
- 渠道余额：dim_channel.balance 记录当前余额（默认 0），记账时联动增减。
- 幂等：所有建表用 IF NOT EXISTS；种子仅在对应表为空时补插，不重复不复活已删项。
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（本文件位于 script/）
DATA_DIR = os.path.join(BASE_DIR, "data")
ACCOUNTS_DB = os.path.join(DATA_DIR, "accounts.db")

# ---- 默认 seed 定义 ----
# 预设分类树：一级场景 → 二级子项（三级商家在记账页内联新增，无需预置）
SCENES = [
    ("餐饮", ["食堂", "外卖", "快餐", "聚餐", "奶茶甜点"]),
    ("居住", ["水电物业"]),
    ("交通", ["地铁公交", "打车", "加油"]),
    ("购物", ["生活用品", "日用品", "电子", "服饰"]),
    ("娱乐", ["游戏", "电影演出", "运动健身"]),
    ("医疗健康", ["药品", "体检"]),
    ("教育", ["书籍", "课程"]),
    ("通讯", ["话费流量", "宽带"]),
    ("其他", ["杂项"]),
    ("收入", ["生活费收入", "工资", "奖金", "兼职", "理财"]),
]
MOTIVES = ["独自消费", "社交消费", "为他人消费"]   # 消费场景（互斥穷尽）
CHANNELS = ["微信零钱", "零钱通", "支付宝余额", "余额宝", "现金", "校园卡"]


def get_conn(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str  # 统一按 UTF-8 处理文本，支持中文用户名
    conn.execute("PRAGMA encoding='UTF-8';")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_accounts_conn():
    """账户库连接（accounts + sessions）。"""
    return get_conn(ACCOUNTS_DB)


def get_user_db_path(uid):
    """指定用户的业务库文件路径：data/{uid}.db"""
    return os.path.join(DATA_DIR, "{}.db".format(uid))


def delete_user_db(uid):
    """删除指定用户业务库文件（不存在则忽略）。"""
    path = get_user_db_path(uid)
    if os.path.exists(path):
        os.remove(path)


def get_user_conn(uid):
    """指定用户业务库连接。"""
    return get_conn(get_user_db_path(uid))


# ---- 账户库（accounts / sessions）----
def init_accounts_db():
    """初始化账户库结构：用户表 + 会话表。幂等，可重复调用。"""
    conn = get_accounts_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT,
            user_agent TEXT,
            FOREIGN KEY (user_id) REFERENCES accounts(id)
        );
    """)
    conn.commit()
    conn.close()


def init_user_db(uid):
    """初始化指定用户的业务库（星型模型所有表）。幂等，可重复调用。"""
    conn = get_user_conn(uid)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dim_category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER,
            level INTEGER NOT NULL CHECK(level IN (1,2,3)),
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (parent_id) REFERENCES dim_category(id)
        );
        CREATE TABLE IF NOT EXISTS dim_motive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS dim_channel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            balance REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS records (
            uuid TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            amount REAL NOT NULL,
            category_id INTEGER NOT NULL,
            motive_id INTEGER,
            channel_id INTEGER,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (category_id) REFERENCES dim_category(id),
            FOREIGN KEY (motive_id) REFERENCES dim_motive(id),
            FOREIGN KEY (channel_id) REFERENCES dim_channel(id)
        );
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, category_id, month),
            FOREIGN KEY (category_id) REFERENCES dim_category(id)
        );
        CREATE TABLE IF NOT EXISTS channel_calibrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            before REAL NOT NULL,
            after REAL NOT NULL,
            delta REAL NOT NULL,
            date TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (channel_id) REFERENCES dim_channel(id)
        );
        CREATE INDEX IF NOT EXISTS idx_dim_category_parent ON dim_category(parent_id);
        CREATE INDEX IF NOT EXISTS idx_records_date ON records(date);
        CREATE INDEX IF NOT EXISTS idx_records_category ON records(category_id);
        CREATE INDEX IF NOT EXISTS idx_records_channel ON records(channel_id);
    """)
    conn.commit()
    conn.close()


def seed_user_db(uid):
    """写入默认种子：三级分类树（一级场景 + 二级子项）、三条消费场景、六个渠道。

    幂等：仅在对应表为空时补插，不会重复插入，也不会复活用户已删除的项。
    """
    conn = get_user_conn(uid)
    try:
        # 分类树：仅当没有一级场景时种入完整预设树
        has_scene = conn.execute("SELECT 1 FROM dim_category WHERE level=1 LIMIT 1").fetchone()
        if not has_scene:
            scene_order = 0
            for scene, subs in SCENES:
                scene_order += 1
                cur = conn.execute(
                    "INSERT INTO dim_category (name, parent_id, level, sort_order) VALUES (?,NULL,1,?)",
                    (scene, scene_order))
                scene_id = cur.lastrowid
                for i, sub in enumerate(subs, 1):
                    conn.execute(
                        "INSERT INTO dim_category (name, parent_id, level, sort_order) VALUES (?,?,2,?)",
                        (sub, scene_id, i))
        # 消费场景：仅在为空时种入
        if not conn.execute("SELECT 1 FROM dim_motive LIMIT 1").fetchone():
            for i, m in enumerate(MOTIVES, 1):
                conn.execute(
                    "INSERT INTO dim_motive (name, sort_order) VALUES (?,?)", (m, i))
        # 渠道：仅在为空时种入（余额默认 0）
        if not conn.execute("SELECT 1 FROM dim_channel LIMIT 1").fetchone():
            for i, c in enumerate(CHANNELS, 1):
                conn.execute(
                    "INSERT INTO dim_channel (name, sort_order, balance) VALUES (?,?,0)",
                    (c, i))
        conn.commit()
    finally:
        conn.close()


def init_user_db_with_seed(uid):
    """一次性完成建库 + 补种子（注册新用户/新增分库时调用）。"""
    init_user_db(uid)
    seed_user_db(uid)