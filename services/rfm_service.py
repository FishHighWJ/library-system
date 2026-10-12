"""
RFM 用户分群服务
================
将电商 RFM 模型迁移到图书馆场景：

- **R**ecency：最近一次借阅距今天数（越小越活跃）
- **F**requency：累计借阅次数
- **M**onetary → **Breadth**：借阅涉猎的不同分类数

设计决策（面试可辩护）：
- 图书馆无货币维度，传统 M（消费金额）在此无对应。
- 选"涉猎分类数"而非"借阅总时长"或"按时归还率"：
  - 时长依赖 return_date，活跃借阅为 NULL 会引入偏差；
  - 按时归还率是行为质量指标，与 F（频次）语义重叠；
  - 分类广度与 e-commerce 的消费广度语义一致，且与 F 正交，避免重复计数。
- 零借阅用户（F=0）单独归为 Inactive，不参与 R/F 四分位计算
  （R 在无借阅时无意义，纳入分位会污染阈值）。

召回闭环（v2 新增）：
- generate_recall_actions：对 At-risk/Lost/Inactive 用户基于历史借阅分类生成个性化推荐书单
- analyze_recall_effect：横向对比召回目标 vs 高价值用户的近期借阅率，量化召回空间
- send_recall_notifications：写入 Notification 表触发实际召回动作
"""

from datetime import datetime, timedelta
from sqlalchemy import func
from models import db, User, BorrowRecord, Book, Notification


def _percentile(sorted_values, q):
    """
    线性插值法计算分位数（与 numpy.percentile 默认行为一致）。
    纯 Python 实现避免在 service 层硬依赖 numpy，便于单元测试。
    """
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def compute_rfm():
    """
    计算 all 用户的 R / F / M 三维指标。

    :return: list[dict] 每项含
             {user_id, username, R, F, M, last_borrow}
             R 单位：天（无借阅记为 None）
             F 单位：次
             M 单位：个分类
    """
    # 一次性 LEFT JOIN 拉全表，避免 N+1 查询
    rows = (
        db.session.query(
            User.id.label("user_id"),
            User.username.label("username"),
            func.max(BorrowRecord.borrow_date).label("last_borrow"),
            func.count(BorrowRecord.id).label("freq"),
            func.count(func.distinct(Book.category_id)).label("breadth"),
        )
        .outerjoin(BorrowRecord, BorrowRecord.user_id == User.id)
        .outerjoin(Book, Book.id == BorrowRecord.book_id)
        .group_by(User.id, User.username)
        .all()
    )

    now = datetime.now()
    result = []
    for r in rows:
        freq = int(r.freq or 0)
        last = r.last_borrow
        recency = (now - last).days if last is not None else None
        result.append({
            "user_id": r.user_id,
            "username": r.username,
            "R": recency,
            "F": freq,
            "M": int(r.breadth or 0) if freq > 0 else 0,
            "last_borrow": last,
        })
    return result


# 分群定义：便于模板/前端统一渲染颜色与文案
SEGMENT_META = {
    "Champions":  {"color": "#dc3545", "desc": "近期活跃 + 高频借阅，核心读者"},
    "Loyal":      {"color": "#fd7e14", "desc": "高频借阅但近期未活跃，需召回"},
    "Potential":  {"color": "#0d6efd", "desc": "近期活跃但频次低，可培养"},
    "At-risk":    {"color": "#ffc107", "desc": "近期沉睡，有流失风险"},
    "Lost":       {"color": "#6c757d", "desc": "长期未借阅，已流失"},
    "Inactive":   {"color": "#adb5bd", "desc": "注册后从未借阅"},
}


def segment_users(rfm_list):
    """
    按 R / F 四分位数阈值给用户打分群标签。

    阈值计算（仅对 F>0 的活跃用户）：
    - R_top25  = 25 分位（R <= 此值 → 近期活跃）
    - F_top25  = 75 分位（F >= 此值 → 高频）

    分群规则：
    - Inactive：F == 0
    - Champions：R 在顶 25% 且 F 在顶 25%
    - Loyal：F 在顶 25% 且 R 不在顶 25%
    - Potential：R 在顶 25% 且 F 不在顶 25%
    - Lost：R 在底 25% 且 F 在底 25%
    - At-risk：R 在底 25% 且 F 不在底 25%（兜底）
    - Others：其余归入 Potential 或 At-risk 的中间桶

    :return: tuple(active_segmented, segment_counts)
             active_segmented: list[dict] 含原 RFM + segment 字段
             segment_counts: dict[segment_name] -> count
    """
    # 分离零借阅用户
    inactive = [u for u in rfm_list if u["F"] == 0]
    active = [u for u in rfm_list if u["F"] > 0]

    if not active:
        # 全员零借阅，仅返回 Inactive
        segmented = [
            {**u, "segment": "Inactive"} for u in inactive
        ]
        counts = {k: 0 for k in SEGMENT_META}
        counts["Inactive"] = len(inactive)
        return segmented, counts

    # 计算 R / F 四分位阈值（仅基于活跃用户）
    r_values = sorted([u["R"] for u in active if u["R"] is not None])
    f_values = sorted([u["F"] for u in active])
    r_top25 = _percentile(r_values, 0.25)   # R 越小越新，<=顶 25 分位即活跃
    r_bot25 = _percentile(r_values, 0.75)    # R >= 底 25 分位即沉睡
    f_top25 = _percentile(f_values, 0.75)   # F >= 顶 25 分位即高频
    f_bot25 = _percentile(f_values, 0.25)   # F <= 底 25 分位即低频

    segmented = []
    counts = {k: 0 for k in SEGMENT_META}

    for u in inactive:
        segmented.append({**u, "segment": "Inactive"})
        counts["Inactive"] += 1

    for u in active:
        r, f = u["R"], u["F"]
        if r is not None and r <= r_top25 and f >= f_top25:
            seg = "Champions"
        elif f >= f_top25:
            seg = "Loyal"
        elif r is not None and r <= r_top25:
            seg = "Potential"
        elif r is not None and r >= r_bot25 and f <= f_bot25:
            seg = "Lost"
        elif r is not None and r >= r_bot25:
            seg = "At-risk"
        else:
            # 中间地带：按 R 新旧倾向分桶
            seg = "Potential" if (r is not None and r <= r_bot25) else "At-risk"
        segmented.append({**u, "segment": seg})
        counts[seg] += 1

    return segmented, counts


def get_rfm_overview():
    """
    供路由调用的门面：计算 RFM + 分群 + 聚合 ECharts 所需数据。

    :return: dict 含
        - scatter_data: list[{R, F, M, username, user_id, segment, color}]
        - pie_data: list[{name, value, color}]
        - table_data: list[{username, R, F, M, segment, segment_desc}]
        - segment_meta: SEGMENT_META
        - totals: {users, active, inactive}
    """
    rfm = compute_rfm()
    segmented, counts = segment_users(rfm)

    scatter_data = [
        {
            "value": [u["R"] if u["R"] is not None else 9999, u["F"], u["M"]],
            "name": u["username"],
            "user_id": u["user_id"],
            "segment": u["segment"],
            "itemStyle": {"color": SEGMENT_META[u["segment"]]["color"]},
        }
        for u in segmented
    ]

    pie_data = [
        {"name": k, "value": counts[k], "itemStyle": {"color": v["color"]}}
        for k, v in SEGMENT_META.items()
        if counts.get(k, 0) > 0
    ]

    table_data = [
        {
            "user_id": u["user_id"],
            "username": u["username"],
            "R": u["R"] if u["R"] is not None else "—",
            "F": u["F"],
            "M": u["M"],
            "segment": u["segment"],
            "segment_desc": SEGMENT_META[u["segment"]]["desc"],
            "segment_color": SEGMENT_META[u["segment"]]["color"],
            "last_borrow": u["last_borrow"].strftime("%Y-%m-%d") if u["last_borrow"] else "—",
        }
        for u in sorted(segmented, key=lambda x: (list(SEGMENT_META.keys()).index(x["segment"]), -x["F"]))
    ]

    # 召回闭环：动作 + 效果对比
    recall_actions = generate_recall_actions(segmented)
    recall_effect = analyze_recall_effect(segmented)

    return {
        "scatter_data": scatter_data,
        "pie_data": pie_data,
        "table_data": table_data,
        "segment_meta": SEGMENT_META,
        "totals": {
            "users": len(segmented),
            "active": len(segmented) - counts["Inactive"],
            "inactive": counts["Inactive"],
        },
        "recall_actions": recall_actions,
        "recall_effect": recall_effect,
    }


# ============ 召回闭环（运营动作 + 效果分析） ============

# 需要召回的分群
RECALL_SEGMENTS = {"At-risk", "Lost", "Inactive"}
# 作为对照的高价值分群
CHAMPION_SEGMENTS = {"Champions", "Loyal"}


def generate_recall_actions(segmented, top_n=3):
    """
    对 At-risk / Lost / Inactive 用户生成个性化召回推荐书单。

    推荐策略（面试可辩护）：
    - 优先推荐用户历史借阅过的分类下的可借书（个性化 + 兴趣匹配）
    - 历史为空（Inactive）时，退化为热门可借书（cold-start 兜底）
    - 排除用户已借过的书（避免重复推荐）
    - 按 available_count 倒序取前 top_n（提高命中可借概率）

    :param segmented: segment_users() 返回的列表
    :param top_n: 每个用户推荐几本书
    :return: list[dict] 每项含
             {user_id, username, segment, reason, recommended_books: [{id, title, author}]}
    """
    targets = [u for u in segmented if u["segment"] in RECALL_SEGMENTS]
    if not targets:
        return []

    # 批量取每个目标用户历史借阅过的分类
    target_ids = [u["user_id"] for u in targets]
    cat_rows = (
        db.session.query(
            BorrowRecord.user_id.label("uid"),
            Book.category_id.label("cid"),
        )
        .join(Book, Book.id == BorrowRecord.book_id)
        .filter(BorrowRecord.user_id.in_(target_ids))
        .distinct()
        .all()
    )
    user_cats = {}
    for r in cat_rows:
        user_cats.setdefault(r.uid, set()).add(r.cid)

    # 批量取每个目标用户已借过的 book_id（避免重复推荐）
    borrowed_ids = (
        db.session.query(BorrowRecord.user_id, BorrowRecord.book_id)
        .filter(BorrowRecord.user_id.in_(target_ids))
        .all()
    )
    user_borrowed = {}
    for uid, bid in borrowed_ids:
        user_borrowed.setdefault(uid, set()).add(bid)

    # 批量取所有可借书（available_count>0），按分类分组
    avail_books = (
        Book.query.filter(Book.available_count > 0).all()
    )
    books_by_cat = {}
    for b in avail_books:
        books_by_cat.setdefault(b.category_id, []).append(b)

    # 热门兜底：按 available_count 倒序的全局可借书
    fallback_pool = sorted(avail_books, key=lambda b: -b.available_count)[: top_n * 3]

    actions = []
    for u in targets:
        uid = u["user_id"]
        cats = user_cats.get(uid, set())
        already = user_borrowed.get(uid, set())

        # 从历史分类中找可借且未借过的书
        pool = []
        for cid in cats:
            for b in books_by_cat.get(cid, []):
                if b.id not in already:
                    pool.append(b)
        pool.sort(key=lambda b: -b.available_count)

        # 兜底
        if len(pool) < top_n:
            for b in fallback_pool:
                if b.id not in already and b not in pool:
                    pool.append(b)
                if len(pool) >= top_n:
                    break

        recs = [
            {"id": b.id, "title": b.title, "author": b.author}
            for b in pool[:top_n]
        ]
        if not recs:
            continue

        if u["segment"] == "Inactive":
            reason = "注册后从未借阅，推荐馆藏热门书作 cold-start"
        elif u["segment"] == "Lost":
            reason = "长期未借阅，推荐其历史兴趣分类下的新书召回"
        else:  # At-risk
            reason = "近期沉睡有流失风险，按其历史分类推荐召回"

        actions.append({
            "user_id": uid,
            "username": u["username"],
            "segment": u["segment"],
            "reason": reason,
            "recommended_books": recs,
        })
    return actions


def analyze_recall_effect(segmented, window_days=7):
    """
    横向对比召回目标 vs 高价值用户的近期借阅率，量化召回空间。

    逻辑：
    - target_group = At-risk + Lost + Inactive 用户
    - champion_group = Champions + Loyal 用户
    - 统计两组在最近 window_days 天内的借阅次数，计算人均借阅率
    - gap = champion_rate - target_rate（正值表示召回空间）

    :return: dict {target_count, champion_count, target_rate, champion_rate, gap, lift_pct}
    """
    target_ids = [u["user_id"] for u in segmented if u["segment"] in RECALL_SEGMENTS]
    champion_ids = [u["user_id"] for u in segmented if u["segment"] in CHAMPION_SEGMENTS]

    since = datetime.now() - timedelta(days=window_days)

    def _count_borrows(uids):
        if not uids:
            return 0
        return int(
            db.session.query(func.count(BorrowRecord.id))
            .filter(BorrowRecord.user_id.in_(uids))
            .filter(BorrowRecord.borrow_date >= since)
            .scalar() or 0
        )

    target_borrows = _count_borrows(target_ids)
    champion_borrows = _count_borrows(champion_ids)

    target_rate = target_borrows / len(target_ids) if target_ids else 0
    champion_rate = champion_borrows / len(champion_ids) if champion_ids else 0
    gap = champion_rate - target_rate
    # 召回潜力：若能把 target 拉到 champion 水平，借阅量能提升多少 %
    lift_pct = (gap / champion_rate * 100) if champion_rate > 0 else 0.0

    return {
        "window_days": window_days,
        "target_count": len(target_ids),
        "champion_count": len(champion_ids),
        "target_borrows": target_borrows,
        "champion_borrows": champion_borrows,
        "target_rate": round(target_rate, 2),
        "champion_rate": round(champion_rate, 2),
        "gap": round(gap, 2),
        "lift_pct": round(lift_pct, 1),
    }


def send_recall_notifications(actions):
    """
    对召回动作列表写入 Notification 表，触发实际召回。

    :param actions: generate_recall_actions 返回的列表
    :return: int 发送条数
    """
    sent = 0
    for a in actions:
        books_str = "、".join(f"《{b['title']}》" for b in a["recommended_books"])
        notif = Notification(
            user_id=a["user_id"],
            notification_type="system_notice",
            title="📚 为你推荐新书，快来唤醒阅读习惯",
            content=f"基于你的阅读历史，为你推荐：{books_str}。借阅即可获得经验值奖励！",
        )
        db.session.add(notif)
        sent += 1
    db.session.commit()
    return sent
