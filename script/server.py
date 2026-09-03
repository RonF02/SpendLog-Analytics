# -*- coding: utf-8 -*-
"""SpendLog-Analytics 分析型记账 PWA —— HTTP 服务与路由。

部署：0.0.0.0:8090（与旧版 8080 错开，可同时运行互不干扰）。

基于 Python 标准库 http.server + sqlite3，无第三方依赖。
业务逻辑集中在独立模块（下方 import）：
  auth / admin      —— 认证、会话、管理员（阶段 2）
  db                —— 数据库连接与初始化
  categories / records / statistics / budgets / balance —— 后续阶段挂载
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from admin import (list_users, change_password, admin_reset_password,
                   set_user_disabled, delete_user,
                   list_sessions as admin_list_sessions,
                   force_logout_session as admin_force_logout)
from auth import (ensure_admin, register, login, logout, check_auth,
                  create_user, list_sessions, revoke_session, delete_account)
from categories import get_categories, add_category, delete_category, reorder_categories
from db import init_accounts_db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（本文件位于 script/）
STATIC_DIR = os.path.join(BASE_DIR, "static")
HOST = "0.0.0.0"
DEFAULT_PORT = 8090


def parse_args():
    parser = argparse.ArgumentParser(description="SpendLog-Analytics 分析型记账服务")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="监听端口（默认 {}）".format(DEFAULT_PORT))
    return parser.parse_args()


def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "SpendLogAnalytics/0.1"

    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _query_param(self, key):
        q = self.path.split("?", 1)
        if len(q) < 2:
            return None
        for part in q[1].split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k == key:
                    return v
        return None

    def _bearer_token(self):
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            return h[7:].strip()
        return None

    def _require_admin(self):
        """管理员鉴权。通过返回用户信息，否则已发错误响应并返回 None。"""
        user = check_auth(self._bearer_token())
        if not user:
            json_response(self, {"code": 1, "message": "未登录或登录已过期"}, 401)
            return None
        if not user["is_admin"]:
            json_response(self, {"code": 403, "message": "无权限"}, 403)
            return None
        return user

    # ---- 路由 ----
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/auth/me":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 1, "message": "未登录或登录已过期"}, 401)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": user})
            return
        if path == "/api/admin/users":
            if not self._require_admin():
                return
            json_response(self, {"code": 0, "message": "ok", "data": list_users()})
            return
        if path == "/api/admin/sessions":
            if not self._require_admin():
                return
            json_response(self, {"code": 0, "message": "ok", "data": admin_list_sessions()})
            return
        if path in ("/", "/index.html"):
            self._serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path.startswith("/api/"):
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            if path == "/api/sessions":
                json_response(self, {"code": 0, "message": "ok",
                                     "data": list_sessions(user["id"], self._bearer_token())})
            elif path == "/api/categories":
                json_response(self, {"code": 0, "message": "ok",
                                     "data": get_categories(user["id"])})
            else:
                json_response(self, {"code": 404, "message": "Not Found"}, 404)
        else:
            self._serve_file(os.path.join(STATIC_DIR, path.lstrip("/")), self._guess_type(path))

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            payload = self._read_json()
        except Exception:
            json_response(self, {"code": 1, "message": "JSON 解析失败"}, 400)
            return
        if path == "/api/auth/login":
            data, err = login(payload.get("username"), payload.get("password"),
                              self.headers.get("User-Agent", ""))
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/auth/register":
            data, err = register(payload.get("username"), payload.get("password"),
                                 payload.get("confirm_password"))
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data}, 201)
            return
        if path == "/api/auth/logout":
            logout(self._bearer_token())
            json_response(self, {"code": 0, "message": "ok"})
            return
        if path == "/api/auth/password":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            data, err = change_password(user["id"], payload.get("old_password"),
                                        payload.get("new_password"), self._bearer_token())
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/sessions/revoke":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            data, err = revoke_session(user["id"], payload.get("token"), self._bearer_token())
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/categories/reorder":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            data, err = reorder_categories(user["id"], payload.get("ids"), payload.get("parent_id"))
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/categories":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            data, err = add_category(user["id"], payload.get("name"), payload.get("parent_id"))
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data}, 201)
            return
        if path.startswith("/api/admin/"):
            if not self._require_admin():
                return
            if path == "/api/admin/users/create":
                data, err = create_user(payload.get("username"), payload.get("password"))
                if err:
                    json_response(self, {"code": 1, "message": err}, 400)
                else:
                    json_response(self, {"code": 0, "message": "ok", "data": data}, 201)
                return
            if path == "/api/admin/sessions/revoke":
                data, err = admin_force_logout(payload.get("token"), self._bearer_token())
                if err:
                    json_response(self, {"code": 1, "message": err}, 400)
                else:
                    json_response(self, {"code": 0, "message": "ok", "data": data})
                return
            uid = _to_int(payload.get("user_id"))
            if uid is None:
                json_response(self, {"code": 1, "message": "缺少有效的 user_id"}, 400)
                return
            if path == "/api/admin/users/reset_password":
                data, err = admin_reset_password(uid, payload.get("new_password"))
            elif path == "/api/admin/users/disable":
                data, err = set_user_disabled(uid, True)
            elif path == "/api/admin/users/enable":
                data, err = set_user_disabled(uid, False)
            else:
                json_response(self, {"code": 1, "message": "Not Found"}, 404)
                return
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        json_response(self, {"code": 404, "message": "Not Found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path == "/api/auth/delete":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            data, err = delete_account(user["id"])
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/admin/users":
            if not self._require_admin():
                return
            uid = _to_int(self._query_param("user_id"))
            if uid is None:
                json_response(self, {"code": 1, "message": "缺少有效的 user_id"}, 400)
                return
            data, err = delete_user(uid)
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        if path == "/api/categories":
            user = check_auth(self._bearer_token())
            if not user:
                json_response(self, {"code": 401, "message": "未登录或登录已过期"}, 401)
                return
            cid = _to_int(self._query_param("id"))
            if cid is None:
                json_response(self, {"code": 1, "message": "缺少有效的分类 id"}, 400)
                return
            data, err = delete_category(user["id"], cid)
            if err:
                json_response(self, {"code": 1, "message": err}, 400)
            else:
                json_response(self, {"code": 0, "message": "ok", "data": data})
            return
        json_response(self, {"code": 404, "message": "Not Found"}, 404)

    # ---- 静态文件 ----
    def _serve_file(self, path, content_type):
        if not os.path.isfile(path):
            json_response(self, {"code": 404, "message": "Not Found"}, 404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 开发期禁用缓存，改动即时生效
        self.end_headers()
        self.wfile.write(body)

    def _guess_type(self, path):
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
            ".ico": "image/x-icon",
            ".webmanifest": "application/manifest+json; charset=utf-8",
        }
        return mime.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


if __name__ == "__main__":
    args = parse_args()
    init_accounts_db()
    ensure_admin()
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    print("SpendLog-Analytics running at http://{}:{}/  ".format(HOST, args.port))
    print("手机访问请使用电脑局域网 IP，例如 http://<局域网IP>:{}/".format(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()