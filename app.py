"""
主应用入口 - 图书馆图书管理系统
增强版：WAL模式、错误处理、安全加固

启动方式:
    python app.py

访问地址:
    http://127.0.0.1:5000
"""

import os
import logging
from flask import Flask, render_template, jsonify, request
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from config import config
from models import db, User, OperationLog
from routes import auth_bp, books_bp, borrow_bp, feedback_bp, achievement_bp, analysis_bp

# CSRF 防护
csrf = CSRFProtect()

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('library.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def create_app(config_name="default"):
    """
    工厂函数创建Flask应用
    便于不同环境使用不同配置
    """
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # 生产环境安全门禁：SECRET_KEY 必须由环境变量提供（在 create_app 内检查而非 config.py
    # 类体中 raise，后者会导致任何未设该环境变量的环境在 import 时就崩溃）
    if config_name == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "生产环境必须设置环境变量 SECRET_KEY"
            "（生成方式：python -c \"import secrets; print(secrets.token_hex(32))\"）"
        )

    # ---- 初始化扩展 ----
    db.init_app(app)
    csrf.init_app(app)  # CSRF 防护，自动保护所有 POST 请求

    # ---- SQLite 优化配置（无 WAL 版本，兼容 PythonAnywhere） ----
    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        with app.app_context():
            from sqlalchemy import event, text

            @event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                """SQLite 连接优化：忙等待、缓存、同步模式"""
                cursor = dbapi_connection.cursor()
                # 忙等待 5 秒，遇到锁时等待而不是立即报错
                cursor.execute("PRAGMA busy_timeout=5000")
                # NORMAL 同步模式：平衡安全性和速度
                cursor.execute("PRAGMA synchronous=NORMAL")
                # 64MB 页缓存（负数表示 KB 数）
                cursor.execute("PRAGMA cache_size=-64000")
                # 使用 DELETE 日志模式（默认，兼容性最好）
                cursor.execute("PRAGMA journal_mode=DELETE")
                # 临时表存内存，提升排序/分组性能
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.close()

            logger.info("SQLite 优化配置已加载（busy_timeout + cache_size + DELETE journal）")

    # ---- Flask-Login 配置 ----
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "请先登录"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ---- 注册蓝图 ----
    app.register_blueprint(auth_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(borrow_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(achievement_bp)
    app.register_blueprint(analysis_bp)

    # ---- 上下文处理器：注入全局模板变量 ----
    @app.context_processor
    def inject_global_vars():
        from flask import request
        from models import Notification, Feedback
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            unread = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            pending_fb = Feedback.query.filter_by(status="pending").count() if current_user.is_admin else 0
            return {
                "unread_count": unread,
                "feedback_pending_count": pending_fb,
            }
        return {"unread_count": 0, "feedback_pending_count": 0}

    # ---- 全局错误处理 ----
    @app.errorhandler(404)
    def page_not_found(e):
        if request_is_api():
            return jsonify({"error": "资源不存在"}), 404
        return render_template("error.html", code=404, message="页面不存在"), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"服务器内部错误: {e}", exc_info=True)
        db.session.rollback()
        if request_is_api():
            return jsonify({"error": "服务器内部错误"}), 500
        return render_template("error.html", code=500, message="服务器内部错误"), 500

    @app.errorhandler(403)
    def forbidden(e):
        if request_is_api():
            return jsonify({"error": "权限不足"}), 403
        return render_template("error.html", code=403, message="权限不足"), 403

    # ---- 请求频率限制（简易版，防止恶意刷接口） ----
    from collections import defaultdict, deque
    from datetime import datetime, timedelta
    request_history = defaultdict(deque)  # {ip: deque of timestamps}
    login_fail_history = defaultdict(deque)  # {ip: deque of failed login timestamps}

    @app.before_request
    def rate_limit():
        """每分钟最多60个请求，防止恶意刷"""
        from flask import request
        if request.endpoint in ('static', None):
            return

        ip = request.remote_addr or "unknown"
        now = datetime.now()
        history = request_history[ip]

        # 清理1分钟前的记录
        while history and (now - history[0]).total_seconds() > 60:
            history.popleft()

        history.append(now)

        if len(history) > 60:  # 1分钟超过60次请求
            logger.warning(f"IP {ip} 请求频率过高: {len(history)} 次/分钟")
            return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # ---- 安全响应头 ----
    @app.after_request
    def set_security_headers(response):
        """为所有响应添加安全头"""
        response.headers['X-Frame-Options'] = 'DENY'  # 防止点击劫持
        response.headers['X-Content-Type-Options'] = 'nosniff'  # 防止 MIME 嗅探
        response.headers['X-XSS-Protection'] = '1; mode=block'  # XSS 防护
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'  # 控制 Referer 泄露
        # 敏感页面禁止缓存
        if request and request.endpoint and 'login' in str(request.endpoint):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
        return response

    # ---- 创建数据库表 ----
    with app.app_context():
        db.create_all()
        # 自动创建管理员账号（首次运行）
        if not User.query.filter_by(username="admin").first():
            # 管理员密码从环境变量读取（无默认值，强制部署时设置）
            admin_password = os.environ.get("ADMIN_PASSWORD")
            if not admin_password:
                logger.warning("⚠️ 未设置 ADMIN_PASSWORD 环境变量，admin 账号将无法登录")
                logger.warning("   请复制 .env.example 为 .env 并设置 ADMIN_PASSWORD")
                admin_password = "change-me-please"  # 占位符，部署后必须改
            admin = User(
                username="admin",
                email="admin@library.com",
                role="admin",
                phone="13800000000",
            )
            admin.set_password(admin_password)
            db.session.add(admin)

            reader = User(
                username="reader",
                email="reader@library.com",
                role="reader",
                phone="13900000000",
            )
            reader.set_password(os.environ.get("READER_PASSWORD", "change-me-please"))
            db.session.add(reader)
            db.session.commit()
            logger.info("初始账号创建成功: admin（密码见环境变量或默认值）")
            logger.warning("⚠️ 请尽快登录修改默认管理员密码！")

    logger.info(f"应用启动完成 (配置: {config_name})")
    return app


def request_is_api():
    """判断是否为API请求"""
    from flask import request
    return request.path.startswith("/api/") or request.content_type == "application/json"


# 创建应用实例
app = create_app(os.environ.get("FLASK_CONFIG", "default"))


if __name__ == "__main__":
    # 默认仅本机访问，避免开发环境 DEBUG 模式下 Werkzeug debugger 暴露到外网
    # 需要外网访问时设置环境变量 HOST=0.0.0.0
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=app.config.get("DEBUG", False))
