"""
借阅量预测服务
================
用线性回归预测未来 14 天每日借阅量。

模型选择（面试可辩护）：
- 特征 = 线性日趋势（day_index）+ 星期几 one-hot（6 列，丢 1 防共线性）
- 线性回归能捕捉周季节性（周末 vs 工作日），系数完全可解释
- 否决 ARIMA：小数据下过度工程，需平稳性检验，调参成本高
- 否决纯移动平均：忽略周季节性与趋势

置信区间：
- CI = 残差标准差 × 1.96（95% 置信区间，统计上诚实）
- 用阴影带（areaStyle）可视化

边界：
- 历史不足 14 天时返回 error，不强行预测
"""

from datetime import datetime, timedelta, date
from collections import defaultdict

import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy import func

from models import db, BorrowRecord


# 星期中文标签（0=周一 ... 6=周日）
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def get_daily_counts(history_days=90):
    """
    聚合最近 history_days 天的每日借阅数，缺日补 0。

    :return: list[dict] {date: 'YYYY-MM-DD', count: int, weekday: 0-6}
    """
    start = datetime.now() - timedelta(days=history_days)
    rows = (
        db.session.query(
            func.date(BorrowRecord.borrow_date).label("d"),
            func.count(BorrowRecord.id).label("c"),
        )
        .filter(BorrowRecord.borrow_date >= start)
        .group_by(func.date(BorrowRecord.borrow_date))
        .all()
    )
    by_date = {str(r.d): int(r.c) for r in rows}

    result = []
    for i in range(history_days):
        d = (start + timedelta(days=i)).date()
        key = d.strftime("%Y-%m-%d")
        result.append({
            "date": key,
            "count": by_date.get(key, 0),
            "weekday": d.weekday(),  # 0=周一
        })
    return result


def fit_and_predict(history_days=90, horizon=14):
    """
    用线性回归（趋势 + 星期几 one-hot）拟合历史，预测未来 horizon 天。

    特征矩阵 X（每行 = 一天）：
    - col 0: day_index（线性趋势，0..N-1）
    - col 1..6: 星期二..星期日的 one-hot（以周一为基准，丢周一防共线性）

    :return: dict
        成功: {dates, actual, predicted, ci_lower, ci_upper, coef, history_days, horizon}
        失败: {error: str}
    """
    daily = get_daily_counts(history_days)
    if len(daily) < 14:
        return {"error": f"数据不足，至少需要 14 天借阅记录（当前 {len(daily)} 天）"}

    # ---- 构造特征矩阵 ----
    X = []
    y = []
    for i, d in enumerate(daily):
        # 趋势项
        feats = [i]
        # 星期 one-hot：周一=基准（全 0），周二..周日各一列
        wd = d["weekday"]
        dow_onehot = [0] * 6
        if wd >= 1:  # 1=周二..6=周日
            dow_onehot[wd - 1] = 1
        feats.extend(dow_onehot)
        X.append(feats)
        y.append(d["count"])

    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)

    # ---- 拟合线性回归 ----
    model = LinearRegression()
    model.fit(X, y)

    # 残差标准差 → 95% CI
    residuals = y - model.predict(X)
    residual_std = float(np.std(residuals)) if len(y) > 1 else 0.0
    ci_half = residual_std * 1.96

    # ---- 预测未来 horizon 天 ----
    last_date = datetime.strptime(daily[-1]["date"], "%Y-%m-%d").date()
    future_X = []
    future_dates = []
    for j in range(horizon):
        idx = len(daily) + j
        d = last_date + timedelta(days=j + 1)
        feats = [idx]
        wd = d.weekday()
        dow_onehot = [0] * 6
        if wd >= 1:
            dow_onehot[wd - 1] = 1
        feats.extend(dow_onehot)
        future_X.append(feats)
        future_dates.append(d.strftime("%Y-%m-%d"))

    future_X = np.array(future_X, dtype=float)
    future_pred = model.predict(future_X)
    # 借阅量不可为负
    future_pred = np.maximum(future_pred, 0)

    # ---- 系数（可解释性：展示趋势 + 各星期相对周一的增量） ----
    coef_names = ["趋势(天)"] + WEEKDAY_LABELS[1:]  # 周二..周日
    coef = {
        name: float(c)
        for name, c in zip(coef_names, model.coef_)
    }
    coef["截距(周一基准)"] = float(model.intercept_)

    # ---- 历史拟合值（用于图表"实际 vs 拟合"对比） ----
    actual = [d["count"] for d in daily]
    fitted = model.predict(X).tolist()
    history_dates = [d["date"] for d in daily]

    return {
        "dates": history_dates + future_dates,
        "actual": actual + [None] * horizon,          # 未来无实际值
        "fitted": fitted + [None] * horizon,           # 历史拟合段
        "predicted": [None] * len(daily) + future_pred.tolist(),  # 预测段
        "ci_lower": [None] * len(daily) + (future_pred - ci_half).clip(min=0).tolist(),
        "ci_upper": [None] * len(daily) + (future_pred + ci_half).tolist(),
        "coef": coef,
        "residual_std": residual_std,
        "history_days": len(daily),
        "horizon": horizon,
    }


def get_forecast_overview(history_days=90, horizon=14):
    """
    供路由调用的门面，统一返回渲染所需数据。

    :return: dict 含 dates/actual/fitted/predicted/ci_lower/ci_upper/coef/或 error
    """
    result = fit_and_predict(history_days=history_days, horizon=horizon)
    if "error" in result:
        return {"error": result["error"]}
    # 补充星期系数卡片所需数据
    dow_coef = []
    intercept = result["coef"].get("截距(周一基准)", 0)
    for i, label in enumerate(WEEKDAY_LABELS):
        if i == 0:
            val = intercept
        else:
            val = intercept + result["coef"].get(label, 0)
        dow_coef.append({"label": label, "value": float(val)})
    result["dow_coef"] = dow_coef
    result["weekday_labels"] = WEEKDAY_LABELS
    return result


# ============ 模型评估（MAE / RMSE / R² + 残差分析） ============

def _build_feature_matrix(daily):
    """把 daily 列表转成特征矩阵 X 和标签向量 y（趋势 + 星期 one-hot）。"""
    X, y = [], []
    for i, d in enumerate(daily):
        feats = [i]
        wd = d["weekday"]
        dow_onehot = [0] * 6
        if wd >= 1:
            dow_onehot[wd - 1] = 1
        feats.extend(dow_onehot)
        X.append(feats)
        y.append(d["count"])
    return np.array(X, dtype=float), np.array(y, dtype=float)


def evaluate_model(history_days=90, test_ratio=0.2):
    """
    时序交叉验证：前 (1-test_ratio) 训练，后 test_ratio 验证。

    评估指标：
    - MAE  = mean(|y_true - y_pred|)
    - RMSE = sqrt(mean((y_true - y_pred)^2))
    - R²   = 1 - SS_res / SS_tot（决定系数，越接近 1 越好）

    :return: dict
        成功: {mae, rmse, r2, scatter, residuals, train_size, test_size, ...}
        失败: {error: str}
    """
    daily = get_daily_counts(history_days)
    if len(daily) < 20:
        return {"error": f"数据不足，评估至少需要 20 天借阅记录（当前 {len(daily)} 天）"}

    X, y = _build_feature_matrix(daily)
    split = int(len(X) * (1 - test_ratio))
    if split < 14:
        return {"error": "训练集不足 14 天，无法评估"}

    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = LinearRegression()
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    y_pred = np.maximum(y_pred, 0)  # 借阅量不可为负

    residuals = y_test - y_pred
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_test - np.mean(y_test)) ** 2))
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # 实际 vs 预测散点
    scatter = [
        {"value": [float(a), float(p)], "name": d["date"]}
        for a, p, d in zip(y_test, y_pred, daily[split:])
    ]

    # 残差直方图（按区间分桶）
    res_list = residuals.tolist()
    bins = [-5, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 5]
    hist_counts = [0] * (len(bins) - 1)
    bin_labels = []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        if lo < 0 and hi <= 0:
            bin_labels.append(f"[{lo},{hi}]")
        elif lo >= 0:
            bin_labels.append(f"[{lo},{hi}]")
        else:
            bin_labels.append(f"[{lo},{hi}]")
    for r in res_list:
        for i in range(len(bins) - 1):
            if bins[i] <= r < bins[i + 1] or (i == len(bins) - 2 and r == bins[-1]):
                hist_counts[i] += 1
                break

    return {
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "scatter": scatter,
        "scatter_dates": [d["date"] for d in daily[split:]],
        "residual_hist": {"labels": bin_labels, "counts": hist_counts},
        "train_size": len(X_train),
        "test_size": len(X_test),
        "test_ratio": test_ratio,
        "history_days": len(daily),
        "y_test_mean": float(np.mean(y_test)),
        "y_test_std": float(np.std(y_test)),
    }


def _evaluate_xgb(X_train, y_train, X_test, y_test):
    """
    用 XGBoost 训练并评估，返回 MAE/RMSE/R² 和预测值。

    设计决策（面试可辩护）：
    - 树模型在小样本下容易过拟合，用保守超参（n_estimators=80, max_depth=3）
    - 不做网格搜索：数据量太小，CV 调参比 LR 多花的时间成本不值
    - 用作对比基线，证明 LR 在本场景的选择合理
    """
    from xgboost import XGBRegressor
    model = XGBRegressor(
        n_estimators=80,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
        n_jobs=1,
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    y_pred = np.maximum(y_pred, 0)

    residuals = y_test - y_pred
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_test - np.mean(y_test)) ** 2))
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {
        "mae": mae, "rmse": rmse, "r2": r2,
        "y_pred": y_pred.tolist(),
        "feature_importances": model.feature_importances_.tolist(),
    }


def get_evaluation_overview(history_days=90):
    """路由门面：评估数据（LR + XGBoost 对比）+ 元信息。"""
    daily = get_daily_counts(history_days)
    if len(daily) < 20:
        return {"error": f"数据不足，评估至少需要 20 天借阅记录（当前 {len(daily)} 天）"}

    X, y = _build_feature_matrix(daily)
    test_ratio = 0.2
    split = int(len(X) * (1 - test_ratio))
    if split < 14:
        return {"error": "训练集不足 14 天，无法评估"}

    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    # 线性回归评估
    lr_result = evaluate_model(history_days=history_days)
    if "error" in lr_result:
        return lr_result

    # XGBoost 评估（同一份训练/测试集）
    try:
        xgb_result = _evaluate_xgb(X_train, y_train, X_test, y_test)
        lr_result["xgb"] = xgb_result
        # 特征重要性对应的名字
        feature_names = ["趋势(天)"] + WEEKDAY_LABELS[1:]
        lr_result["xgb"]["feature_names"] = feature_names
        # XGBoost 散点（实际 vs 预测）
        lr_result["xgb"]["scatter"] = [
            {"value": [float(a), float(p)], "name": d["date"]}
            for a, p, d in zip(y_test, xgb_result["y_pred"], daily[split:])
        ]
    except ImportError:
        # xgboost 未安装时静默降级，仅展示 LR
        pass

    return lr_result
