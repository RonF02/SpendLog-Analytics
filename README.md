# SpendLog-Analytics

分析型记账 PWA。以**星型模型**组织记账数据，围绕「场景 → 子项」分类、消费场景、渠道与预算，提供多维聚合报表与下钻筛选，全部数据按用户存储于独立的 SQLite 库中。

## 功能特性

- **记账**：场景 → 子项 →（三级商家）分类体系，长按/右键删除、拖拽排序，消费场景 + 渠道（可新建），支出/收入金额切换，记录联动渠道余额。
- **多维报表**：收入 / 支出 / 结余，场景、消费场景、渠道、消费分布、预算执行等模块；「钱去哪了」支持下钻到叶子。
- **筛选与下钻**：可折叠筛选面板支持**同一维度多值复选**，选中项以**颜色**提示；下钻到叶子场景时逐条列出具体消费条目，点击即可**定位到记录明细**的对应行。
- **在线编辑**：记录明细中可直接修改日期 / 时间 / 金额 / 分类 / 消费场景 / 渠道 / 备注，并自动联动渠道余额。
- **数据能力**：Excel 导入/导出（含分类全路径）、预算设置、渠道余额校准、多用户独立 SQLite 库。
- **PWA**：离线可用，滚动安装在手机/桌面。

## 技术栈

- 后端：Python 标准库（`http.server` + `sqlite3`），无第三方依赖
- 前端：原生 HTML / CSS / JavaScript，渐进式 Web App（PWA，离线可用）
- 存储：SQLite（账户库 `data/accounts.db` + 每用户业务库 `data/{uid}.db`）
- 部署：Docker / Docker Compose

## 快速启动（本地）

```bash
# 启动服务（默认端口 8090）
python script/server.py --port 8090
```

访问 http://localhost:8090，首次使用「注册」创建账号。管理员账号内置（`admin`），可用于用户与会话管理。

## Docker 部署

```bash
docker compose up -d
```

- 服务名：`spendlog-analytics`
- 端口：`8090:8090`
- 数据卷：`spendlog-analytics-data:/app/data`
- 时区：`Asia/Shanghai`

## 目录结构

```
script/           后端：server / db / auth / admin / categories / records / statistics / budgets / balance
static/           前端：index.html / style.css / manifest.webmanifest / sw.js / icons
docs/             重构方案与阶段计划
```

## API 概览

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/api/auth/register` | 注册（自动建业务库并播种） |
| POST | `/api/auth/login` | 登录，返回 token |
| GET  | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/logout` | 登出 |
| GET  | `/api/categories` | 分类树（含 `used` 可删标记） |
| POST | `/api/categories` | 新增分类 |
| DELETE | `/api/categories?id=` | 删除（被引用或子项未删则拒绝） |
| POST | `/api/categories/reorder` | 同级排序 |
| GET  | `/api/motives` | 消费场景列表 |
| GET  | `/api/channels` | 渠道列表 + 上次渠道 |
| POST | `/api/channels` | 新建渠道 |
| POST | `/api/records` | 记账（联动渠道余额） |
| GET  | `/api/report/aggregate` | 月度聚合报表（多维可组合筛选/下钻） |
| GET  | `/api/budget` | 查该月预算 |
| POST | `/api/budget` | 设置/覆盖预算 |
| GET  | `/api/balance` | 各渠道余额 |
| POST | `/api/balance/calibrate` | 校准渠道余额 |
| GET  | `/api/sessions` | 会话管理 |
| POST | `/api/sessions/revoke` | 强制下线 |
| GET/POST | `/api/admin/*` | 管理员：用户、会话管理 |

`/api/report/aggregate` 支持参数：`month`(必选, YYYY-MM)、`category_id`、`motive`、`channel`、`is_weekend`、`period`、`month_part`，可任意组合。

## 数据模型

- `dim_category`：分类（level 1/2/3，`parent_id` 自关联）
- `dim_motive`：消费场景（独自 / 社交 / 为他人，固定三条）
- `dim_channel`：渠道（含 `balance`）
- `records`：事实表（date / time / amount / category / motive / channel / note）
- `budgets`：预算（`UNIQUE(user_id, category_id, month)`）
- `channel_calibrations`：余额校准历史（before / after / delta）

> 收入类分类不参与消费统计；「余额」统计使用全部金额，支出聚合仅统计支出。