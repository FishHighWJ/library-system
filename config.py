"""
配置文件 - 图书馆图书管理系统
集中管理所有配置项，方便修改和维护

安全说明：
- SECRET_KEY 优先从环境变量读取，生产环境务必设置
- 数据库路径可通过 DATABASE_URL 环境变量切换（支持 SQLite/MySQL/PostgreSQL）
- SQLite 使用 DELETE journal + BEGIN IMMEDIATE 方案处理并发
"""

import os

# 项目根目录
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """基础配置类"""

    # Flask 密钥，用于 Session 加密
    # 开发环境使用固定值方便调试；生产环境通过环境变量或 ProductionConfig  override
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "dev-secret-key-DO-NOT-USE-IN-PRODUCTION-a8f3c2b1"
    )

    # 数据库配置
    # 开发环境默认 SQLite；生产环境可通过 DATABASE_URL 切换到 MySQL/PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'library.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 数据库引擎配置
    # 注意：SQLite 使用 NullPool（单文件数据库不支持连接池），
    # 如果切换到 MySQL/PostgreSQL，可启用连接池参数
    SQLALCHEMY_ENGINE_OPTIONS = {}

    # 分页配置
    PER_PAGE = 10

    # 借阅配置
    MAX_BORROW_DAYS = 30          # 最长借阅天数
    MAX_BORROW_COUNT = 5           # 每人最多借阅数量
    OVERDUE_FINE_PER_DAY = 0.5    # 逾期罚款（元/天）

    # 文件上传配置
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

    # 安全配置
    # 生产环境（HTTPS）请将 SESSION_COOKIE_SECURE 设为 True
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 86400  # Session 有效期 24 小时


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    SQLALCHEMY_ECHO = False  # 设为 True 可打印 SQL 语句调试


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False

    # 生产环境密钥：仅从环境变量读取，不提供任何默认值
    # 未设置时 create_app() 会拒绝启动（见 app.py），避免使用已知密钥导致 session 可伪造
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # 生产环境强制开启 Session Cookie 安全标志（需 HTTPS）
    SESSION_COOKIE_SECURE = True

    # 生产环境建议使用 MySQL/PostgreSQL 以支持更高并发
    # 取消下面注释并配置环境变量 DATABASE_URL 即可切换：
    # DATABASE_URL=mysql+pymysql://user:password@host:3306/library_db?charset=utf8mb4


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    DEBUG = True
    # 测试环境使用内存数据库，不污染真实数据
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False  # 测试环境关闭 CSRF 以方便自动化测试
    SECRET_KEY = "test-secret-key-for-unit-tests-only"


# 配置字典，通过 FLASK_CONFIG 环境变量切换
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
