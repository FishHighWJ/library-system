"""
认证路由 - 用户注册、登录、登出
使用 Flask-Login 管理会话状态
安全增强：密码复杂度校验、登录失败限制、Session 重新生成
"""

import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, BorrowRecord

auth_bp = Blueprint("auth", __name__)


def validate_password(password):
    """
    密码复杂度校验
    要求：至少8位，包含大小写字母和数字
    返回: (True, "") 或 (False, 错误信息)
    """
    if len(password) < 8:
        return False, "密码至少需要8位"
    if not re.search(r'[A-Z]', password):
        return False, "密码需要包含至少一个大写字母"
    if not re.search(r'[a-z]', password):
        return False, "密码需要包含至少一个小写字母"
    if not re.search(r'\d', password):
        return False, "密码需要包含至少一个数字"
    return True, ""


def check_login_lockout(ip):
    """
    检查 IP 是否因登录失败过多被锁定
    返回: (True, "") 可以尝试登录 / (False, 错误信息) 已被锁定
    """
    from app import app
    # 获取 app 实例中的 login_fail_history
    # 这里用 session 来跟踪失败次数（简化版）
    fail_key = f"login_fails_{ip}"
    lock_key = f"login_lock_{ip}"
    
    from datetime import datetime, timedelta
    lock_until = session.get(lock_key)
    if lock_until:
        lock_time = datetime.fromisoformat(lock_until)
        if datetime.now() < lock_time:
            remain = int((lock_time - datetime.now()).total_seconds() / 60) + 1
            return False, f"登录失败次数过多，请 {remain} 分钟后再试"
        else:
            # 锁定过期，清除记录
            session.pop(lock_key, None)
            session.pop(fail_key, None)
    
    fails = session.get(fail_key, 0)
    if fails >= 5:
        lock_time = datetime.now() + timedelta(minutes=15)
        session[lock_key] = lock_time.isoformat()
        return False, "登录失败次数过多，已锁定15分钟"
    
    return True, ""


def record_login_failure(ip):
    """记录一次登录失败，达到5次自动锁定15分钟"""
    from datetime import datetime, timedelta
    fail_key = f"login_fails_{ip}"
    lock_key = f"login_lock_{ip}"
    fails = session.get(fail_key, 0) + 1
    session[fail_key] = fails
    if fails >= 5:
        lock_time = datetime.now() + timedelta(minutes=15)
        session[lock_key] = lock_time.isoformat()
    return fails


def clear_login_failures(ip):
    """登录成功后清除失败记录"""
    session.pop(f"login_fails_{ip}", None)
    session.pop(f"login_lock_{ip}", None)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """用户注册"""
    if current_user.is_authenticated:
        return redirect(url_for("books.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        phone = request.form.get("phone", "").strip()

        # ---- 输入验证 ----
        if not username or not email or not password:
            flash("请填写所有必填项", "danger")
            return render_template("register.html")

        if len(username) < 3 or len(username) > 20:
            flash("用户名长度需在3-20个字符之间", "danger")
            return render_template("register.html")

        # 密码复杂度校验
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "danger")
            return render_template("register.html")

        if password != confirm:
            flash("两次密码输入不一致", "danger")
            return render_template("register.html")

        # ---- 唯一性检查 ----
        if User.query.filter_by(username=username).first():
            flash("用户名已被注册", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("邮箱已被注册", "danger")
            return render_template("register.html")

        # ---- 创建用户 ----
        user = User(username=username, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("注册成功，请登录", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """用户登录"""
    if current_user.is_authenticated:
        return redirect(url_for("books.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr or "unknown"

        # 检查是否被锁定
        can_login, lock_msg = check_login_lockout(ip)
        if not can_login:
            flash(lock_msg, "danger")
            return render_template("login.html")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash("账号已被禁用，请联系管理员", "danger")
                return render_template("login.html")

            # 清除登录失败记录
            clear_login_failures(ip)

            # Session Fixation 防护：登录成功后重新生成 Session
            session.clear()
            login_user(user)

            flash(f"欢迎回来，{user.username}！", "success")
            # 管理员跳转看板，读者跳转首页
            if user.is_admin:
                return redirect(url_for("borrow.dashboard"))
            return redirect(url_for("books.index"))
        else:
            # 记录登录失败
            fails = record_login_failure(ip)
            remaining = 5 - fails
            if remaining > 0:
                flash(f"用户名或密码错误，还可尝试 {remaining} 次", "danger")
            else:
                flash("登录失败次数过多，已锁定15分钟", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    """用户登出"""
    logout_user()
    flash("已安全退出", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile")
@login_required
def profile():
    """个人中心"""
    my_borrows = (
        BorrowRecord.query
        .filter_by(user_id=current_user.id)
        .order_by(BorrowRecord.borrow_date.desc())
        .all()
    )
    return render_template("profile.html", borrows=my_borrows)
