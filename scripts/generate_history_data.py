"""
历史借阅数据生成脚本
====================
造 6 个月 × 50 用户的借阅记录，让 RFM 能分出 5-6 类、预测模型有足够样本。

用户角色设计（让分群可分辨）：
- 重度活跃（10 人）：每周 2-3 次，涉猎全分类，最近 3 天内有借阅 → Champions
- 中度活跃（10 人）：每两周 1 次，2-3 个分类，最近 7 天 → Potential/Loyal
- 高频沉睡（8 人）：前 4 月高频，后 2 月沉睡 → Loyal/At-risk
- 低频活跃（10 人）：每月 1 次，1-2 分类，最近 10 天 → Potential
- 流失用户（12 人）：前 3 月有借阅，后 3 月消失 → Lost/At-risk

借阅量模式：
- 工作日 > 周末（图书馆场景符合直觉）
- 每天有随机波动
- 月初借阅略多（发薪日效应模拟）

运行方式：python scripts/generate_history_data.py
"""

import os
import sys
import random
from datetime import datetime, timedelta

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db, User, Book, Category, BorrowRecord


def clear_borrow_data():
    """清空旧借阅记录 + 造数据用户（保留 admin / reader / 原有书籍）"""
    # 删除所有借阅记录
    BorrowRecord.query.delete()
    # 删除所有非 admin/reader 的用户（造数据用户会重建）
    User.query.filter(~User.username.in_(['admin', 'reader'])).delete()
    db.session.commit()
    print("  - 已清空旧借阅记录和造数据用户")


def ensure_categories_and_books():
    """确保有至少 5 个分类 + 30 本书可供借阅"""
    cat_names = ['计算机', '文学', '历史', '科学', '艺术', '经济', '哲学', '教育']
    cats = {c.name: c for c in Category.query.all()}
    for name in cat_names:
        if name not in cats:
            c = Category(name=name)
            db.session.add(c)
            db.session.flush()
            cats[name] = c

    # 补足书籍到至少 30 本
    existing = Book.query.count()
    if existing < 30:
        titles = [
            "Python编程从入门到实践", "数据科学手册", "机器学习实战", "深度学习入门",
            "算法导论", "计算机网络", "操作系统概念", "数据库系统实现",
            "百年孤独", "三体", "活着", "围城", "平凡的世界", "白夜行", "解忧杂货店",
            "人类简史", "未来简史", "明朝那些事儿", "史记", "万历十五年",
            "时间简史", "自私的基因", "物种起源", "量子物理史话",
            "艺术的故事", "西方美术史", "中国书法理论",
            "经济学原理", "国富论", "博弈论与经济模型",
            "中国哲学简史", "西方哲学史", "论语新解",
            "教育心理学", "学习的本质", "教学原理",
        ]
        for i, t in enumerate(titles):
            if Book.query.filter_by(title=t).first():
                continue
            cat = cats[cat_names[i % len(cat_names)]]
            b = Book(
                title=t, author=f"作者{i+1}", total_count=20, available_count=20,
                category_id=cat.id
            )
            db.session.add(b)
    db.session.commit()
    print(f"  - 分类 {len(cats)} 个 / 书籍 {Book.query.count()} 本")


def create_users():
    """造 50 个用户分 5 类"""
    roles = [
        ("heavy", 10),    # 重度活跃
        ("medium", 10),   # 中度活跃
        ("sleepy", 8),    # 高频沉睡
        ("light", 10),    # 低频活跃
        ("churn", 12),    # 流失用户
    ]
    users_by_role = {}
    for role, count in roles:
        users_by_role[role] = []
        for i in range(count):
            username = f"{role}_{i:02d}"
            u = User(username=username, email=f"{username}@demo.com", role="reader")
            u.set_password("Demo@2026!")
            db.session.add(u)
            users_by_role[role].append(u)
    db.session.commit()
    print(f"  - 创建 {sum(len(v) for v in users_by_role.values())} 个演示用户")
    return users_by_role


def gen_borrow_records(users_by_role, days=180):
    """按角色生成 180 天借阅记录

    数据模式设计（让线性回归有信号可学）：
    - 上升趋势：越近的日期借阅概率越高（模拟图书馆用户增长）
    - 周末效应：周末借阅量降低（工作日 / 周末 = 2:1）
    - 月初效应：每月前 5 天借阅略多
    """
    now = datetime.now()
    books = Book.query.all()
    if not books:
        print("  ! 无可用书籍，跳过")
        return

    records = []

    def trend_factor(days_ago):
        """时间趋势因子：越近（days_ago 小）借阅越多"""
        # 线性增长：最早 0.6，最近 1.4
        return 0.6 + 0.8 * (1 - days_ago / days)

    def is_weekend(days_ago):
        d = now - timedelta(days=days_ago)
        return d.weekday() >= 5  # 5=周六 6=周日

    def is_month_start(days_ago):
        d = now - timedelta(days=days_ago)
        return d.day <= 5

    def pick_book(user_id, used_cats):
        """尽量让同一用户借不同分类的书（让 M 维度有意义）"""
        available = [b for b in books if b.category_id not in used_cats] or books
        b = random.choice(available)
        used_cats.add(b.category_id)
        return b

    def make_record(user, days_ago, used_cats):
        borrow_date = now - timedelta(days=days_ago)
        due = borrow_date + timedelta(days=30)
        # 80% 已归还，20% 在借
        if random.random() < 0.8:
            return_days = random.randint(5, 25)
            return_date = borrow_date + timedelta(days=return_days)
            status = "returned"
        else:
            return_date = None
            status = "borrowed"
        b = pick_book(user.id, used_cats)
        return BorrowRecord(
            user_id=user.id, book_id=b.id,
            borrow_date=borrow_date, due_date=due,
            return_date=return_date, status=status, version=0
        )

    def should_borrow(base_prob, days_ago):
        """综合趋势/周末/月初调整借阅概率"""
        p = base_prob * trend_factor(days_ago)
        if is_weekend(days_ago):
            p *= 0.5  # 周末减半
        if is_month_start(days_ago):
            p *= 1.3  # 月初加 30%
        return min(p, 0.9)  # 上限 0.9

    # 重度活跃：每周 2-3 次
    for u in users_by_role["heavy"]:
        used_cats = set()
        for d in range(days):
            if d < 3 or should_borrow(0.35, d) > random.random():
                if should_borrow(0.35, d) > random.random() * 0.6:
                    records.append(make_record(u, d, used_cats))

    # 中度活跃：每两周 1 次
    for u in users_by_role["medium"]:
        used_cats = set()
        for d in range(days):
            if d < 7 or should_borrow(0.07, d) > random.random():
                if should_borrow(0.07, d) > random.random() * 0.7:
                    records.append(make_record(u, d, used_cats))

    # 高频沉睡：前 4 月高频，后 2 月沉睡
    for u in users_by_role["sleepy"]:
        used_cats = set()
        for d in range(days):
            if d < 60:  # 前2月高频
                if should_borrow(0.3, d) > random.random():
                    records.append(make_record(u, d, used_cats))

    # 低频活跃：每月 1 次
    for u in users_by_role["light"]:
        used_cats = set()
        for d in range(days):
            if d < 10 or should_borrow(0.03, d) > random.random():
                if should_borrow(0.03, d) > random.random() * 0.7:
                    records.append(make_record(u, d, used_cats))

    # 流失用户：前 3 月活跃
    for u in users_by_role["churn"]:
        used_cats = set()
        for d in range(days):
            if d < 90:  # 前3月活跃
                if should_borrow(0.15, d) > random.random():
                    records.append(make_record(u, d, used_cats))

    db.session.bulk_save_objects(records)
    db.session.commit()
    print(f"  - 生成 {len(records)} 条借阅记录（180 天 × {sum(len(v) for v in users_by_role.values())} 用户）")


def main():
    print("=" * 60)
    print("开始生成历史借阅数据")
    print("=" * 60)

    app = create_app("default")
    with app.app_context():
        print("[1/4] 清空旧数据...")
        clear_borrow_data()
        print("[2/4] 确保分类和书籍充足...")
        ensure_categories_and_books()
        print("[3/4] 创建演示用户...")
        users_by_role = create_users()
        print("[4/4] 生成借阅记录...")
        gen_borrow_records(users_by_role, days=180)

        print("=" * 60)
        print("✅ 数据生成完成！")
        print(f"   - 用户数: {User.query.count()}")
        print(f"   - 书籍数: {Book.query.count()}")
        print(f"   - 借阅记录: {BorrowRecord.query.count()}")
        print(f"   - 时间跨度: 最近 180 天")
        print("=" * 60)
        print("现在可以访问 /analysis/rfm 和 /analysis/prediction 查看效果")


if __name__ == "__main__":
    main()
