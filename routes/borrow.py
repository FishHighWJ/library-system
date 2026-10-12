"""
借阅管理路由 - 借书、还书、借阅记录、数据看板
增强版：并发安全、错误处理、审计日志

并发说明：
- SQLite 下 with_for_update() 为空操作（SQLite 不支持 SELECT ... FOR UPDATE）
- 实际并发安全由 @db_retry(use_immediate=True) 中的 BEGIN IMMEDIATE 保证
- 迁移到 MySQL/PostgreSQL 后，with_for_update() 将自动生效
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from sqlalchemy import func, text
from models import db, Book, BorrowRecord, User, OperationLog, Category, EncouragingQuote
from routes.achievement import (
    get_or_create_stat, check_achievements,
    update_streak, update_category_count
)
from utils import db_retry, log_operation

borrow_bp = Blueprint("borrow", __name__)

# 日志记录器
logger = logging.getLogger(__name__)

# 从config读取配置
MAX_BORROW_DAYS = 30
MAX_BORROW_COUNT = 5
OVERDUE_FINE = 0.5


# =================== 借书（并发安全版） ===================

@borrow_bp.route("/borrow/<int:book_id>", methods=["POST"])
@login_required
@db_retry(use_immediate=True)
def borrow_book(book_id):
    """借阅图书 - 增强版，防止并发竞态条件"""
    # SQLite 下 with_for_update() 为空操作，实际靠 BEGIN IMMEDIATE 保证并发安全
    # 迁移到 MySQL/PostgreSQL 后此行锁将自动生效
    book = db.session.query(Book).filter_by(id=book_id).with_for_update().first()
    if not book:
        flash("图书不存在", "danger")
        return redirect(url_for("books.index"))

    # ---- 借阅前检查（在锁内执行，确保数据一致） ----
    if book.available_count <= 0:
        flash("该书已无可借副本", "danger")
        return redirect(url_for("books.book_detail", book_id=book_id))

    # 检查借阅数量上限
    active_count = BorrowRecord.query.filter_by(
        user_id=current_user.id, status="borrowed"
    ).count()
    if active_count >= MAX_BORROW_COUNT:
        flash(f"您已借阅{active_count}本，达到上限{MAX_BORROW_COUNT}本", "danger")
        return redirect(url_for("books.book_detail", book_id=book_id))

    # 检查是否已借过同一本书且未还（防重复借阅）
    existing = BorrowRecord.query.filter_by(
        user_id=current_user.id, book_id=book_id, status="borrowed"
    ).first()
    if existing:
        flash("您已借阅该书且尚未归还", "warning")
        return redirect(url_for("books.book_detail", book_id=book_id))

    # ---- 创建借阅记录 ----
    record = BorrowRecord(
        user_id=current_user.id,
        book_id=book_id,
        borrow_date=datetime.now(),
        due_date=datetime.now() + timedelta(days=MAX_BORROW_DAYS),
        status="borrowed",
    )
    db.session.add(record)

    # 原子操作：使用 UPDATE 语句减少可借数量，带 WHERE 条件确保不会变成负数
    result = db.session.query(Book).filter(
        Book.id == book_id,
        Book.available_count > 0
    ).update({Book.available_count: Book.available_count - 1})

    if result == 0:
        # 并发场景：另一个用户已经借走了最后一本
        db.session.rollback()
        flash("抱歉，该书刚刚被借走，请选择其他图书", "danger")
        return redirect(url_for("books.book_detail", book_id=book_id))

    # 记录审计日志
    log_operation(
        current_user.id, "borrow", "book", book_id,
        f"借阅《{book.title}》，应还日期{record.due_date.strftime('%Y-%m-%d')}"
    )

    # ---- 游戏化：经验值 + 成就检测 ----
    stat = get_or_create_stat(current_user.id)
    stat.total_books_borrowed += 1

    # 借书 +10 经验
    levelups = stat.add_exp(10)

    # 更新连续借阅天数
    update_streak(stat, record.borrow_date)

    # 更新分类数
    update_category_count(stat, current_user.id)

    # 检查成就
    new_achs = check_achievements(current_user.id, "borrow")
    if new_achs:
        for ach in new_achs:
            flash(
                f"🏆 成就解锁：{ach['name']}！奖励{ach['reward_exp']}经验",
                "info"
            )

    # 升级提示
    if levelups:
        for lu in levelups:
            flash(
                f"🎉 恭喜升级！当前等级：Lv.{lu['new_level']} {lu['new_title']}",
                "success"
            )

    # 随机鼓励语录（存入session，在详情页显示）
    quote = EncouragingQuote.get_random("borrow", stat.level)
    if quote:
        session["last_quote"] = {"content": quote.content, "author": quote.author}

    db.session.commit()
    flash(
        f"借阅成功！《{book.title}》应还日期：{record.due_date.strftime('%Y-%m-%d')}",
        "success",
    )
    return redirect(url_for("borrow.my_borrows"))


# =================== 还书（并发安全版） ===================

@borrow_bp.route("/return/<int:record_id>", methods=["POST"])
@login_required
@db_retry(use_immediate=True)
def return_book(record_id):
    """归还图书 - 增强版，防止并发竞态条件"""
    # 使用行级锁查询借阅记录
    record = db.session.query(BorrowRecord).filter_by(id=record_id).with_for_update().first()
    if not record:
        flash("借阅记录不存在", "danger")
        return redirect(url_for("borrow.my_borrows"))

    # 权限检查：本人或管理员
    if record.user_id != current_user.id and not current_user.is_admin:
        flash("无权操作", "danger")
        return redirect(url_for("borrow.my_borrows"))

    if record.status == "returned":
        flash("该书已归还", "info")
        return redirect(url_for("borrow.my_borrows"))

    # ---- 处理归还 ----
    record.return_date = datetime.now()
    record.status = "returned"

    # 计算逾期罚款
    if record.is_overdue:
        record.calculate_fine(OVERDUE_FINE)
        flash(
            f"归还成功！逾期{record.overdue_days}天，罚款{record.fine}元",
            "warning",
        )
    else:
        flash("归还成功！感谢按时归还", "success")

    # 原子操作：恢复可借数量，带条件防止超过总数
    book = db.session.query(Book).filter_by(id=record.book_id).with_for_update().first()
    if book and book.available_count < book.total_count:
        book.available_count += 1

    # 记录审计日志
    log_operation(
        current_user.id, "return", "book", record.book_id,
        f"归还《{book.title}»，状态：{'逾期' if record.is_overdue else '正常'}"
    )

    # ---- 游戏化：还书经验 + 成就检测 ----
    stat = get_or_create_stat(record.user_id)

    # 还书 +2 经验；逾期还书不扣经验，但不奖励
    if not record.is_overdue:
        stat.add_exp(2)
    else:
        stat.total_fine_paid += record.fine or 0

    # 更新按时归还率和平均阅读天数
    from routes.achievement import update_on_time_rate, update_avg_read_days
    update_on_time_rate(stat, record.user_id)
    update_avg_read_days(stat, record.user_id)

    # 检查成就（还书相关）
    if not record.is_overdue:
        check_achievements(record.user_id, "return")
    check_achievements(record.user_id, "speed")

    # 还书鼓励语录
    if record.user_id == current_user.id:
        quote = EncouragingQuote.get_random("return", stat.level)
        if quote:
            session["last_quote"] = {"content": quote.content, "author": quote.author}

    db.session.commit()
    return redirect(url_for("borrow.my_borrows"))


# =================== 我的借阅记录 ===================

@borrow_bp.route("/my-borrows")
@login_required
def my_borrows():
    """查看自己的借阅记录"""
    records = (
        BorrowRecord.query
        .filter_by(user_id=current_user.id)
        .order_by(BorrowRecord.borrow_date.desc())
        .all()
    )
    return render_template("my_borrows.html", records=records)


# =================== 全部借阅记录（管理员） ===================

@borrow_bp.route("/all-records")
@login_required
def all_records():
    """管理员查看全部借阅记录"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")

    query = BorrowRecord.query
    if status_filter:
        query = query.filter_by(status=status_filter)

    pagination = query.order_by(BorrowRecord.borrow_date.desc()).paginate(
        page=page, per_page=15, error_out=False
    )

    return render_template(
        "all_records.html",
        pagination=pagination,
        records=pagination.items,
        status_filter=status_filter,
    )


# =================== 数据看板（管理员）- 增强版 ===================

def _collect_dashboard_metrics():
    """
    收集数据看板所需的全部指标（供 dashboard 模板与 /dashboard/api/data 共享）。
    抽出为独立函数体现 DRY，并使 JSON 端点与初始渲染数据同源。
    """
    # ---- 统计数据 ----
    total_books = Book.query.count()
    total_copies = db.session.query(func.sum(Book.total_count)).scalar() or 0
    borrowed_count = (
        BorrowRecord.query.filter_by(status="borrowed").count()
    )
    total_users = User.query.count()
    overdue_count = BorrowRecord.query.filter(
        BorrowRecord.due_date < datetime.now(),
        BorrowRecord.return_date.is_(None),
    ).count()

    # ---- 热门图书 TOP5（序列化为 dict，便于 JSON 化与模板统一） ----
    popular_rows = (
        db.session.query(Book, func.count(BorrowRecord.id).label("borrow_times"))
        .join(BorrowRecord)
        .group_by(Book.id)
        .order_by(func.count(BorrowRecord.id).desc())
        .limit(5)
        .all()
    )
    popular_books = [
        {"title": b.title, "author": b.author, "times": int(t)}
        for b, t in popular_rows
    ]

    # ---- 近7天借阅趋势（按日聚合 + 补零，保证 7 个点） ----
    seven_days_ago = datetime.now() - timedelta(days=7)
    daily_stats = (
        db.session.query(
            func.date(BorrowRecord.borrow_date).label("date"),
            func.count(BorrowRecord.id).label("count")
        )
        .filter(BorrowRecord.borrow_date >= seven_days_ago)
        .group_by(func.date(BorrowRecord.borrow_date))
        .order_by(func.date(BorrowRecord.borrow_date))
        .all()
    )
    trend_data = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        count = 0
        for stat in daily_stats:
            if str(stat.date) == date:
                count = int(stat.count)
                break
        trend_data.append({"date": date[5:], "count": count})  # 只取 MM-DD

    # ---- 分类统计（图书分布 + 各分类借出） ----
    category_rows = (
        db.session.query(
            Category.name,
            func.count(Book.id).label("book_count"),
            func.sum(Book.total_count).label("total_copies"),
            func.sum(Book.total_count - Book.available_count).label("borrowed"),
        )
        .join(Book, Book.category_id == Category.id)
        .group_by(Category.id)
        .all()
    )
    category_stats = [
        {
            "name": row.name,
            "book_count": int(row.book_count or 0),
            "total_copies": int(row.total_copies or 0),
            "borrowed": int(row.borrowed or 0),
        }
        for row in category_rows
    ]

    # ---- 当前活跃用户数（今天有操作的） ----
    today = datetime.now().strftime("%Y-%m-%d")
    active_today = (
        db.session.query(func.count(func.distinct(OperationLog.user_id)))
        .filter(func.date(OperationLog.created_at) == today)
        .scalar() or 0
    )

    return {
        "stats": {
            "total_books": total_books,
            "total_copies": int(total_copies),
            "borrowed_count": borrowed_count,
            "total_users": total_users,
            "overdue_count": overdue_count,
            "active_today": active_today,
        },
        "popular_books": popular_books,
        "trend_data": trend_data,
        "category_stats": category_stats,
    }


@borrow_bp.route("/dashboard")
@login_required
def dashboard():
    """数据看板 - 统计概览 + ECharts 可视化 + 实时监控"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    metrics = _collect_dashboard_metrics()

    # 近期借阅与操作日志是事件列表（非聚合），保持表格形式
    recent_records = (
        BorrowRecord.query
        .order_by(BorrowRecord.borrow_date.desc())
        .limit(10)
        .all()
    )
    recent_logs = (
        OperationLog.query
        .order_by(OperationLog.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard.html",
        stats=metrics["stats"],
        popular_books=metrics["popular_books"],
        trend_data=metrics["trend_data"],
        category_stats=metrics["category_stats"],
        recent_records=recent_records,
        recent_logs=recent_logs,
    )


@borrow_bp.route("/dashboard/api/data")
@login_required
def dashboard_api_data():
    """数据看板 JSON 端点：供前端 fetch 局部刷新，避免整页 reload 销毁 ECharts 实例"""
    if not current_user.is_admin:
        return jsonify({"error": "权限不足"}), 403
    metrics = _collect_dashboard_metrics()
    return jsonify(metrics)


# =================== 用户管理（管理员） ===================

@borrow_bp.route("/users")
@login_required
def user_list():
    """用户管理列表"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("user_list.html", users=users)


@borrow_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@db_retry(use_immediate=True)
def toggle_user(user_id):
    """启用/禁用用户"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("不能禁用自己", "warning")
        return redirect(url_for("borrow.user_list"))

    user.is_active = not user.is_active
    status = "启用" if user.is_active else "禁用"

    log_operation(
        current_user.id, "toggle_user", "user", user_id,
        f"{status}用户 {user.username}"
    )

    db.session.commit()
    flash(f"用户 {user.username} 已{status}", "info")
    return redirect(url_for("borrow.user_list"))
