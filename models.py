"""
数据模型 - 图书馆图书管理系统
定义数据库表结构：用户、图书分类、图书、借阅记录
使用 Flask-SQLAlchemy ORM 映射数据库
"""

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# 创建SQLAlchemy实例，在app.py中初始化
db = SQLAlchemy()


class User(UserMixin, db.Model):
    """用户模型 - 管理员和普通读者"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, comment="用户名")
    email = db.Column(db.String(120), unique=True, nullable=False, comment="邮箱")
    password_hash = db.Column(db.String(255), nullable=False, comment="密码哈希")
    role = db.Column(db.String(20), default="reader", comment="角色: admin/reader")
    phone = db.Column(db.String(20), comment="手机号")
    is_active = db.Column(db.Boolean, default=True, comment="是否启用")
    created_at = db.Column(db.DateTime, default=datetime.now, comment="注册时间")

    # 关联借阅记录
    borrows = db.relationship("BorrowRecord", backref="user", lazy="dynamic")

    def set_password(self, password):
        """设置密码（加密存储）"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        """判断是否为管理员"""
        return self.role == "admin"

    def __repr__(self):
        return f"<User {self.username}>"


class Category(db.Model):
    """图书分类模型"""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, comment="分类名称")
    description = db.Column(db.String(200), comment="分类描述")
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联图书
    books = db.relationship("Book", backref="category", lazy="dynamic")

    def __repr__(self):
        return f"<Category {self.name}>"


class Book(db.Model):
    """图书模型"""

    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), unique=True, comment="ISBN号")
    title = db.Column(db.String(200), nullable=False, comment="书名")
    author = db.Column(db.String(100), nullable=False, comment="作者")
    publisher = db.Column(db.String(100), comment="出版社")
    publish_date = db.Column(db.Date, comment="出版日期")
    price = db.Column(db.Float, default=0, comment="价格")
    description = db.Column(db.Text, comment="简介")
    cover_url = db.Column(db.String(500), default="", comment="封面图URL")
    total_count = db.Column(db.Integer, default=1, comment="总数量")
    available_count = db.Column(db.Integer, default=1, comment="可借数量")
    location = db.Column(db.String(100), comment="馆藏位置")
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), comment="分类ID")
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联借阅记录
    borrows = db.relationship("BorrowRecord", backref="book", lazy="dynamic")

    @property
    def is_available(self):
        """是否可借"""
        return self.available_count > 0

    def __repr__(self):
        return f"<Book {self.title}>"


class BorrowRecord(db.Model):
    """借阅记录模型"""

    __tablename__ = "borrow_records"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)
    borrow_date = db.Column(db.DateTime, default=datetime.now, comment="借阅日期")
    due_date = db.Column(db.DateTime, nullable=False, comment="应还日期")
    return_date = db.Column(db.DateTime, nullable=True, comment="实际归还日期")
    status = db.Column(db.String(20), default="borrowed", comment="状态: borrowed/returned/overdue")
    fine = db.Column(db.Float, default=0, comment="罚款金额")
    remark = db.Column(db.String(200), comment="备注")
    # 并发控制：版本号，用于乐观锁
    version = db.Column(db.Integer, default=0, comment="乐观锁版本号")

    @property
    def is_overdue(self):
        """是否逾期"""
        if self.status == "returned":
            return False
        return datetime.now() > self.due_date

    @property
    def overdue_days(self):
        """逾期天数"""
        if not self.is_overdue:
            return 0
        delta = datetime.now() - self.due_date
        return delta.days

    def calculate_fine(self, fine_per_day=0.5):
        """计算罚款"""
        if self.is_overdue:
            self.fine = self.overdue_days * fine_per_day
        return self.fine

    def __repr__(self):
        return f"<BorrowRecord {self.id}>"


class OperationLog(db.Model):
    """操作审计日志模型 - 记录所有关键操作"""

    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, comment="操作用户ID")
    action = db.Column(db.String(50), nullable=False, comment="操作类型: borrow/return/add_book/edit_book/delete_book/login/register/toggle_user")
    target_type = db.Column(db.String(30), comment="操作对象类型: book/user/category")
    target_id = db.Column(db.Integer, comment="操作对象ID")
    detail = db.Column(db.String(500), comment="操作详情")
    ip_address = db.Column(db.String(50), comment="IP地址")
    created_at = db.Column(db.DateTime, default=datetime.now, comment="操作时间")

    # 关联用户
    operator = db.relationship("User", backref="operation_logs", foreign_keys=[user_id])

    def __repr__(self):
        return f"<OperationLog {self.id} {self.action}>"


class Feedback(db.Model):
    """用户反馈模型 - 意见建议、图书荐购"""

    __tablename__ = "feedbacks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, comment="提交用户ID")
    feedback_type = db.Column(db.String(20), nullable=False, comment="类型: suggestion/book_request/bug_report/complaint")
    # suggestion=功能建议, book_request=图书荐购, bug_report=问题报告, complaint=投诉
    title = db.Column(db.String(200), nullable=False, comment="标题")
    content = db.Column(db.Text, nullable=False, comment="详细内容")

    # 图书荐购专用字段
    book_title = db.Column(db.String(200), comment="荐购书名")
    book_author = db.Column(db.String(100), comment="荐购作者")
    book_isbn = db.Column(db.String(20), comment="荐购ISBN")
    book_publisher = db.Column(db.String(100), comment="荐购出版社")
    book_price = db.Column(db.Float, comment="荐购价格")
    book_category = db.Column(db.String(50), comment="荐购分类建议")

    # 状态管理
    status = db.Column(db.String(20), default="pending", comment="状态: pending/reviewing/accepted/rejected/resolved")
    # pending=待处理, reviewing=处理中, accepted=已采纳, rejected=已驳回, resolved=已解决
    admin_reply = db.Column(db.Text, comment="管理员回复")
    priority = db.Column(db.Integer, default=0, comment="优先级: 0普通 1重要 2紧急")

    created_at = db.Column(db.DateTime, default=datetime.now, comment="提交时间")
    replied_at = db.Column(db.DateTime, nullable=True, comment="回复时间")

    # 关联用户和回复人
    submitter = db.relationship("User", backref="feedbacks", foreign_keys=[user_id])
    rating = db.Column(db.Integer, default=0, comment="用户满意度评分: 0未评 1-5星")

    def __repr__(self):
        return f"<Feedback {self.id} {self.feedback_type}>"


class Notification(db.Model):
    """站内通知模型 - 到期提醒、反馈回复、系统公告"""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, comment="接收用户ID")
    notification_type = db.Column(db.String(30), nullable=False, comment="类型: due_reminder/overdue_notice/feedback_reply/system_notice")
    # due_reminder=到期提醒, overdue_notice=逾期通知, feedback_reply=反馈回复, system_notice=系统公告
    title = db.Column(db.String(200), nullable=False, comment="通知标题")
    content = db.Column(db.Text, nullable=False, comment="通知内容")
    related_id = db.Column(db.Integer, comment="关联ID（借阅记录/反馈ID等）")
    is_read = db.Column(db.Boolean, default=False, comment="是否已读")
    created_at = db.Column(db.DateTime, default=datetime.now, comment="创建时间")

    # 关联用户
    recipient = db.relationship("User", backref="notifications", foreign_keys=[user_id])

    def __repr__(self):
        return f"<Notification {self.id} {self.notification_type}>"


class ReadingStat(db.Model):
    """阅读统计模型 - 用户的阅读数据和等级"""

    __tablename__ = "reading_stats"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    # 等级与经验
    level = db.Column(db.Integer, default=1, comment="等级")
    exp = db.Column(db.Integer, default=0, comment="经验值")
    title = db.Column(db.String(20), default="书童", comment="称号")

    # 累计统计
    total_books_borrowed = db.Column(db.Integer, default=0, comment="累计借阅图书数")
    total_categories_read = db.Column(db.Integer, default=0, comment="涉猎分类数")
    total_fine_paid = db.Column(db.Float, default=0, comment="累计罚款金额")
    on_time_return_rate = db.Column(db.Float, default=100.0, comment="按时归还率(%)")

    # 连续借阅
    current_streak = db.Column(db.Integer, default=0, comment="当前连续借阅天数")
    longest_streak = db.Column(db.Integer, default=0, comment="最长连续借阅天数")
    last_borrow_date = db.Column(db.Date, nullable=True, comment="最近一次借阅日期")

    # 阅读速度
    fastest_read_hours = db.Column(db.Float, nullable=True, comment="最快读完时间(小时)")
    avg_read_days = db.Column(db.Float, default=0, comment="平均阅读天数")

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联用户
    user = db.relationship("User", backref=db.backref("reading_stat", uselist=False))

    LEVEL_EXP = [0, 50, 150, 350, 700, 1200, 2000, 3000, 5000, 10000]
    LEVEL_TITLES = [
        "书童", "书生", "秀才", "举人", "贡士",
        "进士", "探花", "榜眼", "状元", "大学士"
    ]

    @property
    def next_level_exp(self):
        """下一级所需经验"""
        if self.level >= len(self.LEVEL_EXP):
            return None
        return self.LEVEL_EXP[self.level]  # level从1开始，索引用level值

    @property
    def exp_progress(self):
        """当前等级经验进度百分比"""
        if self.level >= len(self.LEVEL_EXP):
            return 100
        current_level_base = self.LEVEL_EXP[self.level - 1] if self.level > 0 else 0
        next_level = self.LEVEL_EXP[self.level] if self.level < len(self.LEVEL_EXP) else current_level_base
        diff = next_level - current_level_base
        if diff <= 0:
            return 100
        return int(min(100, (self.exp - current_level_base) / diff * 100))

    def add_exp(self, amount):
        """增加经验值，自动升级，返回升级信息列表"""
        levelups = []
        self.exp += amount

        while True:
            if self.level >= len(self.LEVEL_EXP):
                break
            next_exp = self.LEVEL_EXP[self.level]  # level从1开始
            if self.exp >= next_exp:
                self.level += 1
                self.title = self.LEVEL_TITLES[self.level - 1]
                levelups.append({
                    "new_level": self.level,
                    "new_title": self.title,
                })
            else:
                break

        return levelups

    def __repr__(self):
        return f"<ReadingStat user={self.user_id} Lv.{self.level} {self.title}>"


class Achievement(db.Model):
    """成就定义模型"""

    __tablename__ = "achievements"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, comment="成就名称")
    description = db.Column(db.String(200), nullable=False, comment="成就描述")
    icon = db.Column(db.String(50), default="trophy", comment="图标(bootstrap icon名)")
    icon_color = db.Column(db.String(20), default="warning", comment="图标颜色")
    category = db.Column(db.String(20), default="general", comment="分类: borrow/category/speed/social/special")
    # borrow=借阅类, category=分类探索, speed=速度类, social=社交类, special=特殊类
    condition_type = db.Column(db.String(30), nullable=False, comment="条件类型")
    # borrow_count=借阅数量, streak_days=连续天数, category_count=分类数量,
    # read_speed=阅读速度, fine_free=零罚款, first_action=首次动作, feedback_accepted=荐购采纳
    condition_value = db.Column(db.Integer, default=1, comment="条件数值")
    reward_exp = db.Column(db.Integer, default=0, comment="奖励经验值")
    rarity = db.Column(db.String(10), default="common", comment="稀有度: common/rare/epic/legendary")
    sort_order = db.Column(db.Integer, default=0, comment="排序")
    is_active = db.Column(db.Boolean, default=True, comment="是否启用")
    created_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Achievement {self.id} {self.name}>"


class UserAchievement(db.Model):
    """用户成就关联表"""

    __tablename__ = "user_achievements"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey("achievements.id"), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.now, comment="获得时间")

    # 关联
    user = db.relationship("User", backref="user_achievements")
    achievement = db.relationship("Achievement", backref="user_achievements")

    __table_args__ = (
        db.UniqueConstraint("user_id", "achievement_id", name="unique_user_achievement"),
    )

    def __repr__(self):
        return f"<UserAchievement user={self.user_id} ach={self.achievement_id}>"


class EncouragingQuote(db.Model):
    """鼓励语录库"""

    __tablename__ = "encouraging_quotes"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(300), nullable=False, comment="语录内容")
    author = db.Column(db.String(50), default="佚名", comment="作者")
    category = db.Column(db.String(20), default="general", comment="分类: general/borrow/return/levelup/special")
    min_level = db.Column(db.Integer, default=0, comment="最低等级显示")
    max_level = db.Column(db.Integer, default=999, comment="最高等级显示")

    @classmethod
    def get_random(cls, category="general", level=1):
        """随机获取一条适合当前等级的语录"""
        import random
        quotes = cls.query.filter(
            cls.category == category,
            cls.min_level <= level,
            cls.max_level >= level,
        ).all()
        if not quotes:
            quotes = cls.query.filter_by(category="general").all()
        if not quotes:
            return None
        return random.choice(quotes)

    def __repr__(self):
        return f"<Quote {self.id}: {self.content[:20]}>"
