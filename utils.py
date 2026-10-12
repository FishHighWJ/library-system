"""
工具函数模块 - 集中管理通用工具，避免循环导入
包含：数据库重试、操作日志、BEGIN IMMEDIATE 上下文管理器等
"""

import logging
import time
from functools import wraps
from contextlib import contextmanager

from flask import request, flash, redirect
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError

logger = logging.getLogger(__name__)

# 数据库重试最大次数
DB_RETRY_MAX = 3


def get_db():
    """懒加载获取 db 对象，避免循环导入"""
    from models import db
    return db


def log_operation(user_id, action, target_type, target_id, detail=""):
    """记录操作审计日志"""
    try:
        from models import OperationLog
        db = get_db()
        log = OperationLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=request.remote_addr if request else "system",
        )
        db.session.add(log)
    except Exception as e:
        logger.error(f"记录审计日志失败: {e}")


@contextmanager
def begin_immediate():
    """
    BEGIN IMMEDIATE 上下文管理器
    在事务开始时立即获取 RESERVED 锁，避免两个事务同时升级锁导致的 database is locked 错误

    使用方式：
        with begin_immediate():
            # 写操作
            db.session.add(...)
            db.session.commit()
    """
    db = get_db()
    # 先结束当前可能存在的事务
    db.session.close()
    # 开启 IMMEDIATE 事务
    db.session.execute(text("BEGIN IMMEDIATE"))
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        # 确保 session 状态正确
        pass


def db_retry(max_retries=DB_RETRY_MAX, use_immediate=False):
    """
    数据库重试装饰器 - 处理数据库锁等临时错误

    参数:
        max_retries: 最大重试次数
        use_immediate: 是否使用 BEGIN IMMEDIATE 模式（写操作建议开启）
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    if use_immediate:
                        # 使用 BEGIN IMMEDIATE 模式
                        db = get_db()
                        db.session.close()
                        db.session.execute(text("BEGIN IMMEDIATE"))
                        try:
                            result = f(*args, **kwargs)
                            db.session.commit()
                            return result
                        except Exception:
                            db.session.rollback()
                            raise
                    else:
                        result = f(*args, **kwargs)
                        return result
                except OperationalError as e:
                    last_error = e
                    db = get_db()
                    db.session.rollback()
                    error_msg = str(e).lower()
                    if "database is locked" in error_msg or "deadlock" in error_msg or "busy" in error_msg:
                        wait_time = 0.1 * (2 ** attempt)  # 指数退避: 0.1s, 0.2s, 0.4s
                        logger.warning(f"数据库锁定，第{attempt+1}次重试，等待{wait_time:.2f}s...")
                        time.sleep(wait_time)
                        continue
                    raise
                except SQLAlchemyError as e:
                    db = get_db()
                    db.session.rollback()
                    last_error = e
                    raise
            # 重试用尽
            db = get_db()
            db.session.rollback()
            logger.error(f"数据库重试{max_retries}次后仍失败: {last_error}")
            flash("系统繁忙，请稍后重试", "danger")
            return redirect(request.url)
        return wrapper
    return decorator
