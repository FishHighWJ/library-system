"""
集成测试 - 关键业务路径端到端验证
运行方式: pytest tests/test_integration.py -v

覆盖范围：
- 工具函数（utils.py）：log_operation / begin_immediate / db_retry
- 认证流程（routes/auth.py）：登录 / 登出 / 未授权拦截
- 图书路由（routes/books.py）：列表 / 详情 / 搜索
- 借阅流程（routes/borrow.py）：借书 / 还书 / 看板
- 数据分析路由（routes/analysis.py）：管理员可访问 / 读者被拒
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ 测试专用账号密码（与生产隔离，固定值便于复现） ============
TEST_ADMIN_PASSWORD = "TestAdmin@2026!"
TEST_READER_PASSWORD = "TestReader@2026!"


# ============ Fixtures ============

@pytest.fixture
def app():
    os.environ['FLASK_CONFIG'] = 'testing'
    os.environ['SECRET_KEY'] = 'test-secret-key-for-unit-tests-only'
    os.environ['ADMIN_PASSWORD'] = TEST_ADMIN_PASSWORD
    os.environ['READER_PASSWORD'] = TEST_READER_PASSWORD
    from app import create_app
    app = create_app('testing')
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_with_seed(app):
    """初始化数据库 + 种子数据（1 分类 + 2 本书 + 1 读者借阅记录）"""
    from models import db, Category, Book, User, BorrowRecord
    with app.app_context():
        db.create_all()
        cat = Category(name="integration_cat")
        db.session.add(cat)
        db.session.flush()
        book = Book(title="测试书A", author="作者A", total_count=3,
                    available_count=3, category_id=cat.id, isbn="978-0000000001")
        db.session.add(book)
        db.session.flush()
        # 借一本给 reader，制造历史数据
        reader = User.query.filter_by(username="reader").first()
        if reader:
            db.session.add(BorrowRecord(
                user_id=reader.id, book_id=book.id,
                borrow_date=datetime.now() - timedelta(days=5),
                due_date=datetime.now() + timedelta(days=25),
                status="borrowed",
            ))
            book.available_count -= 1
        db.session.commit()
        yield db.session
        db.session.remove()


@pytest.fixture
def admin_client(app, db_with_seed):
    """已登录管理员的 client"""
    client = app.test_client()
    client.post('/login', data={
        'username': 'admin',
        'password': TEST_ADMIN_PASSWORD,
    }, follow_redirects=True)
    return client


@pytest.fixture
def reader_client(app, db_with_seed):
    """已登录读者的 client"""
    client = app.test_client()
    client.post('/login', data={
        'username': 'reader',
        'password': TEST_READER_PASSWORD,
    }, follow_redirects=True)
    return client


# ============ 工具函数测试 ============

class TestUtils:
    """utils.py 工具函数测试"""

    def test_log_operation(self, app, db_with_seed):
        """测试审计日志记录"""
        from utils import log_operation
        from models import OperationLog
        with app.test_request_context('/'):
            log_operation(user_id=1, action="test_action",
                           target_type="book", target_id=1, detail="test")
            logs = OperationLog.query.filter_by(action="test_action").all()
            assert len(logs) >= 1
            assert logs[-1].target_id == 1

    def test_log_operation_no_request(self, app, db_with_seed):
        """测试无 request 上下文时 ip_address 兜底为 system"""
        from utils import log_operation
        from models import OperationLog
        # 在非 request 上下文调用（request 为 None）
        log_operation(user_id=1, action="bg_action",
                      target_type="book", target_id=2)
        log = OperationLog.query.filter_by(action="bg_action").first()
        assert log is not None
        assert log.ip_address == "system"

    def test_begin_immediate_commit(self, app, db_with_seed):
        """测试 BEGIN IMMEDIATE 正常提交"""
        from utils import begin_immediate
        from models import db, Category
        with app.app_context():
            with begin_immediate():
                db.session.add(Category(name="immediate_test"))
            cat = Category.query.filter_by(name="immediate_test").first()
            assert cat is not None

    def test_begin_immediate_rollback(self, app, db_with_seed):
        """测试 BEGIN IMMEDIATE 异常时回滚"""
        from utils import begin_immediate
        from models import db, Category
        with app.app_context():
            with pytest.raises(ValueError):
                with begin_immediate():
                    db.session.add(Category(name="rollback_test"))
                    raise ValueError("intentional")
            cat = Category.query.filter_by(name="rollback_test").first()
            assert cat is None

    def test_db_retry_normal_path(self, app, db_with_seed):
        """测试 db_retry 装饰器正常路径"""
        from utils import db_retry

        @db_retry(max_retries=3)
        def success_fn():
            return "ok"

        with app.test_request_context('/'):
            result = success_fn()
            assert result == "ok"

    def test_db_retry_with_lock_error(self, app, db_with_seed):
        """测试 db_retry 遇到锁错误时重试并最终成功"""
        from utils import db_retry
        from sqlalchemy.exc import OperationalError
        call_count = {"n": 0}

        @db_retry(max_retries=3)
        def flaky_fn():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise OperationalError("stmt", {}, Exception("database is locked"))
            return "recovered"

        with app.test_request_context('/'):
            result = flaky_fn()
            assert result == "recovered"
            assert call_count["n"] == 2


# ============ 认证流程测试 ============

class TestAuthIntegration:
    """认证路由集成测试"""

    def test_login_page_get(self, client):
        """GET /login 返回 200"""
        resp = client.get('/login')
        assert resp.status_code == 200
        assert '登录' in resp.data.decode('utf-8')

    def test_admin_login_success(self, app, db_with_seed):
        """管理员正确密码登录成功"""
        client = app.test_client()
        resp = client.post('/login', data={
            'username': 'admin',
            'password': TEST_ADMIN_PASSWORD,
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_login_wrong_password(self, app, db_with_seed):
        """错误密码登录失败"""
        client = app.test_client()
        resp = client.post('/login', data={
            'username': 'admin',
            'password': 'wrongpassword',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # 应包含错误提示
        assert '密码' in resp.data.decode('utf-8') or '失败' in resp.data.decode('utf-8')

    def test_logout(self, admin_client):
        """登录后登出"""
        resp = admin_client.get('/logout', follow_redirects=True)
        assert resp.status_code == 200

    def test_register_page(self, client):
        """GET /register 返回 200"""
        resp = client.get('/register')
        assert resp.status_code == 200


# ============ 图书路由测试 ============

class TestBookIntegration:
    """图书路由集成测试"""

    def test_book_list_requires_login(self, client):
        """未登录访问图书列表 → 重定向到登录"""
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code in (301, 302)

    def test_book_list_after_login(self, reader_client):
        """登录后访问图书列表 → 200"""
        resp = reader_client.get('/', follow_redirects=True)
        assert resp.status_code == 200

    def test_book_detail(self, reader_client, db_with_seed):
        """图书详情页正常返回"""
        resp = reader_client.get('/book/1', follow_redirects=True)
        assert resp.status_code == 200

    def test_book_detail_not_found(self, reader_client, db_with_seed):
        """不存在的图书 ID 登录后返回 404"""
        resp = reader_client.get('/book/99999', follow_redirects=True)
        assert resp.status_code == 404

    def test_book_search(self, reader_client, db_with_seed):
        """搜索功能正常"""
        resp = reader_client.get('/?q=测试', follow_redirects=True)
        assert resp.status_code == 200


# ============ 借阅流程测试 ============

class TestBorrowIntegration:
    """借阅流程集成测试"""

    def test_my_borrows_requires_login(self, client):
        """未登录访问我的借阅 → 重定向到登录"""
        resp = client.get('/my-borrows', follow_redirects=False)
        assert resp.status_code in (301, 302)

    def test_my_borrows_after_login(self, reader_client):
        """登录后访问我的借阅 → 200"""
        resp = reader_client.get('/my-borrows', follow_redirects=True)
        assert resp.status_code == 200

    def test_borrow_book(self, reader_client, db_with_seed):
        """读者借书流程"""
        resp = reader_client.post('/borrow/1', follow_redirects=True)
        assert resp.status_code == 200
        # 验证 available_count 减 1
        from models import db, Book
        with reader_client.application.app_context():
            db.session.remove()
            book = Book.query.get(1)
            assert book.available_count < book.total_count

    def test_return_book(self, reader_client, db_with_seed):
        """读者还书流程"""
        # 先借一本
        reader_client.post('/borrow/1', follow_redirects=True)
        # 查 reader 的借阅记录
        from models import db, BorrowRecord, User
        with reader_client.application.app_context():
            db.session.remove()
            reader = User.query.filter_by(username="reader").first()
            records = BorrowRecord.query.filter_by(
                user_id=reader.id, status="borrowed"
            ).all()
            assert len(records) > 0
            record_id = records[-1].id
        # 还书
        resp = reader_client.post(f'/return/{record_id}', follow_redirects=True)
        assert resp.status_code == 200
        with reader_client.application.app_context():
            db.session.remove()
            rec = BorrowRecord.query.get(record_id)
            assert rec.status == "returned"

    def test_dashboard_requires_admin(self, reader_client):
        """读者访问数据看板 → 403 或重定向"""
        resp = reader_client.get('/dashboard', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_dashboard_admin_ok(self, admin_client):
        """管理员访问数据看板 → 200"""
        resp = admin_client.get('/dashboard', follow_redirects=True)
        assert resp.status_code == 200


# ============ 数据分析路由测试 ============

class TestAnalysisIntegration:
    """数据分析路由集成测试"""

    def test_rfm_requires_admin(self, reader_client):
        """读者访问 RFM 分群 → 403"""
        resp = reader_client.get('/analysis/rfm', follow_redirects=False)
        assert resp.status_code == 403

    def test_rfm_admin_ok(self, admin_client):
        """管理员访问 RFM 分群 → 200"""
        resp = admin_client.get('/analysis/rfm', follow_redirects=True)
        assert resp.status_code == 200

    def test_prediction_admin_ok(self, admin_client):
        """管理员访问借阅预测 → 200"""
        resp = admin_client.get('/analysis/prediction', follow_redirects=True)
        assert resp.status_code == 200

    def test_evaluation_admin_ok(self, admin_client):
        """管理员访问模型评估 → 200"""
        resp = admin_client.get('/analysis/evaluation', follow_redirects=True)
        assert resp.status_code == 200

    def test_prediction_requires_login(self, client):
        """未登录访问预测页 → 重定向到登录"""
        resp = client.get('/analysis/prediction', follow_redirects=False)
        assert resp.status_code in (301, 302)


# ============ 反馈路由测试 ============

class TestFeedbackIntegration:
    """反馈路由集成测试"""

    def test_feedback_list_requires_login(self, client):
        """未登录访问反馈列表 → 重定向"""
        resp = client.get('/feedback', follow_redirects=False)
        assert resp.status_code in (301, 302)

    def test_feedback_list_after_login(self, reader_client):
        """登录后访问反馈列表 → 200"""
        resp = reader_client.get('/feedback', follow_redirects=True)
        assert resp.status_code == 200

    def test_feedback_form_page(self, reader_client):
        """反馈表单页 → 200"""
        resp = reader_client.get('/feedback/new', follow_redirects=True)
        assert resp.status_code == 200

    def test_submit_suggestion_feedback(self, reader_client):
        """提交意见建议反馈 → 成功重定向"""
        resp = reader_client.post('/feedback/new', data={
            'feedback_type': 'suggestion',
            'title': '测试建议',
            'content': '这是一条测试建议内容',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from models import db, Feedback
        with reader_client.application.app_context():
            db.session.remove()
            fb = Feedback.query.filter_by(title='测试建议').first()
            assert fb is not None
            assert fb.feedback_type == 'suggestion'

    def test_submit_book_request_feedback(self, reader_client):
        """提交图书荐购反馈 → 成功"""
        resp = reader_client.post('/feedback/new', data={
            'feedback_type': 'book_request',
            'title': '荐购《深度学习》',
            'content': '希望图书馆采购此书',
            'book_title': '深度学习',
            'book_author': 'Ian Goodfellow',
            'book_isbn': '9787112234211',
            'book_publisher': '人民邮电出版社',
            'book_price': '99.0',
            'book_category': '计算机',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from models import db, Feedback
        with reader_client.application.app_context():
            db.session.remove()
            fb = Feedback.query.filter_by(title='荐购《深度学习》').first()
            assert fb is not None
            assert fb.feedback_type == 'book_request'
            assert fb.book_title == '深度学习'

    def test_submit_feedback_missing_title(self, reader_client):
        """提交缺标题的反馈 → 闪现错误"""
        resp = reader_client.post('/feedback/new', data={
            'feedback_type': 'suggestion',
            'title': '',
            'content': '内容',
        }, follow_redirects=False)
        # 缺标题应回到表单页（200）而非重定向
        assert resp.status_code == 200

    def test_feedback_manage_admin_ok(self, admin_client):
        """管理员访问反馈管理 → 200"""
        resp = admin_client.get('/feedback/manage', follow_redirects=True)
        assert resp.status_code == 200

    def test_notifications_page(self, reader_client):
        """通知中心页 → 200"""
        resp = reader_client.get('/notifications', follow_redirects=True)
        assert resp.status_code == 200
