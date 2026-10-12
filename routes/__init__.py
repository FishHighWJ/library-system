"""
路由包初始化 - 注册所有蓝图
蓝图( Blueprint )实现模块化路由管理
"""

from .auth import auth_bp
from .books import books_bp
from .borrow import borrow_bp
from .feedback import feedback_bp
from .achievement import achievement_bp
from .analysis import analysis_bp

__all__ = ["auth_bp", "books_bp", "borrow_bp", "feedback_bp", "achievement_bp", "analysis_bp"]
