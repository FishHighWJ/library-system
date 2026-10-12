"""
反馈管理路由 - 用户反馈、图书荐购、通知系统
读者可提交意见建议和荐购请求，管理员可查看回复并转化为图书
"""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy import func
from models import db, Book, Category, Feedback, Notification, BorrowRecord, User

feedback_bp = Blueprint("feedback", __name__)


# =================== 用户提交反馈 ===================

@feedback_bp.route("/feedback")
@login_required
def feedback_list():
    """用户查看自己提交的反馈"""
    page = request.args.get("page", 1, type=int)
    pagination = (
        Feedback.query
        .filter_by(user_id=current_user.id)
        .order_by(Feedback.created_at.desc())
        .paginate(page=page, per_page=10, error_out=False)
    )
    return render_template("feedback_list.html", pagination=pagination, feedbacks=pagination.items)


@feedback_bp.route("/feedback/new", methods=["GET", "POST"])
@login_required
def feedback_new():
    """提交新反馈/荐购"""
    categories = Category.query.all()

    if request.method == "POST":
        feedback_type = request.form.get("feedback_type", "suggestion")
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("请填写标题和内容", "danger")
            return render_template("feedback_form.html", categories=categories)

        fb = Feedback(
            user_id=current_user.id,
            feedback_type=feedback_type,
            title=title,
            content=content,
        )

        # 如果是图书荐购，额外保存图书信息
        if feedback_type == "book_request":
            fb.book_title = request.form.get("book_title", "").strip()
            fb.book_author = request.form.get("book_author", "").strip()
            fb.book_isbn = request.form.get("book_isbn", "").strip()
            fb.book_publisher = request.form.get("book_publisher", "").strip()
            fb.book_price = request.form.get("book_price", 0, type=float)
            fb.book_category = request.form.get("book_category", "").strip()

            if not fb.book_title:
                flash("荐购请填写书名", "danger")
                return render_template("feedback_form.html", categories=categories)

        db.session.add(fb)
        db.session.commit()
        flash("提交成功！我们会尽快处理并回复", "success")
        return redirect(url_for("feedback.feedback_list"))

    return render_template("feedback_form.html", categories=categories)


@feedback_bp.route("/feedback/<int:fb_id>/rate", methods=["POST"])
@login_required
def feedback_rate(fb_id):
    """用户对处理结果评分"""
    fb = Feedback.query.get_or_404(fb_id)
    if fb.user_id != current_user.id:
        flash("无权操作", "danger")
        return redirect(url_for("feedback.feedback_list"))

    rating = request.form.get("rating", 0, type=int)
    if rating < 1 or rating > 5:
        flash("评分无效", "danger")
        return redirect(url_for("feedback.feedback_list"))

    fb.rating = rating
    db.session.commit()
    flash("感谢您的评价！", "success")
    return redirect(url_for("feedback.feedback_list"))


# =================== 管理员反馈管理 ===================

@feedback_bp.route("/feedback/manage")
@login_required
def feedback_manage():
    """管理员反馈管理页面"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    type_filter = request.args.get("type", "")

    query = Feedback.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if type_filter:
        query = query.filter_by(feedback_type=type_filter)

    pagination = (
        query
        .order_by(Feedback.priority.desc(), Feedback.created_at.desc())
        .paginate(page=page, per_page=15, error_out=False)
    )

    # 统计
    stats = {
        "total": Feedback.query.count(),
        "pending": Feedback.query.filter_by(status="pending").count(),
        "accepted": Feedback.query.filter_by(status="accepted").count(),
        "resolved": Feedback.query.filter_by(status="resolved").count(),
    }

    return render_template(
        "feedback_manage.html",
        pagination=pagination,
        feedbacks=pagination.items,
        stats=stats,
        status_filter=status_filter,
        type_filter=type_filter,
    )


@feedback_bp.route("/feedback/<int:fb_id>/reply", methods=["POST"])
@login_required
def feedback_reply(fb_id):
    """管理员回复反馈"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    fb = Feedback.query.get_or_404(fb_id)
    reply = request.form.get("admin_reply", "").strip()
    new_status = request.form.get("status", "pending")

    if not reply and new_status != "rejected":
        flash("请填写回复内容", "danger")
        return redirect(url_for("feedback.feedback_detail", fb_id=fb_id))

    fb.admin_reply = reply
    fb.status = new_status
    fb.replied_at = datetime.now()

    # 给用户发送站内通知
    type_names = {
        "suggestion": "功能建议",
        "book_request": "图书荐购",
        "bug_report": "问题报告",
        "complaint": "投诉",
    }
    notice = Notification(
        user_id=fb.user_id,
        notification_type="feedback_reply",
        title=f"您的{type_names.get(fb.feedback_type, '反馈')}已有回复",
        content=f"反馈「{fb.title}」已处理，状态：{fb.status}。回复：{reply[:100]}",
        related_id=fb.id,
    )
    db.session.add(notice)

    db.session.commit()
    flash("回复成功，已通知用户", "success")
    return redirect(url_for("feedback.feedback_detail", fb_id=fb_id))


@feedback_bp.route("/feedback/<int:fb_id>")
@login_required
def feedback_detail(fb_id):
    """反馈详情"""
    fb = Feedback.query.get_or_404(fb_id)

    # 权限：本人或管理员
    if fb.user_id != current_user.id and not current_user.is_admin:
        flash("无权查看", "danger")
        return redirect(url_for("books.index"))

    return render_template("feedback_detail.html", fb=fb)


@feedback_bp.route("/feedback/<int:fb_id>/convert", methods=["POST"])
@login_required
def feedback_convert(fb_id):
    """将荐购反馈直接转化为图书上架"""
    if not current_user.is_admin:
        flash("权限不足", "danger")
        return redirect(url_for("books.index"))

    fb = Feedback.query.get_or_404(fb_id)
    if fb.feedback_type != "book_request":
        flash("只有荐购反馈可以转为图书", "warning")
        return redirect(url_for("feedback.feedback_detail", fb_id=fb_id))

    # 查找或创建分类
    category = None
    if fb.book_category:
        category = Category.query.filter_by(name=fb.book_category).first()

    # 创建图书
    book = Book(
        isbn=fb.book_isbn or "",
        title=fb.book_title,
        author=fb.book_author or "未知",
        publisher=fb.book_publisher or "",
        price=fb.book_price or 0,
        description=f"根据用户荐购请求添加。荐购人：{fb.submitter.username}",
        total_count=1,
        available_count=1,
        category_id=category.id if category else None,
    )
    db.session.add(book)

    # 更新反馈状态
    fb.status = "resolved"
    fb.admin_reply = fb.admin_reply or ""
    fb.admin_reply += f"\n[系统] 已根据荐购添加图书《{fb.book_title}》"

    # 通知用户
    notice = Notification(
        user_id=fb.user_id,
        notification_type="feedback_reply",
        title=f"您荐购的《{fb.book_title}》已到馆！",
        content=f"您荐购的《{fb.book_title}》已添加到馆藏，欢迎借阅！",
        related_id=fb.id,
    )
    db.session.add(notice)

    db.session.commit()
    flash(f"已将《{fb.book_title}》添加到馆藏", "success")
    return redirect(url_for("books.book_detail", book_id=book.id))


# =================== 站内通知 ===================

@feedback_bp.route("/notifications")
@login_required
def notifications():
    """查看站内通知"""
    page = request.args.get("page", 1, type=int)
    pagination = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=15, error_out=False)
    )
    unread_count = Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).count()
    return render_template(
        "notifications.html",
        pagination=pagination,
        notifications=pagination.items,
        unread_count=unread_count,
    )


@feedback_bp.route("/notifications/read/<int:n_id>", methods=["POST"])
@login_required
def mark_read(n_id):
    """标记通知为已读"""
    notice = Notification.query.get_or_404(n_id)
    if notice.user_id != current_user.id:
        flash("无权操作", "danger")
        return redirect(url_for("feedback.notifications"))

    notice.is_read = True
    db.session.commit()
    return redirect(url_for("feedback.notifications"))


@feedback_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    """全部标记为已读"""
    Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).update({"is_read": True})
    db.session.commit()
    flash("已全部标记为已读", "info")
    return redirect(url_for("feedback.notifications"))
