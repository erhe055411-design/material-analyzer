/**
 * 素材经营分析系统 - 前端逻辑 (v3)
 * 适配巨量视频库CSV格式
 */

// ========== 全局状态 ==========
const S = {
    page: 'import',
    pid: null,
    projects: [],
    overview: null,
    pendingFile: null,
    pendingPreview: null,
    _analysisState: null,
    _autoFilter: null
};

// ========== API工具 ==========
function getVisitorId() {
    const key = 'material_analyzer_visitor_id';
    let id = localStorage.getItem(key);
    if (!id) {
        const randomPart = (window.crypto && crypto.randomUUID)
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        id = `visitor-${randomPart}`;
        localStorage.setItem(key, id);
    }
    return id;
}

async function api(url, opts = {}) {
    const isFormData = opts.body instanceof FormData;
    opts.headers = { 'X-Visitor-Id': getVisitorId(), ...opts.headers };
    if (!isFormData) opts.headers = { 'Content-Type': 'application/json', ...opts.headers };
    const res = await fetch(url, opts);
    const contentType = res.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');
    const payload = isJson ? await res.json() : await res.text();

    if (!res.ok) {
        if (isJson && payload?.error) {
            throw new Error(payload.error);
        }
        if (res.status === 404) {
            throw new Error('接口不存在或后端/Serverless 函数未部署，请检查 API 路由配置。');
        }
        throw new Error(`请求失败：${res.status} ${res.statusText}`);
    }
    return payload;
}

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', async () => {
    // 导航绑定
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => goTo(item.dataset.page));
    });
    document.getElementById('projectSelector').addEventListener('change', (e) => {
        S.pid = e.target.value ? parseInt(e.target.value) : null;
        S.overview = null;
        updateProjectButtons();
        render();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeGlobalAIAssistant();
    });
    document.getElementById('aiAssistantFAB')?.addEventListener('click', openGlobalAIAssistant);
    document.getElementById('aiAssistantFAB')?.classList.remove('hidden');
    // 加载项目列表
    await loadProjects();
    render();
});

function goTo(page) {
    S.page = page;
    document.querySelectorAll('.nav-item').forEach(i => i.classList.toggle('active', i.dataset.page === page));
    render();
    updateAIAssistantContext();
}

function render() {
    const fn = { dashboard: renderDashboard, analysis: renderAnalysis, recommend: renderRecommend, import: renderImport, tags: renderTags, rules: renderRules };
    (fn[S.page] || renderDashboard)();
    updateAIAssistantContext();
}

// ========== 工具函数 ==========
function fmt(n, decimals = 0) {
    if (n == null || isNaN(n)) return '-';
    n = parseFloat(n);
    if (Math.abs(n) >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
    return n.toFixed(decimals).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
}

function fmtInt(n) {
    return fmt(n, 0);
}

function fmtPct(n, decimals = 2) {
    if (n == null || isNaN(n)) return '-';
    return `${parseFloat(n).toFixed(decimals)}%`;
}

function fmtCost(n) {
    if (n == null || isNaN(n)) return '-';
    n = parseFloat(n);
    if (Math.abs(n) >= 10000) return '¥' + (n / 10000).toFixed(2).replace(/0+$/, '').replace(/\.$/, '') + '万';
    return '¥' + n.toFixed(2);
}

function reviewStatusBadge(status) {
    if (!status || status === '审核通过') {
        return '<span class="rs-badge rs-pass">未卡审</span>';
    } else if (status === '审核不通过') {
        return '<span class="rs-badge rs-fail">卡审</span>';
    }
    return '<span class="rs-badge">-</span>';
}

function gradeBadge(g, potential, qg, pg) {
    let html = `<span class="gb gb-${g}">${g || '-'}</span>`;
    if (potential) html += '<span class="gb gb-P" title="潜力素材">P</span>';
    if (qg) html += '<span class="gb gb-Q" title="优质素材">优</span>';
    if (pg) html += '<span class="gb gb-BD" title="劣质素材">劣</span>';
    return html;
}

function materialActionBadge(m) {
    const grade = m.grade || 'C';
    const conversions = Number(m.conversion || 0);
    const cost = Number(m.cost || 0);
    if (m.is_poor_grade || (grade === 'C' && cost > 0 && conversions === 0)) {
        return '<span class="action-badge action-stop">降预算/暂停</span>';
    }
    if (m.is_quality_grade || grade === 'S') {
        return '<span class="action-badge action-scale">复制放量</span>';
    }
    if (grade === 'A') {
        return '<span class="action-badge action-keep">稳定观察</span>';
    }
    if (m.is_potential || grade === 'P') {
        return '<span class="action-badge action-test">小预算测试</span>';
    }
    if (grade === 'B') {
        return '<span class="action-badge action-opt">优化素材</span>';
    }
    return '<span class="action-badge action-watch">继续观察</span>';
}

function materialNameCell(name) {
    const safe = escapeHtml(name || '-');
    return `<div class="material-name-cell" title="${safe}">
        <span class="material-name-text">${safe}</span>
        ${copyButtonHtml(name)}
    </div>`;
}

// ========== 项目管理 ==========
async function loadProjects() {
    try {
        S.projects = await api('/api/projects');
    } catch (e) {
        S.projects = [];
    }
    // 按素材数量降序排列
    S.projects.sort((a, b) => (b.material_count || 0) - (a.material_count || 0));

    const sel = document.getElementById('projectSelector');
    const currentExists = S.pid && S.projects.some(p => p.id === S.pid);
    if (!currentExists) S.pid = null;
    if (!S.pid && S.projects.length > 0) {
        const withData = S.projects.filter(p => (p.material_count || 0) > 0);
        S.pid = withData.length > 0 ? withData[0].id : S.projects[0].id;
    }
    sel.innerHTML = '<option value="">选择项目...</option>' +
        S.projects.map(p => `<option value="${p.id}" ${S.pid === p.id ? 'selected' : ''}>${p.name} (${p.material_count || 0}条)</option>`).join('');
    sel.value = S.pid || '';
    updateProjectButtons();
}

function updateProjectButtons() {
    const btnRename = document.getElementById('btnRenameProject');
    const btnDelete = document.getElementById('btnDeleteProject');
    const btnClear = document.getElementById('btnClearProject');
    if (S.pid) {
        btnRename.style.display = '';
        btnDelete.style.display = '';
        btnClear.style.display = '';
    } else {
        btnRename.style.display = 'none';
        btnDelete.style.display = 'none';
        btnClear.style.display = 'none';
    }
}

function showCreateProject() { document.getElementById('createProjectModal').classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

async function createProject() {
    const name = document.getElementById('newProjectName').value.trim();
    if (!name) return alert('请输入项目名称');
    try {
        const p = await api('/api/projects', { method: 'POST', body: JSON.stringify({ name, description: '' }) });
        S.pid = p.id;
        await loadProjects();
        closeModal('createProjectModal');
        goTo('import');
    } catch (e) { alert(e.message); }
}

function showRenameProject() {
    if (!S.pid) return;
    const proj = S.projects.find(p => p.id === S.pid);
    if (!proj) return;
    document.getElementById('renameProjectName').value = proj.name;
    document.getElementById('renameProjectModal').classList.remove('hidden');
}

async function renameProject() {
    const name = document.getElementById('renameProjectName').value.trim();
    if (!name) return alert('请输入项目名称');
    try {
        await api(`/api/projects/${S.pid}`, { method: 'PUT', body: JSON.stringify({ name }) });
        await loadProjects();
        closeModal('renameProjectModal');
    } catch (e) { alert(e.message); }
}

function showDeleteProject() {
    if (!S.pid) return;
    const proj = S.projects.find(p => p.id === S.pid);
    const name = proj ? proj.name : '该项目';
    const count = proj ? (proj.material_count || 0) : 0;
    let msg = `确定要删除项目「${name}」吗？`;
    if (count > 0) msg += `\n该项目包含 ${count} 条素材数据，删除后不可恢复！`;
    msg += `\n\n点击「确认删除」将立即删除。`;
    document.getElementById('deleteProjectMsg').textContent = msg;
    document.getElementById('deleteProjectModal').classList.remove('hidden');
}

async function deleteProject() {
    if (!S.pid) return;
    try {
        await api(`/api/projects/${S.pid}`, { method: 'DELETE' });
        S.pid = null;
        await loadProjects();
        closeModal('deleteProjectModal');
        updateProjectButtons();
        render();
    } catch (e) { alert(e.message); }
}

function showClearProject() {
    if (!S.pid) return;
    const proj = S.projects.find(p => p.id === S.pid);
    const count = proj ? (proj.material_count || 0) : 0;
    if (count === 0) {
        alert('该项目暂无素材数据，无需清空');
        return;
    }
    document.getElementById('clearProjectModal').classList.remove('hidden');
}

async function clearProjectData() {
    if (!S.pid) return;
    try {
        await api(`/api/projects/${S.pid}/clear`, { method: 'POST' });
        S.overview = null;
        await loadProjects();
        closeModal('clearProjectModal');
        render();
    } catch (e) { alert(e.message); }
}

function exportData() {
    if (!S.pid) return alert('请先选择项目');
    window.open(`/api/projects/${S.pid}/export`);
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[ch]));
}

function copyButtonHtml(name) {
    const safeArg = escapeHtml(JSON.stringify(String(name || '')));
    return `<span class="copy-btn" onclick="copyMaterialName(event, ${safeArg})" title="复制素材名称">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
    </span>`;
}

function fallbackCopyText(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    let ok = false;
    try {
        ok = document.execCommand('copy');
    } finally {
        document.body.removeChild(textarea);
    }
    return ok;
}

let lastHiddenCopyButton = null;

// 复制素材名称到剪贴板
async function copyMaterialName(event, name) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    name = String(name || '').trim();
    if (!name || name === '-') {
        alert('没有可复制的素材名称');
        return;
    }

    const btn = event?.currentTarget;

    let copied = false;
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(name);
            copied = true;
        }
    } catch (err) {
        console.warn('Clipboard API 复制失败，尝试兼容方案:', err);
    }

    if (!copied) {
        copied = fallbackCopyText(name);
    }

    if (copied) {
        if (lastHiddenCopyButton && lastHiddenCopyButton !== btn && document.body.contains(lastHiddenCopyButton)) {
            lastHiddenCopyButton.classList.remove('hidden');
        }
        btn?.classList.add('hidden');
        lastHiddenCopyButton = btn || null;
    } else {
        alert('复制失败，请手动选中文案复制');
    }
}

// ========== 项目看板 ==========
async function renderDashboard() {
    const el = document.getElementById('pageContent');
    if (!S.pid) {
        el.innerHTML = '<div class="empty"><h3>请先选择项目</h3><p>在顶部下拉栏选择一个项目，或新建项目后导入数据</p></div>';
        return;
    }
    el.innerHTML = '<div class="loading">加载中...</div>';

    try {
        const data = await api(`/api/projects/${S.pid}/overview`);
        S.overview = data;
        const s = data.stats;

        el.innerHTML = `
        ${renderExecutiveDashboard(data)}

        <!-- 素材分类卡片 -->
        <div class="section-title">素材分级分布 <span class="section-hint">点击卡片查看对应素材</span></div>
        <div class="class-grid">
            ${renderClassCard('S', 'S级·核心跑量', '#FF4D4F', data.grade_distribution, '消耗占比前10%且转化≥3')}
            ${renderClassCard('A', 'A级·稳定产出', '#FAAD14', data.grade_distribution, '消耗占比前30%且转化≥1')}
            ${renderClassCard('B', 'B级·有待提升', '#1890FF', data.grade_distribution, '有转化但消耗占比不高')}
            ${renderClassCard('C', 'C级·低效素材', '#9CA3AF', data.grade_distribution, '低消耗低转化，可考虑关停')}
        </div>

        <!-- 特殊素材卡片 -->
        <div class="chart-row">
            ${renderSpecialCard('potential', '🔥 潜力素材', '#52C41A', data.potential_stats, '低消耗但有转化/高CTR信号，建议放量测试')}
            ${renderSpecialCard('quality', '🏆 优质素材', '#1890FF', data.quality_stats, '消耗>中位数+有转化+成本<中位数，放量主力')}
            ${renderSpecialCard('poor', '⚠️ 劣质素材', '#FF4D4F', data.poor_stats, '消耗>中位数+零转化或成本>2倍中位数，建议关停')}
        </div>

        <!-- 图表区 -->
        ${data.grade_distribution && data.grade_distribution.length > 0 ? `
        <div class="overview-charts-grid">
            <div class="card chart-card overview-chart-card"><div class="card-title">分级分布</div><div class="card-subtitle">看 S/A/B/C 素材结构与消耗承接</div><div id="gradeChart" class="chart-box large"></div></div>
            <div class="card chart-card overview-chart-card"><div class="card-title">成本区间分布</div><div class="card-subtitle">看素材消耗集中在哪些测试/止损区间</div><div id="costTierChart" class="chart-box large"></div></div>
        </div>
        ` : ''}

        <!-- 账户排行 -->
        ${data.account_ranking && data.account_ranking.length > 0 ? `
        <div class="card"><div class="card-title">账户排行</div>
        <div class="table-wrap"><table><thead><tr><th>账户</th><th>投放目的</th><th>素材数</th><th>消耗</th><th>转化</th><th>转化成本</th><th>点击率</th></tr></thead>
        <tbody>${data.account_ranking.map(a => `<tr><td>${a.account_name || a.account_id}</td><td>${a.campaign_purpose || '-'}</td><td>${a.material_count}</td><td>${fmtCost(a.total_cost)}</td><td>${fmt(a.total_conversion)}</td><td>${fmt(a.avg_conv_cost)}</td><td>${a.avg_ctr}%</td></tr>`).join('')}</tbody></table></div></div>
        ` : ''}
        `;

        renderCharts(data);
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

function renderExecutiveDashboard(data) {
    const s = data.stats || {};
    const d = data.diagnosis || {};
    const level = d.cpa_level || 'neutral';
    const actions = d.actions || [];
    return `
        <div class="exec-dashboard">
            <div class="exec-insight-card ${level}">
                <div class="section-eyebrow">投手经营判断</div>
                <h2>经营概览</h2>
                <p>${escapeHtml(d.headline || '当前项目数据已更新，请结合分级分布与素材诊断继续分析。')}</p>
                <div class="exec-actions">
                    ${actions.map(a => `<span>✓ ${escapeHtml(a)}</span>`).join('') || '<span>✓ 优先关注高耗低转化与可复制素材</span>'}
                </div>
            </div>
            <div class="kpi-row pro">
                ${renderKpiCard('总消耗', fmtCost(s.total_cost), '30天累计投放体量', 'spend')}
                ${renderKpiCard('总点击', fmt(s.total_click), `CTR ${fmt(d.ctr || s.avg_ctr || 0)}%`, 'click')}
                ${renderKpiCard('总转化', fmt(s.total_conversion), `CVR ${fmt(d.cvr || 0)}%`, 'conv')}
                ${renderKpiCard('转化成本', fmtCost(s.avg_conv_cost), escapeHtml(d.cpa_health || '等待转化成本判断'), `cpa ${level}`)}
                ${renderKpiCard('有效素材率', `${fmt(d.effective_rate || 0)}%`, `${fmt(d.effective_count || 0)}条可继续投/测`, 'effective')}
                ${renderKpiCard('止损素材', `${fmt(d.stop_loss_count || 0)}条`, `相关消耗 ${fmtCost(d.stop_loss_cost || 0)}`, 'risk')}
            </div>
        </div>`;
}

function renderKpiCard(label, value, sub, type) {
    return `<div class="kpi pro ${type}">
        <div class="kpi-label">${label}</div>
        <div class="kpi-val">${value}</div>
        <div class="kpi-sub">${sub}</div>
    </div>`;
}

function renderClassCard(grade, title, color, dist, hint) {
    const d = (dist || []).find(x => x.grade === grade) || { count: 0, cost: 0, conversion: 0 };
    return `<div class="class-card" style="border-top:3px solid ${color}" onclick="viewClass('grade','${grade}')">
        <div class="class-head"><span class="gb gb-${grade}" style="font-size:18px">${grade}</span>${title}</div>
        <div class="class-nums"><strong>${d.count}</strong><span>条素材</span></div>
        <div class="class-sub">消耗 ${fmtCost(d.cost)} · 转化 ${fmt(d.conversion)}</div>
        <div class="class-hint">${hint}</div>
    </div>`;
}

function renderSpecialCard(type, title, color, stats, hint) {
    const d = stats || { count: 0, cost: 0, conversion: 0 };
    return `<div class="class-card" style="border-top:3px solid ${color}" onclick="viewClass('grade','${type}')">
        <div class="class-head" style="color:${color};font-weight:700">${title}</div>
        <div class="class-nums"><strong>${d.count}</strong><span>条素材</span></div>
        <div class="class-sub">消耗 ${fmtCost(d.cost)} · 转化 ${fmt(d.conversion)}</div>
        <div class="class-hint">${hint}</div>
    </div>`;
}

function viewClass(key, val) {
    S.page = 'analysis';
    S._autoFilter = { key, val };
    document.querySelectorAll('.nav-item').forEach(i => i.classList.toggle('active', i.dataset.page === 'analysis'));
    render();
}

function renderCharts(data) {
    // 分级分布图
    const gEl = document.getElementById('gradeChart');
    if (gEl) {
        const chart = echarts.init(gEl);
        const grades = ['S', 'A', 'B', 'C'];
        const colors = { S: '#FF4D4F', A: '#FAAD14', B: '#1890FF', C: '#9CA3AF' };
        const map = {};
        (data.grade_distribution || []).forEach(d => map[d.grade] = d);
        chart.setOption({
            tooltip: { trigger: 'item', formatter: '{b}<br/>素材数：{c}<br/>占比：{d}%' },
            legend: { bottom: 0, icon: 'circle', itemGap: 18, textStyle: { color: '#64748B' } },
            series: [{
                name: '分级分布',
                type: 'pie',
                radius: ['48%', '72%'],
                center: ['50%', '44%'],
                avoidLabelOverlap: true,
                itemStyle: { borderColor: '#fff', borderWidth: 4, borderRadius: 8 },
                label: { formatter: '{b}\n{c}条', color: '#334155', fontWeight: 700 },
                data: grades.map(g => ({ name: g, value: map[g]?.count || 0, itemStyle: { color: colors[g] } }))
            }]
        });
        chart.on('click', (p) => viewClass('grade', p.name));
        window.addEventListener('resize', () => chart.resize());
    }
    // 成本区间分布图
    const cEl = document.getElementById('costTierChart');
    if (cEl && data.cost_tier_distribution) {
        const chart = echarts.init(cEl);
        const tierColors = ['#52C41A', '#95DE64', '#FAAD14', '#FF7875', '#FF4D4F', '#8C8C8C'];
        chart.setOption({
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps) => `${ps[0].axisValue}<br/>素材数：${fmt(ps[0].value)}条` },
            grid: { left: 42, right: 18, top: 22, bottom: 42 },
            xAxis: { type: 'category', data: data.cost_tier_distribution.map(d => d.tier), axisTick: { show: false }, axisLine: { lineStyle: { color: '#E5E7EB' } }, axisLabel: { color: '#64748B' } },
            yAxis: { type: 'value', name: '素材数', splitLine: { lineStyle: { color: '#EEF2F7' } }, axisLabel: { color: '#64748B' } },
            series: [{
                type: 'bar',
                barWidth: 34,
                data: data.cost_tier_distribution.map((d, i) => ({
                    value: d.count,
                    itemStyle: { color: tierColors[i % tierColors.length], borderRadius: [10, 10, 4, 4] }
                })),
                label: { show: true, position: 'top', color: '#334155', fontWeight: 700 }
            }]
        });
        window.addEventListener('resize', () => chart.resize());
    }
}

// ========== 素材分析页 ==========
async function renderAnalysis() {
    const el = document.getElementById('pageContent');
    if (!S.pid) {
        el.innerHTML = '<div class="empty"><h3>请先选择项目</h3></div>';
        return;
    }

    // 确定初始筛选
    const autoFilter = S._autoFilter || {};
    S._autoFilter = null;
    if (!S._analysisState) {
        S._analysisState = { grade: '', account_id: '', purpose: '', review_status: '', batch_id: '', keyword: '', sort: 'cost', order: 'desc', page: 1 };
    }
    if (autoFilter.key && autoFilter.val) {
        S._analysisState[autoFilter.key] = autoFilter.val;
    }

    const st = S._analysisState;

    el.innerHTML = `
    <div class="filter-bar">
        <div class="filter-tabs" id="gradeTabs">
            <button class="ftab ${!st.grade ? 'active' : ''}" data-v="">全部 <em class="tab-count" data-count="all">-</em></button>
            <button class="ftab ${st.grade==='S' ? 'active' : ''}" data-v="S"><span class="gb gb-S">S</span>核心 <em class="tab-count" data-count="S">-</em></button>
            <button class="ftab ${st.grade==='A' ? 'active' : ''}" data-v="A"><span class="gb gb-A">A</span>稳定 <em class="tab-count" data-count="A">-</em></button>
            <button class="ftab ${st.grade==='B' ? 'active' : ''}" data-v="B"><span class="gb gb-B">B</span>待提 <em class="tab-count" data-count="B">-</em></button>
            <button class="ftab ${st.grade==='C' ? 'active' : ''}" data-v="C"><span class="gb gb-C">C</span>低效 <em class="tab-count" data-count="C">-</em></button>
            <button class="ftab ${st.grade==='potential' ? 'active' : ''}" data-v="potential"><span class="gb gb-P">P</span>潜力 <em class="tab-count" data-count="potential">-</em></button>
            <button class="ftab ${st.grade==='quality' ? 'active' : ''}" data-v="quality"><span class="gb gb-Q">优</span>优质 <em class="tab-count" data-count="quality">-</em></button>
            <button class="ftab ${st.grade==='poor' ? 'active' : ''}" data-v="poor"><span class="gb gb-BD">劣</span>劣质 <em class="tab-count" data-count="poor">-</em></button>
        </div>
        <div class="filter-row">
            <select id="fAccount" onchange="filterChange('account_id',this.value)"></select>
            <select id="fPurpose" onchange="filterChange('purpose',this.value)"></select>
            <select id="fReview" onchange="filterChange('review_status',this.value)">
                <option value="" ${st.review_status===''?'selected':''}>全部审核</option>
                <option value="审核通过" ${st.review_status==='审核通过'?'selected':''}>未卡审</option>
                <option value="审核不通过" ${st.review_status==='审核不通过'?'selected':''}>卡审</option>
            </select>
            <select id="fBatch" onchange="filterChange('batch_id',this.value)">
                <option value="" ${st.batch_id===''?'selected':''}>全部批次</option>
            </select>
            <input type="text" id="fKeyword" placeholder="搜索素材/计划名称" value="${st.keyword}" onkeyup="debounceSearch()">
            <select id="fSort" onchange="filterChange('sort',this.value)">
                <option value="cost" ${st.sort==='cost'?'selected':''}>按消耗</option>
                <option value="conversion" ${st.sort==='conversion'?'selected':''}>按转化</option>
                <option value="conversion_cost" ${st.sort==='conversion_cost'?'selected':''}>按转化成本</option>
                <option value="ctr" ${st.sort==='ctr'?'selected':''}>按点击率</option>
                <option value="show" ${st.sort==='show'?'selected':''}>按展示</option>
            </select>
            <button class="btn btn-sm btn-secondary" onclick="clearFilters()">重置</button>
        </div>
    </div>
    <div class="card">
        <div id="materialsTable" class="table-wrap"><div class="loading">加载中...</div></div>
        <div id="materialsPagination" class="pagination"></div>
    </div>`;

    // 绑定分级tab
    document.querySelectorAll('#gradeTabs .ftab').forEach(btn => {
        btn.addEventListener('click', () => {
            S._analysisState.grade = btn.dataset.v;
            S._analysisState.page = 1;
            document.querySelectorAll('#gradeTabs .ftab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadMaterials();
        });
    });

    await loadFilterOptions();
    await loadMaterials();
}

function filterChange(key, val) {
    if (!S._analysisState) return;
    S._analysisState[key] = val;
    S._analysisState.page = 1;
    loadMaterials();
}

let _searchTimer;
function debounceSearch() {
    if (!S._analysisState) return;
    S._analysisState.keyword = document.getElementById('fKeyword').value;
    S._analysisState.page = 1;
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(loadMaterials, 300);
}

function clearFilters() {
    S._analysisState = { grade: '', account_id: '', purpose: '', review_status: '', batch_id: '', keyword: '', sort: 'cost', order: 'desc', page: 1 };
    renderAnalysis();
}

async function loadFilterOptions() {
    try {
        const accounts = await api(`/api/projects/${S.pid}/accounts`);
        const accSel = document.getElementById('fAccount');
        if (accSel) {
            accSel.innerHTML = '<option value="">全部账户</option>' + accounts.map(a => `<option value="${a.id}" ${S._analysisState.account_id == a.id ? 'selected' : ''}>${a.account_name || a.account_id}</option>`).join('');
        }
        const purposeData = await api(`/api/projects/${S.pid}/purpose-analysis`);
        const purSel = document.getElementById('fPurpose');
        if (purSel) {
            purSel.innerHTML = '<option value="">全部投放目的</option>' + purposeData.map(p => `<option value="${p.campaign_purpose}" ${S._analysisState.purpose === p.campaign_purpose ? 'selected' : ''}>${p.campaign_purpose}</option>`).join('');
        }
        // 加载批次选项
        const batches = await api(`/api/projects/${S.pid}/batches`);
        const batchSel = document.getElementById('fBatch');
        if (batchSel) {
            batchSel.innerHTML = '<option value="">全部批次</option>' + batches.map(b => `<option value="${b.id}" ${S._analysisState.batch_id == b.id ? 'selected' : ''}>${b.batch_name || b.filename} (${b.actual_count || 0}条)</option>`).join('');
        }
    } catch (e) { /* ignore */ }
}

async function loadMaterials(page) {
    if (!S._analysisState) return;
    if (page) S._analysisState.page = page;
    const st = S._analysisState;
    const sort = document.getElementById('fSort')?.value || st.sort;

    const params = new URLSearchParams({
        grade: st.grade || '', account_id: st.account_id || '', purpose: st.purpose || '',
        review_status: st.review_status || '', batch_id: st.batch_id || '', keyword: st.keyword || '', sort: sort, order: 'desc', page: st.page, size: 50
    });

    try {
        const data = await api(`/api/projects/${S.pid}/materials?${params}`);
        S.materials = data.items || [];
        const tbl = document.getElementById('materialsTable');
        if (!tbl) return;

        updateGradeTabCounts(data.grade_counts || {});

        if (!data.items || data.items.length === 0) {
            tbl.innerHTML = '<div class="empty"><p>当前筛选条件下没有素材</p></div>';
            renderPagination(0, st.page);
            return;
        }

        // AI 深度分析按钮暂时隐藏；保留全选和其他功能逻辑
        const hasItems = data.items && data.items.length > 0;
        const aiBarHtml = hasItems ? `
        <div class="ai-action-bar">
            <div class="ai-action-left">
                <input type="checkbox" class="ai-check" id="selectAll" onclick="toggleSelectAll(this)"> <label for="selectAll">全选</label>
                <span id="selectedCount" style="margin-left:12px;color:#999;font-size:12px"></span>
            </div>
        </div>` : '';

        tbl.innerHTML = aiBarHtml + `<table class="materials-pro-table"><thead><tr>
            <th style="width:30px"><input type="checkbox" id="selectAllHeader" onclick="toggleSelectAll(this)"></th>
            <th>分级</th><th class="name-col">素材名称</th><th>审核状态</th><th>消耗</th><th>展示</th><th>点击</th>
            <th>CTR</th><th>转化</th><th>转化成本</th><th>建议动作</th><th>状态</th>
        </tr></thead><tbody>${data.items.map(m => `<tr>
            <td><input type="checkbox" class="ai-check" data-id="${m.id}" onchange="updateSelectCount()"></td>
            <td>${gradeBadge(m.grade || '-', m.is_potential, m.is_quality_grade, m.is_poor_grade)}</td>
            <td class="td-name">${materialNameCell(m.material_name || '-')}</td>
            <td>${reviewStatusBadge(m.review_status)}</td>
            <td class="num">${fmtCost(m.cost)}</td>
            <td class="num">${fmtInt(m.show)}</td>
            <td class="num">${fmtInt(m.click)}</td>
            <td class="num">${fmtPct(m.ctr)}</td>
            <td class="num strong">${fmtInt(m.conversion)}</td>
            <td class="num">${fmtCost(m.conversion_cost)}</td>
            <td>${materialActionBadge(m)}</td>
            <td>${m.status || '-'}</td>
        </tr>`).join('')}</tbody></table>`;

        renderPagination(data.total, st.page);
    } catch (e) {
        const tbl = document.getElementById('materialsTable');
        if (tbl) tbl.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

function updateGradeTabCounts(counts) {
    document.querySelectorAll('#gradeTabs .tab-count').forEach(el => {
        const key = el.dataset.count;
        const val = counts && counts[key] != null ? counts[key] : 0;
        el.textContent = fmtInt(val);
    });
}

function renderPagination(total, page) {
    const el = document.getElementById('materialsPagination');
    if (!el) return;
    const pages = Math.ceil(total / 50);
    if (pages <= 1) { el.innerHTML = `<span>共 ${total} 条</span>`; return; }
    let html = `<span>共 ${total} 条</span>`;
    if (page > 1) html += `<button onclick="loadMaterials(${page - 1})">上一页</button>`;
    for (let i = 1; i <= pages; i++) {
        if (Math.abs(i - page) <= 2 || i === 1 || i === pages) {
            html += `<button class="${i === page ? 'active' : ''}" onclick="loadMaterials(${i})">${i}</button>`;
        } else if (Math.abs(i - page) === 3) {
            html += '<span>...</span>';
        }
    }
    if (page < pages) html += `<button onclick="loadMaterials(${page + 1})">下一页</button>`;
    el.innerHTML = html;
}

// ========== 推荐上新 ==========
async function renderRecommend() {
    const el = document.getElementById('pageContent');
    if (!S.pid) {
        el.innerHTML = '<div class="empty">请选择项目</div>';
        return;
    }
    el.innerHTML = '<div class="loading">加载推荐素材中...</div>';

    try {
        const data = await api(`/api/projects/${S.pid}/recommend`);
        const sections = data.sections || {};
        el.innerHTML = `
        <div class="recommend-page pro">
            <div class="rec-command-center">
                <div>
                    <div class="section-eyebrow">AI 投放动作建议</div>
                    <h2>🆕 推荐上新素材</h2>
                    <p>${escapeHtml(data.summary?.headline || '根据当前项目素材表现生成上新建议')}</p>
                </div>
                <div class="rec-command-metrics">
                    <div><strong>${fmt(data.summary?.total_materials || 0)}</strong><span>素材样本</span></div>
                    <div><strong>¥${fmt(data.summary?.project_avg_cpa || 0)}</strong><span>项目均CPA</span></div>
                    <div><strong>${fmt(data.summary?.project_avg_ctr || 0)}%</strong><span>项目均CTR</span></div>
                </div>
            </div>
            ${recommendStrategySection('increment', sections.increment, data.increment || [])}
            ${recommendStrategySection('stable', sections.stable, data.stable || [])}
            ${recommendStrategySection('potential', sections.potential, data.potential || [])}
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

function recFallbackMetrics(items) {
    return { count: items.length, total_cost: 0, total_conversion: 0, avg_cpa: 0, avg_ctr: 0, s_count: 0, quality_count: 0, potential_count: 0 };
}

function recommendStrategySection(type, section = {}, items = []) {
    const defaults = {
        increment: { title: '增量系列', priority: '高优先级', positioning: '已验证高效素材，用于复制计划、扩人群、小幅加预算', action: '优先复制计划，小幅加预算。', rule: 'S/A级或优质标签素材。' },
        stable: { title: '稳量系列', priority: '中高优先级', positioning: '低CPA且有转化沉淀，用于维持产出和稳态扩量', action: '保持预算稳定，复制相同卖点结构。', rule: '有转化且CPA靠前。' },
        potential: { title: '潜力测试系列', priority: '测试优先级', positioning: '样本不足但前端信号好，用于小预算二次验证', action: '单独测试，禁止直接放量。', rule: 'P级/潜力标签素材。' }
    };
    section = { ...defaults[type], ...section };
    const m = section.metrics || recFallbackMetrics(items);
    const icon = type === 'increment' ? '📈' : type === 'stable' ? '⚖️' : '🧪';
    return `
        <div class="recommend-section pro rec-${type}" data-expanded="true">
            <div class="recommend-header-bar pro" onclick="toggleRecommendSection(this)">
                <div class="recommend-title pro">
                    <span class="recommend-tag tag-${type}">${icon} ${escapeHtml(section.title)}</span>
                    <span class="recommend-priority">${escapeHtml(section.priority)}</span>
                    <span class="recommend-subtitle">${escapeHtml(section.positioning)}</span>
                    <span class="recommend-count">${fmt(m.count || items.length)} 条</span>
                </div>
                <span class="recommend-toggle">▼</span>
            </div>
            <div class="recommend-body">
                <div class="rec-kpi-grid">
                    <div><span>平均CPA</span><strong>¥${fmt(m.avg_cpa || 0)}</strong></div>
                    <div><span>总转化</span><strong>${fmt(m.total_conversion || 0)}</strong></div>
                    <div><span>平均CTR</span><strong>${fmt(m.avg_ctr || 0)}%</strong></div>
                    <div><span>命中标签</span><strong>${fmt((m.s_count || 0) + (m.quality_count || 0) + (m.potential_count || 0))}</strong></div>
                </div>
                <div class="rec-action-box"><span>建议动作</span><strong>${escapeHtml(section.action)}</strong></div>
                <div class="rec-rule">筛选口径：${escapeHtml(section.rule)}</div>
                ${renderRecommendTable(items, type)}
            </div>
        </div>`;
}

function toggleRecommendSection(header) {
    const section = header.closest('.recommend-section');
    const body = section.querySelector('.recommend-body');
    const toggle = header.querySelector('.recommend-toggle');
    const isExpanded = section.dataset.expanded === 'true';
    body.style.display = isExpanded ? 'none' : '';
    toggle.textContent = isExpanded ? '▶' : '▼';
    section.dataset.expanded = isExpanded ? 'false' : 'true';
}

function renderRecommendTable(items, type) {
    if (!items || items.length === 0) {
        return `<div class="empty" style="padding:30px"><p>暂无推荐素材，请先应用新版分级或导入更多数据</p></div>`;
    }

    return `<div class="table-wrap rec-table-wrap"><table class="rec-table">
        <thead><tr>
            <th>排名</th><th>素材与分级</th><th>效率表现</th><th>推荐依据 / 风险提示</th><th>账户</th><th>操作状态</th>
        </tr></thead>
        <tbody>${items.map((m, idx) => recommendRow(m, idx)).join('')}</tbody>
    </table></div>`;
}

function recommendRow(m, idx) {
    const reasons = (m.reasons || []).slice(0, 2).map(r => `<span>✓ ${escapeHtml(r)}</span>`).join('');
    const risks = (m.risks || []).slice(0, 1).map(r => `<span>⚠ ${escapeHtml(r)}</span>`).join('');
    return `<tr>
        <td><span class="rank-badge rank-${idx < 3 ? idx + 1 : ''}">${idx + 1}</span></td>
        <td class="td-name" title="${escapeHtml(m.material_name || '')}">
            <div class="rec-name-line">${copyButtonHtml(m.material_name || '')}${escapeHtml(m.material_name || '-')}</div>
            <div class="rec-subline">${gradeBadge(m.grade || '-', m.is_potential, m.is_quality_grade, m.is_poor_grade)}</div>
        </td>
        <td>
            <div class="rec-eff">${fmtCost(m.cost)} · ${fmt(m.conversion)}转化</div>
            <div class="rec-subline">CPA ${fmtCost(m.conversion_cost)} · CTR ${fmt(m.ctr)}% · 点击 ${fmt(m.click)}</div>
        </td>
        <td>
            <div class="rec-reasons">${reasons || '<span>✓ 进入该系列筛选池</span>'}</div>
            <div class="rec-risks">${risks || '<span>⚠ 需结合预算和人群继续观察</span>'}</div>
        </td>
        <td>${escapeHtml(m.account_name || m.acc_id || '-')}</td>
        <td>${reviewStatusBadge(m.review_status)}<div class="rec-subline">${escapeHtml(m.status || '-')}</div></td>
    </tr>`;
}

// ========== 数据导入 ==========
async function renderImport() {
    const el = document.getElementById('pageContent');
    if (!S.pid) {
        el.innerHTML = `
        <div class="import-hero">
            <div class="import-hero-icon">📥</div>
            <h2>开始你的第一次素材分析</h2>
            <p>先创建一个项目，再上传巨量引擎导出的 Excel / CSV。系统会自动识别字段、生成素材诊断、剪辑BD分析和 AI 优化建议。</p>
            <div class="import-steps">
                <div><b>1</b><span>新建项目</span></div>
                <div><b>2</b><span>上传数据</span></div>
                <div><b>3</b><span>查看诊断</span></div>
            </div>
            <button class="btn btn-primary btn-hero" onclick="showCreateProject()">新建项目并导入数据</button>
            <div class="import-hero-tip">支持 .xlsx / .xls / .csv，建议直接使用巨量引擎导出的原始报表。</div>
        </div>`;
        return;
    }

    el.innerHTML = `
    <div class="card import-card">
        <div class="card-title">第一步：导入素材数据</div>
        <div class="import-subtitle">上传巨量引擎导出的 Excel / CSV，系统会自动识别字段并生成分析结果。</div>
        <div class="upload-zone upload-zone-primary" id="uploadZone" ondragover="event.preventDefault()" ondrop="handleDrop(event)">
            <div class="upload-icon">📥</div>
            <p><b>拖拽文件到这里</b>，或 <a href="javascript:void(0)" onclick="document.getElementById('fileInput').click()">点击上传数据文件</a></p>
            <small>支持 .xlsx / .xls / .csv</small>
            <input type="file" id="fileInput" accept=".csv,.xlsx,.xls" style="display:none" onchange="handleFile(this.files[0])">
        </div>
        <div id="importResult"></div>
    </div>
    <div class="card" style="margin-top:16px">
        <div class="card-title">导入记录</div>
        <div id="batchList"><div class="loading">加载中...</div></div>
    </div>`;

    await loadBatchList();
}

async function loadBatchList() {
    const el = document.getElementById('batchList');
    if (!el) return;
    try {
        const batches = await api(`/api/projects/${S.pid}/batches`);
        if (!batches || batches.length === 0) {
            el.innerHTML = '<div class="empty" style="padding:30px"><p>暂无导入记录</p></div>';
            return;
        }
        el.innerHTML = `<div class="table-wrap"><table>
            <thead><tr><th>文件名</th><th>素材数</th><th>消耗</th><th>转化</th><th>导入时间</th><th>操作</th></tr></thead>
            <tbody>${batches.map(b => `<tr>
                <td class="td-name" title="${b.filename || ''}">${b.batch_name || b.filename || '-'}</td>
                <td>${b.actual_count || 0}</td>
                <td>${fmtCost(b.total_cost || 0)}</td>
                <td>${fmt(b.total_conversion || 0)}</td>
                <td>${b.created_at || '-'}</td>
                <td><button class="btn btn-sm btn-danger" onclick="deleteBatch(${b.id}, '${(b.batch_name || b.filename || '').replace(/'/g, "\\'")}')">删除</button></td>
            </tr>`).join('')}</tbody>
        </table></div>`;
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

async function deleteBatch(bid, name) {
    if (!confirm(`确定要删除导入记录「${name}」吗？\n该批次下的所有素材数据将被删除，不可恢复。`)) return;
    try {
        await api(`/api/batches/${bid}`, { method: 'DELETE' });
        await loadBatchList();
        await loadProjects();
        S.overview = null;
    } catch (e) { alert('删除失败: ' + e.message); }
}

async function handleFile(file) {
    if (!S.pid) {
        document.getElementById('importResult').innerHTML = `<div class="error-box">请先选择项目后再导入数据</div>`;
        return;
    }
    
    // 第一阶段：上传文件获取预览和映射建议
    const previewForm = new FormData();
    previewForm.append('file', file);
    
    try {
        document.getElementById('importResult').innerHTML = `<div class="loading">正在解析文件字段映射...</div>`;
        const preview = await api('/api/preview', { method: 'POST', body: previewForm });
        
        if (preview.error) {
            document.getElementById('importResult').innerHTML = `<div class="error-box">${preview.error}</div>`;
            return;
        }
        
        // 显示映射浮层
        showMappingModal(file, preview);
    } catch (e) {
        document.getElementById('importResult').innerHTML = `<div class="error-box">预览解析失败: ${e.message}</div>`;
    }
}

function showMappingModal(file, preview) {
    const allColumns = preview.columns || [];
    const mapping = preview.field_mapping || {};
    const details = preview.mapping_details || {};
    const warnings = preview.warnings || [];
    const sample = preview.sample || [];
    
    // 标准字段列表（按重要性排序）
    const stdFields = [
        { key: 'material_name', label: '素材名称', required: true },
        { key: 'material_id', label: '素材ID' },
        { key: 'account_id', label: '账户ID' },
        { key: 'account_name', label: '账户名称' },
        { key: 'campaign_name', label: '计划名称' },
        { key: 'campaign_purpose', label: '投放目的' },
        { key: 'cost', label: '消耗', required: true },
        { key: 'show', label: '展示' },
        { key: 'click', label: '点击' },
        { key: 'ctr', label: '点击率' },
        { key: 'conversion', label: '转化数', required: true },
        { key: 'conversion_cost', label: '转化成本', required: true },
        { key: 'conversion_rate', label: '转化率' },
        { key: 'roi', label: 'ROI' },
        { key: 'review_status', label: '审核状态' },
        { key: 'status', label: '投放状态' },
        { key: 'date_range', label: '日期' },
        { key: 'material_type', label: '素材类型' },
        { key: 'deep_conversion', label: '深度转化' },
        { key: 'deep_conversion_cost', label: '深度转化成本' },
        { key: 'avg_click_cost', label: '点击单价' },
        { key: 'cpm', label: '千次展现费用' },
    ];
    
    // 构建原始列标签
    const mappedCols = new Set(Object.values(mapping));
    const origTags = allColumns.map(col => {
        const isMapped = mappedCols.has(col);
        return `<span class="mapping-orig-tag ${isMapped ? 'mapped' : 'unmapped'}">${col}</span>`;
    }).join('');
    
    // 构建警告提示
    let alertHtml = '';
    const coreMissing = stdFields.filter(f => f.required && !mapping[f.key]);
    if (coreMissing.length > 0) {
        alertHtml += `<div class="mapping-alert error">⚠️ 核心字段缺失：${coreMissing.map(f => f.label).join('、')} — 部分分析功能将受限</div>`;
    }
    const hasUnmapped = allColumns.some(c => !mappedCols.has(c));
    if (hasUnmapped) {
        alertHtml += `<div class="mapping-alert warn">以下原始列未匹配到标准字段，可手动映射或忽略</div>`;
    }
    
    // 构建映射行
    const mappingRows = stdFields.map(field => {
        const currentMap = mapping[field.key] || '';
        const detail = details[field.key] || {};
        const score = detail.score || 0;
        const candidates = detail.candidates || [];
        
        // 下拉选项：空 + 所有原始列
        const options = [`<option value="">-- 不映射 --</option>`,
            ...allColumns.map(col => {
                const selected = col === currentMap ? 'selected' : '';
                const isRecommended = candidates.some(c => c.column === col);
                const indicator = isRecommended ? ' ★' : '';
                return `<option value="${col.replace(/"/g, '&quot;')}" ${selected}>${col}${indicator}</option>`;
            })
        ].join('');
        
        let scoreClass = 'low';
        if (score >= 80) scoreClass = 'high';
        else if (score >= 40) scoreClass = 'mid';
        
        const scoreText = currentMap ? (score >= 100 ? '精确匹配' : `置信度 ${Math.round(score)}%`) : '未匹配';
        
        return `
        <div class="mapping-row">
            <div class="mapping-field-label ${field.required ? 'required' : ''}">${field.label}</div>
            <select class="mapping-select ${!currentMap ? 'unmapped' : ''}" data-field="${field.key}" id="map-${field.key}">
                ${options}
            </select>
            <div class="mapping-score ${scoreClass}">${scoreText}</div>
        </div>
        `;
    }).join('');
    
    // 样本数据
    const sampleHtml = sample.length > 0 
        ? `<div class="mapping-sample">
            <h4>数据样本（前3行）</h4>
            <pre>${JSON.stringify(sample.slice(0, 3), null, 2)}</pre>
        </div>` 
        : '';
    
    // 组装浮层
    const modalHtml = `
    <div class="mapping-overlay" id="mappingOverlay">
        <div class="mapping-modal">
            <div class="mapping-header">
                <h3>📋 字段映射确认 — ${file.name} (${preview.total_rows} 行)</h3>
                <button class="close-btn" onclick="closeMappingModal()">&times;</button>
            </div>
            <div class="mapping-body">
                ${alertHtml}
                <div class="mapping-section-title">原始列列表</div>
                <div class="mapping-orig-cols">${origTags}</div>
                <div class="mapping-section-title">标准字段映射</div>
                <div style="font-size:12px;color:#999;margin-bottom:8px;">★ = 系统推荐匹配项，带 * 为核心字段</div>
                ${mappingRows}
                ${sampleHtml}
            </div>
            <div class="mapping-footer">
                <div style="font-size:12px;color:#999;">检测到 ${allColumns.length} 个原始列，已匹配 ${Object.keys(mapping).length} 个标准字段</div>
                <div class="btn-group">
                    <button class="btn" onclick="closeMappingModal()">取消</button>
                    <button class="btn btn-primary" onclick="confirmMappingAndImport()">✅ 确认导入</button>
                </div>
            </div>
        </div>
    </div>
    `;
    
    // 插入到页面
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // 存储当前文件和预览数据供确认时使用
    S.pendingFile = file;
    S.pendingPreview = preview;
}

function closeMappingModal() {
    const overlay = document.getElementById('mappingOverlay');
    if (overlay) overlay.remove();
    S.pendingFile = null;
    S.pendingPreview = null;
    document.getElementById('importResult').innerHTML = '';
}

async function confirmMappingAndImport() {
    if (!S.pendingFile || !S.pendingPreview) return;
    
    // 收集用户选择的映射
    const userMapping = {};
    document.querySelectorAll('.mapping-select').forEach(select => {
        const field = select.dataset.field;
        const value = select.value;
        if (value) {
            userMapping[field] = value;
        }
    });
    
    // 构建导入请求
    const form = new FormData();
    form.append('file', S.pendingFile);
    form.append('project_id', S.pid || '');
    form.append('mapping_override', JSON.stringify(userMapping));
    
    document.getElementById('importResult').innerHTML = `<div class="loading">正在导入数据...</div>`;
    closeMappingModal();
    
    try {
        const data = await api('/api/import', { method: 'POST', body: form });
        if (data.error) {
            document.getElementById('importResult').innerHTML = `<div class="error-box">导入失败: ${data.error}</div>`;
            return;
        }
        document.getElementById('importResult').innerHTML = `
            <div class="success-box">✅ 导入成功！共导入 ${data.rows_imported || 0} 条素材
                <button class="btn btn-sm" onclick="S.overview=null;goTo('dashboard')">查看看板</button>
            </div>`;
        loadProjects();
        loadBatchList();
    } catch (e) {
        document.getElementById('importResult').innerHTML = `<div class="error-box">导入失败: ${e.message}</div>`;
    }
}

function handleDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
}

// ========== 剪辑BD分析 ==========
async function renderTags() {
    const el = document.getElementById('pageContent');
    if (!S.pid) { el.innerHTML = '<div class="empty"><h3>请先选择项目</h3></div>'; return; }
    el.innerHTML = '<div class="loading">加载中...</div>';

    try {
        const [actorData, bdData] = await Promise.all([
            api(`/api/projects/${S.pid}/tag-analysis?tag_type=actor`),
            api(`/api/projects/${S.pid}/tag-analysis?tag_type=bd`)
        ]);

        el.innerHTML = `
        <div class="card-grid">
            <div class="card"><div class="card-title">剪辑分析</div>
            <div class="table-wrap"><table><thead><tr><th>剪辑</th><th>素材数</th><th>消耗</th><th>转化</th><th>转化成本</th><th>点击率</th></tr></thead>
            <tbody>${actorData.map(d => `<tr><td>${d.tag_value || '未分类'}</td><td>${d.material_count}</td><td>${fmtCost(d.total_cost)}</td><td>${fmt(d.total_conversion)}</td><td>${fmt(d.avg_cost)}</td><td>${d.avg_ctr}%</td></tr>`).join('')}</tbody></table></div></div>

            <div class="card"><div class="card-title">BD分析</div>
            <div class="table-wrap"><table><thead><tr><th>BD</th><th>素材数</th><th>消耗</th><th>转化</th><th>转化成本</th><th>点击率</th></tr></thead>
            <tbody>${bdData.map(d => `<tr><td>${d.tag_value || '未分类'}</td><td>${d.material_count}</td><td>${fmtCost(d.total_cost)}</td><td>${fmt(d.total_conversion)}</td><td>${fmt(d.avg_cost)}</td><td>${d.avg_ctr}%</td></tr>`).join('')}</tbody></table></div></div>
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

// ========== 分级规则 ==========
async function renderRules() {
    const el = document.getElementById('pageContent');
    try {
        const rules = await api('/api/grade-rules');
        el.innerHTML = `
        <div class="card">
            <div class="card-title">专业投放分级规则</div>
            <div class="rule-hint">
                <p><strong>新版逻辑：从“消耗分层”升级为“投手动作导向”。</strong></p>
                <ul>
                    <li><span class="gb gb-S">S</span> 可放量：样本充分 + 转化数达标 + CPA ≤ 目标CPA</li>
                    <li><span class="gb gb-A">A</span> 稳定跑：有转化 + CPA ≤ 目标CPA × 1.2，可小幅加预算</li>
                    <li><span class="gb gb-B">B</span> 待优化：有转化但样本/成本未达A，建议改封面、标题、定向或出价</li>
                    <li><span class="gb gb-P">P</span> 潜力：低消耗阶段点击效率好、CPC不高，建议二次测试</li>
                    <li><span class="gb gb-C">C</span> 低效：达到止损线仍无转化，或CPA明显超标</li>
                    <li><span class="gb gb-Q">优</span> 优质标签：样本充分且CPA低于目标/项目中位，可作为复制素材</li>
                    <li><span class="gb gb-BD">劣</span> 劣质标签：消耗充分但无转化或成本严重超标，建议关停</li>
                </ul>
                <p class="muted">目标CPA填0时，系统会自动使用项目内有效转化成本中位数作为动态目标。</p>
            </div>
            <div class="table-wrap"><table>
            <thead><tr><th>规则名</th><th>目标CPA</th><th>样本线</th><th>止损线</th><th>S转化≥</th><th>S CPA</th><th>A CPA</th><th>B CPA</th><th>潜力消耗≤</th><th>默认</th><th>操作</th></tr></thead>
            <tbody>${rules.map(r => `<tr>
                <td>${r.name}</td>
                <td>${Number(r.target_cpa || 0).toFixed(0)}</td>
                <td>${Number(r.min_sample_cost || 0).toFixed(0)}</td>
                <td>${Number(r.stop_loss_cost || 0).toFixed(0)}</td>
                <td>${r.s_conversion_min}</td>
                <td>≤${Number(r.s_cpa_ratio || 1).toFixed(1)}x</td>
                <td>≤${Number(r.a_cpa_ratio || 1.2).toFixed(1)}x</td>
                <td>≤${Number(r.b_cpa_ratio || 1.6).toFixed(1)}x</td>
                <td>${Number(r.potential_cost_max || 0).toFixed(0)}</td>
                <td>${r.is_default ? '✓' : ''}</td>
                <td><button class="btn btn-sm" onclick="useRule(${r.id})">应用到当前项目</button></td>
            </tr>`).join('')}</tbody></table></div>
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

async function useRule(rid) {
    if (!S.pid) return alert('请先选择项目');
    try {
        await api(`/api/projects/${S.pid}/regrade`, { method: 'POST', body: JSON.stringify({ rule_id: rid }) });
        alert('规则已应用，分级已更新');
        S.overview = null;
        render();
    } catch (e) { alert(e.message); }
}

// ========== AI智能诊断 ==========
function toggleSelectAll(checkbox) {
    const checked = checkbox.checked;
    document.querySelectorAll('.ai-check[data-id]').forEach(cb => {
        cb.checked = checked;
    });
    updateSelectCount();
}

function updateSelectCount() {
    const count = document.querySelectorAll('.ai-check[data-id]:checked').length;
    const el = document.getElementById('selectedCount');
    if (el) {
        el.textContent = count > 0 ? `已选 ${count} 条` : '';
    }
    // 如果AI助手弹窗已打开，实时更新上下文
    const overlay = document.getElementById('aiAssistantOverlay');
    if (overlay && !overlay.classList.contains('hidden')) {
        updateAIAssistantContext();
    }
}

async function singleAIDiagnosis(materialId, materialName) {
    if (!S.pid) return alert('请先选择项目');
    await runAIDiagnosis([materialId], [materialName || '素材']);
}

async function batchAIDiagnosis() {
    if (!S.pid) return alert('请先选择项目');
    const checked = document.querySelectorAll('.ai-check[data-id]:checked');
    if (checked.length === 0) {
        alert('请至少选择一条素材');
        return;
    }
    if (checked.length > 20) {
        alert('一次最多诊断20条素材，请减少选择数量');
        return;
    }
    const ids = Array.from(checked).map(cb => parseInt(cb.dataset.id));
    await runAIDiagnosis(ids);
}

async function runAIDiagnosis(materialIds, names) {
    try {
        // 显示加载中
        showAIDiagnosisModal(null, 'loading');
        
        const data = await api(`/api/projects/${S.pid}/ai-diagnosis`, {
            method: 'POST',
            body: JSON.stringify({ material_ids: materialIds })
        });
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        showAIDiagnosisModal(data, 'result');
    } catch (e) {
        alert('AI诊断失败: ' + e.message);
        closeAIDiagnosisModal();
    }
}

function showAIDiagnosisModal(data, mode) {
    closeAIDiagnosisModal();
    // items 必须在 if/else 外部定义，否则 loading 模式下 1158 行 title 引用会报错
    const items = (mode === 'loading') ? [] : (Array.isArray(data) ? data : (data.items || []));

    let bodyHtml = '';
    if (mode === 'loading') {
        bodyHtml = `<div class="loading">🤖 AI正在分析素材数据...</div>`;
    } else {
        const sourceHint = !Array.isArray(data) && data.source === 'local_rules'
            ? '<div class="ai-source-hint">当前使用本地规则诊断；如需大模型结果，请在后端/Serverless 环境变量中配置 AI_API_KEY。</div>'
            : '';
        const warningHint = !Array.isArray(data) && data.warning
            ? `<div class="ai-source-hint warning">${data.warning}</div>`
            : '';
        bodyHtml = sourceHint + warningHint + items.map(item => {
            const diagPoints = item.diagnosis.map(d => `
                <div class="ai-diag-point ${d.type}">
                    <span class="tag">${d.tag}</span>
                    ${d.text}
                </div>
            `).join('');
            
            return `
            <div class="ai-diag-item">
                <div class="ai-diag-title">
                    ${copyButtonHtml(item.material_name || '')}
                    ${escapeHtml(item.material_name || '未命名素材')}
                </div>
                <div class="ai-diag-list">${diagPoints}</div>
            </div>`;
        }).join('');
    }
    
    const title = mode === 'loading' ? '🤖 AI智能诊断' : `🤖 AI诊断结果 (${items.length}条素材)`;
    
    const modalHtml = `
    <div class="ai-modal-overlay" id="aiDiagnosisOverlay">
        <div class="ai-modal">
            <div class="ai-modal-header">
                <h3>${title}</h3>
                <button class="close-btn" onclick="closeAIDiagnosisModal()">&times;</button>
            </div>
            <div class="ai-modal-body">
                ${bodyHtml}
            </div>
            <div class="ai-modal-footer">
                <button class="btn" onclick="closeAIDiagnosisModal()">关闭</button>
            </div>
        </div>
    </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    loadAIChatHistory(ids.length);
    document.getElementById('aiChatInput')?.focus();
}

function closeAIDiagnosisModal() {
    const overlay = document.getElementById('aiDiagnosisOverlay');
    if (overlay) overlay.remove();
}

// ========== DeepSeek AI 深度分析 ==========

async function openAIChat(options = {}) {
    if (!S.pid) return alert('请先选择项目');
    const checked = document.querySelectorAll('.ai-check[data-id]:checked');
    let ids = Array.from(checked).map(cb => parseInt(cb.dataset.id));
    const isGlobal = !!options.global;

    if (ids.length === 0 && isGlobal) {
        if (!S.materials || S.materials.length === 0) {
            try {
                const data = await api(`/api/projects/${S.pid}/materials?limit=20`);
                S.materials = data.items || [];
            } catch (e) {
                console.warn('加载素材上下文失败', e);
            }
        }
        ids = (S.materials || []).slice(0, 20).map(m => m.id).filter(Boolean);
    }
    if (ids.length === 0) {
        alert(isGlobal ? '当前项目还没有可分析的素材，请先导入素材数据' : '请至少选择一条素材');
        return;
    }
    if (ids.length > 20) {
        alert('一次最多分析20条素材，请减少选择数量');
        return;
    }

    closeAIChatModal();

    const modalHtml = `
    <div class="ai-modal-overlay" id="aiChatOverlay">
        <div class="ai-modal ai-chat-modal">
            <div class="ai-modal-header">
                <h3>✨ AI投放助手 (${ids.length}条素材)</h3>
                <div class="ai-chat-header-actions">
                    <button class="btn btn-sm" onclick="clearAIChatHistory()">清空记录</button>
                    <button class="close-btn" onclick="closeAIChatModal()">&times;</button>
                </div>
            </div>
            <div class="ai-modal-body">
                <div class="ai-context-hint">${checked.length ? `正在分析你选中的 ${ids.length} 条素材` : `当前未勾选素材，默认分析当前项目最近 ${ids.length} 条素材`}</div>
                <div class="ai-chat-suggestions">
                    <button class="suggestion-chip" onclick="document.getElementById('aiChatInput').value=this.textContent">分析这些素材的整体表现，哪些值得继续放量？</button>
                    <button class="suggestion-chip" onclick="document.getElementById('aiChatInput').value=this.textContent">哪些素材的转化成本偏高，可能的原因是什么？</button>
                    <button class="suggestion-chip" onclick="document.getElementById('aiChatInput').value=this.textContent">给我素材优化的具体建议</button>
                    <button class="suggestion-chip" onclick="document.getElementById('aiChatInput').value=this.textContent">分析点击率和转化率的关系，找出问题素材</button>
                </div>
                <div class="ai-chat-history-title">
                    <span>历史聊天记录</span>
                    <small id="aiChatHistoryStatus">加载中...</small>
                </div>
                <div class="ai-chat-result ai-chat-messages" id="aiChatResult"></div>
            </div>
            <div class="ai-modal-footer ai-chat-input-bar">
                <input type="text" id="aiChatInput" class="ai-chat-input" placeholder="输入你的分析问题..." onkeydown="if(event.key==='Enter')sendAIChat()">
                <button class="btn btn-deepseek" id="aiChatSendBtn" onclick="sendAIChat(${JSON.stringify(ids)})">发送</button>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    loadAIChatHistory(ids.length);
    document.getElementById('aiChatInput')?.focus();
}

function closeAIChatModal() {
    const overlay = document.getElementById('aiChatOverlay');
    if (overlay) overlay.remove();
}

async function sendAIChat(materialIds) {
    const input = document.getElementById('aiChatInput');
    const question = (input?.value || '').trim();
    if (!question) return alert('请输入问题');

    const ids = materialIds || (() => {
        const checked = document.querySelectorAll('.ai-check[data-id]:checked');
        return Array.from(checked).map(cb => parseInt(cb.dataset.id));
    })();

    if (!ids.length) return alert('请至少选择一条素材');

    const resultDiv = document.getElementById('aiChatResult');
    const sendBtn = document.getElementById('aiChatSendBtn');

    appendAIChatMessage('user', question);
    saveAIChatMessage('user', question);
    input.value = '';
    const loadingId = appendAIChatMessage('assistant', '<div class="spinner small"></div>正在分析，请稍候...', true);
    if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = '发送中...'; }

    try {
        const data = await api(`/api/projects/${S.pid}/ai-chat`, {
            method: 'POST',
            body: JSON.stringify({ material_ids: ids, question: question })
        });

        if (data.error) {
            throw new Error(data.error);
        }

        updateAIChatMessage(loadingId, formatAIReply(data.reply));
        saveAIChatMessage('assistant', data.reply);
    } catch (e) {
        const errText = `❌ ${e.message}`;
        updateAIChatMessage(loadingId, `<div class="ai-chat-error">${escapeHtml(errText)}</div>`);
        saveAIChatMessage('assistant', errText);
    } finally {
        if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = '发送'; }
        resultDiv.scrollTop = resultDiv.scrollHeight;
    }
}

function getAIChatHistoryKey() {
    return `material_ai_chat_history_${S.pid || 'default'}`;
}

function getAIChatHistory() {
    try {
        return JSON.parse(localStorage.getItem(getAIChatHistoryKey()) || '[]');
    } catch (e) {
        return [];
    }
}

function saveAIChatMessage(role, content) {
    const history = getAIChatHistory();
    history.push({ role, content, time: Date.now() });
    const saved = history.slice(-60);
    localStorage.setItem(getAIChatHistoryKey(), JSON.stringify(saved));
    const status = document.getElementById('aiChatHistoryStatus');
    if (status) status.textContent = `已保存 ${saved.length} 条`;
}

function loadAIChatHistory(materialCount) {
    const history = getAIChatHistory();
    const status = document.getElementById('aiChatHistoryStatus');
    if (!history.length) {
        if (status) status.textContent = '暂无历史记录';
        appendAIChatMessage('assistant', `暂无历史记录。已读取你选中的 ${materialCount} 条素材，你可以像聊天一样问我：哪些素材值得放量、哪里成本偏高、下一步怎么优化。`);
        return;
    }
    if (status) status.textContent = `已保存 ${history.length} 条`;
    history.forEach(msg => {
        if (msg.role === 'assistant' && !String(msg.content || '').startsWith('❌')) {
            appendAIChatMessage(msg.role, formatAIReply(msg.content), true);
        } else {
            appendAIChatMessage(msg.role, msg.content);
        }
    });
}

function clearAIChatHistory() {
    if (!confirm('确定清空当前项目的 AI 聊天记录吗？')) return;
    localStorage.removeItem(getAIChatHistoryKey());
    const resultDiv = document.getElementById('aiChatResult');
    if (resultDiv) resultDiv.innerHTML = '';
    const status = document.getElementById('aiChatHistoryStatus');
    if (status) status.textContent = '暂无历史记录';
    appendAIChatMessage('assistant', '聊天记录已清空。你可以重新提问，我会继续基于当前选中的素材进行分析。');
}

function appendAIChatMessage(role, content, isHtml = false) {
    const resultDiv = document.getElementById('aiChatResult');
    if (!resultDiv) return '';
    const id = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const avatar = role === 'user' ? '我' : 'AI';
    const safeContent = isHtml ? content : escapeHtml(content).replace(/\n/g, '<br>');
    resultDiv.insertAdjacentHTML('beforeend', `
        <div class="ai-chat-message ${role}" id="${id}">
            <div class="ai-chat-avatar">${avatar}</div>
            <div class="ai-chat-bubble">${safeContent}</div>
        </div>
    `);
    resultDiv.scrollTop = resultDiv.scrollHeight;
    return id;
}

function updateAIChatMessage(id, html) {
    const msg = document.getElementById(id);
    const bubble = msg ? msg.querySelector('.ai-chat-bubble') : null;
    if (bubble) bubble.innerHTML = html;
}

function formatAIReply(text) {
    if (!text) return '';
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    html = html
        .replace(/^### (.+)$/gm, '<h4 class="ai-reply-h">$1</h4>')
        .replace(/^## (.+)$/gm, '<h4 class="ai-reply-h">$1</h4>')
        .replace(/^# (.+)$/gm, '<h4 class="ai-reply-h">$1</h4>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/^\d+\.\s/gm, '<br>$&')
        .replace(/\n/g, '<br>');
    return html;
}

// ========== 全局AI助手 ==========

const AI_PAGE_SUGGESTIONS = {
    import: {
        label: '数据导入',
        icon: '📥',
        suggestions: [
            '检查这批导入数据有没有异常',
            '哪些字段缺失会影响分析？',
            '帮我识别重复素材和异常值',
            '生成一份导入校验报告',
            '导入失败怎么快速排查？'
        ]
    },
    dashboard: {
        label: '经营概览',
        icon: '📊',
        suggestions: [
            '今天盘面最大问题是什么？',
            '哪些指标正在拖累转化？',
            '给我3条优先优化动作',
            '生成老板能看懂的复盘总结',
            '哪些素材应该放量或止损？'
        ]
    },
    analysis: {
        label: '素材诊断',
        icon: '📈',
        suggestions: [
            '找出高消耗无转化素材',
            '列出可复制放量素材',
            '生成停投建议清单',
            '分析低CTR素材共性',
            '按当前筛选给我优化动作'
        ],
        checked_suggestions: [
            '分析这{n}条素材的共性特征',
            '这{n}条里哪些值得复制放量？',
            '这{n}条素材的CPA风险排序',
            '给这{n}条素材生成处理动作',
            '这{n}条素材哪些应该降预算或停投？'
        ]
    },
    recommend: {
        label: '推荐上新',
        icon: '🆕',
        suggestions: [
            '解释这批推荐上新的理由',
            '生成明日上新计划',
            '整理可复用素材方向',
            '列出推荐素材的风险点',
            '把上新建议整理成执行清单'
        ]
    },
    tags: {
        label: '剪辑BD分析',
        icon: '👥',
        suggestions: [
            '哪个剪辑最值得加量？',
            '哪个BD素材转化质量最好？',
            '找出高效剪辑BD组合',
            '给剪辑团队优化建议',
            '生成BD团队复盘口径'
        ]
    },
    rules: {
        label: '分级规则',
        icon: '⚙️',
        suggestions: [
            '当前分级规则怎么理解？',
            'S/A/B/C分别该怎么处理？',
            '潜力素材应该如何测试？',
            '优质和劣质的判定依据是什么？',
            '规则调整后会影响哪些动作？'
        ]
    }
};

function openGlobalAIAssistant() {
    const overlay = document.getElementById('aiAssistantOverlay');
    const fab = document.getElementById('aiAssistantFAB');
    if (overlay) {
        overlay.classList.remove('hidden');
    }
    fab?.classList.add('hidden');
    updateAIAssistantContext();
    // 加载历史聊天记录
    renderAIChatHistory();
    setTimeout(() => document.getElementById('aiAssistantInput')?.focus(), 80);
}

function closeGlobalAIAssistant() {
    const overlay = document.getElementById('aiAssistantOverlay');
    const fab = document.getElementById('aiAssistantFAB');
    if (overlay) {
        overlay.classList.add('hidden');
    }
    fab?.classList.remove('hidden');
}

function updateAIAssistantContext() {
    const pageConfig = AI_PAGE_SUGGESTIONS[S.page] || AI_PAGE_SUGGESTIONS.dashboard;
    const pageTag = document.getElementById('aiContextPage');
    const projectTag = document.getElementById('aiContextProject');
    const selectedTag = document.getElementById('aiContextSelected');
    const suggestionsEl = document.getElementById('aiAssistantSuggestions');
    const statusEl = document.getElementById('aiAssistantStatus');

    if (pageTag) {
        pageTag.textContent = `${pageConfig.icon} ${pageConfig.label}`;
    }

    if (projectTag) {
        const proj = S.projects.find(p => p.id === S.pid);
        projectTag.textContent = proj ? `📁 ${proj.name}` : '未选项目';
        projectTag.style.display = S.pid ? '' : 'none';
    }

    // 检测已选素材
    let checkedCount = 0;
    let activeSuggestions = pageConfig.suggestions;
    if (S.page === 'analysis') {
        const checked = document.querySelectorAll('.ai-check[data-id]:checked');
        checkedCount = checked.length;
        if (checkedCount > 0 && pageConfig.checked_suggestions) {
            activeSuggestions = pageConfig.checked_suggestions.map(s => s.replace(/\{n\}/g, checkedCount));
        }
    }

    // 显示/隐藏已选素材标签
    if (selectedTag) {
        if (checkedCount > 0) {
            selectedTag.textContent = `✅ 已选 ${checkedCount} 条素材`;
            selectedTag.style.display = '';
        } else {
            selectedTag.style.display = 'none';
        }
    }

    // 渲染快捷建议
    if (suggestionsEl) {
        suggestionsEl.innerHTML = activeSuggestions.map(s =>
            `<button class="ai-suggestion-chip" onclick="sendGlobalAIQuestion('${s.replace(/'/g, "\\'")}')">${s}</button>`
        ).join('');
    }

    // 更新状态文案
    if (statusEl) {
        if (!S.pid) {
            statusEl.textContent = '请先选择项目';
        } else if (checkedCount > 0) {
            statusEl.textContent = `基于${checkedCount}条已选素材分析`;
        } else {
            statusEl.textContent = `基于${pageConfig.label}分析`;
        }
    }
}

async function sendGlobalAIQuestion(question) {
    const input = document.getElementById('aiAssistantInput');
    const q = (question || (input?.value || '')).trim();
    if (!q) return;

    if (input) input.value = '';

    // 获取选中的素材ID（仅在素材分析页）
    let materialIds = [];
    if (S.page === 'analysis') {
        const checked = document.querySelectorAll('.ai-check[data-id]:checked');
        materialIds = Array.from(checked).map(cb => parseInt(cb.dataset.id));
    }

    // 添加用户消息
    appendGlobalAIMessage('user', q);

    // 显示加载状态
    const loadingId = appendGlobalAIMessage('assistant', '<div class="spinner small"></div>正在分析，请稍候...', true);
    const sendBtn = document.getElementById('aiAssistantSendBtn');
    if (sendBtn) { sendBtn.disabled = true; }

    try {
        const data = await api(`/api/projects/${S.pid || 0}/ai-chat-general`, {
            method: 'POST',
            body: JSON.stringify({
                question: q,
                page_context: S.page,
                material_ids: materialIds
            })
        });

        if (data.error) {
            throw new Error(data.error);
        }

        updateGlobalAIMessage(loadingId, formatAIReply(data.reply));

        // 保存到历史记录
        const history = loadAIChatHistory();
        history.push({ role: 'user', content: q, timestamp: Date.now() });
        history.push({ role: 'assistant', content: data.reply, timestamp: Date.now(), model: data.model });
        saveAIChatHistory(history);

    } catch (e) {
        const errText = `❌ ${e.message}`;
        updateGlobalAIMessage(loadingId, `<div class="ai-chat-error">${escapeHtml(errText)}</div>`);

        // 即使出错也保存用户的问题
        const history = loadAIChatHistory();
        history.push({ role: 'user', content: q, timestamp: Date.now() });
        history.push({ role: 'assistant', content: `❌ ${e.message}`, timestamp: Date.now(), model: 'error' });
        saveAIChatHistory(history);
    } finally {
        if (sendBtn) { sendBtn.disabled = false; }
        const messagesEl = document.getElementById('aiAssistantMessages');
        if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
    }
}

function appendGlobalAIMessage(role, content, isHtml = false) {
    const messagesEl = document.getElementById('aiAssistantMessages');
    if (!messagesEl) return '';

    // 隐藏欢迎消息
    const welcomeMsg = messagesEl.querySelector('.ai-welcome-message');
    if (welcomeMsg) welcomeMsg.style.display = 'none';

    const id = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const avatar = role === 'user' ? '👤' : '🤖';
    const safeContent = isHtml ? content : escapeHtml(content).replace(/\n/g, '<br>');

    messagesEl.insertAdjacentHTML('beforeend', `
        <div class="ai-chat-message ${role}" id="${id}">
            <div class="ai-chat-avatar">${avatar}</div>
            <div class="ai-chat-bubble">${safeContent}</div>
        </div>
    `);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return id;
}

function updateGlobalAIMessage(id, html) {
    const msg = document.getElementById(id);
    const bubble = msg ? msg.querySelector('.ai-chat-bubble') : null;
    if (bubble) bubble.innerHTML = html;
}

// ========== 历史聊天记录 ==========
const AI_HISTORY_MAX = 50;

function getAIChatHistoryKey() {
    const pid = S.pid || 'global';
    return `ai_chat_history_${pid}`;
}

function loadAIChatHistory() {
    try {
        const key = getAIChatHistoryKey();
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : [];
    } catch (e) {
        console.error('加载历史记录失败:', e);
        return [];
    }
}

function saveAIChatHistory(history) {
    try {
        const key = getAIChatHistoryKey();
        // 限制最多保留50条
        if (history.length > AI_HISTORY_MAX) {
            history = history.slice(history.length - AI_HISTORY_MAX);
        }
        localStorage.setItem(key, JSON.stringify(history));
    } catch (e) {
        console.error('保存历史记录失败:', e);
    }
}

function clearAIChatHistory() {
    const key = getAIChatHistoryKey();
    const count = loadAIChatHistory().length;
    if (count === 0) {
        alert('当前项目暂无聊天记录');
        return;
    }
    if (!confirm(`确定要清空当前项目的 ${count} 条聊天记录吗？\n此操作不可恢复。`)) {
        return;
    }
    localStorage.removeItem(key);
    // 清空消息区域，重新显示欢迎语
    const messagesEl = document.getElementById('aiAssistantMessages');
    if (messagesEl) {
        messagesEl.innerHTML = `
            <div class="ai-welcome-message">
                <div class="ai-welcome-avatar">🤖</div>
                <div class="ai-welcome-text">
                    <p>你好！我是AI素材助手。</p>
                    <p>我可以根据你当前所在的页面，提供针对性的分析建议。</p>
                    <p>试试上方的问题，或直接输入你想了解的内容。</p>
                </div>
            </div>
        `;
    }
    // 显示提示
    const hint = document.createElement('div');
    hint.className = 'ai-assistant-message assistant';
    hint.innerHTML = `
        <div class="ai-chat-avatar">🤖</div>
        <div class="ai-chat-bubble" style="background:#f6ffed;color:#52c41a;font-size:12px;">
            ✅ 聊天记录已清空
        </div>
    `;
    messagesEl?.appendChild(hint);
    messagesEl && (messagesEl.scrollTop = messagesEl.scrollHeight);
}

function renderAIChatHistory() {
    const history = loadAIChatHistory();
    const messagesEl = document.getElementById('aiAssistantMessages');
    if (!messagesEl) return;

    // 清空并重新渲染
    messagesEl.innerHTML = '';

    if (history.length === 0) {
        // 没有历史记录，显示欢迎语
        messagesEl.innerHTML = `
            <div class="ai-welcome-message">
                <div class="ai-welcome-avatar">🤖</div>
                <div class="ai-welcome-text">
                    <p>你好！我是AI素材助手。</p>
                    <p>我可以根据你当前所在的页面，提供针对性的分析建议。</p>
                    <p>试试上方的问题，或直接输入你想了解的内容。</p>
                </div>
            </div>
        `;
        return;
    }

    // 渲染历史记录
    history.forEach(record => {
        const avatar = record.role === 'user' ? '👤' : '🤖';
        const roleClass = record.role;
        const content = record.role === 'assistant' 
            ? formatAIReply(record.content)
            : escapeHtml(record.content).replace(/\n/g, '<br>');
        
        messagesEl.insertAdjacentHTML('beforeend', `
            <div class="ai-chat-message ${roleClass}">
                <div class="ai-chat-avatar">${avatar}</div>
                <div class="ai-chat-bubble">${content}</div>
            </div>
        `);
    });

    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendGlobalAIMessage(role, content, isHtml = false) {
    const messagesEl = document.getElementById('aiAssistantMessages');
    if (!messagesEl) return '';

    // 隐藏欢迎消息
    const welcomeMsg = messagesEl.querySelector('.ai-welcome-message');
    if (welcomeMsg) welcomeMsg.style.display = 'none';

    const id = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const avatar = role === 'user' ? '👤' : '🤖';
    const safeContent = isHtml ? content : escapeHtml(content).replace(/\n/g, '<br>');

    messagesEl.insertAdjacentHTML('beforeend', `
        <div class="ai-chat-message ${role}" id="${id}">
            <div class="ai-chat-avatar">${avatar}</div>
            <div class="ai-chat-bubble">${safeContent}</div>
        </div>
    `);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return id;
}

// Expose AI assistant handlers for inline HTML callbacks and compatibility.
window.openGlobalAIAssistant = openGlobalAIAssistant;
window.closeGlobalAIAssistant = closeGlobalAIAssistant;
window.sendGlobalAIQuestion = sendGlobalAIQuestion;
