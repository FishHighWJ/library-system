# 图书馆图书管理系统

> 个人项目 | Python Flask + SQLite + Bootstrap + ECharts + scikit-learn
>
> 支持图书管理、借阅归还、用户反馈、成就系统、游戏化阅读激励，**并集成数据分析模块（ECharts 可视化看板 / RFM 用户分群 / 借阅量预测）**

## 项目简介

一个基于 Flask Web 框架的图书馆图书管理系统，实现图书管理、用户管理、借阅管理、用户反馈、游戏化成就等完整功能，并在 v2 版本新增**数据分析模块**：ECharts 可视化看板、RFM 用户分群、基于线性回归的借阅量预测。系统采用蓝图模块化架构 + services 分层，支持管理员和读者两种角色。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | Flask 3.x | Python 轻量级 Web 框架 |
| ORM | Flask-SQLAlchemy 3.0.5 | 数据库 ORM 映射 |
| 认证 | Flask-Login | 用户登录状态管理 |
| 数据库 | SQLite | 轻量级文件数据库，免安装 |
| 前端 | Bootstrap 5 + Jinja2 + ECharts 5.4 | 响应式 UI + 模板引擎 + 数据可视化 |
| 数据分析 | scikit-learn + numpy + pandas | 线性回归预测 + 数据聚合 |
| 语言 | Python 3.8+ | 后端逻辑 |
| 版本控制 | Git | 版本管理 |

## 功能模块

### 读者功能
- 注册 / 登录 / 退出
- 浏览图书列表（搜索、分类筛选、分页）
- 查看图书详情与借阅记录
- 借阅图书（限制：每人最多 5 本，借期 30 天）
- 归还图书（逾期自动计算罚款）
- 查看个人借阅记录
- 个人中心（借阅统计）
- 提交反馈与图书荐购
- 查看反馈处理进度与回复
- 站内通知中心
- **成就系统**：等级、经验值、成就徽章、排行榜
- **阅读鼓励**：借还书时随机推送名人名言

### 管理员功能
- 读者全部功能
- 添加 / 编辑 / 删除图书
- 分类管理（增删查）
- 查看全部借阅记录（按状态筛选）
- 数据看板（统计概览、热门图书 TOP5、借阅趋势、分类统计）
- 用户管理（启用/禁用用户）
- 反馈管理（查看、回复、转图书上架）
- 操作审计日志（记录所有关键操作）
- 成就中心管理

### 数据分析模块（v2 新增）

本模块将项目从"Web 全栈"升级为"带数据分析能力的全栈项目"，是数据科学专业背景下的核心加分项。

#### 1. ECharts 可视化看板（`/dashboard`）
- **7 天借阅趋势**：折线图 + 面积填充，按日聚合 + 缺日补零
- **分类借阅分布**：饼图，展示各分类馆藏占比
- **热门借阅 TOP5**：横向条形图，前三名红/橙/黄色高亮
- **操作日志与近期借阅**：保持表格（事件列表非聚合数据）
- **局部刷新**：原 `window.location.reload()` 改为 `fetch("/dashboard/api/data")`，避免整页刷新销毁 ECharts 实例；JSON 端点与模板初始渲染同源（`_collect_dashboard_metrics` 共享）

#### 2. RFM 用户分群（`/analysis/rfm`）
将电商 RFM 模型迁移到图书馆场景：
- **R**ecency = 最近一次借阅距今天数（越小越活跃）
- **F**requency = 累计借阅次数
- **M**onetary → **Breadth** = 借阅涉猎的不同分类数（图书馆无货币维度，以阅读广度替代）
- 按四分位数阈值分 6 群：Champions / Loyal / Potential / At-risk / Lost / Inactive
- 零借阅用户直接归 Inactive，不参与分位计算（避免污染阈值）
- 可视化：散点图（X=Recency Y=Frequency 气泡=Breadth）+ 饼图 + 用户明细表

> **设计决策**：M 维度选"涉猎分类数"而非"借阅时长"——后者依赖 return_date（活跃借阅为 NULL 会引入偏差）；"按时归还率"是质量指标与 F 语义重叠。广度与 e-commerce 的消费广度语义一致，且与 F 正交。

#### 3. 借阅量预测（`/analysis/prediction`）
- **模型**：线性回归（趋势项 + 星期二~星期日 one-hot，以周一为基准防共线性）
- **理由**：图书馆流量有强星期效应，线性回归能捕捉周季节性且系数可解释；ARIMA 对小数据过度工程需平稳性检验
- **置信区间**：残差标准差 × 1.96（95% CI，统计上诚实）
- **可视化**：实际值（实线）+ 历史拟合（虚线）+ 预测值（虚线）+ CI 阴影带；星期系数卡片可现场演示"周末 vs 工作日"效应
- **边界**：历史不足 14 天返回 error，不强行预测

### 安全与并发特性
- 密码加密存储（Werkzeug generate_password_hash）
- **CSRF 防护**（Flask-WTF，所有 POST 请求自动验证 Token）
- **密码复杂度校验**（至少8位，含大小写字母和数字）
- **登录失败锁定**（5次失败后锁定15分钟，防止暴力破解）
- **Session 安全**（HttpOnly + 登录后重新生成 Session + 有效期控制）
- **安全响应头**（X-Frame-Options / X-Content-Type-Options / X-XSS-Protection / Referrer-Policy）
- **生产环境独立密钥**（64字节随机 SECRET_KEY，非默认值）
- 请求频率限制（60次/分钟，防刷接口）
- BEGIN IMMEDIATE + 指数退避重试（解决 SQLite 并发锁问题）
- with_for_update 行级锁（迁移到 MySQL/PostgreSQL 后自动生效）
- 操作审计日志（可追溯所有关键操作）

## 快速开始

### 环境准备

```bash
# 1. 确保已安装 Python 3.8+
python --version

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量（生产环境必做，本地开发可跳过）
cp .env.example .env
# 编辑 .env 填入真实密钥
```

### 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SECRET_KEY` | 无（必须设置） | Flask Session 加密密钥，生产环境必须替换为 64 字节随机字符串 |
| `ADMIN_PASSWORD` | 无（必须设置） | 管理员初始密码，仅首次启动创建 admin 账号时使用 |
| `READER_PASSWORD` | change-me-please | 读者初始密码，仅首次启动创建 reader 账号时使用 |
| `FLASK_CONFIG` | development | 配置环境：development / production / testing |
| `DATABASE_URL` | sqlite:///library.db | 数据库连接，可切换 MySQL/PostgreSQL |
| `SESSION_SECURE` | false | 生产环境 HTTPS 设为 true |

> ⚠️ 生产环境请务必通过 `.env` 文件或环境变量设置强随机 `SECRET_KEY`，不要使用默认值。
> 生成方式：`python -c "import secrets; print(secrets.token_hex(64))"`

### 启动项目

```bash
# 方式一：直接运行（自动创建数据库和初始账号）
python app.py

# 方式二：先生成测试数据再运行（推荐）
python init_db.py    # 初始化分类、图书、成就、语录等测试数据
python app.py        # 启动服务
```

### 访问系统

打开浏览器访问：http://127.0.0.1:5000

### 测试账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | 见 `.env.example` 中的 `ADMIN_PASSWORD` |
| 读者 | reader | 见 `.env.example` 中的 `READER_PASSWORD` |

> ⚠️ 部署到生产环境前请务必通过环境变量 `ADMIN_PASSWORD` / `READER_PASSWORD` 设置强密码！
> 
> 也可登录后在个人中心修改密码。

## 项目结构

```
library_system/
├── app.py                 # 主应用入口（工厂函数、蓝图注册、全局配置）
├── config.py              # 配置文件（开发/生产环境切换）
├── models.py              # 数据模型定义
├── utils.py               # 工具函数（db_retry、log_operation、begin_immediate）
├── init_db.py             # 数据库初始化脚本（测试数据）
├── requirements.txt       # Python 依赖清单
├── wsgi.py                # WSGI 入口（PythonAnywhere 部署用）
├── README.md              # 项目文档
├── routes/                # 路由模块（蓝图 Blueprint，路由层薄：仅鉴权+渲染）
│   ├── __init__.py        # 路由包初始化
│   ├── auth.py            # 认证路由（注册/登录/登出/个人中心）
│   ├── books.py           # 图书管理路由（CRUD/搜索/分类）
│   ├── borrow.py          # 借阅管理路由（借书/还书/看板/dashboard JSON 端点）
│   ├── feedback.py        # 反馈路由（意见建议/图书荐购/通知）
│   ├── achievement.py     # 成就路由（等级/经验/成就/排行榜）
│   └── analysis.py        # 数据分析路由（RFM 分群/借阅预测）
├── services/              # 业务逻辑服务层（关注点分离，复杂逻辑下沉）
│   ├── __init__.py
│   ├── rfm_service.py     # RFM 计算 + 四分位分群
│   └── forecast_service.py # 借阅量预测（线性回归 + CI）
├── templates/             # Jinja2 模板
│   ├── base.html          # 基础模板（导航栏/页脚/ECharts CDN/Flash消息）
│   ├── index.html         # 图书列表首页
│   ├── login.html         # 登录页
│   ├── register.html      # 注册页
│   ├── book_detail.html   # 图书详情页
│   ├── book_form.html     # 添加/编辑图书表单
│   ├── my_borrows.html    # 我的借阅记录
│   ├── all_records.html   # 全部借阅记录（管理员）
│   ├── dashboard.html     # 数据看板（ECharts 可视化，管理员）
│   ├── rfm_analysis.html  # RFM 用户分群（scatter+pie+表格）
│   ├── borrow_prediction.html # 借阅量预测（实际/拟合/预测+CI）
│   ├── user_list.html     # 用户管理（管理员）
│   ├── categories.html    # 分类管理（管理员）
│   ├── profile.html       # 个人中心
│   ├── feedback_form.html # 反馈/荐购提交页
│   ├── feedback_list.html # 我的反馈列表
│   ├── feedback_detail.html # 反馈详情
│   ├── feedback_manage.html # 反馈管理（管理员）
│   ├── notifications.html # 站内通知中心
│   ├── achievement_center.html # 成就中心
│   ├── ranking.html       # 阅读排行榜
│   └── error.html         # 错误页面
├── static/                # 静态资源
│   ├── css/style.css      # 自定义样式
│   └── js/main.js         # 前端交互脚本（看板 fetch 局部刷新）
├── tests/                 # 单元测试
│   ├── __init__.py
│   ├── test_basic.py      # 基础测试（密码校验/模型/安全头/CSRF）
│   ├── test_analysis.py   # 数据分析测试（RFM 分群/预测/模型评估/召回闭环）
│   └── test_integration.py # 集成测试（认证/图书/借阅/反馈/分析路由全流程）
└── library.db             # SQLite 数据库文件（运行后自动生成，已 gitignore）
```

## 数据库设计

### 数据表一览

| 表名 | 说明 | 主要字段 |
|------|------|----------|
| users | 用户表 | id, username, email, password_hash, role, is_active |
| categories | 分类表 | id, name, description |
| books | 图书表 | id, isbn, title, author, publisher, price, total_count, available_count, category_id |
| borrow_records | 借阅记录 | id, user_id, book_id, borrow_date, due_date, return_date, status, fine, version |
| operation_logs | 操作审计 | id, user_id, action, target_type, target_id, detail, ip_address |
| feedbacks | 用户反馈 | id, user_id, feedback_type, title, content, status, admin_reply |
| notifications | 站内通知 | id, user_id, notification_type, title, content, is_read |
| reading_stats | 阅读统计 | id, user_id, level, exp, title, total_books_borrowed, streak |
| achievements | 成就定义 | id, name, description, condition_type, condition_value, reward_exp |
| user_achievements | 用户成就 | id, user_id, achievement_id, earned_at |
| encouraging_quotes | 鼓励语录 | id, content, author, category, min_level, max_level |

## 部署

### 本地运行

```bash
python app.py
```

### PythonAnywhere 部署

1. 注册 PythonAnywhere 账号
2. 创建 Web App（选择 Flask + Python 3.x）
3. 上传项目文件到服务器
4. 修改 WSGI 配置文件指向你的 app
5. 安装依赖：`pip install -r requirements.txt --user`
6. Reload 应用

### Docker 部署（推荐）

```bash
# 1. 准备环境变量（生产环境务必修改 SECRET_KEY 与 ADMIN_PASSWORD）
cp .env.example .env
# 编辑 .env 填入真实的密钥与密码

# 2. 一键构建并启动
docker-compose up --build -d

# 3. 访问 http://localhost:5000
# 4. 查看日志
docker-compose logs -f library

# 5. 停止
docker-compose down
```

**Docker 部署特性**：
- 基于 `python:3.11-slim` 精简镜像，构建后约 400MB
- 数据库文件挂载到宿主机 `./data/library.db`，容器重建不丢数据
- 健康检查：每 30 秒探测 `/login`，3 次失败自动重启
- 环境变量从 `.env` 读取，密钥不写死在镜像中

> ⚠️ 生产环境请务必通过 `.env` 文件设置强随机 `SECRET_KEY`，不要使用默认值。

## 开发流程

### 1. 需求分析
明确系统功能模块与角色权限

### 2. 数据库设计
设计表结构、字段、外键关系

### 3. 后端开发
- 搭建 Flask 项目骨架
- 定义 SQLAlchemy 数据模型
- 按模块实现路由（蓝图 Blueprint）

### 4. 前端开发
- 基础模板与组件复用
- Bootstrap + Jinja2 渲染页面
- 交互优化与响应式适配

### 5. 测试
- 功能测试（各模块 CRUD）
- 权限测试（管理员 vs 读者）
- 并发测试（借阅竞态条件）
- 边界测试（借阅上限、逾期罚款）
- **覆盖率统计**：`pytest` 自动统计代码覆盖率，当前达到 72%+，含单元测试 + 关键路径集成测试

```bash
# 运行全部测试并统计覆盖率
pytest

# 仅运行数据分析模块测试
pytest tests/test_analysis.py -v

# 查看覆盖率 HTML 报告（浏览器打开 htmlcov/index.html）
pytest && start htmlcov/index.html
```

### 6. 部署上线
- 本地联调验证
- 生产环境部署
- 监控与维护

## 开发环境

- Python: 3.8+（兼容 3.13）
- Flask: 3.x
- Flask-SQLAlchemy: 3.0.5
- SQLAlchemy: >=2.0.36（兼容 Python 3.13）
- Flask-WTF: >=1.2.0（CSRF 防护）
- scikit-learn: >=1.3（借阅量预测线性回归）
- numpy: >=1.24 / pandas: >=2.0（数据聚合）
- ECharts: 5.4.3（CDN 引入，前端可视化）
- 编辑器: VS Code / PyCharm
- 版本控制: Git + GitHub/Gitee

## 注意事项

- 本项目使用 SQLite，适合小规模部署；高并发场景建议迁移至 MySQL/PostgreSQL
- 默认账号密码仅用于开发测试，生产环境请务必修改
- `SECRET_KEY` 请通过环境变量配置，不要硬编码在代码中
- 数据库文件 `library.db` 已加入 `.gitignore`，不会被提交到版本库

## License

MIT - 软件工程课程项目
