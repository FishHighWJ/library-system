"""
数据分析模块单元测试 - RFM 分群 + 借阅预测
运行方式: pytest tests/test_analysis.py -v
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    """创建测试用 Flask 应用（内存 SQLite，不污染真实数据）"""
    os.environ['FLASK_CONFIG'] = 'testing'
    os.environ['SECRET_KEY'] = 'test-secret-key-for-unit-tests-only'
    from app import create_app
    app = create_app('testing')
    yield app


@pytest.fixture
def db_session(app):
    """初始化数据库并 yield session，测试结束自动回滚"""
    from models import db
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.remove()


def _seed_users_and_categories(session, n_users=10):
    """造 n_users 个用户（含 1 个零借阅）+ 3 个分类 + 5 本书"""
    from models import User, Book, Category
    cats = [Category(name=f"cat{i}") for i in range(3)]
    session.add_all(cats)
    session.flush()
    books = [
        Book(title=f"b{i}", author="a", total_count=10, available_count=10,
             category_id=cats[i % 3].id)
        for i in range(5)
    ]
    session.add_all(books)
    session.flush()
    users = []
    for i in range(n_users):
        u = User(username=f"tu{i}", email=f"tu{i}@x.com", role="reader")
        u.set_password("Test1234")
        session.add(u)
        users.append(u)
    session.flush()
    # 最后一个用户保持零借阅（验证 Inactive 桶）
    return users[:-1], users[-1], books, cats


class TestRFM:
    """RFM 用户分群测试"""

    def test_rfm_segmentation(self, app, db_session):
        """种子 10 用户（含 1 零借阅），断言 Inactive 非空、各桶占比合理"""
        from models import BorrowRecord
        from services.rfm_service import compute_rfm, segment_users

        users, inactive_user, books, _ = _seed_users_and_categories(db_session, 10)
        now = datetime.now()

        # 设计借阅模式使分群可分辨
        # users[0..2]: 高频近期 → Champions/Potential
        # users[3..5]: 高频沉睡 → Loyal/Lost
        # users[6..8]: 低频沉睡 → At-risk/Lost
        patterns = [
            (25, 0),   # u0: 25 次, 今天
            (20, 1),   # u1
            (18, 0),   # u2
            (25, 30),  # u3: 高频但 30 天前
            (20, 40),
            (18, 50),
            (3, 60),   # 低频沉睡
            (2, 70),
            (1, 80),
        ]
        for u, (freq, days_ago) in zip(users, patterns):
            for j in range(freq):
                session_rec = BorrowRecord(
                    user_id=u.id,
                    book_id=books[(u.id * 7 + j) % 5].id,
                    borrow_date=now - timedelta(days=days_ago + j),
                    due_date=now + timedelta(days=30),
                    status="borrowed",
                )
                db_session.add(session_rec)
        db_session.commit()

        rfm = compute_rfm()
        # app.py 自动建了 admin + reader 两个零借阅用户，加上测试造的 10 个 = 至少 11 用户
        total = len(rfm)
        assert total >= 11

        segmented, counts = segment_users(rfm)
        # 断言：零借阅用户落 Inactive 桶（至少 3 个：admin/reader + 我们造的 1 个）
        assert counts["Inactive"] >= 3
        # 断言：总人数守恒
        assert sum(counts.values()) == total
        # 断言：Champions 桶不超过活跃用户的 50%（四分位上界容差防小样本抖动）
        active_total = total - counts["Inactive"]
        if active_total > 0:
            assert counts["Champions"] <= active_total * 0.5
        # 断言：每个分群用户都带 segment 标签
        assert all("segment" in s for s in segmented)
        # 断言：零借阅用户的 F=0
        inactive_rows = [s for s in segmented if s["segment"] == "Inactive"]
        assert all(r["F"] == 0 for r in inactive_rows)


class TestForecast:
    """借阅量预测测试"""

    def _seed_borrows(self, session, days):
        """造 days 天借阅数据（每天 3~7 次随机）"""
        from models import Book, Category, BorrowRecord, User
        cat = Category(name="fc0")
        session.add(cat)
        session.flush()
        book = Book(title="fb", author="a", total_count=999,
                    available_count=999, category_id=cat.id)
        session.add(book)
        session.flush()
        u = User(username="fu", email="fu@x.com", role="reader")
        u.set_password("Test1234")
        session.add(u)
        session.flush()
        now = datetime.now()
        import random
        random.seed(42)
        for i in range(days):
            d = now - timedelta(days=days - 1 - i)
            n = 3 + random.randint(0, 4)
            # 周末多借
            if d.weekday() >= 5:
                n += 2
            for _ in range(n):
                session.add(BorrowRecord(
                    user_id=u.id, book_id=book.id, borrow_date=d,
                    due_date=d + timedelta(days=30), status="borrowed"
                ))
        session.commit()
        return u.id

    def test_forecast_output_shape(self, app, db_session):
        """种子 60 天借阅，断言预测长度=14、值>=0、CI 包裹预测"""
        self._seed_borrows(db_session, 60)
        from services.forecast_service import fit_and_predict
        result = fit_and_predict(history_days=60, horizon=14)

        # 不应有 error
        assert "error" not in result
        # 预测段长度 = horizon
        predicted_seg = [p for p in result["predicted"] if p is not None]
        assert len(predicted_seg) == 14
        # 所有预测值非负（借阅量不可为负）
        assert all(p >= 0 for p in predicted_seg)
        # CI 下界 <= 预测 <= CI 上界
        ci_lower = [c for c in result["ci_lower"] if c is not None]
        ci_upper = [c for c in result["ci_upper"] if c is not None]
        assert len(ci_lower) == 14 and len(ci_upper) == 14
        for lo, pred, hi in zip(ci_lower, predicted_seg, ci_upper):
            assert lo <= pred <= hi
        # 系数包含趋势 + 7 个星期项
        assert "趋势(天)" in result["coef"]
        assert "截距(周一基准)" in result["coef"]
        # dates 长度 = 历史 + 预测
        assert len(result["dates"]) == 60 + 14

    def test_forecast_insufficient_data(self, app, db_session):
        """种子 5 天，断言返回 error 字段"""
        self._seed_borrows(db_session, 5)
        from services.forecast_service import fit_and_predict
        result = fit_and_predict(history_days=5, horizon=14)
        assert "error" in result
        assert "数据不足" in result["error"]


class TestEvaluation:
    """模型评估测试"""

    def _seed_borrows_30d(self, session):
        """造 30 天借阅数据用于评估"""
        from models import Book, Category, BorrowRecord, User
        from datetime import datetime, timedelta
        import random
        cat = Category(name="ec0")
        session.add(cat)
        session.flush()
        book = Book(title="eb", author="a", total_count=999,
                    available_count=999, category_id=cat.id)
        session.add(book)
        session.flush()
        u = User(username="eu", email="eu@x.com", role="reader")
        u.set_password("Test1234")
        session.add(u)
        session.flush()
        now = datetime.now()
        random.seed(123)
        for i in range(30):
            d = now - timedelta(days=29 - i)
            n = 3 + random.randint(0, 4)
            if d.weekday() >= 5:
                n += 2
            for _ in range(n):
                session.add(BorrowRecord(
                    user_id=u.id, book_id=book.id, borrow_date=d,
                    due_date=d + timedelta(days=30), status="borrowed"
                ))
        session.commit()

    def test_evaluation_metrics_shape(self, app, db_session):
        """种子 30 天，断言 MAE>=0、RMSE>=0、R² 在 [-1,1]、散点长度=测试集"""
        self._seed_borrows_30d(db_session)
        from services.forecast_service import evaluate_model
        result = evaluate_model(history_days=30, test_ratio=0.2)

        assert "error" not in result
        assert result["mae"] >= 0
        assert result["rmse"] >= 0
        assert -1 <= result["r2"] <= 1.0
        # 30 天 × 0.2 = 6 天验证集
        assert result["test_size"] == 6
        assert len(result["scatter"]) == 6
        # 残差直方图标签数与计数数一致
        assert len(result["residual_hist"]["labels"]) == len(result["residual_hist"]["counts"])

    def test_evaluation_insufficient_data(self, app, db_session):
        """种子 10 天，断言返回 error（<20 天阈值）"""
        self._seed_borrows_30d(db_session)
        from services.forecast_service import evaluate_model
        result = evaluate_model(history_days=10, test_ratio=0.2)
        assert "error" in result
        assert "数据不足" in result["error"]


class TestRecall:
    """RFM 召回闭环测试"""

    def _seed_recall_scenario(self, session, n_users=8):
        """造场景：含 Champions/At-risk/Lost/Inactive 多分群 + 可借书"""
        from models import User, Book, Category, BorrowRecord
        cats = [Category(name=f"rc{i}") for i in range(3)]
        session.add_all(cats)
        session.flush()
        books = [
            Book(title=f"rb{i}", author="a", total_count=10,
                 available_count=10, category_id=cats[i % 3].id)
            for i in range(6)
        ]
        session.add_all(books)
        session.flush()
        users = []
        for i in range(n_users):
            u = User(username=f"ru{i}", email=f"ru{i}@x.com", role="reader")
            u.set_password("Test1234")
            session.add(u)
            users.append(u)
        session.flush()
        now = datetime.now()
        # users[0..1]: 高频近期 → Champions
        # users[2..3]: 高频沉睡 → Loyal/Lost
        # users[4..5]: 低频沉睡 → At-risk/Lost
        # users[6..7]: 零借阅 → Inactive
        patterns = [
            (25, 0), (20, 1),    # Champions
            (25, 30), (20, 40),   # Loyal/Lost
            (3, 60), (2, 70),     # At-risk/Lost
        ]
        for u, (freq, days_ago) in zip(users[:6], patterns):
            for j in range(freq):
                session.add(BorrowRecord(
                    user_id=u.id, book_id=books[(u.id * 3 + j) % 6].id,
                    borrow_date=now - timedelta(days=days_ago + j),
                    due_date=now + timedelta(days=30), status="borrowed"
                ))
        session.commit()
        return users, books

    def test_generate_recall_targets_only(self, app, db_session):
        """断言召回动作只针对 At-risk/Lost/Inactive 用户"""
        self._seed_recall_scenario(db_session, 8)
        from services.rfm_service import compute_rfm, segment_users, generate_recall_actions
        rfm = compute_rfm()
        segmented, _ = segment_users(rfm)
        actions = generate_recall_actions(segmented, top_n=2)
        # 所有动作的 segment 必须在召回目标集合
        from services.rfm_service import RECALL_SEGMENTS
        assert all(a["segment"] in RECALL_SEGMENTS for a in actions)
        # 至少有召回目标（测试场景保证 At-risk/Lost/Inactive 存在）
        assert len(actions) > 0
        # 每个动作的推荐书单非空
        assert all(len(a["recommended_books"]) > 0 for a in actions)
        # 推荐书单结构正确
        assert all("title" in b and "author" in b for a in actions for b in a["recommended_books"])

    def test_send_recall_notifications(self, app, db_session):
        """断言发送召回后 Notification 表新增记录"""
        from models import Notification
        self._seed_recall_scenario(db_session, 8)
        from services.rfm_service import (
            compute_rfm, segment_users,
            generate_recall_actions, send_recall_notifications,
        )
        before = Notification.query.count()
        rfm = compute_rfm()
        segmented, _ = segment_users(rfm)
        actions = generate_recall_actions(segmented, top_n=2)
        sent = send_recall_notifications(actions)
        assert sent == len(actions)
        after = Notification.query.count()
        assert after - before == sent
        # 验证通知内容包含"推荐"
        notif = Notification.query.order_by(Notification.id.desc()).first()
        assert "推荐" in notif.content

    def test_analyze_recall_effect(self, app, db_session):
        """断言召回效果分析返回结构正确"""
        self._seed_recall_scenario(db_session, 8)
        from services.rfm_service import compute_rfm, segment_users, analyze_recall_effect
        rfm = compute_rfm()
        segmented, _ = segment_users(rfm)
        effect = analyze_recall_effect(segmented, window_days=7)
        assert effect["target_count"] > 0   # 有召回目标
        assert effect["champion_count"] > 0  # 有高价值对照
        assert effect["window_days"] == 7
        assert effect["target_rate"] >= 0
        assert effect["champion_rate"] >= 0
        # gap = champion_rate - target_rate
        assert abs(effect["gap"] - (effect["champion_rate"] - effect["target_rate"])) < 0.01
