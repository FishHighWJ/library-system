"""
数据库初始化脚本 - 生成测试数据
运行: python init_db.py
会创建分类、图书、成就、语录等示例数据
"""

import random
from app import app
from models import (
    db, Category, Book, User, BorrowRecord,
    Achievement, EncouragingQuote, ReadingStat
)
from datetime import datetime, timedelta


def init_categories():
    """创建图书分类"""
    categories = [
        ("文学小说", "中外文学小说、散文、诗歌"),
        ("计算机科学", "编程、算法、软件工程、人工智能"),
        ("历史人文", "世界历史、人物传记、文化研究"),
        ("经济管理", "经济学、管理学、金融投资"),
        ("自然科学", "数学、物理、化学、生物"),
        ("艺术设计", "设计、音乐、绘画、影视"),
    ]
    for name, desc in categories:
        cat = Category.query.filter_by(name=name).first()
        if not cat:
            cat = Category(name=name, description=desc)
            db.session.add(cat)
    db.session.commit()
    print(f"[OK] 创建 {len(categories)} 个分类")


def init_books():
    """创建示例图书"""
    sample_books = [
        ("9787111407010", "算法导论", "Thomas H. Cormen", "机械工业出版社", 128, "计算机科学", "A-01-001", 3),
        ("9787121362407", "Python编程：从入门到实践", "Eric Matthes", "人民邮电出版社", 89, "计算机科学", "A-01-002", 5),
        ("9787115546081", "深入理解计算机系统", "Randal E. Bryant", "人民邮电出版社", 139, "计算机科学", "A-01-003", 2),
        ("9787302517508", "数据结构（C语言版）", "严蔚敏", "清华大学出版社", 39, "计算机科学", "A-01-004", 4),
        ("9787115489496", "图解HTTP", "上野宣", "人民邮电出版社", 59, "计算机科学", "A-01-005", 3),
        ("9787108018831", "百年孤独", "加西亚·马尔克斯", "三联书店", 55, "文学小说", "B-02-001", 3),
        ("9787544291170", "活着", "余华", "南海出版公司", 35, "文学小说", "B-02-002", 5),
        ("9787544270878", "解忧杂货店", "东野圭吾", "南海出版公司", 39.5, "文学小说", "B-02-003", 4),
        ("9787020002207", "红楼梦", "曹雪芹", "人民文学出版社", 59.7, "文学小说", "B-02-004", 3),
        ("9787506365437", "平凡的世界", "路遥", "北京十月文艺出版社", 79, "文学小说", "B-02-005", 2),
        ("9787544258617", "追风筝的人", "卡勒德·胡赛尼", "南海出版公司", 29, "文学小说", "B-02-006", 4),
        ("9787100075597", "万历十五年", "黄仁宇", "中华书局", 38, "历史人文", "C-03-001", 2),
        ("9787108018824", "人类简史", "尤瓦尔·赫拉利", "三联书店", 68, "历史人文", "C-03-002", 3),
        ("9787550255874", "枪炮、病菌与钢铁", "贾雷德·戴蒙德", "中信出版社", 58, "历史人文", "C-03-003", 2),
        ("9787508681439", "经济学原理", "曼昆", "中信出版社", 128, "经济管理", "D-04-001", 3),
        ("9787111557963", "管理的实践", "彼得·德鲁克", "机械工业出版社", 49, "经济管理", "D-04-002", 2),
        ("9787544258709", "薛兆丰经济学讲义", "薛兆丰", "中信出版社", 58, "经济管理", "D-04-003", 4),
        ("9787514215197", "时间简史", "史蒂芬·霍金", "北京联合出版公司", 45, "自然科学", "E-05-001", 3),
        ("9787108023098", "美的历程", "李泽厚", "三联书店", 56, "艺术设计", "F-06-001", 2),
        ("9787550283112", "艺术的故事", "贡布里希", "广西美术出版社", 280, "艺术设计", "F-06-002", 1),
    ]

    created = 0
    for isbn, title, author, publisher, price, cat_name, loc, count in sample_books:
        if Book.query.filter_by(isbn=isbn).first():
            continue
        cat = Category.query.filter_by(name=cat_name).first()
        book = Book(
            isbn=isbn,
            title=title,
            author=author,
            publisher=publisher,
            price=price,
            description=f"《{title}》是由{author}编著的优秀图书，馆藏位置：{loc}",
            total_count=count,
            available_count=count,
            location=loc,
            category_id=cat.id if cat else None,
        )
        db.session.add(book)
        created += 1
    db.session.commit()
    print(f"[OK] 创建 {created} 本示例图书")


def init_borrow_records():
    """创建示例借阅记录"""
    reader = User.query.filter_by(username="reader").first()
    if not reader:
        return

    books = Book.query.limit(3).all()
    for book in books:
        if book.available_count <= 0:
            continue
        existing = BorrowRecord.query.filter_by(
            user_id=reader.id, book_id=book.id, status="borrowed"
        ).first()
        if existing:
            continue

        record = BorrowRecord(
            user_id=reader.id,
            book_id=book.id,
            borrow_date=datetime.now() - timedelta(days=random.randint(1, 20)),
            due_date=datetime.now() + timedelta(days=random.randint(1, 15)),
            status="borrowed",
        )
        db.session.add(record)
        book.available_count -= 1
    db.session.commit()
    print("[OK] 创建示例借阅记录")


def init_achievements():
    """创建成就定义"""
    achievements_data = [
        # ---- 借阅类 ----
        ("初出茅庐", "完成第一次借阅", "book-half", "primary", "borrow", "first_action", 1, 10, "common", 1),
        ("小有所成", "累计借阅5本图书", "book", "primary", "borrow", "borrow_count", 5, 30, "common", 2),
        ("手不释卷", "累计借阅10本图书", "journal-bookmark", "primary", "borrow", "borrow_count", 10, 50, "rare", 3),
        ("博览群书", "累计借阅30本图书", "library", "primary", "borrow", "borrow_count", 30, 100, "rare", 4),
        ("汗牛充栋", "累计借阅50本图书", "stack", "primary", "borrow", "borrow_count", 50, 200, "epic", 5),
        ("学富五车", "累计借阅100本图书", "mortarboard", "primary", "borrow", "borrow_count", 100, 500, "legendary", 6),

        # ---- 连续借阅 ----
        ("坚持不懈", "连续3天借阅", "fire", "danger", "borrow", "streak_days", 3, 20, "common", 10),
        ("锲而不舍", "连续7天借阅", "fire", "danger", "borrow", "streak_days", 7, 50, "rare", 11),
        ("滴水穿石", "连续30天借阅", "fire", "danger", "borrow", "streak_days", 30, 200, "epic", 12),

        # ---- 分类探索 ----
        ("涉猎广泛", "阅读2个不同分类的图书", "compass", "success", "category", "category_count", 2, 20, "common", 20),
        ("跨界探索", "阅读4个不同分类的图书", "globe", "success", "category", "category_count", 4, 50, "rare", 21),
        ("全才读者", "阅读全部6个分类的图书", "globe2", "success", "category", "category_count", 6, 150, "epic", 22),

        # ---- 速度类 ----
        ("一目十行", "24小时内读完一本书", "lightning-charge", "warning", "speed", "read_speed", 24, 30, "rare", 30),
        ("速读达人", "8小时内读完一本书", "lightning", "warning", "speed", "read_speed", 8, 80, "epic", 31),
        ("闪电读者", "2小时内读完一本书", "bolt", "warning", "speed", "read_speed", 2, 200, "legendary", 32),

        # ---- 守信类 ----
        ("信守承诺", "按时归还5本书", "check-circle", "info", "borrow", "return_count", 5, 30, "common", 40),
        ("准时达人", "按时归还20本书", "clock", "info", "borrow", "return_count", 20, 80, "rare", 41),
        ("零罚款骑士", "借阅10本以上且从未逾期", "shield-check", "info", "borrow", "fine_free", 10, 100, "epic", 42),

        # ---- 特殊类 ----
        ("反馈之声", "提交第一条反馈建议", "chat-dots", "secondary", "special", "first_action", 1, 10, "common", 50),
        ("荐购贡献者", "您的荐购被采纳并添加到馆藏", "gift", "secondary", "special", "first_action", 1, 50, "rare", 51),
    ]

    created = 0
    for (name, desc, icon, color, cat, cond_type,
         cond_val, reward, rarity, order) in achievements_data:
        if Achievement.query.filter_by(name=name).first():
            continue
        ach = Achievement(
            name=name,
            description=desc,
            icon=icon,
            icon_color=color,
            category=cat,
            condition_type=cond_type,
            condition_value=cond_val,
            reward_exp=reward,
            rarity=rarity,
            sort_order=order,
        )
        db.session.add(ach)
        created += 1

    db.session.commit()
    print(f"[OK] 创建 {created} 个成就定义")


def init_quotes():
    """创建鼓励语录库"""
    quotes_data = [
        # 通用语录
        ("阅读是一座随身携带的避难所。", "毛姆", "general", 0, 999),
        ("读书破万卷，下笔如有神。", "杜甫", "general", 0, 999),
        ("书籍是人类进步的阶梯。", "高尔基", "general", 0, 999),
        ("腹有诗书气自华。", "苏轼", "general", 0, 999),
        ("读万卷书，行万里路。", "刘彝", "general", 0, 999),

        # 借书时
        ("又一本好书被你收入囊中，知识之旅再次启程！", "图书馆", "borrow", 0, 999),
        ("每一本借出的书，都是一次与智慧的约会。", "图书馆", "borrow", 0, 999),
        ("你借走的不只是一本书，更是一段思想的旅程。", "图书馆", "borrow", 0, 999),
        ("书犹药也，善读之可以医愚。好好享用吧！", "刘向", "borrow", 0, 999),
        ("此刻你手中的书，也许就是改变你的那本。", "图书馆", "borrow", 0, 999),

        # 还书时
        ("感谢你让知识重新流转，让更多人受益！", "图书馆", "return", 0, 999),
        ("读完一本书，就像完成了一次精神的远行。", "图书馆", "return", 0, 999),
        ("归还不是结束，而是下一本好书的开始。", "图书馆", "return", 0, 999),
        ("按时归还的你，是图书馆最欣赏的读者。", "图书馆", "return", 0, 999),
        ("书山有路勤为径，期待你的下一次出发！", "韩愈", "return", 0, 999),

        # 升级时
        ("恭喜升级！你的阅读之路越走越宽。", "图书馆", "levelup", 0, 999),
        ("等级提升，眼界开阔。继续在书海中探索吧！", "图书馆", "levelup", 0, 999),
        ("每一次升级，都是知识的积淀在开花结果。", "图书馆", "levelup", 0, 999),
        ("你已经超越了大多数读者，继续前行！", "图书馆", "levelup", 5, 999),
        ("学海无涯，你的进步令人刮目相看。", "图书馆", "levelup", 7, 999),

        # 低等级专属鼓励
        ("千里之行，始于足下。你的阅读旅程才刚开始！", "老子", "general", 1, 2),
        ("不必着急，每一页都是成长。", "图书馆", "general", 1, 3),
        ("坚持借阅，你会发现自己悄然蜕变。", "图书馆", "general", 1, 4),

        # 高等级专属
        ("你已经是一位博览群书的读者，令人敬佩。", "图书馆", "general", 7, 999),
        ("在阅读的路上，你已走在了最前列。", "图书馆", "general", 8, 999),
        ("学富五车，非一日之功。你是真正的阅读者。", "图书馆", "general", 9, 999),
    ]

    created = 0
    for content, author, category, min_lv, max_lv in quotes_data:
        if EncouragingQuote.query.filter_by(content=content).first():
            continue
        q = EncouragingQuote(
            content=content,
            author=author,
            category=category,
            min_level=min_lv,
            max_level=max_lv,
        )
        db.session.add(q)
        created += 1

    db.session.commit()
    print(f"[OK] 创建 {created} 条鼓励语录")


def init_reading_stats():
    """为现有用户创建阅读统计记录"""
    users = User.query.all()
    created = 0
    for user in users:
        if not ReadingStat.query.filter_by(user_id=user.id).first():
            stat = ReadingStat(user_id=user.id)
            db.session.add(stat)
            created += 1
    db.session.commit()
    print(f"[OK] 创建 {created} 条阅读统计记录")


def main():
    """主函数"""
    print("=" * 50)
    print("开始初始化数据库...")
    print("=" * 50)

    with app.app_context():
        db.create_all()

        # 检查是否已有数据
        if Category.query.count() > 0:
            print("[提示] 数据库已有数据，跳过初始化")
            confirm = input("是否重新创建测试数据？(y/N): ")
            if confirm.lower() != "y":
                print("取消操作")
                return

        init_categories()
        init_books()
        init_borrow_records()
        init_achievements()
        init_quotes()
        init_reading_stats()

    print("=" * 50)
    print("数据库初始化完成！")
    print("管理员账号: admin")
    print("读者账号: reader")
    print("初始密码请查看 .env.example 或环境变量 ADMIN_PASSWORD / READER_PASSWORD")
    print("=" * 50)


if __name__ == "__main__":
    main()
