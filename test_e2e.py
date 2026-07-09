"""端到端测试脚本 - 生成测试数据并验证完整流程"""
import pandas as pd
import numpy as np
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from models import init_db, get_db
from data_processor import identify_columns, clean_dataframe, parse_file, clean_numeric
from grade_engine import compute_grades, get_default_rules, apply_grades_to_db


def generate_test_data():
    """生成模拟巨量导出数据"""
    np.random.seed(42)
    n = 200

    data = {
        '素材名称': [f'素材_{i:03d}' for i in range(n)],
        '素材ID': [f'CRE_{np.random.randint(100000, 999999)}' for _ in range(n)],
        '素材类型': np.random.choice(['视频', '图片', '图文'], n),
        '账户ID': np.random.choice(['ADV001', 'ADV002', 'ADV003'], n),
        '账户名称': np.random.choice(['品牌推广账户', '效果投放账户', '测试账户'], n),
        '投放目的': np.random.choice(['转化', '点击', '曝光'], n),
        '计划名称': [f'计划_{np.random.randint(1, 20)}' for _ in range(n)],
        '消耗': np.random.exponential(500, n).round(2),
        '展示': np.random.randint(1000, 500000, n),
        '点击': np.random.randint(10, 10000, n),
        '点击率': None,  # 让系统自动计算
        '转化': np.random.choice([0, 0, 0, 1, 2, 3, 5, 8, 15, 30], n),
        '转化成本': None,  # 让系统自动计算
        '转化率': None,
        'ROI': np.random.choice([0, 0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0], n),
    }

    df = pd.DataFrame(data)
    filepath = os.path.join(os.path.dirname(__file__), 'uploads', 'test_data.xlsx')
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_excel(filepath, index=False)
    print(f"✅ 测试数据已生成: {filepath} ({n}行)")
    return filepath


def test_field_identification():
    """测试字段自动识别"""
    print("\n--- 测试字段自动识别 ---")
    columns = ['素材名称', '素材ID', '账户ID', '投放目的', '消耗', '展示', '点击', '转化', 'ROI']
    mapping = identify_columns(columns)

    expected = {'material_name': '素材名称', 'material_id': '素材ID', 'account_id': '账户ID',
                'campaign_purpose': '投放目的', 'cost': '消耗', 'show': '展示', 'click': '点击',
                'conversion': '转化', 'roi': 'ROI'}

    for key, val in expected.items():
        assert mapping.get(key) == val, f"字段识别失败: {key} -> 期望 {val}, 实际 {mapping.get(key)}"
        print(f"  ✅ {key} -> {val}")

    # 测试英文列名
    columns_en = ['material_name', 'cost', 'impressions', 'clicks', 'conversions']
    mapping_en = identify_columns(columns_en)
    assert 'material_name' in mapping_en
    assert 'cost' in mapping_en
    assert 'show' in mapping_en  # impressions -> show
    print("  ✅ 英文字段识别通过")


def test_data_cleaning():
    """测试数据清洗"""
    print("\n--- 测试数据清洗 ---")
    df = pd.DataFrame({
        '素材名称': ['A', 'B', 'C'],
        '消耗': ['1,234.56', '5.67%', 'N/A'],
        '展示': [10000, 5000, None],
        '点击': [100, 50, 0],
    })
    mapping = {'material_name': '素材名称', 'cost': '消耗', 'show': '展示', 'click': '点击'}
    df_clean = clean_dataframe(df, mapping)

    assert df_clean['cost'].iloc[0] == 1234.56, f"千分位清洗失败: {df_clean['cost'].iloc[0]}"
    print(f"  ✅ 千分位清洗: 1,234.56 -> {df_clean['cost'].iloc[0]}")

    assert df_clean['cost'].iloc[1] == 0.0567, f"百分比清洗失败: {df_clean['cost'].iloc[1]}"
    print(f"  ✅ 百分比清洗: 5.67% -> {df_clean['cost'].iloc[1]}")

    assert df_clean['cost'].iloc[2] == 0.0, f"N/A清洗失败: {df_clean['cost'].iloc[2]}"
    print(f"  ✅ N/A清洗: N/A -> {df_clean['cost'].iloc[2]}")

    # 自动计算点击率
    assert df_clean['ctr'].iloc[0] == 100 / 10000, f"点击率计算失败: {df_clean['ctr'].iloc[0]}"
    print(f"  ✅ 自动计算点击率: {df_clean['ctr'].iloc[0]}")


def test_grade_engine():
    """测试素材分级引擎"""
    print("\n--- 测试素材分级引擎 ---")
    # 确保数据库已初始化（分级引擎可能查询默认规则）
    init_db()

    materials = [
        {'id': 1, 'cost': 10000, 'roi': 2.5, 'conversion': 30, 'conversion_cost': 333},
        {'id': 2, 'cost': 8000, 'roi': 1.8, 'conversion': 20, 'conversion_cost': 400},
        {'id': 3, 'cost': 5000, 'roi': 1.2, 'conversion': 10, 'conversion_cost': 500},
        {'id': 4, 'cost': 3000, 'roi': 0.8, 'conversion': 5, 'conversion_cost': 600},
        {'id': 5, 'cost': 100, 'roi': 0, 'conversion': 0, 'conversion_cost': 0},
        {'id': 6, 'cost': 50, 'roi': 0, 'conversion': 0, 'conversion_cost': 0},
    ]

    graded = compute_grades(materials)

    # 检查分级结果
    grade_counts = {}
    for m in graded:
        grade_counts[m['grade']] = grade_counts.get(m['grade'], 0) + 1

    print(f"  分级结果: {grade_counts}")
    assert 'grade' in graded[0], "缺少grade字段"
    assert graded[0]['grade'] == 'S', f"最高消耗素材应为S级，实际为{graded[0]['grade']}"
    print(f"  ✅ S级素材: 消耗{graded[0]['cost']}, ROI={graded[0]['roi']}")

    # 无转化的素材应为C级
    c_grade = [m for m in graded if m['conversion'] == 0]
    assert all(m['grade'] == 'C' for m in c_grade), f"无转化素材应为C级"
    print(f"  ✅ C级素材: 无转化素材正确归为C级")


def test_file_parsing():
    """测试文件解析"""
    print("\n--- 测试文件解析 ---")
    filepath = generate_test_data()

    df, mapping, details, warnings = parse_file(filepath)
    print(f"  解析行数: {len(df)}")
    print(f"  识别字段: {list(mapping.keys())}")

    assert len(df) == 200, f"行数不匹配: {len(df)}"
    assert 'cost' in mapping, "未识别消耗字段"
    assert 'show' in mapping, "未识别展示字段"
    print(f"  ✅ 文件解析通过")


def test_database():
    """测试数据库操作"""
    print("\n--- 测试数据库 ---")
    init_db()
    conn = get_db()

    # 测试项目创建
    conn.execute("INSERT OR IGNORE INTO projects (name) VALUES (?)", ('测试项目',))
    conn.commit()
    cur = conn.execute("SELECT * FROM projects WHERE name='测试项目'")
    assert cur.fetchone() is not None, "项目创建失败"
    print("  ✅ 项目创建")

    # 测试默认分级规则
    cur = conn.execute("SELECT * FROM grade_rules WHERE is_default=1")
    rule = cur.fetchone()
    assert rule is not None, "默认规则不存在"
    assert rule['s_cost_pct'] == 10.0, f"S级消耗百分位错误: {rule['s_cost_pct']}"
    print(f"  ✅ 默认分级规则: S级TOP{rule['s_cost_pct']}%, ROI≥{rule['s_roi_min']}")

    # 测试完整导入流程
    filepath = os.path.join(os.path.dirname(__file__), 'uploads', 'test_data.xlsx')
    df, mapping, details, warnings = parse_file(filepath)
    df = clean_dataframe(df, mapping)

    cur = conn.execute("SELECT id FROM projects WHERE name='测试项目'")
    pid = cur.fetchone()['id']

    # 创建账户
    for acc_id in df['account_id'].unique():
        acc_data = df[df['account_id'] == acc_id].iloc[0]
        conn.execute("""
            INSERT OR IGNORE INTO accounts (project_id, account_id, account_name, campaign_purpose)
            VALUES (?, ?, ?, ?)
        """, (pid, str(acc_id), str(acc_data.get('account_name', '')), str(acc_data.get('campaign_purpose', ''))))

    conn.commit()

    # 插入素材
    cur = conn.execute("SELECT id, account_id FROM accounts WHERE project_id=?", (pid,))
    acc_map = {str(r['account_id']): r['id'] for r in cur.fetchall()}

    count = 0
    for _, row in df.iterrows():
        aid = acc_map.get(str(row.get('account_id', '')))
        if not aid:
            continue
        conn.execute("""
            INSERT INTO materials (account_id, material_name, material_id, material_type,
                campaign_name, cost, show, click, ctr, conversion, conversion_cost,
                conversion_rate, roi, batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (aid, str(row.get('material_name', '')), str(row.get('material_id', '')),
              str(row.get('material_type', '')), str(row.get('campaign_name', '')),
              float(row.get('cost', 0)), float(row.get('show', 0)), float(row.get('click', 0)),
              float(row.get('ctr', 0)), float(row.get('conversion', 0)),
              float(row.get('conversion_cost', 0)), float(row.get('conversion_rate', 0)),
              float(row.get('roi', 0)), 'test_data.xlsx'))
        count += 1

    conn.commit()
    print(f"  ✅ 导入 {count} 条素材")

    # 分级
    updated = apply_grades_to_db(project_id=pid)
    print(f"  ✅ 分级完成: {updated} 条")

    # 验证分级结果
    cur = conn.execute("""
        SELECT grade, COUNT(*) as cnt FROM materials
        JOIN accounts ON materials.account_id = accounts.id
        WHERE accounts.project_id=? GROUP BY grade ORDER BY grade
    """, (pid,))
    grade_dist = {r['grade']: r['cnt'] for r in cur.fetchall()}
    print(f"  分级分布: {grade_dist}")
    assert len(grade_dist) > 0, "分级结果为空"

    conn.close()
    print("  ✅ 数据库测试全部通过")


if __name__ == '__main__':
    print("=" * 50)
    print("  素材经营分析系统 - 端到端测试")
    print("=" * 50)

    test_field_identification()
    test_data_cleaning()
    test_grade_engine()
    test_file_parsing()
    test_database()

    print("\n" + "=" * 50)
    print("  ✅ 全部测试通过！")
    print("=" * 50)
