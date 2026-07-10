"""素材分级引擎 - 投手决策导向：目标CPA、样本充分度、止损线、潜力信号"""

from models import get_db


def _num(value, default=0):
    """安全转数值，兼容数据库空值/字符串。"""
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _positive(value):
    value = _num(value, 0)
    return value if value > 0 else None


DEFAULT_RULES = {
    'name': '专业投放分级规则',
    'target_cpa': 0,
    'min_sample_cost': 300,
    'stop_loss_cost': 800,
    's_cost_pct': 30,
    's_conversion_min': 3,
    's_cpa_ratio': 1.0,
    'a_cost_pct': 50,
    'a_conversion_min': 1,
    'a_cpa_ratio': 1.2,
    'b_conversion_min': 1,
    'b_cpa_ratio': 1.6,
    'potential_cost_max': 300,
    'potential_ctr_min': 0,
    'potential_click_min': 20,
    'potential_cpc_ratio': 1.2,
}


def compute_project_stats(materials):
    """计算项目级统计指标，用于动态阈值。"""
    if not materials:
        return {}

    costs = [m.get('cost', 0) or 0 for m in materials]
    conversions = [m.get('conversion', 0) or 0 for m in materials]
    clicks = [m.get('click', 0) or 0 for m in materials]
    ctrs = [m.get('ctr', 0) or 0 for m in materials]

    conv_costs = []
    for m in materials:
        conv = m.get('conversion', 0) or 0
        cost = m.get('cost', 0) or 0
        if conv > 0:
            conv_cost = m.get('conversion_cost') or cost / conv
            if conv_cost > 0:
                conv_costs.append(conv_cost)

    def percentile(data, p):
        if not data:
            return 0
        data = sorted(data)
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = min(f + 1, len(data) - 1)
        if f == c:
            return data[f]
        return data[f] * (c - k) + data[c] * (k - f)

    total_cost = sum(costs)
    total_click = sum(clicks)
    avg_cpc = total_cost / total_click if total_click > 0 else 0

    return {
        'cost_p10': percentile(costs, 90),
        'cost_p30': percentile(costs, 70),
        'cost_p50': percentile(costs, 50),
        'cost_p70': percentile(costs, 30),
        'conv_cost_p50': percentile(conv_costs, 50),
        'conv_cost_p80': percentile(conv_costs, 80),
        'avg_ctr': sum(ctrs) / len(ctrs) if ctrs else 0,
        'avg_cpc': avg_cpc,
        'total_materials': len(materials),
        'total_cost': total_cost,
        'total_conversion': sum(conversions),
    }


def normalize_rules(rules, stats=None):
    """合并默认规则，并根据项目数据补齐动态阈值。"""
    merged = DEFAULT_RULES.copy()
    if rules:
        merged.update({k: v for k, v in dict(rules).items() if v is not None})

    stats = stats or {}
    target_cpa = _positive(merged.get('target_cpa')) or _positive(stats.get('conv_cost_p50')) or 0
    min_sample_cost = _positive(merged.get('min_sample_cost')) or max(target_cpa or 0, _num(stats.get('cost_p50'), 0), 300)
    stop_loss_cost = _positive(merged.get('stop_loss_cost')) or max(min_sample_cost * 2, (target_cpa or min_sample_cost) * 2)
    potential_cost_max = _positive(merged.get('potential_cost_max')) or min_sample_cost
    potential_ctr_min = _positive(merged.get('potential_ctr_min')) or (_num(stats.get('avg_ctr'), 0) * 1.2)

    merged.update({
        'target_cpa': target_cpa,
        'min_sample_cost': min_sample_cost,
        'stop_loss_cost': stop_loss_cost,
        'potential_cost_max': potential_cost_max,
        'potential_ctr_min': potential_ctr_min,
        's_cost_pct': _num(merged.get('s_cost_pct'), 30),
        's_conversion_min': _num(merged.get('s_conversion_min'), 3),
        's_cpa_ratio': _num(merged.get('s_cpa_ratio'), 1.0),
        'a_cost_pct': _num(merged.get('a_cost_pct'), 50),
        'a_conversion_min': _num(merged.get('a_conversion_min'), 1),
        'a_cpa_ratio': _num(merged.get('a_cpa_ratio'), 1.2),
        'b_conversion_min': _num(merged.get('b_conversion_min'), 1),
        'b_cpa_ratio': _num(merged.get('b_cpa_ratio'), 1.6),
        'potential_click_min': _num(merged.get('potential_click_min'), 20),
        'potential_cpc_ratio': _num(merged.get('potential_cpc_ratio'), 1.2),
    })
    return merged


def classify_material(material, stats, rules=None):
    """单个素材分级：S/A/B/C/P 对应放量、稳跑、优化、止损、二次测试。"""
    rules = normalize_rules(rules, stats)

    cost = _num(material.get('cost'), 0)
    conversion = _num(material.get('conversion'), 0)
    click = _num(material.get('click'), 0)
    ctr = _num(material.get('ctr'), 0)
    conversion_cost = _num(material.get('conversion_cost'), 0)
    if conversion > 0 and conversion_cost <= 0:
        conversion_cost = cost / conversion if conversion else 0
    cpc = cost / click if click > 0 else 0

    target_cpa = rules['target_cpa']
    min_sample_cost = rules['min_sample_cost']
    stop_loss_cost = rules['stop_loss_cost']

    high_volume_threshold = stats.get('cost_p30', 0) if rules['s_cost_pct'] <= 30 else stats.get('cost_p50', 0)
    mid_volume_threshold = stats.get('cost_p50', 0) if rules['a_cost_pct'] <= 50 else stats.get('cost_p70', 0)

    has_target = target_cpa > 0
    s_cpa_ok = conversion_cost > 0 and (not has_target or conversion_cost <= target_cpa * rules['s_cpa_ratio'])
    a_cpa_ok = conversion_cost > 0 and (not has_target or conversion_cost <= target_cpa * rules['a_cpa_ratio'])
    b_cpa_ok = conversion_cost > 0 and (not has_target or conversion_cost <= target_cpa * rules['b_cpa_ratio'])

    if (conversion >= rules['s_conversion_min'] and
            cost >= max(min_sample_cost, high_volume_threshold) and
            s_cpa_ok):
        return 'S'

    if (conversion >= rules['a_conversion_min'] and
            cost >= min(min_sample_cost, mid_volume_threshold or min_sample_cost) and
            a_cpa_ok):
        return 'A'

    if cost >= stop_loss_cost and conversion <= 0:
        return 'C'
    if has_target and conversion > 0 and conversion_cost > target_cpa * max(rules['b_cpa_ratio'], 1.6):
        return 'C'

    if conversion >= rules['b_conversion_min'] and (b_cpa_ok or cost < min_sample_cost):
        return 'B'

    avg_cpc = _num(stats.get('avg_cpc'), 0)
    cpc_ok = avg_cpc <= 0 or cpc <= avg_cpc * rules['potential_cpc_ratio']
    ctr_ok = ctr >= rules['potential_ctr_min'] if rules['potential_ctr_min'] > 0 else False
    if (cost <= rules['potential_cost_max'] and
            click >= rules['potential_click_min'] and
            cpc_ok and
            (ctr_ok or conversion > 0)):
        return 'P'

    return 'C'


def classify_quality(material, stats, rules=None):
    """识别优质/劣质素材：用于辅助标签，不替代 S/A/B/C/P 主等级。"""
    rules = normalize_rules(rules, stats)

    cost = _num(material.get('cost'), 0)
    conversion = _num(material.get('conversion'), 0)
    conversion_cost = _num(material.get('conversion_cost'), 0)
    if conversion > 0 and conversion_cost <= 0:
        conversion_cost = cost / conversion if conversion else 0

    target_cpa = rules['target_cpa']
    min_sample_cost = rules['min_sample_cost']
    stop_loss_cost = rules['stop_loss_cost']
    median_conv_cost = _positive(stats.get('conv_cost_p50')) or target_cpa

    candidates = [x for x in [target_cpa, median_conv_cost] if x and x > 0]
    quality_cpa_line = min(candidates) if candidates else 0
    if conversion > 0 and cost >= min_sample_cost and quality_cpa_line and conversion_cost <= quality_cpa_line:
        return '优'

    if cost >= stop_loss_cost and conversion <= 0:
        return '劣'
    if target_cpa > 0 and conversion > 0 and conversion_cost > target_cpa * 1.8:
        return '劣'
    if median_conv_cost and conversion > 0 and conversion_cost > median_conv_cost * 2:
        return '劣'

    return None


def apply_grades_to_db(project_id=None, rules=None):
    """对数据库中的素材应用分级"""
    conn = get_db()

    sql = "SELECT m.* FROM materials m"
    params = []
    if project_id:
        sql += " JOIN accounts a ON m.account_id = a.id WHERE a.project_id=?"
        params.append(project_id)

    cur = conn.execute(sql, params)
    materials = [dict(row) for row in cur.fetchall()]

    stats = compute_project_stats(materials)
    normalized_rules = normalize_rules(rules, stats)
    updated = 0

    for material in materials:
        grade = classify_material(material, stats, normalized_rules)
        quality = classify_quality(material, stats, normalized_rules)

        final_grade = quality if quality == '劣' else grade
        if quality == '优' and grade in ('S', 'A'):
            final_grade = '优'

        conn.execute(
            "UPDATE materials SET grade=? WHERE id=?",
            (final_grade, material['id'])
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_grade_summary(project_id=None):
    """获取分级统计"""
    conn = get_db()

    sql = """
        SELECT 
            COALESCE(grade, '未分级') as grade,
            COUNT(*) as count,
            SUM(cost) as total_cost,
            SUM(conversion) as total_conversion,
            AVG(CASE WHEN conversion > 0 THEN conversion_cost ELSE NULL END) as avg_conv_cost,
            AVG(ctr) as avg_ctr
        FROM materials m
    """
    params = []
    if project_id:
        sql += " JOIN accounts a ON m.account_id = a.id WHERE a.project_id=?"
        params.append(project_id)

    sql += " GROUP BY grade ORDER BY CASE grade WHEN '优' THEN 0 WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'P' THEN 4 WHEN 'C' THEN 5 WHEN '劣' THEN 6 ELSE 7 END"

    cur = conn.execute(sql, params)
    result = [dict(row) for row in cur.fetchall()]
    conn.close()

    return result


def _rule_columns():
    conn = get_db()
    rows = conn.execute("PRAGMA table_info(grade_rules)").fetchall()
    conn.close()
    return {row['name'] for row in rows}


def get_all_rules():
    """获取全部分级规则。"""
    conn = get_db()
    cur = conn.execute("SELECT * FROM grade_rules ORDER BY is_default DESC, id ASC")
    rules = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rules


def get_default_rules():
    """获取默认规则；没有数据库规则时返回内置默认值。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM grade_rules WHERE is_default=1 ORDER BY id ASC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else DEFAULT_RULES.copy()


def create_rules(name='新规则', **data):
    """创建规则，只写入数据库实际存在的字段。"""
    data = dict(data or {})
    data.pop('id', None)
    data['name'] = name or data.get('name') or '新规则'
    columns = _rule_columns() - {'id', 'created_at'}
    payload = {k: v for k, v in data.items() if k in columns}
    if 'is_default' not in payload:
        payload['is_default'] = 0
    if not payload:
        raise ValueError('没有可保存的规则字段')

    keys = list(payload.keys())
    placeholders = ','.join(['?'] * len(keys))
    conn = get_db()
    cur = conn.execute(
        f"INSERT INTO grade_rules ({','.join(keys)}) VALUES ({placeholders})",
        [payload[k] for k in keys]
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_rules(rid, **data):
    """更新规则，只更新数据库实际存在的字段。"""
    data = dict(data or {})
    data.pop('id', None)
    data.pop('created_at', None)
    columns = _rule_columns() - {'id', 'created_at'}
    payload = {k: v for k, v in data.items() if k in columns}
    if not payload:
        return 0

    assignments = ', '.join([f"{k}=?" for k in payload.keys()])
    conn = get_db()
    cur = conn.execute(
        f"UPDATE grade_rules SET {assignments} WHERE id=?",
        [payload[k] for k in payload.keys()] + [rid]
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


def delete_rules(rid):
    """删除非默认规则。"""
    conn = get_db()
    row = conn.execute("SELECT is_default FROM grade_rules WHERE id=?", (rid,)).fetchone()
    if row and row['is_default']:
        conn.close()
        raise ValueError('默认规则不能删除')
    cur = conn.execute("DELETE FROM grade_rules WHERE id=?", (rid,))
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count
