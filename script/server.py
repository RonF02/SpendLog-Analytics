# -*- coding: utf-8 -*-
"""SpendLog-Analytics 分析型记账 PWA —— HTTP 服务骨架（阶段 0）。

部署：0.0.0.0:8090（与旧版 8080 错开，可同时运行互不干扰）。

阶段 0 只搭建「Python 标准库 http.server」架构骨架并清空业务逻辑：
- 提供端口参数（--port，默认 8090）
- 提供 JSON 响应 / 读取、查询参数、Bearer Token、静态文件分发等通用基建
- 业务路由（认证/分类/记账/统计等）将在后续阶段分模块挂载

后续模块容器（按《阶段计划》将要新增）：
  db / auth / admin / categories / records / statistics / budgets / balance
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

    # ---- 路由（阶段 0 仅服务静态页面，业务 API 待挂载）----
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path.startswith("/api/"):
            # 业务接口在后续阶段由各自模块挂载，此处占位返回未实现
            json_response(self, {"code": 501, "message": "API 尚未实现（阶段 0 仅服务静态页面）"}, 501)
        else:
            self._serve_file(os.path.join(STATIC_DIR, path.lstrip("/")), self._guess_type(path))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            json_response(self, {"code": 501, "message": "API 尚未实现（阶段 0 仅服务静态页面）"}, 501)
            return
        json_response(self, {"code": 404, "message": "Not Found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            json_response(self, {"code": 501, "message": "API 尚未实现（阶段 0 仅服务静态页面）"}, 501)
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
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    print("SpendLog-Analytics running at http://{}:{}/  ".format(HOST, args.port))
    print("手机访问请使用电脑局域网 IP，例如 http://<局域网IP>:{}/".format(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()