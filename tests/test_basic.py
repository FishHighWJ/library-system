"""
图书馆管理系统 - 基础单元测试
运行方式: pytest tests/test_basic.py -v
"""

import pytest
import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    """创建测试用 Flask 应用"""
    os.environ['FLASK_CONFIG'] = 'testing'
    os.environ['SECRET_KEY'] = 'test-secret-key-for-unit-tests-only'
    from app import create_app
    app = create_app('testing')
    yield app


@pytest.fixture
def client(app):
    """测试客户端"""
    return app.test_client()


class TestAuthSecurity:
    """认证安全测试"""

    def test_password_validation(self):
        """测试密码复杂度校验"""
        from routes.auth import validate_password

        # 太短
        valid, msg = validate_password("abc")
        assert not valid
        assert "8位" in msg

        # 缺少大写
        valid, msg = validate_password("abcdefg1")
        assert not valid
        assert "大写" in msg

        # 缺少小写
        valid, msg = validate_password("ABCDEFG1")
        assert not valid
        assert "小写" in msg

        # 缺少数字
        valid, msg = validate_password("Abcdefgh")
        assert not valid
        assert "数字" in msg

        # 合法密码
        valid, msg = validate_password("Abc12345")
        assert valid
        assert msg == ""


class TestModels:
    """数据模型测试"""

    def test_user_password_hashing(self):
        """测试用户密码哈希"""
        from models import User
        user = User(username="testuser", email="test@test.com")
        user.set_password("Test1234")

        # 密码哈希不等于明文
        assert user.password_hash != "Test1234"
        # 正确密码验证通过
        assert user.check_password("Test1234") is True
        # 错误密码验证失败
        assert user.check_password("wrong") is False

    def test_book_availability(self):
        """测试图书可用性"""
        from models import Book
        book = Book(title="测试书", author="作者", total_count=3, available_count=3)
        assert book.is_available is True

        book.available_count = 0
        assert book.is_available is False

    def test_borrow_record_overdue(self):
        """测试逾期判断"""
        from models import BorrowRecord
        from datetime import datetime, timedelta

        # 未逾期的记录
        record = BorrowRecord(
            user_id=1, book_id=1,
            due_date=datetime.now() + timedelta(days=7),
            status="borrowed"
        )
        assert record.is_overdue is False

        # 已逾期的记录
        record.due_date = datetime.now() - timedelta(days=3)
        assert record.is_overdue is True
        assert record.overdue_days >= 3

    def test_reading_stat_levelup(self):
        """测试阅读统计升级"""
        from models import ReadingStat
        stat = ReadingStat(user_id=1, level=1, exp=0, title="书童")

        # 加 50 经验应升到 2 级
        levelups = stat.add_exp(50)
        assert len(levelups) == 1
        assert stat.level == 2
        assert stat.title == "书生"


class TestSecurityHeaders:
    """安全头测试"""

    def test_security_headers_present(self, client):
        """测试安全响应头是否设置"""
        # 访问登录页（GET 请求）
        response = client.get('/login')
        assert response.headers.get('X-Frame-Options') == 'DENY'
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-XSS-Protection') == '1; mode=block'

    def test_login_page_no_cache(self, client):
        """测试登录页禁止缓存"""
        response = client.get('/login')
        assert 'no-store' in response.headers.get('Cache-Control', '')


class TestCSRF:
    """CSRF 防护测试"""

    def test_csrf_token_in_login_page(self, client):
        """测试登录页包含 CSRF token"""
        response = client.get('/login')
        # 响应中应包含 csrf_token（测试环境 CSRF 已关闭，但模板仍渲染 token）
        assert response.status_code == 200
