"""字段自动识别与数据清洗模块"""
import pandas as pd
import json
import re
import os
from typing import Dict, List, Tuple, Optional

# 巨量导出表头关键词映射
FIELD_PATTERNS = {
    'material_name': ['素材名称', '创意名称', '视频名称', '图片名称', '创意标题', 'material_name', 'creative_name'],
    'material_id': ['素材ID', '创意ID', '视频ID', '图片ID', '素材id', 'creative_id', 'material_id'],
    'material_type': ['素材类型', '创意类型', '素材格式', 'creative_type', 'material_type'],
    'account_id': ['账户ID', '广告主ID', '账号ID', 'account_id', 'advertiser_id'],
    'account_name': ['账户名称', '广告主名称', '账号名称', 'account_name', 'advertiser_name'],
    'campaign_name': ['计划名称', '广告计划名称', '推广计划名称', 'campaign_name'],
    'campaign_purpose': ['投放目的', '优化目标', '推广目的', '投放目标', 'campaign_purpose', 'optimization_goal'],
    'adgroup_name': ['广告组名称', '推广组名称', 'adgroup_name'],
    'cost': ['消耗', '花费', '总花费', '广告花费', 'cost', 'spend'],
    'show': ['展示', '展示数', '展示次数', '展现', '展现数', 'impressions', 'show'],
    'click': ['点击', '点击数', '点击次数', 'click', 'clicks'],
    'ctr': ['点击率', 'CTR', 'ctr'],
    'conversion': ['转化', '转化数', '转化次数', 'conversion', 'conversions', '激活数'],
    'conversion_cost': ['转化成本', '转化单价', 'CPA', 'cpa', 'conversion_cost', 'cost_per_conversion'],
    'conversion_rate': ['转化率', 'CVR', 'cvr', 'conversion_rate'],
    'roi': ['ROI', 'roi', '投入产出比', '投产比'],
    'deep_conversion': ['深度转化次数', '深度转化', '深度转化数', 'deep_conversion'],
    'deep_conversion_cost': ['深度转化成本', '深度转化单价', 'deep_conversion_cost'],
    'deep_conversion_rate': ['深度转化率', 'deep_conversion_rate'],
    'click_url': ['点击链接', '落地页', '链接', 'click_url', 'landing_url'],
    'image_url': ['图片链接', '图片URL', 'image_url', 'image'],
    'video_url': ['视频链接', '视频URL', 'video_url', 'video'],
    'date_range': ['日期', '统计日期', '投放日期', 'date', 'stat_date', 'report_date'],
    'status': ['投放情况', '投放状态', '状态', 'status'],
    'review_status': ['审核建议', '审核状态', 'review_status'],
    'material_evaluation': ['素材评估', '评估', 'evaluation'],
    'linked_adgroup_count': ['关联在投单元数', '关联单元数', 'linked_count'],
    'tags': ['标签', 'tag', 'tags'],
    'avg_click_cost': ['平均点击单价', '点击单价', 'cpc', 'avg_click_cost'],
    'cpm': ['平均千次展现费用', '千次展现费用', 'cpm'],
}

# 必须识别的核心字段（缺失时给出警告）
CORE_FIELDS = ['cost', 'conversion', 'conversion_cost']


def parse_filename_info(filename: str) -> Dict[str, str]:
    """
    从巨量导出文件名中提取信息
    格式: 视频库_1850561844587531_2026_07_02_13_27_31.csv
    或:   创意库_1850561844587531_2026_07_02.csv
    """
    info = {
        'source_type': '',    # 视频库/创意库/图片库
        'account_id': '',     # 账户ID
        'export_time': '',    # 导出时间
        'date_start': '',     # 数据起始日期
        'date_end': '',       # 数据截止日期
    }

    basename = os.path.splitext(os.path.basename(filename))[0]

    # 匹配: 类型_账户ID_时间
    m = re.match(r'^(视频库|创意库|图片库|素材库|报表)_(\d+)_(\d{4})_(\d{2})_(\d{2})(?:_(\d{2})_(\d{2})_(\d{2}))?$', basename)
    if m:
        info['source_type'] = m.group(1)
        info['account_id'] = m.group(2)
        info['export_time'] = f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
        if m.group(6):
            info['export_time'] += f" {m.group(6)}:{m.group(7)}:{m.group(8)}"

    return info


def parse_video_name(name: str) -> Dict[str, str]:
    """
    解析视频名称中的结构化信息
    格式: 编号+价格+产品+剪辑+BD+文案关键词.mp4
    例: 推送视频_1+4.13+钙尔奇1791+李传权+BDlsl+家里的（改1）.mp4
    说明：历史字段名 actor 保持兼容，但业务含义展示为“剪辑”。
    """
    result = {
        'video_code': '',     # 编号
        'price_point': '',    # 价格点
        'product': '',        # 产品
        'actor': '',          # 剪辑/负责人（历史字段名保持 actor 兼容）
        'bd': '',             # BD
        'copywriting': '',    # 文案关键词
        'version': '',        # 版本号(改1/改2)
    }

    if not name:
        return result

    # 去掉扩展名
    clean = re.sub(r'\.(mp4|mov|avi|mkv|jpg|jpeg|png|gif)$', '', str(name), flags=re.IGNORECASE)

    parts = clean.split('+')

    if len(parts) >= 1:
        result['video_code'] = parts[0].strip()
    if len(parts) >= 2:
        # 第二段可能是价格点(如1.14)或其它
        val = parts[1].strip()
        if re.match(r'^\d+\.?\d*$', val):
            result['price_point'] = val
    if len(parts) >= 3:
        result['product'] = parts[2].strip()
    if len(parts) >= 4:
        result['actor'] = parts[3].strip()
    if len(parts) >= 5:
        # BD标识
        bd_val = parts[4].strip()
        if bd_val.upper().startswith('BD'):
            result['bd'] = bd_val
        else:
            result['bd'] = bd_val
    if len(parts) >= 6:
        # 文案关键词（可能包含版本号）
        remaining = '+'.join(parts[5:]).strip()
        # 提取版本号
        ver_match = re.search(r'[（(](改\d*)[）)]', remaining)
        if ver_match:
            result['version'] = ver_match.group(1)
            remaining = re.sub(r'[（(]改\d*[）)]', '', remaining).strip()
        result['copywriting'] = remaining

    return result


def identify_columns(columns: List[str]) -> Tuple[Dict[str, str], Dict[str, Dict]]:
    """
    自动识别Excel/CSV列名到标准字段的映射
    返回: (mapping, details)
    mapping: {标准字段名: 原始列名}
    details: {标准字段名: {column, score, candidates: [{column, score}]}}
    """
    mapping = {}
    used_columns = set()
    details = {}

    for std_field, patterns in FIELD_PATTERNS.items():
        best_match = None
        best_score = 0
        candidates = []

        for col in columns:
            if col in used_columns:
                continue

            col_clean = str(col).strip()
            col_score = 0
            for pattern in patterns:
                # 精确匹配
                if col_clean.lower() == pattern.lower():
                    col_score = 100
                    break

                # 包含匹配
                if pattern.lower() in col_clean.lower():
                    score = len(pattern) / len(col_clean) * 80
                    if score > col_score:
                        col_score = score

            if col_score > 0:
                candidates.append({'column': col, 'score': round(col_score, 1)})

            if col_score > best_score:
                best_match = col
                best_score = col_score

            if best_score == 100:
                break

        if best_match and best_score >= 40:
            mapping[std_field] = best_match
            used_columns.add(best_match)

        details[std_field] = {
            'column': best_match,
            'score': round(best_score, 1),
            'candidates': sorted(candidates, key=lambda x: x['score'], reverse=True)[:5]
        }

    return mapping, details


def clean_numeric(value) -> Optional[float]:
    """清洗数值字段，处理百分比、千分位等格式"""
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s or s in ('-', '--', 'N/A', 'n/a', 'null', 'NULL', ''):
        return 0.0

    # 处理百分比
    if '%' in s:
        s = s.replace('%', '').strip()
        try:
            return float(s) / 100
        except ValueError:
            return 0.0

    # 处理千分位
    s = s.replace(',', '')

    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_numeric_raw(value):
    """清洗数值但保留百分比原值（巨量导出中点击率2.26表示2.26%，不是0.0226）"""
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s or s in ('-', '--', 'N/A', 'n/a', 'null', 'NULL', ''):
        return 0.0

    if '%' in s:
        s = s.replace('%', '').strip()

    s = s.replace(',', '')

    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_dataframe(df: pd.DataFrame, mapping: Dict[str, str], filename: str = '') -> pd.DataFrame:
    """
    根据字段映射清洗DataFrame
    - 重命名列
    - 清洗数值
    - 填充默认值
    - 解析视频名称结构化信息
    - 从文件名提取账户ID/时间段
    """
    # 反向映射：标准字段 -> 原始列名
    rename_map = {v: k for k, v in mapping.items()}
    df = df.rename(columns=rename_map)

    # 巨量导出的百分比列已经是数值形式（如2.26表示2.26%），不除以100
    pct_fields = ['ctr', 'conversion_rate', 'deep_conversion_rate']
    numeric_fields = ['cost', 'show', 'click', 'conversion',
                      'conversion_cost', 'roi',
                      'deep_conversion', 'deep_conversion_cost',
                      'linked_adgroup_count', 'avg_click_cost', 'cpm']

    for field in numeric_fields:
        if field in df.columns:
            df[field] = df[field].apply(clean_numeric_raw)

    for field in pct_fields:
        if field in df.columns:
            df[field] = df[field].apply(clean_numeric_raw)

    # 文本字段清洗
    text_fields = ['material_name', 'material_id', 'material_type',
                   'account_id', 'account_name', 'campaign_name',
                   'campaign_purpose', 'adgroup_name', 'date_range',
                   'click_url', 'image_url', 'video_url',
                   'status', 'review_status', 'material_evaluation', 'tags']

    for field in text_fields:
        if field in df.columns:
            df[field] = df[field].fillna('').astype(str).str.strip()
        else:
            df[field] = ''

    # 确保核心数值字段存在（缺失时填充0）
    for field in ['cost', 'show', 'click', 'ctr', 'conversion', 'conversion_cost', 'conversion_rate', 'roi',
                  'deep_conversion', 'deep_conversion_cost', 'linked_adgroup_count', 'avg_click_cost', 'cpm']:
        if field not in df.columns:
            df[field] = 0.0

    # 如果点击率全为0，自动计算（百分比形式）
    if df['ctr'].sum() == 0 and df['show'].sum() > 0:
        df['ctr'] = df.apply(
            lambda r: round(r['click'] / r['show'] * 100, 2) if r['show'] > 0 else 0, axis=1
        )

    # 如果转化率全为0，自动计算（百分比形式）
    if df['conversion_rate'].sum() == 0 and df['conversion'].sum() > 0 and df['click'].sum() > 0:
        df['conversion_rate'] = df.apply(
            lambda r: round(r['conversion'] / r['click'] * 100, 2) if r['click'] > 0 else 0, axis=1
        )

    # 如果转化成本全为0，自动计算
    if df['conversion_cost'].sum() == 0 and df['conversion'].sum() > 0:
        df['conversion_cost'] = df.apply(
            lambda r: round(r['cost'] / r['conversion'], 2) if r['conversion'] > 0 else 0, axis=1
        )

    # 生成素材默认名称（如果为空）
    if 'material_name' in df.columns:
        df['material_name'] = df.apply(
            lambda r: r['material_name'] if r['material_name']
            else (r['material_id'] if r['material_id'] else f"素材_{r.name}"),
            axis=1
        )

    # ===== 从文件名提取信息 =====
    file_info = parse_filename_info(filename)

    # 如果没有账户ID列，从文件名填充
    if df['account_id'].replace('', '0').astype(str).str.strip().eq('').all() or df['account_id'].iloc[0] == '':
        if file_info.get('account_id'):
            df['account_id'] = file_info['account_id']

    # 设置导出时间/数据时间段
    if file_info.get('export_time'):
        df['export_time'] = file_info['export_time']
    if file_info.get('source_type'):
        df['source_type'] = file_info['source_type']

    # ===== 解析视频名称结构化信息 =====
    parsed = df['material_name'].apply(parse_video_name)
    df['video_code'] = parsed.apply(lambda x: x['video_code'])
    df['price_point'] = parsed.apply(lambda x: x['price_point'])
    df['product'] = parsed.apply(lambda x: x['product'])
    df['actor'] = parsed.apply(lambda x: x['actor'])
    df['bd'] = parsed.apply(lambda x: x['bd'])
    df['copywriting'] = parsed.apply(lambda x: x['copywriting'])
    df['version'] = parsed.apply(lambda x: x['version'])

    # 投放情况标记为是否已使用
    if 'status' in df.columns:
        df['is_active'] = df['status'].apply(lambda x: 1 if '已使用' in str(x) else 0)
    else:
        df['is_active'] = 0

    # 素材评估
    if 'material_evaluation' in df.columns:
        df['is_quality'] = df['material_evaluation'].apply(lambda x: 1 if '优质' in str(x) else 0)
    else:
        df['is_quality'] = 0

    return df


def parse_file(filepath: str) -> Tuple[pd.DataFrame, Dict[str, str], Dict[str, Dict], List[str]]:
    """
    解析Excel或CSV文件
    返回: (DataFrame, 字段映射, 映射详情, 警告列表)
    """
    warnings = []
    filename = os.path.basename(filepath)

    try:
        if filepath.endswith('.csv'):
            # 尝试不同编码（优先utf-8-sig，巨量新版本常用）
            for encoding in ['utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'gb2312', 'latin1']:
                try:
                    df = pd.read_csv(filepath, encoding=encoding)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            else:
                df = pd.read_csv(filepath, encoding='utf-8', errors='replace')
        else:
            df = pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        raise ValueError(f"文件解析失败: {str(e)}")

    # 清理列名
    df.columns = [str(c).strip() for c in df.columns]

    # 删除空行
    df = df.dropna(how='all')

    if len(df) == 0:
        raise ValueError("文件中没有有效数据行")

    # 自动识别字段
    mapping, details = identify_columns(df.columns.tolist())

    # 检查核心字段
    for core in CORE_FIELDS:
        if core not in mapping:
            warnings.append(f"未识别到核心字段「{core}」，部分分析功能可能受限")

    # 识别未映射的列
    mapped_cols = set(mapping.values())
    unmapped = [c for c in df.columns if c not in mapped_cols]
    if unmapped:
        warnings.append(f"以下列未自动匹配: {', '.join(unmapped[:10])}")

    # 文件名信息提示
    file_info = parse_filename_info(filename)
    if file_info.get('account_id'):
        warnings.append(f"从文件名识别到账户ID: {file_info['account_id']}, 导出时间: {file_info.get('export_time', '未知')}")

    return df, mapping, details, warnings
