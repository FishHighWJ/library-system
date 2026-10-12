"""
数据分析路由 - RFM 用户分群 + 借阅量预测
路由层薄：仅鉴权 + 调 service + 渲染模板，业务逻辑下沉到 services/
"""

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for
from flask_login import login_required, current_user

from services.rfm_service import (
    get_rfm_overview,
    generate_recall_actions,
    send_recall_notifications,
)
from services.forecast_service import get_forecast_overview, get_evaluation_overview

analysis_bp = Blueprint("analysis", __name__)


def _admin_only():
    """管理员鉴权门禁"""
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


@analysis_bp.route("/analysis/rfm")
@login_required
def rfm():
    """RFM 用户分群：scatter + pie + 表格 + 召回动作区块"""
    _admin_only()
    ctx = get_rfm_overview()
    return render_template("rfm_analysis.html", **ctx)


@analysis_bp.route("/analysis/rfm/recall", methods=["POST"])
@login_required
def rfm_recall():
    """执行召回：给 At-risk/Lost/Inactive 用户发站内通知"""
    _admin_only()
    from services.rfm_service import compute_rfm, segment_users
    rfm = compute_rfm()
    segmented, _ = segment_users(rfm)
    actions = generate_recall_actions(segmented)
    sent = send_recall_notifications(actions)
    flash(f"已向 {sent} 位用户发送召回通知", "success")
    return redirect(url_for("analysis.rfm"))


@analysis_bp.route("/analysis/prediction")
@login_required
def prediction():
    """借阅量预测：实际 vs 预测 + CI 阴影 + 星期系数卡"""
    _admin_only()
    ctx = get_forecast_overview()
    return render_template("borrow_prediction.html", **ctx)


@analysis_bp.route("/analysis/evaluation")
@login_required
def evaluation():
    """模型评估：MAE / RMSE / R² + 实际vs预测散点 + 残差直方图"""
    _admin_only()
    ctx = get_evaluation_overview()
    return render_template("model_evaluation.html", **ctx)
