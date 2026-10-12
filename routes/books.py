"""
图书管理路由 - 图书的增删改查、搜索、分类管理
管理员可进行图书CRUD操作，读者只能查看
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, Book, Category, BorrowRecord
from functools import wraps

books_bp = Blueprint("books", __name__)


def admin_required(f):
    """管理员权限装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("权限不足，需要管理员身份", "danger")
            return redirect(url_for("books.index"))
        return f(*args, **kwargs)
    return decorated_function


# =================== 首页 & 图书列表 ===================

@books_bp.route("/")
@books_bp.route("/index")
@login_required
def index():
    """图书列表页 - 支持搜索和分类筛选"""
    page = request.args.get("page", 1, type=int)
    keyword = request.args.get("keyword", "").strip()
    category_id = request.args.get("category_id", type=int)
    per_page = 10

    query = Book.query

    # 关键词搜索（书名/作者/ISBN）
    if keyword:
        query = query.filter(
            db.or_(
                Book.title.contains(keyword),
                Book.author.contains(keyword),
                Book.isbn.contains(keyword),
            )
        )

    # 分类筛选
    if category_id:
        query = query.filter_by(category_id=category_id)

    pagination = query.order_by(Book.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    categories = Category.query.all()

    return render_template(
        "index.html",
        books=pagination.items,
        pagination=pagination,
        categories=categories,
        keyword=keyword,
        current_category=category_id,
    )


# =================== 图书详情 ===================

@books_bp.route("/book/<int:book_id>")
@login_required
def book_detail(book_id):
    """图书详情页"""
    book = Book.query.get_or_404(book_id)
    # 查询该书的借阅记录
    records = book.borrows.order_by(BorrowRecord.borrow_date.desc()).limit(5).all()
    return render_template("book_detail.html", book=book, records=records)


# =================== 添加图书 ===================

@books_bp.route("/book/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_book():
    """添加图书（管理员）"""
    categories = Category.query.all()

    if request.method == "POST":
        book = Book(
            isbn=request.form.get("isbn", "").strip(),
            title=request.form.get("title", "").strip(),
            author=request.form.get("author", "").strip(),
            publisher=request.form.get("publisher", "").strip(),
            price=request.form.get("price", 0, type=float),
            description=request.form.get("description", "").strip(),
            total_count=request.form.get("total_count", 1, type=int),
            available_count=request.form.get("total_count", 1, type=int),
            location=request.form.get("location", "").strip(),
            category_id=request.form.get("category_id", type=int),
        )
        db.session.add(book)
        db.session.commit()
        flash(f"图书《{book.title}》添加成功", "success")
        return redirect(url_for("books.book_detail", book_id=book.id))

    return render_template("book_form.html", categories=categories, book=None)


# =================== 编辑图书 ===================

@books_bp.route("/book/<int:book_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_book(book_id):
    """编辑图书（管理员）"""
    book = Book.query.get_or_404(book_id)
    categories = Category.query.all()

    if request.method == "POST":
        book.isbn = request.form.get("isbn", "").strip()
        book.title = request.form.get("title", "").strip()
        book.author = request.form.get("author", "").strip()
        book.publisher = request.form.get("publisher", "").strip()
        book.price = request.form.get("price", 0, type=float)
        book.description = request.form.get("description", "").strip()
        book.location = request.form.get("location", "").strip()
        book.category_id = request.form.get("category_id", type=int)

        # 调整馆藏数量：已借出 = 总数 - 可借
        old_borrowed = book.total_count - book.available_count
        new_total = request.form.get("total_count", 1, type=int)
        book.total_count = new_total
        book.available_count = max(new_total - old_borrowed, 0)

        db.session.commit()
        flash("图书信息更新成功", "success")
        return redirect(url_for("books.book_detail", book_id=book.id))

    return render_template("book_form.html", book=book, categories=categories)


# =================== 删除图书 ===================

@books_bp.route("/book/<int:book_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_book(book_id):
    """删除图书（管理员）"""
    book = Book.query.get_or_404(book_id)

    # 检查是否有未归还的借阅
    active_borrows = book.borrows.filter_by(status="borrowed").count()
    if active_borrows > 0:
        flash(f"该书有{active_borrows}本借出未还，无法删除", "danger")
        return redirect(url_for("books.book_detail", book_id=book.id))

    db.session.delete(book)
    db.session.commit()
    flash("图书已删除", "info")
    return redirect(url_for("books.index"))


# =================== 分类管理 ===================

@books_bp.route("/categories")
@login_required
@admin_required
def category_list():
    """分类列表"""
    categories = Category.query.all()
    return render_template("categories.html", categories=categories)


@books_bp.route("/categories/add", methods=["POST"])
@login_required
@admin_required
def add_category():
    """添加分类"""
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()

    if not name:
        flash("分类名称不能为空", "danger")
        return redirect(url_for("books.category_list"))

    if Category.query.filter_by(name=name).first():
        flash("分类名称已存在", "danger")
        return redirect(url_for("books.category_list"))

    cat = Category(name=name, description=desc)
    db.session.add(cat)
    db.session.commit()
    flash(f"分类「{name}」添加成功", "success")
    return redirect(url_for("books.category_list"))
