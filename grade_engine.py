"""素材分级引擎 - 以消耗+转化数+转化成本为核心指标，含潜力/优质/劣质素材识别"""
import json
from models import get_db


def get_default_rules():
    """获取默认分级规则"""
    conn = get_db()
    cur = conn.execute("SELECT * FROM grade_rules WHERE is_default=1 LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        's_cost_pct': 10.0, 's_conv_cost_max': 0, 's_conversion_min': 3,
        'a_cost_pct': 30.0, 'a_conv_cost_max': 0, 'a_conversion_min': 1,
        'b_has_conversion': 1, 'b_conv_cost_max': 0,
        'c_max_cost': 50.0,
        'potential_cost_max': 500.0,
        'potential_ctr_mult': 1.5,
        'potential_min_show': 1000,
        'potential_min_click': 20,
    }


def get_all_rules():
    """获取所有分级规则"""
    conn = get_db()
    cur = conn.execute("SELECT * FROM grade_rules ORDER BY is_default DESC, created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_rules(rule_id, **kwargs):
    """更新分级规则"""
    conn = get_db()
    sets = []
    vals = []
    allowed = ('name', 's_cost_pct', 's_conv_cost_max', 's_conversion_min',
               'a_cost_pct', 'a_conv_cost_max', 'a_conversion_min',
               'b_has_conversion', 'b_conv_cost_max', 'c_max_cost', 'is_default',
               'potential_cost_max', 'potential_ctr_mult', 'potential_min_show', 'potential_min_click')
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(rule_id)
    conn.execute(f"UPDATE grade_rules SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_rules(name, **kwargs):
    """创建新分级规则"""
    conn = get_db()
    defaults = get_default_rules()
    fields = {
        'name': name,
        's_cost_pct': kwargs.get('s_cost_pct', defaults['s_cost_pct']),
        's_conv_cost_max': kwargs.get('s_conv_cost_max', defaults.get('s_conv_cost_max', 0)),
        's_conversion_min': kwargs.get('s_conversion_min', defaults['s_conversion_min']),
        'a_cost_pct': kwargs.get('a_cost_pct', defaults['a_cost_pct']),
        'a_conv_cost_max': kwargs.get('a_conv_cost_max', defaults.get('a_conv_cost_max', 0)),
        'a_conversion_min': kwargs.get('a_conversion_min', defaults['a_conversion_min']),
        'b_has_conversion': kwargs.get('b_has_conversion', defaults['b_has_conversion']),
        'b_conv_cost_max': kwargs.get('b_conv_cost_max', defaults.get('b_conv_cost_max', 0)),
        'c_max_cost': kwargs.get('c_max_cost', defaults['c_max_cost']),
        'is_default': 0,
        'potential_cost_max': kwargs.get('potential_cost_max', defaults.get('potential_cost_max', 500)),
        'potential_ctr_mult': kwargs.get('potential_ctr_mult', defaults.get('potential_ctr_mult', 1.5)),
        'potential_min_show': kwargs.get('potential_min_show', defaults.get('potential_min_show', 1000)),
        'potential_min_click': kwargs.get('potential_min_click', defaults.get('potential_min_click', 20)),
    }
    cols = ', '.join(fields.keys())
    placeholders = ', '.join(['?'] * len(fields))
    conn.execute(f"INSERT INTO grade_rules ({cols}) VALUES ({placeholders})", list(fields.values()))
    conn.commit()
    conn.close()


def delete_rules(rule_id):
    """删除分级规则（不可删默认）"""
    conn = get_db()
    cur = conn.execute("SELECT is_default FROM grade_rules WHERE id=?", (rule_id,))
    row = cur.fetchone()
    if row and row['is_default']:
        conn.close()
        raise ValueError("不能删除默认规则")
    conn.execute("DELETE FROM grade_rules WHERE id=?", (rule_id,))
    conn.commit()
    conn.close()


def _calc_project_stats(materials):
    """计算项目级统计指标，用于分级和优质/劣质判断"""
    if not materials:
        return {}
    costs = [m.get('cost', 0) for m in materials]
    shows = [m.get('show', 0) for m in materials]
    clicks = [m.get('click', 0) for m in materials]
    ctrs = [m.get('ctr', 0) for m in materials if m.get('show', 0) > 0]

    total_cost = sum(costs)
    total_show = sum(shows)
    total_click = sum(clicks)

    # 项目平均点击率
    avg_ctr = (total_click / total_show * 100) if total_show > 0 else 0

    # 有消耗素材的中位数消耗
    cost_vals = sorted([c for c in costs if c > 0])
    median_cost = cost_vals[len(cost_vals) // 2] if cost_vals else 0

    # 有转化素材的转化成本中位数
    conv_costs = sorted([m.get('conversion_cost', 0) for m in materials
                         if m.get('conversion', 0) > 0 and m.get('conversion_cost', 0) > 0])
    median_conv_cost = conv_costs[len(conv_costs) // 2] if conv_costs else 0

    # 有消耗素材的消耗中位数（用于优质/劣质判断，比均值更抗长尾干扰）
    median_cost_all = cost_vals[len(cost_vals) // 2] if cost_vals else 0

    return {
        'avg_ctr': avg_ctr,
        'median_cost': median_cost,
        'median_conv_cost': median_conv_cost,
        'median_cost_all': median_cost_all,
        'total_materials': len(materials),
    }


def compute_grades(materials, rules=None):
    """
    对素材列表计算分级 + 潜力/优质/劣质标记
    
    核心逻辑：
    - S/A/B/C 四级：基于消耗+转化数+转化成本
    - P(潜力)：低消耗但有效果信号，值得放量测试
    - 优质：消耗>中位数 AND 有转化 AND 转化成本<中位数
    - 劣质：消耗>中位数 AND（零转化 OR 转化成本>中位数×2）
    """
    if not materials:
        return materials

    if rules is None:
        rules = get_default_rules()

    n = len(materials)
    if n == 0:
        return materials

    # 计算项目级统计
    stats = _calc_project_stats(materials)
    avg_ctr = stats.get('avg_ctr', 2.0)
    median_cost = stats.get('median_cost', 100)
    median_conv_cost = stats.get('median_conv_cost', 100)
    median_cost_all = stats.get('median_cost_all', 0)

    # 按消耗降序排序，计算消耗百分位
    sorted_by_cost = sorted(materials, key=lambda m: m.get('cost', 0), reverse=True)

    total_cost = sum(m.get('cost', 0) for m in materials)
    cumulative = 0
    cost_pct_map = {}
    for m in sorted_by_cost:
        cumulative += m.get('cost', 0)
        pct = (cumulative / total_cost * 100) if total_cost > 0 else 0
        key = m.get('id', id(m))
        cost_pct_map[key] = pct

    # 潜力判断参数
    pot_cost_max = rules.get('potential_cost_max', 500)
    pot_ctr_mult = rules.get('potential_ctr_mult', 1.5)
    pot_min_show = rules.get('potential_min_show', 1000)
    pot_min_click = rules.get('potential_min_click', 20)

    for m in materials:
        key = m.get('id', id(m))
        pct = cost_pct_map.get(key, 100)
        cost = m.get('cost', 0)
        conv = m.get('conversion', 0)
        conv_cost = m.get('conversion_cost', 0)
        show = m.get('show', 0)
        click = m.get('click', 0)
        ctr = m.get('ctr', 0)
        is_active = m.get('is_active', 0)
        is_quality = m.get('is_quality', 0)
        linked_count = m.get('linked_adgroup_count', 0)

        self_pct = (cost / total_cost * 100) if total_cost > 0 else 0

        grade = 'C'
        potential = False
        quality_grade = False
        poor_grade = False

        # ===== S级判断 =====
        in_s_range = pct <= rules.get('s_cost_pct', 10) or self_pct > 5
        s_conv_ok = conv >= rules.get('s_conversion_min', 3)
        s_cost_ok = True
        if rules.get('s_conv_cost_max', 0) > 0 and conv_cost > 0:
            s_cost_ok = conv_cost <= rules.get('s_conv_cost_max', 0)

        if in_s_range and s_conv_ok and s_cost_ok:
            grade = 'S'

        # ===== A级判断 =====
        elif pct <= rules.get('a_cost_pct', 30) or self_pct > 2:
            a_conv_ok = conv >= rules.get('a_conversion_min', 1)
            a_cost_ok = True
            if rules.get('a_conv_cost_max', 0) > 0 and conv_cost > 0:
                a_cost_ok = conv_cost <= rules.get('a_conv_cost_max', 0)

            if a_conv_ok and a_cost_ok:
                grade = 'A'
            elif conv > 0:
                grade = 'B'
            else:
                grade = 'C'

        # ===== B级判断 =====
        elif conv > 0 and rules.get('b_has_conversion', 1):
            b_cost_ok = True
            if rules.get('b_conv_cost_max', 0) > 0 and conv_cost > 0:
                b_cost_ok = conv_cost <= rules.get('b_conv_cost_max', 0)
            if b_cost_ok:
                grade = 'B'
            else:
                grade = 'C'

        # ===== C级 =====
        else:
            if cost > rules.get('c_max_cost', 50) and conv > 0:
                grade = 'B'
            else:
                grade = 'C'

        # ===== 潜力素材识别（仅对B/C级低消耗素材） =====
        if cost < pot_cost_max and grade in ('B', 'C'):
            # 信号1：低消耗有转化（最直接的信号）
            if conv > 0 and conv_cost > 0 and conv_cost <= median_cost * 2:
                potential = True

            # 信号2：点击率显著高于项目均值
            elif show >= pot_min_show and ctr > avg_ctr * pot_ctr_mult:
                potential = True

            # 信号3：高点击+平台优质+在投
            elif click >= pot_min_click and is_quality and linked_count > 0:
                potential = True

            # 信号4：有转化但成本偏高
            elif conv > 0 and conv_cost > 0:
                if conv_cost <= median_cost * 3:
                    potential = True

        # ===== 优质素材识别 =====
        # 消耗>项目中位数 AND 有转化 AND 转化成本<中位数
        if median_cost_all > 0 and median_conv_cost > 0:
            if cost > median_cost_all and conv > 0 and conv_cost > 0 and conv_cost < median_conv_cost:
                quality_grade = True

        # ===== 劣质素材识别 =====
        # 消耗>项目中位数 AND（零转化 OR 转化成本>中位数×2）
        if median_cost_all > 0:
            if cost > median_cost_all:
                if conv == 0:
                    poor_grade = True
                elif conv_cost > 0 and median_conv_cost > 0 and conv_cost > median_conv_cost * 2:
                    poor_grade = True

        m['grade'] = grade
        m['potential'] = potential
        m['quality_grade'] = quality_grade
        m['poor_grade'] = poor_grade

    return materials


def apply_grades_to_db(project_id=None, account_id=None, rules=None):
    """对数据库中素材重新计算分级并更新"""
    conn = get_db()

    query = """
        SELECT m.id, m.cost, m.conversion, m.conversion_cost,
               m.show, m.click, m.ctr, m.is_active, m.is_quality,
               m.linked_adgroup_count
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE 1=1
    """
    params = []

    if project_id:
        query += " AND a.project_id=?"
        params.append(project_id)
    if account_id:
        query += " AND m.account_id=?"
        params.append(account_id)

    cur = conn.execute(query, params)
    materials = [dict(r) for r in cur.fetchall()]

    if not materials:
        conn.close()
        return 0

    graded = compute_grades(materials, rules)
    updated = 0

    for m in graded:
        pot_val = 1 if m.get('potential') else 0
        qg_val = 1 if m.get('quality_grade') else 0
        pg_val = 1 if m.get('poor_grade') else 0
        conn.execute(
            "UPDATE materials SET grade=?, is_potential=?, is_quality_grade=?, is_poor_grade=? WHERE id=?",
            (m['grade'], pot_val, qg_val, pg_val, m['id'])
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated
