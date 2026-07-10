"""素材经营分析系统 - Flask应用主入口"""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path
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


def _safe_float(value, default=0.0):
    """安全转换数值，兼容空值、百分号和字符串。"""
    try:
        if value is None or value == '':
            return default
        if isinstance(value, str):
            value = value.strip().replace('%', '').replace(',', '')
            if not value:
                return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_visitor_id():
    """获取浏览器访客身份，用于免登录数据隔离。"""
    vid = request.headers.get('X-Visitor-Id') or request.cookies.get('visitor_id') or 'legacy'
    vid = ''.join(ch for ch in str(vid) if ch.isalnum() or ch in ('-', '_'))[:80]
    return vid or 'legacy'


def project_belongs_to_visitor(pid):
    conn = get_db()
    row = conn.execute("SELECT id FROM projects WHERE id=? AND visitor_id=?", (pid, get_visitor_id())).fetchone()
    conn.close()
    return bool(row)


@app.before_request
def enforce_project_visitor_scope():
    if not request.path.startswith('/api/projects/'):
        return None
    parts = request.path.strip('/').split('/')
    if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'projects' and parts[2].isdigit():
        if not project_belongs_to_visitor(int(parts[2])):
            return jsonify({'error': '项目不存在'}), 404
    return None


# ========== AI 服务配置 ==========

AI_API_KEY = None
AI_BASE_URL = None
AI_MODEL = None
AI_TIMEOUT = None


def load_project_env():
    """加载项目根目录 .env，并覆盖终端里残留的旧 AI_* 环境变量。"""
    env_path = Path(__file__).resolve().parent / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def load_ai_config():
    """从项目 .env / 环境变量刷新 AI 配置；本地 .env 优先，Serverless 直接用平台环境变量。"""
    load_project_env()
    global AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_TIMEOUT
    AI_API_KEY = os.environ.get('AI_API_KEY') or os.environ.get('OPENAI_API_KEY') or os.environ.get('DEEPSEEK_API_KEY')
    AI_BASE_URL = os.environ.get('AI_BASE_URL', 'https://api.deepseek.com/v1').rstrip('/')
    AI_MODEL = os.environ.get('AI_MODEL', 'deepseek-chat')
    AI_TIMEOUT = int(os.environ.get('AI_TIMEOUT', '30'))


load_ai_config()


class AIServiceError(Exception):
    """AI 服务调用异常。"""


def is_ai_configured():
    return bool(AI_API_KEY)


def call_ai_chat(messages, temperature=0.3, max_tokens=1200):
    """调用 OpenAI-compatible Chat Completions API。

    兼容 DeepSeek(Bearer Token) 和 百度千帆(v3 AK/SK → access_token)。
    前端只请求本服务端接口，API Key 始终从环境变量读取，不进入前端代码。
    """
    if not AI_API_KEY:
        raise AIServiceError('未配置 AI_API_KEY 环境变量')

    # 千帆 v3 AK/SK 认证：走 access_token 方式
    if AI_API_KEY.startswith('bce-v3'):
        return _call_qianfan_v3(messages, temperature, max_tokens)

    # 标准 OpenAI-compatible (DeepSeek / 千帆 v2)
    url = f'{AI_BASE_URL}/chat/completions'
    payload = json.dumps({
        'model': AI_MODEL,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {AI_API_KEY}',
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='ignore')[:500]
        raise AIServiceError(f'AI 服务返回错误：HTTP {e.code} {detail}')
    except urllib.error.URLError as e:
        raise AIServiceError(f'AI 服务网络异常：{e.reason}')
    except Exception as e:
        raise AIServiceError(f'AI 服务调用失败：{e}')

    try:
        return result['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise AIServiceError('AI 服务返回格式异常')


_QIANFAN_ACCESS_TOKEN = None
_QIANFAN_TOKEN_EXPIRY = 0


def _get_qianfan_access_token(ak, sk):
    """获取千帆 access_token，带 20 分钟缓存"""
    global _QIANFAN_ACCESS_TOKEN, _QIANFAN_TOKEN_EXPIRY
    import time
    if _QIANFAN_ACCESS_TOKEN and time.time() < _QIANFAN_TOKEN_EXPIRY:
        return _QIANFAN_ACCESS_TOKEN
    url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}'
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            token = data.get('access_token')
            expires_in = data.get('expires_in', 3600)
            if not token:
                raise AIServiceError(f"千帆获取 token 失败：{data.get('error_description', '未知错误')}")
            _QIANFAN_ACCESS_TOKEN = token
            _QIANFAN_TOKEN_EXPIRY = time.time() + expires_in - 300  # 提前5分钟过期
            return token
    except urllib.error.HTTPError as e:
        raise AIServiceError(f"千帆 token 获取失败 HTTP {e.code}")
    except urllib.error.URLError as e:
        raise AIServiceError(f"千帆 token 网络异常：{e.reason}")


def _call_qianfan_v3(messages, temperature, max_tokens):
    """千帆 v3 AK/SK 认证：先获取 access_token，再调用推理接口"""
    # 解析 AK/SK
    key = AI_API_KEY
    if key.startswith('bce-v3/ALTAK-') and '/' in key[len('bce-v3/'):]:
        ak = key[len('bce-v3/'):].split('/')[0]
        sk = key[len('bce-v3/'):].split('/')[1]
    else:
        raise AIServiceError('千帆 AK/SK 格式异常，应为 bce-v3/ALTAK-xxx/yyy')

    token = _get_qianfan_access_token(ak, sk)
    url = f'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{AI_MODEL}?access_token={token}'

    # 千帆 v3 接口参数
    payload = json.dumps({
        'messages': messages,
        'temperature': temperature,
        'max_output_tokens': max_tokens,
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='ignore')[:500]
        raise AIServiceError(f'千帆服务返回错误：HTTP {e.code} {detail}')
    except urllib.error.URLError as e:
        raise AIServiceError(f'千帆服务网络异常：{e.reason}')

    if 'error' in data:
        raise AIServiceError(f"千帆服务错误：{data['error'].get('message', data['error'])}")

    return data.get('result', '')


# ========== 页面路由 ==========

@app.route('/')
def index():
    return render_template('index.html')


# ========== 项目管理 ==========

@app.route('/api/projects', methods=['GET'])
def list_projects():
    visitor_id = get_visitor_id()
    conn = get_db()
    cur = conn.execute("""
        SELECT p.*, COUNT(DISTINCT a.id) as account_count,
               COUNT(DISTINCT m.id) as material_count,
               COALESCE(SUM(m.cost), 0) as total_cost,
               COALESCE(SUM(m.conversion), 0) as total_conversion
        FROM projects p
        LEFT JOIN accounts a ON a.project_id = p.id
        LEFT JOIN materials m ON m.account_id = a.id
        WHERE p.visitor_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """, (visitor_id,))
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

    visitor_id = get_visitor_id()
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO projects (visitor_id, name, description) VALUES (?, ?, ?)", (visitor_id, name, desc))
        conn.commit()
        pid = cur.lastrowid
        conn.close()
        return jsonify({'id': pid, 'name': name}), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': f'创建失败: {str(e)}'}), 400


@app.route('/api/projects/<int:pid>', methods=['DELETE'])
def delete_project(pid):
    visitor_id = get_visitor_id()
    conn = get_db()
    try:
        conn.execute("DELETE FROM projects WHERE id=? AND visitor_id=?", (pid, visitor_id))
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

    visitor_id = get_visitor_id()
    conn = get_db()
    try:
        if desc is not None:
            conn.execute("UPDATE projects SET name=?, description=? WHERE id=? AND visitor_id=?", (name, desc, pid, visitor_id))
        else:
            conn.execute("UPDATE projects SET name=? WHERE id=? AND visitor_id=?", (name, pid, visitor_id))
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
        df, mapping, details, warnings = parse_file(filepath)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # 清洗数据（传入文件名以提取账户ID等信息）
    df = clean_dataframe(df, mapping, filename=file.filename)

    # 确定项目
    visitor_id = get_visitor_id()
    conn = get_db()
    if project_id:
        cur = conn.execute("SELECT id FROM projects WHERE id=? AND visitor_id=?", (project_id, visitor_id))
        proj = cur.fetchone()
        if not proj:
            conn.close()
            return jsonify({'error': '项目不存在'}), 400
        pid = proj['id']
    elif project_name:
        cur = conn.execute("SELECT id FROM projects WHERE visitor_id=? AND name=?", (visitor_id, project_name))
        proj = cur.fetchone()
        if proj:
            pid = proj['id']
        else:
            cur = conn.execute("INSERT INTO projects (visitor_id, name) VALUES (?, ?)", (visitor_id, project_name))
            pid = cur.lastrowid
    else:
        # 使用文件名作为项目名
        pname = os.path.splitext(file.filename)[0]
        cur = conn.execute("SELECT id FROM projects WHERE visitor_id=? AND name=?", (visitor_id, pname))
        proj = cur.fetchone()
        if proj:
            pid = proj['id']
        else:
            cur = conn.execute("INSERT INTO projects (visitor_id, name) VALUES (?, ?)", (visitor_id, pname))
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
        df, mapping, details, warnings = parse_file(filepath)
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
            CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
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

    # 投手驾驶舱诊断指标
    total_materials = _safe_float(stats.get('material_count'))
    total_click = _safe_float(stats.get('total_click'))
    total_conversion = _safe_float(stats.get('total_conversion'))
    avg_cpa = _safe_float(stats.get('avg_conv_cost'))
    ctr = _safe_float(stats.get('avg_ctr'))
    cvr = round(total_conversion / total_click * 100, 2) if total_click > 0 else 0
    active_count = sum(int(g.get('count') or 0) for g in grade_dist if str(g.get('grade') or '').upper() in ('S', 'A', 'P'))
    quality_count = int(_safe_float(quality_stats.get('count')))
    potential_count = int(_safe_float(potential_stats.get('count')))
    poor_count = int(_safe_float(poor_stats.get('count')))
    effective_count = max(active_count, quality_count + potential_count)
    effective_rate = round(effective_count / total_materials * 100, 2) if total_materials > 0 else 0
    stop_loss_cost = round(_safe_float(poor_stats.get('cost')), 2)
    benchmark_cpas = [_safe_float(g.get('cost')) / _safe_float(g.get('conversion')) for g in grade_dist if _safe_float(g.get('conversion')) > 0]
    benchmark_cpa = round(sum(benchmark_cpas) / len(benchmark_cpas), 2) if benchmark_cpas else avg_cpa

    if avg_cpa <= 0:
        cpa_health = '暂无有效转化成本'
        cpa_level = 'neutral'
    elif benchmark_cpa > 0 and avg_cpa <= benchmark_cpa * 0.9:
        cpa_health = 'CPA健康，效率优于项目基准'
        cpa_level = 'good'
    elif benchmark_cpa > 0 and avg_cpa <= benchmark_cpa * 1.15:
        cpa_health = 'CPA基本稳定，适合结构性优化'
        cpa_level = 'normal'
    else:
        cpa_health = 'CPA偏高，优先排查高耗低转化素材'
        cpa_level = 'warning'

    if effective_rate >= 20:
        material_health = '有效素材率较好，可继续复制放量'
    elif effective_rate >= 8:
        material_health = '有效素材率一般，需要扩大测试与优化池'
    else:
        material_health = '有效素材率偏低，建议优先重构素材供给'

    diagnosis = {
        'ctr': ctr,
        'cvr': cvr,
        'avg_cpa': avg_cpa,
        'benchmark_cpa': benchmark_cpa,
        'cpa_health': cpa_health,
        'cpa_level': cpa_level,
        'effective_count': effective_count,
        'effective_rate': effective_rate,
        'stop_loss_count': poor_count,
        'stop_loss_cost': stop_loss_cost,
        'material_health': material_health,
        'headline': f"当前累计消耗¥{round(_safe_float(stats.get('total_cost')), 2)}，转化{round(total_conversion, 2)}个，CPA为¥{avg_cpa}。{cpa_health}；{material_health}。",
        'actions': [
            '优先复制 S/A/优质素材，作为今日增量候选',
            'P级素材单独建小预算测试计划，避免直接放量',
            'C级/劣质素材进入止损排查，减少无效消耗'
        ]
    }

    conn.close()

    return jsonify({
        'stats': stats,
        'diagnosis': diagnosis,
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


@app.route('/api/projects/<int:pid>/ai-diagnosis', methods=['POST'])
def ai_diagnosis(pid):
    """AI智能评语：单条/批量素材诊断"""
    data = request.get_json() or {}
    material_ids = data.get('material_ids', [])
    
    if not material_ids:
        return jsonify({'error': '未指定素材ID'}), 400
    
    conn = get_db()
    # 获取素材数据
    placeholders = ','.join('?' * len(material_ids))
    cur = conn.execute(f"""
        SELECT m.*, a.account_name, a.campaign_purpose, a.account_id as acc_id,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE m.id IN ({placeholders}) AND a.project_id=?
    """, material_ids + [pid])
    
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    if not rows:
        return jsonify({'error': '未找到指定素材'}), 404
    
    # 生成AI评语：优先调用服务端 AI 代理；未配置或失败时使用本地规则兜底
    results = []
    source = 'ai' if is_ai_configured() else 'local_rules'
    errors = []
    for m in rows:
        try:
            diagnosis = generate_ai_material_diagnosis(m) if is_ai_configured() else generate_material_diagnosis(m)
        except Exception as e:
            source = 'local_rules'
            errors.append(str(e))
            diagnosis = generate_material_diagnosis(m)
        results.append({
            'material_id': m['id'],
            'material_name': m['material_name'],
            'diagnosis': diagnosis
        })
    
    response = {
        'total': len(results),
        'items': results,
        'source': source
    }
    if errors:
        response['warning'] = 'AI调用失败，已自动使用本地规则诊断'
    return jsonify(response)


def generate_ai_material_diagnosis(m):
    """调用大模型生成单条素材诊断，返回与前端兼容的结构。"""
    prompt = f"""
请作为巨量引擎广告投放优化专家，分析下面这条素材数据，输出严格 JSON 数组，不要 Markdown，不要额外解释。
数组元素格式：{{"type":"success|warning|info|error","tag":"不超过6个字","text":"一句可执行诊断建议"}}
最多输出 4 条，优先指出影响投放结果的核心问题或亮点。

素材数据：
- 名称：{m.get('material_name', '-')}
- 账户：{m.get('account_name', '-')}
- 投放目的：{m.get('campaign_purpose', '-')}
- 分级：{m.get('grade', '-')}
- 消耗：{m.get('cost', 0)}
- 展示：{m.get('show', 0)}
- 点击：{m.get('click', 0)}
- CTR：{m.get('ctr', 0)}%
- 转化数：{m.get('conversion', 0)}
- 转化成本：{m.get('conversion_cost', 0)}
- ROI：{m.get('roi', 0)}
- 审核状态：{m.get('review_status', '-')}
- 产品：{m.get('product', '-')}
- 价格点：{m.get('price_point', '-')}
- 剪辑：{m.get('actor', '-')}
- BD：{m.get('bd', '-')}
- 文案：{m.get('copywriting', '-')}
""".strip()

    content = call_ai_chat([
        {'role': 'system', 'content': '你是巨量引擎广告投放优化专家，擅长素材诊断、成本优化和创意复盘。只输出合法 JSON。'},
        {'role': 'user', 'content': prompt}
    ], temperature=0.2, max_tokens=900)

    raw = content.strip()
    if raw.startswith('```'):
        raw = raw.strip('`')
        if raw.lower().startswith('json'):
            raw = raw[4:].strip()
    start = raw.find('[')
    end = raw.rfind(']')
    if start == -1 or end == -1 or end <= start:
        raise AIServiceError('AI 诊断未返回 JSON 数组')

    items = json.loads(raw[start:end + 1])
    normalized = []
    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        point_type = item.get('type') if item.get('type') in ('success', 'warning', 'info', 'error') else 'info'
        tag = str(item.get('tag') or 'AI建议')[:12]
        text = str(item.get('text') or '').strip()
        if text:
            normalized.append({'type': point_type, 'tag': tag, 'text': text})
    if not normalized:
        raise AIServiceError('AI 诊断结果为空')
    return normalized


def generate_material_diagnosis(m):
    """基于素材数据生成智能评语（本地规则引擎）"""
    diagnosis = []
    
    cost = float(m.get('cost', 0) or 0)
    show = float(m.get('show', 0) or 0)
    click = float(m.get('click', 0) or 0)
    ctr = float(m.get('ctr', 0) or 0)
    conversion = float(m.get('conversion', 0) or 0)
    conversion_cost = float(m.get('conversion_cost', 0) or 0)
    grade = m.get('grade', '')
    review_status = m.get('review_status', '')
    
    # 1. 消耗与转化分析
    if cost > 10000 and conversion < 5:
        diagnosis.append({
            'type': 'warning',
            'tag': '高耗低效',
            'text': '消耗超过1万但转化极少，素材吸引力或落地页承接有问题，建议暂停并分析3秒完播率和首帧卖点。'
        })
    elif cost > 5000 and conversion_cost > 500:
        diagnosis.append({
            'type': 'warning',
            'tag': '成本过高',
            'text': '转化成本偏高，建议对比同账户其他素材的成本结构，检查是否定向过窄或出价不合理。'
        })
    elif cost > 0 and conversion_cost < 100 and conversion >= 10:
        diagnosis.append({
            'type': 'success',
            'tag': '优质素材',
            'text': f'转化成本仅{conversion_cost:.0f}元且转化稳定，属于高效素材，建议加大预算放量测试。'
        })
    
    # 2. CTR分析
    if show > 5000:
        if ctr >= 2.0:
            diagnosis.append({
                'type': 'success',
                'tag': '高点击',
                'text': f'CTR达{ctr:.2f}%，素材前3秒吸引力强，建议拆解钩子话术复用到其他素材。'
            })
        elif ctr < 0.3:
            diagnosis.append({
                'type': 'warning',
                'tag': '点击率低',
                'text': f'CTR仅{ctr:.2f}%，素材封面或开头3秒缺乏吸引力，建议优化首帧画面或文案钩子。'
            })
    
    # 3. 数据量判断
    if show < 1000:
        diagnosis.append({
            'type': 'info',
            'tag': '数据不足',
            'text': '展示量不足，数据样本太少难以判断真实表现，建议增加预算或放开定向积累数据。'
        })
    
    # 4. 审核状态
    if review_status == '审核不通过':
        diagnosis.append({
            'type': 'error',
            'tag': '卡审',
            'text': '素材审核不通过，建议检查画面中的敏感元素、文案极限词或医疗/金融相关表述。'
        })
    
    # 5. 分级匹配度
    if grade == 'S' and cost < 5000:
        diagnosis.append({
            'type': 'info',
            'tag': 'S级判断',
            'text': '当前分级为S但消耗不算最高，可能是因为同项目内其他素材表现更优。建议观察后续放量后的稳定性。'
        })
    elif grade == 'C' and conversion_cost < 200:
        diagnosis.append({
            'type': 'info',
            'tag': '误判可能',
            'text': '分级为C但转化成本不算高，可能是因为消耗量低导致分级偏低，建议积累更多数据后重新评估。'
        })
    
    # 6. 综合建议
    if not diagnosis:
        if cost > 0:
            diagnosis.append({
                'type': 'info',
                'tag': '表现平稳',
                'text': '素材表现中规中矩，建议继续观察或微调文案/画面后测试新版本。'
            })
        else:
            diagnosis.append({
                'type': 'info',
                'tag': '无消耗',
                'text': '素材暂无消耗数据，可能是新建素材或已暂停，建议检查投放状态。'
            })
    
    return diagnosis


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
               CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
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
               CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
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
               CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
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
    """按视频名称解析标签分析（剪辑/BD/产品/价格点）"""
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
               CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
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


def _material_metric_summary(items):
    """推荐系列核心指标摘要。"""
    count = len(items or [])
    total_cost = sum(_safe_float(i.get('cost')) for i in items or [])
    total_conversion = sum(_safe_float(i.get('conversion')) for i in items or [])
    total_click = sum(_safe_float(i.get('click')) for i in items or [])
    total_show = sum(_safe_float(i.get('show')) for i in items or [])
    valid_cpas = [_safe_float(i.get('conversion_cost')) for i in items or [] if _safe_float(i.get('conversion')) > 0 and _safe_float(i.get('conversion_cost')) > 0]
    avg_cpa = sum(valid_cpas) / len(valid_cpas) if valid_cpas else 0
    avg_ctr = (sum(_safe_float(i.get('ctr')) for i in items or []) / count) if count else 0
    overall_ctr = (total_click / total_show * 100) if total_show else avg_ctr
    return {
        'count': count,
        'total_cost': round(total_cost, 2),
        'total_conversion': round(total_conversion, 2),
        'avg_cpa': round(avg_cpa, 2),
        'avg_ctr': round(overall_ctr, 2),
        'total_click': round(total_click, 2),
        'quality_count': sum(1 for i in items or [] if _safe_float(i.get('is_quality_grade')) > 0),
        'potential_count': sum(1 for i in items or [] if _safe_float(i.get('is_potential')) > 0),
        's_count': sum(1 for i in items or [] if str(i.get('grade') or '').upper() == 'S'),
    }


def _recommend_reasons(item, section_type, project_avg_cpa, project_avg_ctr):
    """给单条素材生成投手可读的推荐依据与风险。"""
    reasons = []
    risks = []
    grade = str(item.get('grade') or '-')
    cost = _safe_float(item.get('cost'))
    conv = _safe_float(item.get('conversion'))
    cpa = _safe_float(item.get('conversion_cost'))
    ctr = _safe_float(item.get('ctr'))

    if grade in ('S', 'A'):
        reasons.append(f'{grade}级素材，已通过效率验证')
    if item.get('is_quality_grade'):
        reasons.append('优质标签：成本/转化表现优于项目基准')
    if conv > 0 and cpa > 0 and project_avg_cpa > 0:
        diff = (project_avg_cpa - cpa) / project_avg_cpa * 100
        if diff >= 5:
            reasons.append(f'CPA低于项目均值约{round(diff)}%')
        elif cpa <= project_avg_cpa * 1.15:
            reasons.append('CPA接近项目均值，可继续观察放量')
    if ctr > 0 and project_avg_ctr > 0 and ctr >= project_avg_ctr * 1.1:
        reasons.append('CTR高于项目均值，前端吸引力较强')
    if conv >= 3:
        reasons.append(f'累计转化{int(conv)}个，样本具备参考价值')
    if section_type == 'potential':
        reasons.append('低消耗阶段信号较好，适合小预算二次验证')

    if conv == 0 and cost > 0:
        risks.append('暂无转化，禁止直接放量')
    if cpa > 0 and project_avg_cpa > 0 and cpa > project_avg_cpa * 1.2:
        risks.append('CPA高于项目均值，需控制预算')
    if cost < 100 and section_type != 'potential':
        risks.append('样本偏小，建议先观察稳定性')
    if ctr > 0 and project_avg_ctr > 0 and ctr >= project_avg_ctr * 1.5 and conv == 0:
        risks.append('CTR高但无转化，注意骗点击风险')

    return {
        'reasons': reasons[:3] or ['数据表现进入该系列筛选池'],
        'risks': risks[:2] or ['暂无明显风险，仍需结合账户预算与人群承接观察']
    }


@app.route('/api/projects/<int:pid>/recommend', methods=['GET'])
def recommend_materials(pid):
    """推荐上新素材：输出投手动作导向的增量/稳量/潜力系列。"""
    conn = get_db()

    base_select = """
        SELECT m.*, a.account_id as acc_id, a.account_name, a.campaign_purpose,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
    """

    cur = conn.execute("""
        SELECT AVG(CASE WHEN m.conversion > 0 AND m.conversion_cost > 0 THEN m.conversion_cost END) AS avg_cpa,
               AVG(CASE WHEN m.ctr > 0 THEN m.ctr END) AS avg_ctr,
               SUM(m.cost) AS total_cost,
               SUM(m.conversion) AS total_conversion,
               COUNT(*) AS total_materials
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        WHERE a.project_id=?
    """, (pid,))
    project_stats = dict(cur.fetchone() or {})
    project_avg_cpa = _safe_float(project_stats.get('avg_cpa'))
    project_avg_ctr = _safe_float(project_stats.get('avg_ctr'))

    # 增量系列：S/A且优质优先，代表可以复制计划/扩人群/小幅加预算。
    cur = conn.execute(base_select + """
        WHERE a.project_id=? AND (m.grade IN ('S','A') OR m.is_quality_grade=1)
        ORDER BY CASE WHEN m.grade='S' THEN 0 WHEN m.grade='A' THEN 1 ELSE 2 END,
                 m.is_quality_grade DESC, m.conversion DESC, m.cost DESC
        LIMIT 15
    """, (pid,))
    increment_list = [dict(r) for r in cur.fetchall()]

    # 稳量系列：有转化、CPA较低，代表继续跑/小幅扩量。
    cur = conn.execute(base_select + """
        WHERE a.project_id=? AND m.conversion >= 1 AND m.conversion_cost > 0
        ORDER BY m.conversion_cost ASC, m.conversion DESC, m.cost DESC
        LIMIT 15
    """, (pid,))
    stable_list = [dict(r) for r in cur.fetchall()]

    # 潜力测试系列：P标签或低耗高CTR，代表单独小预算验证。
    cur = conn.execute(base_select + """
        WHERE a.project_id=? AND (m.is_potential=1 OR m.grade='P')
        ORDER BY m.is_potential DESC, m.ctr DESC, m.click DESC, m.conversion DESC
        LIMIT 15
    """, (pid,))
    potential_list = [dict(r) for r in cur.fetchall()]

    conn.close()

    sections = {
        'increment': {
            'title': '增量系列',
            'priority': '高优先级',
            'positioning': '已验证高效素材，用于复制计划、扩人群、小幅加预算',
            'action': '优先复制计划，预算建议从当前稳定计划的20%-30%开始加，观察2-3个转化窗口。',
            'rule': 'S/A级或优质标签素材，优先看转化数、CPA和消耗承接能力。',
            'metrics': _material_metric_summary(increment_list),
        },
        'stable': {
            'title': '稳量系列',
            'priority': '中高优先级',
            'positioning': '低CPA且有转化沉淀，用于维持产出和稳态扩量',
            'action': '保持预算稳定，优先复制相同卖点/剪辑结构，谨慎大幅提预算。',
            'rule': '有转化且CPA靠前，优先看成本效率和转化稳定性。',
            'metrics': _material_metric_summary(stable_list),
        },
        'potential': {
            'title': '潜力测试系列',
            'priority': '测试优先级',
            'positioning': '样本不足但前端信号好，用于小预算二次验证',
            'action': '单独建测试计划，控制预算，不建议直接并入放量计划。',
            'rule': 'P级/潜力标签素材，优先看CTR、点击量、低消耗和早期转化苗头。',
            'metrics': _material_metric_summary(potential_list),
        }
    }

    for key, items in [('increment', increment_list), ('stable', stable_list), ('potential', potential_list)]:
        for item in items:
            item.update(_recommend_reasons(item, key, project_avg_cpa, project_avg_ctr))

    summary = {
        'headline': f"今日建议：优先处理{len(increment_list)}条增量素材，稳住{len(stable_list)}条低CPA素材，给{len(potential_list)}条潜力素材单独测试预算。",
        'project_avg_cpa': round(project_avg_cpa, 2),
        'project_avg_ctr': round(project_avg_ctr, 2),
        'total_materials': int(_safe_float(project_stats.get('total_materials'))),
        'total_cost': round(_safe_float(project_stats.get('total_cost')), 2),
        'total_conversion': round(_safe_float(project_stats.get('total_conversion')), 2),
    }

    return jsonify({
        'summary': summary,
        'sections': sections,
        'increment': increment_list,
        'stable': stable_list,
        'potential': potential_list
    })


# ========== AI 对话 ==========

def _build_material_prompt(materials, user_question):
    """将素材数据 + 用户问题组装为 DeepSeek prompt"""
    lines = []
    lines.append("你是一位资深的巨量引擎广告投放优化师，擅长素材经营分析。")
    lines.append("以下是我选中的素材数据（JSON格式），请根据我的问题给出专业、简洁、可执行的分析建议。")
    lines.append("")
    lines.append("素材数据：")
    for i, m in enumerate(materials, 1):
        lines.append(f"--- 素材{i} ---")
        lines.append(f"名称: {m.get('material_name', '-')}")
        lines.append(f"分级: {m.get('grade', '-')}")
        lines.append(f"消耗: {m.get('cost', 0)}")
        lines.append(f"展示: {m.get('show', 0)}")
        lines.append(f"点击: {m.get('click', 0)}")
        lines.append(f"点击率: {m.get('ctr', 0)}%")
        lines.append(f"转化数: {m.get('conversion', 0)}")
        lines.append(f"转化成本: {m.get('conversion_cost', 0)}")
        lines.append(f"审核状态: {m.get('review_status', '-')}")
        if m.get('actor'):
            lines.append(f"剪辑: {m.get('actor')}")
        if m.get('bd'):
            lines.append(f"BD: {m.get('bd')}")
        if m.get('product'):
            lines.append(f"产品: {m.get('product')}")
        lines.append("")
    lines.append(f"我的问题：{user_question}")
    lines.append("")
    lines.append("请用以下格式回答：")
    lines.append("1. 整体分析（2-3句话概括）")
    lines.append("2. 逐条点评（每条素材1-2句，指出亮点或问题）")
    lines.append("3. 优化建议（3条以内可执行建议）")
    return "\n".join(lines)


@app.route('/api/projects/<int:pid>/ai-chat', methods=['POST'])
def ai_chat(pid):
    """AI大模型对话：基于素材数据回答用户问题（原有AI深度分析接口）。"""
    if not is_ai_configured():
        return jsonify({
            'error': '未配置 AI_API_KEY 环境变量，请在本地 .env 或 Serverless 平台环境变量中配置。'
        }), 500

    data = request.get_json() or {}
    material_ids = data.get('material_ids', [])
    user_question = data.get('question', '').strip()

    if not user_question:
        return jsonify({'error': '请输入问题'}), 400

    if not material_ids:
        return jsonify({'error': '请至少选择一条素材'}), 400

    if len(material_ids) > 20:
        return jsonify({'error': '一次最多分析20条素材'}), 400

    # 获取素材数据
    conn = get_db()
    placeholders = ','.join('?' * len(material_ids))
    cur = conn.execute(f"""
        SELECT m.*, a.account_name, a.campaign_purpose, a.account_id as acc_id,
               t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
        FROM materials m
        JOIN accounts a ON m.account_id = a.id
        LEFT JOIN material_tags t ON t.material_id = m.id
        WHERE m.id IN ({placeholders}) AND a.project_id=?
    """, material_ids + [pid])

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return jsonify({'error': '未找到指定素材'}), 404

    # 组装 prompt，通过服务端代理调用 AI，避免 API Key 暴露到前端
    prompt = _build_material_prompt(rows, user_question)

    try:
        reply = call_ai_chat([
            {'role': 'system', 'content': '你是巨量引擎广告投放优化专家，精通素材分析、投放策略和转化优化。'},
            {'role': 'user', 'content': prompt}
        ], temperature=0.6, max_tokens=2000)
        return jsonify({
            'reply': reply,
            'material_count': len(rows),
            'model': AI_MODEL
        })
    except AIServiceError as e:
        return jsonify({'error': str(e)}), 502


# 通用AI对话：页面上下文prompt模板
_PAGE_PROMPT_TEMPLATES = {
    'dashboard': """你正在分析巨量引擎投放项目的整体看板数据。
用户问题：{question}

请基于项目整体表现给出专业分析，包括：
1. 核心指标解读（消耗、转化、成本、素材数等）
2. 分级分布分析（S/A/B/C各级素材的表现特点）
3. 潜力/优质/劣质素材的策略建议
4. 整体投放优化方向""",

    'analysis': """你正在分析巨量引擎素材的详细数据。
用户问题：{question}

请基于素材明细数据给出分析，包括：
1. 筛选条件下的素材表现总结
2. 高价值素材的特征提取
3. 问题素材的诊断和优化建议
4. 账户/投放目的维度的对比分析""",

    'recommend': """你正在分析巨量引擎的推荐上新素材。
用户问题：{question}

请基于推荐素材数据给出分析，包括：
1. 增量系列（放量主力）的评估和建议
2. 稳量系列（稳定产出）的评估和建议
3. 潜力测试系列（值得测试）的评估和建议
4. 上新策略和预算分配建议""",

    'import': """你正在帮助用户导入巨量引擎素材数据。
用户问题：{question}

请基于数据导入场景给出指导，包括：
1. CSV/Excel格式要求和字段说明
2. 字段映射的最佳实践
3. 常见导入问题排查
4. 数据质量检查建议""",

    'tags': """你正在分析巨量引擎素材的剪辑和BD维度数据。
用户问题：{question}

请基于剪辑/BD标签数据给出分析，包括：
1. 剪辑维度的素材表现排名和特征
2. BD维度的投放效果分析
3. 剪辑和BD组合的效果洞察
4. 剪辑和BD团队优化建议""",

    'rules': """你正在解释巨量引擎素材的分级规则。
用户问题：{question}

请基于分级规则给出清晰说明，包括：
1. S/A/B/C四级的判定逻辑和标准
2. 潜力/优质/劣质标签的判定条件
3. 规则参数的含义和调整建议
4. 如何根据业务需求自定义规则"""
}


def _build_general_ai_prompt(page_context, question, project_data=None, material_data=None):
    """根据页面上下文组装通用AI对话prompt。"""
    template = _PAGE_PROMPT_TEMPLATES.get(page_context, _PAGE_PROMPT_TEMPLATES['dashboard'])
    prompt = template.format(question=question)

    # 如果有项目数据，追加到prompt
    if project_data:
        prompt += f"\n\n项目基本信息：\n{json.dumps(project_data, ensure_ascii=False, indent=2)}"

    # 如果有素材数据，追加到prompt
    if material_data:
        prompt += f"\n\n相关素材数据（最多20条）：\n"
        for i, m in enumerate(material_data[:20], 1):
            prompt += f"\n--- 素材{i} ---\n"
            prompt += f"名称: {m.get('material_name', '-')}\n"
            prompt += f"分级: {m.get('grade', '-')}\n"
            prompt += f"消耗: {m.get('cost', 0)}\n"
            prompt += f"展示: {m.get('show', 0)}\n"
            prompt += f"点击: {m.get('click', 0)}\n"
            prompt += f"点击率: {m.get('ctr', 0)}%\n"
            prompt += f"转化数: {m.get('conversion', 0)}\n"
            prompt += f"转化成本: {m.get('conversion_cost', 0)}\n"
            prompt += f"审核状态: {m.get('review_status', '-')}\n"

    return prompt


@app.route('/api/projects/<int:pid>/ai-chat-general', methods=['POST'])
def ai_chat_general(pid):
    """通用AI对话接口：根据页面上下文提供针对性分析。"""
    if not is_ai_configured():
        return jsonify({
            'error': '未配置 AI_API_KEY 环境变量，请在本地 .env 或 Serverless 平台环境变量中配置。'
        }), 500

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    page_context = data.get('page_context', 'dashboard')
    material_ids = data.get('material_ids', [])

    if not question:
        return jsonify({'error': '请输入问题'}), 400

    # 获取项目基本信息
    project_data = None
    material_data = None

    if pid > 0:
        conn = get_db()
        try:
            # 项目基础统计
            cur = conn.execute("""
                SELECT
                    COUNT(DISTINCT a.id) as account_count,
                    COUNT(m.id) as material_count,
                    COALESCE(SUM(m.cost), 0) as total_cost,
                    COALESCE(SUM(m.conversion), 0) as total_conversion,
                    CASE WHEN SUM(m.show) > 0 THEN ROUND(SUM(m.click)*1.0/SUM(m.show)*100, 2) ELSE 0 END as avg_ctr,
                    CASE WHEN SUM(m.conversion) > 0 THEN ROUND(SUM(m.cost)*1.0/SUM(m.conversion), 2) ELSE 0 END as avg_conv_cost
                FROM accounts a
                LEFT JOIN materials m ON m.account_id = a.id
                WHERE a.project_id=?
            """, (pid,))
            project_data = dict(cur.fetchone())

            # 分级分布
            cur = conn.execute("""
                SELECT m.grade, COUNT(*) as count, COALESCE(SUM(m.cost), 0) as cost
                FROM materials m
                JOIN accounts a ON m.account_id = a.id
                WHERE a.project_id=? AND m.grade != ''
                GROUP BY m.grade
            """, (pid,))
            project_data['grade_distribution'] = [dict(r) for r in cur.fetchall()]

            # 如果有指定素材，获取素材详情
            if material_ids:
                placeholders = ','.join('?' * len(material_ids))
                cur = conn.execute(f"""
                    SELECT m.*, a.account_name, a.campaign_purpose, a.account_id as acc_id,
                           t.video_code, t.price_point, t.product, t.actor, t.bd, t.copywriting
                    FROM materials m
                    JOIN accounts a ON m.account_id = a.id
                    LEFT JOIN material_tags t ON t.material_id = m.id
                    WHERE m.id IN ({placeholders}) AND a.project_id=?
                """, material_ids + [pid])
                material_data = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # 组装prompt并调用AI
    prompt = _build_general_ai_prompt(page_context, question, project_data, material_data)

    try:
        reply = call_ai_chat([
            {'role': 'system', 'content': '你是巨量引擎广告投放优化专家，精通素材分析、投放策略和转化优化。请给出专业、简洁、可执行的建议。'},
            {'role': 'user', 'content': prompt}
        ], temperature=0.6, max_tokens=2000)
        return jsonify({
            'reply': reply,
            'model': AI_MODEL
        })
    except AIServiceError as e:
        return jsonify({'error': str(e)}), 502


if __name__ == '__main__':
    # 自动加载 .env 文件（不依赖 python-dotenv）
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    # 去除可能残留的 BOM/控制字符
                    k = k.replace('\ufeff', '')
                    os.environ[k] = v

    load_ai_config()

    print("=" * 50)
    print("  素材经营分析系统启动中...")
    print(f"  数据库: {os.path.join(os.path.dirname(__file__), 'data', 'analyzer.db')}")
    if is_ai_configured():
        print(f"  AI服务: ✅ 已配置（model={AI_MODEL}, base_url={AI_BASE_URL}）")
    else:
        print("  AI服务: ⚠️ 未配置（请设置 AI_API_KEY 环境变量；本地可写入 .env 文件）")
    print("=" * 50)
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
