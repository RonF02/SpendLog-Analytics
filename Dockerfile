# SpendLog-Analytics · 分析型记账（局域网 PWA）
# 后端仅使用 Python 标准库（http.server + sqlite3），无第三方依赖。
# 构建：docker build -t spendlog-analytics .
# 运行：docker run -d -p 8090:8090 -v spendlog-analytics-data:/app/data spendlog-analytics

FROM python:3.12-slim

WORKDIR /app

# 时区设为东八区，保持一致的时间戳（默认容器时区为 UTC）
ENV TZ=Asia/Shanghai

# 拷贝后端与前端静态资源
COPY script/ ./script/
COPY static/ ./static/

# 数据目录（运行时自动创建，挂载为卷以便持久化）
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8090

# 冒烟健康检查：页面返回 200 即视为存活
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/',timeout=3).status==200 else 1)" || exit 1

# 默认监听 0.0.0.0:8090；如需改端口可覆盖：python script/server.py --port 9000
CMD ["python", "script/server.py"]