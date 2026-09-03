# SpendLog-Analytics 新分析型记账系统 · 重构方案

## Context（背景与目标）

旧版 SpendLog（`e:/Programmes/SpendLog`）定位是「记录工具」——记完就完了，分析靠人眼看。
新版要重构为一个**分析工具**：记录只是第一步，系统设计目标是让分析自动发生。

本仓库（`e:/Programmes/SpendLog-Analytics`，当前为空）是**全新独立项目**：
- 从本地旧项目（不是云端）借鉴架构与可复用代码（认证/会话/单页 PWA 模式、零第三方依赖）。
- 两版互不干扰：新版沿用旧版「账户库 + 按用户分库」与「Python 标准库 http.server + sqlite3」技术栈，
  但业务库采用**星型模型**（事实表 + 维度表），并与旧版端口错开（新版默认 8090），可同时部署。

已确认的决策：
1. 第三层「具体商家」**记账时内联快捷添加**（顺手记，不需要预先维护）。
2. **收入 + 支出并存**（金额正负号区分）：消费场景仅对「支出」生效，报表聚焦支出，但保留月份结余。
3. 首版**保留用户/会话管理，砍掉 Excel 导出导入与管理后台**。
4. **不设弹性系数维度**；新增 **预算** 与 **渠道余额追踪**。

---

## 一、数据结构（星型模型，按用户分库 `data/{uid}.db`）

### 维度表 `dim_category`（三层级）
| 字段 | 说明 |
|------|------|
| id | 主键（`records` / `budgets` 均引用此 id） |
| name | 名称 |
| parent_id | 父级 id，一级场景该值为 NULL |
| level | 1=场景(大类) / 2=子项(中类) / 3=商家(具体) |
| sort_order | 同级排序 |

记录的 `category_id` 指向**叶子**（选到商家就指商家，否则指子项），场景由层级隐式推导。

**预设分类树（对应默认 seed，建库按此插入）**

```
场景（一级）
├── 餐饮
│   ├── 食堂
│   ├── 外卖
│   ├── 快餐
│   ├── 聚餐
│   └── 奶茶甜点
├── 居住
│   └── 水电物业
├── 交通
│   ├── 地铁公交
│   ├── 打车
│   └── 加油
├── 购物
│   ├── 生活用品
│   ├── 日用品
│   ├── 电子
│   └── 服饰
├── 娱乐
│   ├── 游戏
│   ├── 电影演出
│   └── 运动健身
├── 医疗健康
│   ├── 药品
│   └── 体检
├── 教育
│   ├── 书籍
│   └── 课程
├── 通讯
│   ├── 话费流量
│   └── 宽带
├── 其他
│   └── 杂项
└── 收入
    ├── 生活费收入
    ├── 工资
    ├── 奖金
    ├── 兼职
    └── 理财
```

### 维度表 `dim_motive`（消费场景）
`id / name / sort_order` — 扁平列表，无父子关系。
种子：独自消费 / 社交消费 / 为他人消费。
三标签**互斥穷尽**：每一笔支出有且只有一种「消费场景」，用户记账时只需回忆「当时有谁」这一客观事实，不需做心理分析。
默认选中「独自消费」（判断标准：花钱时只有自己）。**首版不开放新增场景**——三标签已穷尽所有客观场景，报表页只读展示。

### 维度表 `dim_channel`（渠道）
`id / name / sort_order / balance` — 扁平列表，无父子层级；用户可记账时内联新增。
`balance`（REAL，默认 0）为**当前余额**：记一笔时自动更新（`balance += amount`，支出为负即减、收入为正即加），余额允许为负数、不做拦截。
种子：微信零钱 / 零钱通 / 支付宝余额 / 余额宝 / 现金 / 校园卡。
「记住上一次渠道」由前端实现（读取最近一条记录），不涉及数据结构、无需额外状态表。

### 事实表 `records`
`id(uuid) / user_id / date(原始日期YYYY-MM-DD) / time(HH:MM,可空) / amount(负=支出,正=收入) / category_id / motive_id / channel_id / note / created_at`
- `motive_id` 实际表示**消费场景**（表名/字段名沿用 `motive`，仅语义为消费场景）。
- **时间特征不存库**：日期/时间存原始值，周末·工作日、时段、月初·月末在查询时用 Python 实时派生。
- **记账联动**：新增记录时同步更新对应渠道 `dim_channel.balance`（见「渠道余额追踪」）。

### 预算表 `budgets`
`id / user_id / category_id（指向一级场景）/ month(YYYY-MM) / amount / created_at / updated_at`
- 预算按「用户 × 一级场景 × 月份」唯一，重复设置即覆盖更新金额与 `updated_at`。

### 渠道校准记录表 `channel_calibrations`
`id / user_id / channel_id / before / after / delta / date / note / created_at`
用于「账户余额」模块的**校准**：输入实际余额时，计算调整额 `delta = after - before`，更新渠道余额并写一条校准记录以便追溯。

### 账户库 `accounts`（复用旧版结构）
`id / username / password_hash / created_at / is_admin / is_active`（认证与会话行为沿用旧版 auth.py）。

### 新增行为（维度表可扩展）
| 可新增项 | 新增入口 | 存储 |
| :--- | :--- | :--- |
| 商家（三级分类） | 记账页选择子项后出现「+ 新增商家」 | 写入 `dim_category`（level=3，parent_id=子项 id），**永久保存，下次可直接选复用** |
| 渠道 | 记账页渠道下拉框底部「+ 新建渠道」 | 写入 `dim_channel`（初始 balance=0） |

### 派生时间特征（查询层计算）
- 周末/工作日：date 的 weekday>=5 为周末。
- 时段 period：time 小时 → 凌晨(0-6)/上午(6-12)/下午(12-18)/晚上(18-24)，无 time 记「其他」。
- 月初月中月末 month_part：日 1-10 / 11-20 / 21+。

### 默认 seed（`init_user_db` 建库即种入，新用户开箱可记账）
- `dim_channel`：微信零钱(1) / 零钱通(2) / 支付宝余额(3) / 余额宝(4) / 现金(5) / 校园卡(6)（balance 均 0）
- `dim_motive`：独自消费(1) / 社交消费(2) / 为他人消费(3) —— 消费场景
- `dim_category`：见上方「预设分类树」插入，无弹性值。

不提供上一版迁移：新版从零记账。

---

## 二、后端模块（`script/`，全部 Python 标准库）

| 文件 | 内容 | 来源 |
|------|------|------|
| `server.py` | 路由 + JSON 响应 + 静态文件 + multipart 读取 | 复用旧版，默认端口改 **8090** |
| `db.py` | accounts.db + 按用户建星型库 + 迁移（含 budgets / channel_calibrations） | 账户部分复用旧版，业务库表改写 |
| `auth.py` | 注册/登录/会话/管理员初始化 | **整文件复用旧版**（不依赖业务库结构） |
| `admin.py` | 用户列表/禁用/删除/改密 | 复用旧版精简（保留用户管理，砍后端 UI 层） |
| `categories.py` | 三层分类树 / 增删（用used校验，红=可删灰=不可删）/ reorder（以 id/parent_id 定位） | 旧版扩展为 3 层 |
| `records.py` | 新增一笔（date/time/amount/叶子分类/消费场景/渠道/备注），**联动更新渠道余额** | 改写 |
| `statistics.py` | 多维聚合报表 + 时间特征派生 + 消费分布（均值/中位数） | 改写（核心） |
| `budgets.py` | 预算设置/查询/预算执行报表（预算 vs 实际 vs 结余） | 新增 |
| `balance.py` | 渠道余额查询、余额校准 | 新增 |

### API 设计
- 认证：`/api/auth/register|login|logout|me|password`，`/api/sessions|revoke`（沿旧版）。
- 字典（记账页下拉数据）：`GET /api/motives`（消费场景列表）、`GET /api/channels`（渠道列表，附 `last_used_channel_id`＝最近一条记录所用渠道，供「记住上一次渠道」默认值）。
- 分类：`GET /api/categories`（三层树，返回 id/name/parent_id/level/used）、`POST /api/categories`（add：`{name, parent_id?}`，无 parent_id 即一级）、`DELETE /api/categories?id=`、`POST /api/categories/reorder`（`{ids, parent_id?}` 同级排序）。
- 记账：`POST /api/records`（`{date, time?, amount, category_id(叶子), motive_id, channel_id, note?}`，写记录并更新渠道余额）。
- 预算：`GET /api/budget?month=`（查某月各一级场景预算）、`POST /api/budget`（设置/覆盖：`{category_id, month, amount}`）。
- 余额：`GET /api/balance`（各渠道当前余额）、`POST /api/balance/calibrate`（`{channel_id, balance}`，输入目标余额，自动生成校准记录）。
- 报表核心：`GET /api/report/aggregate?month=YYYY-MM&category_id=&motive=&channel=&is_weekend=&period=&month_part=`，返回：
  - `total`（收入/支出/结余）
  - `scene_breakdown`（`category_id` 为空按一级场景；为一级按该场景子项；为二级按该子项商家——**恰好实现「点击下钻」**）
  - `scenario_breakdown`（按消费场景：独自/社交/为他人 分组；即原 `motive_breakdown` 改名）
  - `channel_breakdown`（按渠道名称分组）
  - `budget`（预算执行：一级场景预算 vs 实际 vs 结余，超支可下钻二级）
  - `spending_dist`（消费分布：按一级/叶子分类金额排序 + 中位数/平均数，无自动标记）
  - `records`（匹配当前全部筛选的明细，供底部面板展示）

  时间特征筛选 `is_weekend/period/month_part` 与渠道筛选 `channel` 交叉作用于所有聚合与明细——满足「场景×渠道×消费场景」任意组合。

### 消费场景只对支出（amount<0）统计；余额用全部。

---

## 三、前端（`static/`，原生 HTML/CSS/JS，无图表库，颜色方案复用旧版）

单页 PWA：登录遮罩（沿用旧版）+ 底部 Tab「记账 | 报表」+ 汉堡抽屉（会话管理/改密/退出/管理员用户列表）。

### 记账页（多维度选择器，默认值覆盖 80%）
1. 金额（正负号）+ 日期 + 时间
2. **场景（必选）** → 子项 chips；选了含商家的子项后出现 **商家 chips + 「＋ 新增商家」内联快捷添加**（写入 `dim_category` 三级并永久保存，下次可直接选，无需重复新增）
3. **消费场景下拉**：默认「独自消费」（判断标准：花钱时只有自己）；首版三个标签已穷尽客观场景，**不开放新增场景**
4. **渠道下拉**：默认「上一次渠道」（前端读取最近一条记录）；下拉框底部 **「+ 新建渠道」** 入口，输入名称后写入 `dim_channel`（初始余额 0）永久复用
5. 备注 + 保存（保存后渠道余额自动增减）

### 报表页（模块化，聚焦分析）
- 月份选择器；**默认「本月 + 不限时间特征」**，用户主动点 chips 才筛选（周末/工作日、时段、月初月中月末）
- 渠道筛选器（chips/下拉）：**按具体渠道名称直接筛选，不做一级归并**——例如选「零钱通」只展示该渠道的记录，报表中的场景/消费场景聚合也随之变化
- **预算执行**：按一级场景列出 预算 vs 实际 vs 结余，超支高亮；点击某场景可下钻到二级分类明细
- **消费分布**：按一级/叶子分类金额降序列表，展示各分类金额 + 记录数 + **中位数/平均数**（仅展示，不自动标记异常）
- **账户余额**：各渠道当前余额列表 + 「校准」入口（输入实际余额 → `POST /api/balance/calibrate`，自动生成校准记录）
- **钱去哪了** → 场景柱状/饼块；点击场景 → 下钻子项 → 点击子项 → 下钻商家 → 商家即为叶子转明细
- **怎么花的** → 消费场景分布（独自 / 社交 / 为他人）；点击任一场景 → 列出对应明细
- 顶部面包屑（场景>子项>商家）可逐级点击返回
- 底部明细表：日期/金额/分类/商家/消费场景/渠道/备注，随当前筛选联动刷新

---

## 四、部署配置（复用旧版 Dockerfile + 新增 compose）
- `Dockerfile`：沿用旧版（python:3.12-slim、TZ=Asia/Shanghai、`COPY script/ static/`、VOLUME /app/data、HEALTHCHECK、`CMD ["python","script/server.py"]`）。默认端口改 8090。
- `docker-compose.yml`（新增）：服务 spendlog-analytics，映射 `8090:8090`、卷 `spendlog-analytics-data:/app/data`。
- `.dockerignore` / `.gitignore`：沿用旧版。
- 新版跑 8090，旧版仍跑 8080 → 两版可同时访问不同 URL，符合「互不干扰、用户切换」。

---

## 五、开发顺序（从简到繁，按此实现）
1. `db.py`：星型模型建表 + 账户库 + 默认 seed（含 `budgets` + `channel_calibrations` + `dim_channel.balance`）
2. `auth.py` / `admin.py` / `categories.py`：认证与三层分类管理
3. `records.py` + 记账页（无弹性滑块，记账联动渠道余额）：能记一笔
4. `statistics.py` + 报表页（预算执行 + 消费分布）：核心报表
5. `budgets.py` + `balance.py`：预算执行报表 + 渠道余额展示与校准
6. 下钻能力：点击图表区块逐级下钻到明细
7. 时间筛选（周末/工作日、时段、月初月末）
8. 多维交叉筛选（场景×渠道×消费场景任意组合）与整体 UI 打磨

## 六、验证（Verification）
- 本地冒烟：`python script/server.py --port 8090`
  - 注册/登录拿 token → `POST /api/records` 记支出与收入，确认对应渠道余额同步增减
  - `POST /api/budget` 设置某月预算 → `GET /api/report/aggregate?month=…` 检查 total/scene/scenario/channel/budget/spending_dist
  - `POST /api/balance/calibrate` 校准余额 → `GET /api/balance` 确认余额与校准记录生成
  - 带 `scene=&sub=` 下钻、带 `is_weekend=&period=`、带 `channel=` 交叉筛选
  - 前端浏览器验证：记账保存、预算执行/消费分布/账户余额渲染、点击下钻、面包屑返回、抽屉会话/退出
- 分类管理：红=可删灰=被用不可删；记账内联新增商家
- 可选：`docker build` 后 `docker-compose up -d` 冒烟 8090