"""素材经营分析系统 - Flask应用主入口"""
import os
import json
from flask import Flask, request, jsonify, send_from_directory, render_template
from models import init_db, get_db
from data_processor import parse_file, clean_dataframe, identify_columns
from grade_engine import (
    get_default_rules, get_all_rules, update_rules,
    create_rules, delete_rules, apply_grades_to_db
)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')

# 开发模式禁用浏览器缓存
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'data'), exist_ok=True)

init_db()


# ========== 页面路由 ==========

@app.route('/')
def index():
    return render_template('index.html')


# ========== 项目管理 ==========

@app.route('/api/projects', methods=['GET'])
def list_projects():
    conn = get_db()
    cur = conn.execute("""
        SELECT p.*, COUNT(DISTINCT a.id) as account_count,
               COUNT(DISTINCT m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion
        FROM projects p
        LEFT JOIN accounts a ON a.project_id = p.id
        LEFT JOIN materials m ON m.account_id = a.id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """)
    projects = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(projects)


@app.route('/api/projects', methods=['POST'])
def create_project():
    data = request.json
    name = data.get('name', '').strip()
    desc = data.get('description', '')
    if not name:
        return jsonify({'error': '项目名称不能为空'}), 400

    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO projects (name, description) VALUES (?, ?)", (name, desc))
        conn.commit()
        pid = cur.lastrowid
        conn.close()
        return jsonify({'id': pid, 'name': name}), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': f'创建失败: {str(e)}'}), 400


@app.route('/api/projects/<int:pid>', methods=['DELETE'])
def delete_project(pid):
    conn = get_db()
    try:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 400
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/projects/<int:pid>/clear', methods=['POST'])
def clear_project_data(pid):
    """清空项目素材数据，保留项目本身"""
    conn = get_db()
    try:
        # 1. 删除素材标签（通过外键或手动）
        conn.execute("""
            DELETE FROM material_tags 
            WHERE material_id IN (
                SELECT m.id FROM materials m 
                JOIN accounts a ON m.account_id = a.id 
                WHERE a.project_id = ?
            )
        """, (pid,))
        
        # 2. 删除素材
        conn.execute("""
            DELETE FROM materials 
            WHERE account_id IN (
                SELECT id FROM accounts WHERE project_id = ?
            )
        """, (pid,))
        
        # 3. 删除批次记录
        conn.execute("DELETE FROM import_batches WHERE project_id=?", (pid,))
        
        # 4. 删除导入日志
        conn.execute("DELETE FROM import_logs WHERE project_name=?", (conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()['name'],))
        
        # 5. 删除账户
        conn.execute("DELETE FROM accounts WHERE project_id=?", (pid,))
        
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'message': '项目数据已清空，项目结构保留'})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 400

@app.route('/api/projects/<int:pid>', methods=['PUT'])
def update_project(pid):
    data = request.json
    name = data.get('name', '').strip()
    desc = data.get('description')
    if not name:
        return jsonify({'error': '项目名称不能为空'}), 400

    conn = get_db()
    try:
        if desc is not None:
            conn.execute("UPDATE projects SET name=?, description=? WHERE id=?", (name, desc, pid))
        else:
            conn.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': f'更新失败: {str(e)}'}), 400


# ========== 数据导入 ==========

@app.route('/api/import', methods=['POST'])
def import_data():
    if 'file' not in request.files:
        return jsonify({'error': '未找到上传文件'}), 400

    file = request.files['file']
    project_id = request.form.get('project_id', '')
    project_name = request.form.get('project_name', '').strip()

    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    # 保存上传文件
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    # 解析文件
    try:
        df, mapping, warnings = parse_file(filepath)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # 清洗数据（传入文件名以提取账户ID等信息）
    df = clean_dataframe(df, mapping, filename=file.filename)

    # 确定项目
    conn = get_db()
    if project_id:
        cur = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,))
        proj = cur.fetchone()
        if not proj:
            conn.close()
            return jsonify({'error': '项目不存在'}), 400
        pid = proj['id']
    elif project_name:
        cur = conn.execute("SELECT id FROM projects WHERE name=?", (project_name,))
        proj = cur.fetchone()
        if proj:
            pid = proj['id']
        else:
            cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (project_name,))
            pid = cur.lastrowid
    else:
        # 使用文件名作为项目名
        pname = os.path.splitext(file.filename)[0]
        cur = conn.execute("SELECT id FROM projects WHERE name=?", (pname,))
        proj = cur.fetchone()
        if proj:
            pid = proj['id']
        else:
            cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (pname,))
            pid = cur.lastrowid

    # 记录导入日志
    cur = conn.execute("""
        INSERT INTO import_logs (filename, project_name, rows_total, field_mapping, status)
        VALUES (?, ?, ?, ?, 'processing')
    """, (file.filename, project_name or os.path.splitext(file.filename)[0], len(df), json.dumps(mapping, ensure_ascii=False)))
    log_id = cur.lastrowid

    # 创建批次记录
    cur = conn.execute("""
        INSERT INTO import_batches (project_id, batch_name, filename, account_id, rows_count, status)
        VALUES (?, ?, ?, ?, 0, 'active')
    """, (pid, os.path.splitext(file.filename)[0], file.filename, ''))
    batch_id_int = cur.lastrowid

    rows_imported = 0
    rows_skipped = 0
    total_cost = 0.0
    total_conversion = 0.0

    # 按账户分组导入
    accounts_in_file = df.groupby('account_id') if 'account_id' in df.columns and df['account_id'].any() else None

    if accounts_in_file is not None:
        for acc_id, group in accounts_in_file:
            acc_id_str = str(acc_id).strip()
            if not acc_id_str or acc_id_str == 'nan':
                rows_skipped += len(group)
                continue

            acc_name = group['account_name'].iloc[0] if 'account_name' in group.columns else ''
            campaign_purpose = group['campaign_purpose'].iloc[0] if 'campaign_purpose' in group.columns else ''

            # 创建或查找账户
            cur = conn.execute("SELECT id FROM accounts WHERE project_id=? AND account_id=?", (pid, acc_id_str))
            acc_row = cur.fetchone()
            if acc_row:
                aid = acc_row['id']
                if acc_name or campaign_purpose:
                    conn.execute("UPDATE accounts SET account_name=COALESCE(NULLIF(?, ''), account_name), campaign_purpose=COALESCE(NULLIF(?, ''), campaign_purpose) WHERE id=?",
                                 (str(acc_name), str(campaign_purpose), aid))
            else:
                cur = conn.execute("""
                    INSERT INTO accounts (project_id, account_id, account_name, campaign_purpose)
                    VALUES (?, ?, ?, ?)
                """, (pid, acc_id_str, str(acc_name), str(campaign_purpose)))
                aid = cur.lastrowid

            # 插入素材（含新字段）
            for _, row in group.iterrows():
                try:
                    cost = float(row.get('cost', 0))
                    conv = float(row.get('conversion', 0))
                    total_cost += cost
                    total_conversion += conv
                    cur2 = conn.execute("""
                        INSERT INTO materials (account_id, material_name, material_id, material_type,
                            campaign_name, adgroup_name, cost, show, click, ctr,
                            conversion, conversion_cost, conversion_rate, roi,
                            deep_conversion, deep_conversion_cost, deep_conversion_rate,
                            avg_click_cost, cpm,
                            status, review_status, material_evaluation,
                            linked_adgroup_count, tags, is_active, is_quality,
                            click_url, image_url, video_url, date_range, batch_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        aid,
                        str(row.get('material_name', '')),
                        str(row.get('material_id', '')),
                        str(row.get('material_type', '')),
                        str(row.get('campaign_name', '')),
                        str(row.get('adgroup_name', '')),
                        cost,
                        float(row.get('show', 0)),
                        float(row.get('click', 0)),
                        float(row.get('ctr', 0)),
                        conv,
                        float(row.get('conversion_cost', 0)),
                        float(row.get('conversion_rate', 0)),
                        float(row.get('roi', 0)),
                        float(row.get('deep_conversion', 0)),
                        float(row.get('deep_conversion_cost', 0)),
                        float(row.get('deep_conversion_rate', 0)),
                        float(row.get('avg_click_cost', 0)),
                        float(row.get('cpm', 0)),
                        str(row.get('status', '')),
                        str(row.get('review_status', '')),
                        str(row.get('material_evaluation', '')),
                        int(row.get('linked_adgroup_count', 0)),
                        str(row.get('tags', '')),
                        int(row.get('is_active', 0)),
                        int(row.get('is_quality', 0)),
                        str(row.get('click_url', '')),
                        str(row.get('image_url', '')),
                        str(row.get('video_url', '')),
                        str(row.get('date_range', '')),
                        str(batch_id_int)
                    ))
                    mid = cur2.lastrowid
                    # 插入标签（视频名称解析）
                    conn.execute("""
                        INSERT INTO material_tags (material_id, video_code, price_point, product,
                            actor, bd, copywriting, version, export_time, source_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (mid,
                         str(row.get('video_code', '')),
                         str(row.get('price_point', '')),
                         str(row.get('product', '')),
                         str(row.get('actor', '')),
                         str(row.get('bd', '')),
                         str(row.get('copywriting', '')),
                         str(row.get('version', '')),
                         str(row.get('export_time', '')),
                         str(row.get('source_type', ''))))
                    rows_imported += 1
                except Exception:
                    rows_skipped += 1
    else:
        # 没有账户ID，创建默认账户
        cur = conn.execute("""
            INSERT INTO accounts (project_id, account_id, account_name, campaign_purpose)
            VALUES (?, ?, ?, ?)
        """, (pid, 'default', '默认账户', ''))
        aid = cur.lastrowid

        for _, row in df.iterrows():
            try:
                cost = float(row.get('cost', 0))
                conv = float(row.get('conversion', 0))
                total_cost += cost
                total_conversion += conv
                cur2 = conn.execute("""
                    INSERT INTO materials (account_id, material_name, material_id, material_type,
                        campaign_name, adgroup_name, cost, show, click, ctr,
                        conversion, conversion_cost, conversion_rate, roi,
                        deep_conversion, deep_conversion_cost, deep_conversion_rate,
                        avg_click_cost, cpm,
                        status, review_status, material_evaluation,
                        linked_adgroup_count, tags, is_active, is_quality,
                        click_url, image_url, video_url, date_range, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    aid,
                    str(row.get('material_name', '')),
                    str(row.get('material_id', '')),
                    str(row.get('material_type', '')),
                    str(row.get('campaign_name', '')),
                    str(row.get('adgroup_name', '')),
                    cost,
                    float(row.get('show', 0)),
                    float(row.get('click', 0)),
                    float(row.get('ctr', 0)),
                    conv,
                    float(row.get('conversion_cost', 0)),
                    float(row.get('conversion_rate', 0)),
                    float(row.get('roi', 0)),
                    float(row.get('deep_conversion', 0)),
                    float(row.get('deep_conversion_cost', 0)),
                    float(row.get('deep_conversion_rate', 0)),
                    float(row.get('avg_click_cost', 0)),
                    float(row.get('cpm', 0)),
                    str(row.get('status', '')),
                    str(row.get('review_status', '')),
                    str(row.get('material_evaluation', '')),
                    int(row.get('linked_adgroup_count', 0)),
                    str(row.get('tags', '')),
                    int(row.get('is_active', 0)),
                    int(row.get('is_quality', 0)),
                    str(row.get('click_url', '')),
                    str(row.get('image_url', '')),
                    str(row.get('video_url', '')),
                    str(row.get('date_range', '')),
                    str(batch_id_int)
                ))
                mid = cur2.lastrowid
                conn.execute("""
                    INSERT INTO material_tags (material_id, video_code, price_point, product,
                        actor, bd, copywriting, version, export_time, source_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (mid,
                     str(row.get('video_code', '')),
                     str(row.get('price_point', '')),
                     str(row.get('product', '')),
                     str(row.get('actor', '')),
                     str(row.get('bd', '')),
                     str(row.get('copywriting', '')),
                     str(row.get('version', '')),
                     str(row.get('export_time', '')),
                     str(row.get('source_type', ''))))
                rows_imported += 1
            except Exception:
                rows_skipped += 1

    # 先提交数据再分级
    conn.commit()

    # 自动分级
    apply_grades_to_db(project_id=pid)

    # 更新导入日志
    conn.execute("""
        UPDATE import_logs SET rows_imported=?, rows_skipped=?, status='completed'
        WHERE id=?
    """, (rows_imported, rows_skipped, log_id))

    # 更新批次记录
    conn.execute("""
        UPDATE import_batches 
        SET rows_count=?, total_cost=?, total_conversion=?, account_id=?, account_name=? 
        WHERE id=?
    """, (rows_imported, total_cost, total_conversion, 
          '', '', batch_id_int))

    conn.commit()
    conn.close()

    return jsonify({
        'project_id': pid,
        'rows_imported': rows_imported,
        'rows_skipped': rows_skipped,
        'field_mapping': mapping,
        'warnings': warnings
    })


# ========== 字段预览（导入前） ==========

@app.route('/api/preview', methods=['POST'])
def preview_file():
    if 'file' not in request.files:
        return jsonify({'error': '未找到上传文件'}), 400

    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"preview_{file.filename}")
    file.save(filepath)

    try:
        df, mapping, warnings = parse_file(filepath)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'total_rows': len(df),
        'columns': df.columns.tolist(),
        'field_mapping': mapping,
        'warnings': warnings,
        'sample': df.head(5).fillna('').to_dict(orient='records')
    })


# ========== 分析查询 ==========

@app.route('/api/projects/<int:pid>/overview', methods=['GET'])
def project_overview(pid):
    """项目总览"""
    conn = get_db()

    # 基础统计
    cur = conn.execute("""
        SELECT
            COUNT(DISTINCT a.id) as account_count,
            COUNT(m.id) as material_count,
            COALESCE(SUM(m.cost), 0) as total_cost,
            COALESCE(SUM(m.show), 0) as total_show,
            COALESCE(SUM(m.click), 0) as total_click,
            COALESCE(SUM(m.conversion), 0) as total_conversion,
            CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
            CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=?
    """, (pid,))
    stats = dict(cur.fetchone())

    # 分级分布
    cur = conn.execute("""
        SELECT m.grade, COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost,
               COALESCE(SUM(m.conversion), 0) as conversion
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND m.grade != ''
        GROUP BY m.grade
        ORDER BY m.grade
    """, (pid,))
    grade_dist = [dict(r) for r in cur.fetchall()]

    # 投放目的分布
    cur = conn.execute("""
        SELECT a.campaign_purpose,
               COUNT(m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=? AND a.campaign_purpose != ''
        GROUP BY a.campaign_purpose
        ORDER BY total_cost DESC
    """, (pid,))
    purpose_dist = [dict(r) for r in cur.fetchall()]

    # 账户排行
    cur = conn.execute("""
        SELECT a.account_id, a.account_name, a.campaign_purpose,
               COUNT(m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost,
               CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=?
        GROUP BY a.id
        ORDER BY total_cost DESC
    """, (pid,))
    account_rank = [dict(r) for r in cur.fetchall()]

    # 成本区间分布
    cur = conn.execute("""
        SELECT
            CASE
                WHEN conversion_cost <= 0 OR conversion_cost IS NULL THEN '无效成本'
                WHEN conversion_cost < 50 THEN '< 50元'
                WHEN conversion_cost < 100 THEN '50-100元'
                WHEN conversion_cost < 200 THEN '100-200元'
                WHEN conversion_cost < 500 THEN '200-500元'
                ELSE '> 500元'
            END as tier,
            COUNT(*) as count,
            COALESCE(SUM(cost), 0) as total_cost,
            COALESCE(SUM(conversion), 0) as total_conversion,
            CASE WHEN SUM(conversion) > 0 THEN ROUND(SUM(cost)*1.0/SUM(conversion), 2) ELSE 0 END as avg_cost
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND conversion_cost > 0
        GROUP BY
            CASE
                WHEN conversion_cost <= 0 OR conversion_cost IS NULL THEN '无效成本'
                WHEN conversion_cost < 50 THEN '< 50元'
                WHEN conversion_cost < 100 THEN '50-100元'
                WHEN conversion_cost < 200 THEN '100-200元'
                WHEN conversion_cost < 500 THEN '200-500元'
                ELSE '> 500元'
            END
        ORDER BY
            CASE
                WHEN conversion_cost < 50 THEN 1
                WHEN conversion_cost < 100 THEN 2
                WHEN conversion_cost < 200 THEN 3
                WHEN conversion_cost < 500 THEN 4
                ELSE 5
            END
    """, (pid,))
    cost_tier_dist = [dict(r) for r in cur.fetchall()]

    # 潜力素材统计
    cur = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost,
               COALESCE(SUM(m.conversion), 0) as conversion
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND m.is_potential=1
    """, (pid,))
    potential_stats = dict(cur.fetchone())

    # 优质素材统计（消耗>中位数 + 有转化 + 转化成本<中位数）
    cur = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost,
               COALESCE(SUM(m.conversion), 0) as conversion
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND m.is_quality_grade=1
    """, (pid,))
    quality_stats = dict(cur.fetchone())

    # 劣质素材统计（消耗>中位数 + 零转化或转化成本>2倍中位数）
    cur = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost,
               COALESCE(SUM(m.conversion), 0) as conversion
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND m.is_poor_grade=1
    """, (pid,))
    poor_stats = dict(cur.fetchone())

    conn.close()

    return jsonify({
        'stats': stats,
        'grade_distribution': grade_dist,
        'cost_tier_distribution': cost_tier_dist,
        'potential_stats': potential_stats,
        'quality_stats': quality_stats,
        'poor_stats': poor_stats,
        'purpose_distribution': purpose_dist,
        'account_ranking': account_rank
    })


@app.route('/api/projects/<int:pid>/materials', methods=['GET'])
def list_materials(pid):
    """素材列表（支持筛选）"""
    grade = request.args.get('grade', '')
    account_id = request.args.get('account_id', '')
    purpose = request.args.get('purpose', '')
    keyword = request.args.get('keyword', '')
    review_status = request.args.get('review_status', '')
    batch_id = request.args.get('batch_id', '')
    sort = request.args.get('sort', 'cost')
    order = request.args.get('order', 'desc')
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))

    conn = get_db()
    query = """
        SELECT m.*, a.account_id as acc_id, a.account_name, a.campaign_purpose, p.name as project_name,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting, t.version
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        JOIN projects p ON a.project_id = p.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=?
    """
    params = [pid]

    if grade == 'potential':
        query += " AND m.is_potential=1"
    elif grade == 'quality':
        query += " AND m.is_quality_grade=1"
    elif grade == 'poor':
        query += " AND m.is_poor_grade=1"
    elif grade:
        query += " AND m.grade=?"
        params.append(grade)
    if account_id:
        query += " AND a.id=?"
        params.append(int(account_id))
    if purpose:
        query += " AND a.campaign_purpose=?"
        params.append(purpose)
    if review_status:
        query += " AND m.review_status=?"
        params.append(review_status)
    if batch_id:
        query += " AND m.batch_id=?"
        params.append(str(batch_id))
    if keyword:
        query += " AND (m.material_name LIKE ? OR m.campaign_name LIKE ? OR m.adgroup_name LIKE ? OR t.actor LIKE ? OR t.bd LIKE ? OR t.copywriting LIKE ?)"
        params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])

    # 安全排序
    allowed_sorts = ['cost', 'show', 'click', 'ctr', 'conversion', 'conversion_cost', 'roi', 'grade', 'material_name']
    if sort not in allowed_sorts:
        sort = 'cost'
    if order not in ('asc', 'desc'):
        order = 'desc'

    query += f" ORDER BY m.{sort} {order.upper()}"

    # 直接查询全部（几百条素材内存分页更高效可靠）
    cur = conn.execute(query, params)
    all_rows = cur.fetchall()
    total = len(all_rows)

    # 分页
    start = (page - 1) * size
    end = start + size
    materials = [dict(r) for r in all_rows[start:end]]
    conn.close()

    return jsonify({
        'total': total,
        'page': page,
        'size': size,
        'items': materials
    })


@app.route('/api/projects/<int:pid>/accounts', methods=['GET'])
def list_accounts(pid):
    """项目下账户列表"""
    conn = get_db()
    cur = conn.execute("""
        SELECT a.*, COUNT(m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=?
        GROUP BY a.id
        ORDER BY total_cost DESC
    """, (pid,))
    accounts = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(accounts)


@app.route('/api/projects/<int:pid>/accounts/<int:aid>/analysis', methods=['GET'])
def account_analysis(pid, aid):
    """账户维度分析"""
    conn = get_db()

    # 账户基础统计
    cur = conn.execute("""
        SELECT a.*, COUNT(m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.show), 0) as total_show,
               COALESCE(SUM(m.click), 0) as total_click,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=? AND a.id=?
        GROUP BY a.id
    """, (pid, aid))
    stats = dict(cur.fetchone()) if cur.fetchone() else {}

    # 分级分布
    cur = conn.execute("""
        SELECT m.grade, COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost,
               COALESCE(SUM(m.conversion), 0) as conversion
        FROM materials m
        WHERE m.account_id=? AND m.grade != ''
        GROUP BY m.grade
        ORDER BY m.grade
    """, (aid,))
    grade_dist = [dict(r) for r in cur.fetchall()]

    # TOP素材
    cur = conn.execute("""
        SELECT * FROM materials WHERE account_id=?
        ORDER BY cost DESC LIMIT 20
    """, (aid,))
    top_materials = [dict(r) for r in cur.fetchall()]

    conn.close()

    return jsonify({
        'stats': stats,
        'grade_distribution': grade_dist,
        'top_materials': top_materials
    })


@app.route('/api/projects/<int:pid>/purpose-analysis', methods=['GET'])
def purpose_analysis(pid):
    """按投放目的分析"""
    conn = get_db()
    cur = conn.execute("""
        SELECT a.campaign_purpose,
               COUNT(DISTINCT a.id) as account_count,
               COUNT(m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.show), 0) as total_show,
               COALESCE(SUM(m.click), 0) as total_click,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
        FROM accounts a
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE a.project_id=? AND a.campaign_purpose != ''
        GROUP BY a.campaign_purpose
        ORDER BY total_cost DESC
    """, (pid,))
    result = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(result)


@app.route('/api/projects/<int:pid>/grade-analysis', methods=['GET'])
def grade_analysis(pid):
    """按素材分级分析"""
    conn = get_db()
    cur = conn.execute("""
        SELECT m.grade,
               COUNT(*) as count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.show), 0) as total_show,
               COALESCE(SUM(m.click), 0) as total_click,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND m.grade != ''
        GROUP BY m.grade
        ORDER BY
            CASE m.grade
                WHEN 'S' THEN 1
                WHEN 'A' THEN 2
                WHEN 'B' THEN 3
                WHEN 'C' THEN 4
                ELSE 5
            END
    """, (pid,))
    result = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(result)


# ========== 分级规则管理 ==========

@app.route('/api/grade-rules', methods=['GET'])
def get_rules():
    return jsonify(get_all_rules())


@app.route('/api/grade-rules', methods=['POST'])
def add_rules():
    data = request.json
    try:
        create_rules(data.get('name', '新规则'), **data)
        return jsonify({'ok': True}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/grade-rules/<int:rid>', methods=['PUT'])
def edit_rules(rid):
    data = request.json
    try:
        update_rules(rid, **data)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/grade-rules/<int:rid>', methods=['DELETE'])
def remove_rules(rid):
    try:
        delete_rules(rid)
        return jsonify({'ok': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/projects/<int:pid>/regrade', methods=['POST'])
def regrade_project(pid):
    """重新计算分级"""
    data = request.json or {}
    rule_id = data.get('rule_id')
    rules = None
    if rule_id:
        conn = get_db()
        cur = conn.execute("SELECT * FROM grade_rules WHERE id=?", (rule_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            rules = dict(row)

    count = apply_grades_to_db(project_id=pid, rules=rules)
    return jsonify({'updated': count})


# ========== 导入日志 ==========

@app.route('/api/import-logs', methods=['GET'])
def import_logs():
    conn = get_db()
    cur = conn.execute("SELECT * FROM import_logs ORDER BY created_at DESC LIMIT 20")
    logs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(logs)


# ========== 批次管理 ==========

@app.route('/api/projects/<int:pid>/batches', methods=['GET'])
def list_batches(pid):
    """获取项目的导入批次列表"""
    conn = get_db()
    cur = conn.execute("""
        SELECT b.*, COUNT(DISTINCT m.id) as actual_count,
               a.account_id as acc_id, a.account_name
        FROM import_batches b
        LEFT JOIN materials m ON m.batch_id = CAST(b.id AS TEXT)
        LEFT JOIN accounts a ON m.account_id = a.id
        WHERE b.project_id=?
        GROUP BY b.id
        ORDER BY b.created_at DESC
    """, (pid,))
    batches = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(batches)


@app.route('/api/batches/<int:bid>', methods=['DELETE'])
def delete_batch(bid):
    """删除批次及其关联的素材"""
    conn = get_db()
    # 先获取批次信息
    cur = conn.execute("SELECT project_id, batch_name FROM import_batches WHERE id=?", (bid,))
    batch = cur.fetchone()
    if not batch:
        conn.close()
        return jsonify({'error': '批次不存在'}), 404
    
    pid = batch['project_id']
    batch_name = batch['batch_name']
    
    # 删除该批次的所有素材（关联的material_tags会通过外键级联删除）
    conn.execute("""
        DELETE FROM materials 
        WHERE batch_id=? AND account_id IN (
            SELECT id FROM accounts WHERE project_id=?
        )
    """, (str(bid), pid))
    
    # 删除批次记录
    conn.execute("DELETE FROM import_batches WHERE id=?", (bid,))
    
    # 清理空账户（没有素材的账户）
    conn.execute("""
        DELETE FROM accounts 
        WHERE project_id=? AND id NOT IN (
            SELECT DISTINCT account_id FROM materials WHERE account_id IS NOT NULL
        )
    """, (pid,))
    
    conn.commit()
    conn.close()
    
    # 重新分级
    apply_grades_to_db(project_id=pid)
    
    return jsonify({'ok': True, 'batch_name': batch_name})


# ========== 数据导出 ==========

@app.route('/api/projects/<int:pid>/potential', methods=['GET'])
def potential_materials(pid):
    """潜力素材列表"""
    conn = get_db()
    cur = conn.execute("""
        SELECT m.*, a.account_id as acc_id, a.account_name,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=? AND m.is_potential=1
        ORDER BY m.cost DESC
    """, (pid,))
    materials = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(materials)


@app.route('/api/projects/<int:pid>/tag-analysis', methods=['GET'])
def tag_analysis(pid):
    """按视频名称解析标签分析（演员/BD/产品/价格点）"""
    tag_type = request.args.get('tag_type', 'actor')  # actor/bd/product/price_point
    conn = get_db()

    allowed_tags = {'actor': 't.actor', 'bd': 't.bd', 'product': 't.product', 'price_point': 't.price_point'}
    tag_col = allowed_tags.get(tag_type, 't.actor')

    cur = conn.execute(f"""
        SELECT {tag_col} as tag_value,
               COUNT(*) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion,
               CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost,
               CASE WHEN SUM(m.click) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
               SUM(CASE WHEN m.grade='S' THEN 1 ELSE 0 END) as s_count,
               SUM(CASE WHEN m.grade='A' THEN 1 ELSE 0 END) as a_count,
               SUM(CASE WHEN m.grade='B' THEN 1 ELSE 0 END) as b_count,
               SUM(CASE WHEN m.grade='C' THEN 1 ELSE 0 END) as c_count
        FROM material_tags t
        JOIN materials m ON t.material_id = m.id
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=? AND {tag_col} != ''
        GROUP BY {tag_col}
        ORDER BY total_cost DESC
    """, (pid,))
    result = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(result)


@app.route('/api/projects/<int:pid>/export', methods=['GET'])
def export_project(pid):
    """导出项目素材数据为CSV"""
    import pandas as pd
    import tempfile

    conn = get_db()
    cur = conn.execute("""
        SELECT m.material_name, m.material_id, m.material_type, m.campaign_name,
               m.adgroup_name, m.cost, m.show, m.click, m.ctr,
               m.conversion, m.conversion_cost, m.conversion_rate, m.roi,
               m.deep_conversion, m.deep_conversion_cost, m.grade,
               m.status, m.material_evaluation, m.is_active,
               m.date_range, a.account_id, a.account_name, a.campaign_purpose,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting,
               p.name as project_name
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        JOIN projects p ON a.project_id = p.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=?
        ORDER BY m.cost DESC
    """, (pid,))

    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    conn.close()

    df = pd.DataFrame(rows, columns=columns)

    tmp = tempfile.NamedTemporaryFile(suffix='.csv', delete=False)
    df.to_csv(tmp.name, index=False, encoding='utf-8-sig')

    return send_from_directory(
        os.path.dirname(tmp.name),
        os.path.basename(tmp.name),
        as_attachment=True,
        download_name=f'素材分析_项目{pid}.csv'
    )


@app.route('/api/projects/<int:pid>/recommend', methods=['GET'])
def recommend_materials(pid):
    """推荐上新素材：增量/稳量/潜力各15条"""
    conn = get_db()
    
    # 增量系列：优质素材中消耗最高（放量主力）
    cur = conn.execute("""
        SELECT m.*, a.account_id as acc_id, a.account_name, a.campaign_purpose,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=? AND m.is_quality_grade=1
        ORDER BY m.cost DESC
        LIMIT 15
    """, (pid,))
    increment_list = [dict(r) for r in cur.fetchall()]
    
    # 稳量系列：优质素材中转化成本最低且转化数稳定（稳定产出）
    cur = conn.execute("""
        SELECT m.*, a.account_id as acc_id, a.account_name, a.campaign_purpose,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=? AND m.is_quality_grade=1 AND m.conversion >= 1
        ORDER BY m.conversion_cost ASC, m.conversion DESC
        LIMIT 15
    """, (pid,))
    stable_list = [dict(r) for r in cur.fetchall()]
    
    # 潜力测试系列：潜力素材中按点击率+转化数排序
    cur = conn.execute("""
        SELECT m.*, a.account_id as acc_id, a.account_name, a.campaign_purpose,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE a.project_id=? AND m.is_potential=1
        ORDER BY m.ctr DESC, m.conversion DESC
        LIMIT 15
    """, (pid,))
    potential_list = [dict(r) for r in cur.fetchall()]
    
    conn.close()
    
    return jsonify({
        'increment': increment_list,
        'stable': stable_list,
        'potential': potential_list
    })


if __name__ == '__main__':
    print("=" * 50)
    print("  素材经营分析系统启动中...")
    print(f"  数据库: {os.path.join(os.path.dirname(__file__), 'data', 'analyzer.db')}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080, debug=False)
