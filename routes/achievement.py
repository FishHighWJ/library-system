"""
成就系统路由 - 等级、成就、排行榜、鼓励语录
游戏化阅读激励机制
"""

from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from models import (
    db, ReadingStat, Achievement, UserAchievement,
    EncouragingQuote, User, BorrowRecord, Book, Category, Notification
)

achievement_bp = Blueprint("achievement", __name__)


# ===================== 成就检测引擎 =====================

def get_or_create_stat(user_id):
    """获取或创建用户阅读统计"""
    stat = ReadingStat.query.filter_by(user_id=user_id).first()
    if not stat:
        stat = ReadingStat(user_id=user_id)
        db.session.add(stat)
        db.session.flush()
    return stat


def check_achievements(user_id, trigger_type, **kwargs):
    """
    检查并解锁成就
    trigger_type: borrow / return / category / speed / streak / social
    返回新解锁的成就列表
    """
    stat = get_or_create_stat(user_id)
    new_achievements = []

    # 获取该类型下所有已启用的成就
    category_map = {
        "borrow": "borrow",
        "return": "borrow",
        "category": "category",
        "speed": "speed",
        "streak": "borrow",
        "social": "social",
        "special": "special",
    }
    cat = category_map.get(trigger_type, "general")

    achievements = Achievement.query.filter_by(
        is_active=True, category=cat
    ).all()

    for ach in achievements:
        # 检查用户是否已获得
        existing = UserAchievement.query.filter_by(
            user_id=user_id, achievement_id=ach.id
        ).first()
        if existing:
            continue

        # 根据条件类型判断
        unlocked = False

        if ach.condition_type == "borrow_count":
            unlocked = stat.total_books_borrowed >= ach.condition_value

        elif ach.condition_type == "streak_days":
            unlocked = stat.longest_streak >= ach.condition_value

        elif ach.condition_type == "category_count":
            unlocked = stat.total_categories_read >= ach.condition_value

        elif ach.condition_type == "read_speed":
            if stat.fastest_read_hours is not None:
                unlocked = stat.fastest_read_hours <= ach.condition_value

        elif ach.condition_type == "fine_free":
            unlocked = (stat.total_books_borrowed >= ach.condition_value
                        and stat.total_fine_paid == 0)

        elif ach.condition_type == "first_action":
            if ach.condition_value == 1 and stat.total_books_borrowed >= 1:
                unlocked = True

        elif ach.condition_type == "return_count":
            returned = BorrowRecord.query.filter_by(
                user_id=user_id, status="returned"
            ).count()
            unlocked = returned >= ach.condition_value

        if unlocked:
            # 解锁成就
            ua = UserAchievement(user_id=user_id, achievement_id=ach.id)
            db.session.add(ua)

            # 奖励经验
            if ach.reward_exp > 0:
                stat.add_exp(ach.reward_exp)

            new_achievements.append({
                "id": ach.id,
                "name": ach.name,
                "description": ach.description,
                "icon": ach.icon,
                "icon_color": ach.icon_color,
                "rarity": ach.rarity,
                "reward_exp": ach.reward_exp,
            })

            # 发送通知
            notice = Notification(
                user_id=user_id,
                notification_type="system_notice",
                title=f"成就解锁：{ach.name}",
                content=f"恭喜！您解锁了成就「{ach.name}」，获得{ach.reward_exp}经验值。",
                related_id=ach.id,
            )
            db.session.add(notice)

    return new_achievements


def update_streak(stat, borrow_date):
    """更新连续借阅天数"""
    today = borrow_date.date() if isinstance(borrow_date, datetime) else borrow_date

    if stat.last_borrow_date is None:
        # 第一次借阅
        stat.current_streak = 1
    elif stat.last_borrow_date == today:
        # 今天已经借过了，不增加
        pass
    elif stat.last_borrow_date == today - timedelta(days=1):
        # 昨天也借了，连续+1
        stat.current_streak += 1
    else:
        # 断了，重新开始
        stat.current_streak = 1

    stat.last_borrow_date = today
    if stat.current_streak > stat.longest_streak:
        stat.longest_streak = stat.current_streak


def update_category_count(stat, user_id):
    """更新涉猎分类数"""
    category_count = (
        db.session.query(func.count(func.distinct(Book.category_id)))
        .join(BorrowRecord, BorrowRecord.book_id == Book.id)
        .filter(BorrowRecord.user_id == user_id, Book.category_id.isnot(None))
        .scalar() or 0
    )
    stat.total_categories_read = category_count


def update_on_time_rate(stat, user_id):
    """更新按时归还率"""
    all_returned = BorrowRecord.query.filter_by(
        user_id=user_id, status="returned"
    ).all()
    if not all_returned:
        stat.on_time_return_rate = 100.0
        return
    on_time = sum(1 for r in all_returned if not r.is_overdue)
    stat.on_time_return_rate = round(on_time / len(all_returned) * 100, 1)


def update_avg_read_days(stat, user_id):
    """更新平均阅读天数"""
    returned = BorrowRecord.query.filter_by(
        user_id=user_id, status="returned"
    ).all()
    if not returned:
        return
    total_days = 0
    for r in returned:
        if r.return_date and r.borrow_date:
            days = (r.return_date - r.borrow_date).total_seconds() / 86400
            total_days += days
            # 更新最快读完时间
            hours = days * 24
            if stat.fastest_read_hours is None or hours < stat.fastest_read_hours:
                stat.fastest_read_hours = round(hours, 1)
    stat.avg_read_days = round(total_days / len(returned), 1)


# ===================== 成就中心页面 =====================

@achievement_bp.route("/achievements")
@login_required
def achievement_center():
    """成就中心"""
    stat = get_or_create_stat(current_user.id)

    # 所有成就（按分类分组）
    all_achievements = Achievement.query.filter_by(is_active=True).order_by(
        Achievement.category, Achievement.sort_order, Achievement.id
    ).all()

    # 用户已获得的成就ID集合
    earned_ids = {
        ua.achievement_id for ua in
        UserAchievement.query.filter_by(user_id=current_user.id).all()
    }

    # 按分类分组
    categories = {
        "borrow": {"name": "借阅达人", "icon": "book", "items": []},
        "category": {"name": "分类探索", "icon": "compass", "items": []},
        "speed": {"name": "速度之星", "icon": "lightning", "items": []},
        "social": {"name": "社交贡献", "icon": "people", "items": []},
        "special": {"name": "特殊成就", "icon": "star", "items": []},
    }

    for ach in all_achievements:
        cat = ach.category if ach.category in categories else "special"
        categories[cat]["items"].append({
            "id": ach.id,
            "name": ach.name,
            "description": ach.description,
            "icon": ach.icon,
            "icon_color": ach.icon_color,
            "rarity": ach.rarity,
            "reward_exp": ach.reward_exp,
            "earned": ach.id in earned_ids,
        })

    # 统计
    total_count = len(all_achievements)
    earned_count = len(earned_ids)

    # 最新获得的成就
    recent_achievements = (
        db.session.query(UserAchievement, Achievement)
        .join(Achievement)
        .filter(UserAchievement.user_id == current_user.id)
        .order_by(UserAchievement.earned_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "achievement_center.html",
        stat=stat,
        categories=categories,
        total_count=total_count,
        earned_count=earned_count,
        recent_achievements=recent_achievements,
    )


# ===================== 排行榜 =====================

@achievement_bp.route("/ranking")
def ranking():
    """借阅排行榜"""
    page = request.args.get("page", 1, type=int)

    # 借阅量排行榜
    top_borrowers = (
        db.session.query(
            User.id,
            User.username,
            ReadingStat.total_books_borrowed,
            ReadingStat.level,
            ReadingStat.title,
        )
        .join(ReadingStat, ReadingStat.user_id == User.id)
        .filter(User.is_active == True)
        .order_by(ReadingStat.total_books_borrowed.desc())
        .limit(20)
        .all()
    )

    # 等级排行榜
    top_levels = (
        db.session.query(
            User.id,
            User.username,
            ReadingStat.level,
            ReadingStat.exp,
            ReadingStat.title,
        )
        .join(ReadingStat, ReadingStat.user_id == User.id)
        .filter(User.is_active == True)
        .order_by(ReadingStat.exp.desc())
        .limit(20)
        .all()
    )

    # 连续天数排行榜
    top_streaks = (
        db.session.query(
            User.id,
            User.username,
            ReadingStat.longest_streak,
            ReadingStat.title,
        )
        .join(ReadingStat, ReadingStat.user_id == User.id)
        .filter(User.is_active == True, ReadingStat.longest_streak > 0)
        .order_by(ReadingStat.longest_streak.desc())
        .limit(20)
        .all()
    )

    # 当前用户排名
    my_rank_borrow = 0
    my_rank_level = 0
    if current_user.is_authenticated:
        my_stat = get_or_create_stat(current_user.id)
        # 借阅排名
        higher = (
            ReadingStat.query
            .filter(ReadingStat.total_books_borrowed > my_stat.total_books_borrowed)
            .count()
        )
        my_rank_borrow = higher + 1
        # 等级排名
        higher_exp = (
            ReadingStat.query
            .filter(ReadingStat.exp > my_stat.exp)
            .count()
        )
        my_rank_level = higher_exp + 1

    return render_template(
        "ranking.html",
        top_borrowers=top_borrowers,
        top_levels=top_levels,
        top_streaks=top_streaks,
        my_rank_borrow=my_rank_borrow,
        my_rank_level=my_rank_level,
    )


# ===================== API：获取随机鼓励语录 =====================

@achievement_bp.route("/api/quote")
@login_required
def get_quote():
    """获取随机鼓励语录（AJAX调用）"""
    stat = get_or_create_stat(current_user.id)
    category = request.args.get("category", "general")
    quote = EncouragingQuote.get_random(category, stat.level)
    if quote:
        return jsonify({
            "content": quote.content,
            "author": quote.author,
        })
    return jsonify({"content": "阅读是进步的阶梯。", "author": "高尔基"})
