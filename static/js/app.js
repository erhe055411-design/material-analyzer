/**
 * 素材经营分析系统 - 前端逻辑 (v3)
 * 适配巨量视频库CSV格式
 */

// ========== 全局状态 ==========
const S = {
    page: 'dashboard',
    pid: null,
    projects: [],
    overview: null,
    _analysisState: null,
    _autoFilter: null
};

// ========== API工具 ==========
async function api(url, opts = {}) {
    opts.headers = { 'Content-Type': 'application/json', ...opts.headers };
    const res = await fetch(url, opts);
    if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `${res.status} ${res.statusText}`);
    }
    return res.json();
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
    // 加载项目列表
    await loadProjects();
    render();
});

function goTo(page) {
    S.page = page;
    document.querySelectorAll('.nav-item').forEach(i => i.classList.toggle('active', i.dataset.page === page));
    render();
}

function render() {
    const fn = { dashboard: renderDashboard, analysis: renderAnalysis, recommend: renderRecommend, import: renderImport, tags: renderTags, rules: renderRules };
    (fn[S.page] || renderDashboard)();
}

// ========== 工具函数 ==========
function fmt(n) {
    if (n == null || isNaN(n)) return '-';
    n = parseFloat(n);
    if (n >= 10000) return (n / 10000).toFixed(1) + '万';
    if (n >= 1000) return n.toFixed(0);
    return n.toFixed(2);
}

function fmtCost(n) {
    if (n == null || isNaN(n)) return '-';
    n = parseFloat(n);
    if (n >= 10000) return (n / 10000).toFixed(2) + '万';
    return n.toFixed(0);
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
    let html = `<span class="gb gb-${g}">${g}</span>`;
    if (potential) html += '<span class="gb gb-P" title="潜力素材">P</span>';
    if (qg) html += '<span class="gb gb-Q" title="优质素材">优</span>';
    if (pg) html += '<span class="gb gb-BD" title="劣质素材">劣</span>';
    return html;
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
    sel.innerHTML = '<option value="">选择项目...</option>' +
        S.projects.map(p => `<option value="${p.id}" ${S.pid === p.id ? 'selected' : ''}>${p.name} (${p.material_count || 0}条)</option>`).join('');
    if (!S.pid && S.projects.length > 0) {
        const withData = S.projects.filter(p => (p.material_count || 0) > 0);
        S.pid = withData.length > 0 ? withData[0].id : S.projects[0].id;
        sel.value = S.pid;
    }
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
        render();
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
        <!-- 核心指标 -->
        <div class="kpi-row">
            <div class="kpi"><div class="kpi-label">总消耗</div><div class="kpi-val">${fmtCost(s.total_cost)}</div></div>
            <div class="kpi"><div class="kpi-label">总转化</div><div class="kpi-val">${fmt(s.total_conversion)}</div></div>
            <div class="kpi"><div class="kpi-label">平均转化成本</div><div class="kpi-val">${fmt(s.avg_conv_cost)}</div></div>
            <div class="kpi"><div class="kpi-label">素材数</div><div class="kpi-val">${s.material_count}</div></div>
            <div class="kpi"><div class="kpi-label">账户数</div><div class="kpi-val">${s.account_count}</div></div>
            <div class="kpi"><div class="kpi-label">均点击率</div><div class="kpi-val">${s.avg_ctr}%</div></div>
        </div>

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
        <div class="chart-row">
            <div class="card chart-card"><div class="card-title">分级分布</div><div id="gradeChart" class="chart-box"></div></div>
            <div class="card chart-card"><div class="card-title">投放目的</div><div id="purposeChart" class="chart-box"></div></div>
            <div class="card chart-card"><div class="card-title">成本区间分布</div><div id="costTierChart" class="chart-box"></div></div>
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
            tooltip: { trigger: 'axis' },
            grid: { left: 50, right: 50, top: 30, bottom: 30 },
            xAxis: { type: 'category', data: grades },
            yAxis: [{ type: 'value', name: '素材数' }, { type: 'value', name: '消耗' }],
            series: [
                { name: '素材数', type: 'bar', data: grades.map(g => map[g]?.count || 0), itemStyle: { color: p => colors[grades[p.dataIndex]] } },
                { name: '消耗', type: 'line', yAxisIndex: 1, data: grades.map(g => parseFloat((map[g]?.cost || 0).toFixed(2))), lineStyle: { color: '#4F6EF7' }, itemStyle: { color: '#4F6EF7' } }
            ]
        });
        chart.on('click', (p) => viewClass('grade', grades[p.dataIndex]));
        window.addEventListener('resize', () => chart.resize());
    }
    // 投放目的图
    const pEl = document.getElementById('purposeChart');
    if (pEl && data.purpose_distribution) {
        const chart = echarts.init(pEl);
        chart.setOption({
            tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
            legend: { orient: 'vertical', right: 10, top: 'center' },
            series: [{ type: 'pie', radius: ['40%', '70%'], center: ['40%', '50%'],
                data: data.purpose_distribution.map(d => ({ name: d.campaign_purpose || '未分类', value: parseFloat((d.total_cost || 0).toFixed(2)) })),
                label: { formatter: '{b}\n{d}%' }
            }]
        });
        chart.on('click', (p) => viewClass('purpose', p.name));
        window.addEventListener('resize', () => chart.resize());
    }
    // 成本区间分布图
    const cEl = document.getElementById('costTierChart');
    if (cEl && data.cost_tier_distribution) {
        const chart = echarts.init(cEl);
        const tierColors = ['#52C41A', '#95DE64', '#FAAD14', '#FF7875', '#FF4D4F', '#8C8C8C'];
        chart.setOption({
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            grid: { left: 50, right: 20, top: 30, bottom: 30 },
            xAxis: { type: 'category', data: data.cost_tier_distribution.map(d => d.tier) },
            yAxis: { type: 'value', name: '素材数' },
            series: [{
                type: 'bar',
                data: data.cost_tier_distribution.map((d, i) => ({
                    value: d.count,
                    itemStyle: { color: tierColors[i % tierColors.length] }
                }))
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
            <button class="ftab ${!st.grade ? 'active' : ''}" data-v="">全部</button>
            <button class="ftab ${st.grade==='S' ? 'active' : ''}" data-v="S"><span class="gb gb-S">S</span>核心</button>
            <button class="ftab ${st.grade==='A' ? 'active' : ''}" data-v="A"><span class="gb gb-A">A</span>稳定</button>
            <button class="ftab ${st.grade==='B' ? 'active' : ''}" data-v="B"><span class="gb gb-B">B</span>待提</button>
            <button class="ftab ${st.grade==='C' ? 'active' : ''}" data-v="C"><span class="gb gb-C">C</span>低效</button>
            <button class="ftab ${st.grade==='potential' ? 'active' : ''}" data-v="potential"><span class="gb gb-P">P</span>潜力</button>
            <button class="ftab ${st.grade==='quality' ? 'active' : ''}" data-v="quality"><span class="gb gb-Q">优</span>优质</button>
            <button class="ftab ${st.grade==='poor' ? 'active' : ''}" data-v="poor"><span class="gb gb-BD">劣</span>劣质</button>
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
        const tbl = document.getElementById('materialsTable');
        if (!tbl) return;

        if (!data.items || data.items.length === 0) {
            tbl.innerHTML = '<div class="empty"><p>当前筛选条件下没有素材</p></div>';
            renderPagination(0, st.page);
            return;
        }

        tbl.innerHTML = `<table><thead><tr>
            <th>分级</th><th>素材名称</th><th>审核状态</th><th>消耗</th><th>展示</th><th>点击</th>
            <th>点击率</th><th>转化数</th><th>转化成本</th><th>状态</th>
        </tr></thead><tbody>${data.items.map(m => `<tr>
            <td>${gradeBadge(m.grade || '-', m.is_potential, m.is_quality_grade, m.is_poor_grade)}</td>
            <td class="td-name" title="${m.material_name || ''}">${m.material_name || '-'}</td>
            <td>${reviewStatusBadge(m.review_status)}</td>
            <td>${fmtCost(m.cost)}</td>
            <td>${fmt(m.show)}</td>
            <td>${fmt(m.click)}</td>
            <td>${m.ctr}%</td>
            <td>${fmt(m.conversion)}</td>
            <td>${fmt(m.conversion_cost)}</td>
            <td>${m.status || '-'}</td>
        </tr>`).join('')}</tbody></table>`;

        renderPagination(data.total, st.page);
    } catch (e) {
        const tbl = document.getElementById('materialsTable');
        if (tbl) tbl.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
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
        el.innerHTML = '<div class="empty"><h3>请先选择项目</h3><p>选择项目后查看推荐上新素材</p></div>';
        return;
    }
    el.innerHTML = '<div class="loading">加载推荐素材中...</div>';

    try {
        const data = await api(`/api/projects/${S.pid}/recommend`);

        el.innerHTML = `
        <div class="recommend-page">
            <div class="recommend-header">
                <h2>🆕 推荐上新素材</h2>
                <p class="recommend-desc">基于投放数据智能筛选，各系列前15条素材</p>
            </div>

            <!-- 增量系列 -->
            <div class="recommend-section" data-expanded="true">
                <div class="recommend-header-bar" onclick="toggleRecommendSection(this)">
                    <div class="recommend-title">
                        <span class="recommend-tag tag-increment">📈 增量系列</span>
                        <span class="recommend-subtitle">优质素材中消耗最高 → 放量主力，增量首选</span>
                        <span class="recommend-count">${(data.increment || []).length} 条</span>
                    </div>
                    <span class="recommend-toggle">▼</span>
                </div>
                <div class="recommend-body">
                    ${renderRecommendTable(data.increment || [], 'increment')}
                </div>
            </div>

            <!-- 稳量系列 -->
            <div class="recommend-section" data-expanded="true">
                <div class="recommend-header-bar" onclick="toggleRecommendSection(this)">
                    <div class="recommend-title">
                        <span class="recommend-tag tag-stable">⚖️ 稳量系列</span>
                        <span class="recommend-subtitle">优质素材中转化成本低且稳定 → 持续产出，ROI最优</span>
                        <span class="recommend-count">${(data.stable || []).length} 条</span>
                    </div>
                    <span class="recommend-toggle">▼</span>
                </div>
                <div class="recommend-body">
                    ${renderRecommendTable(data.stable || [], 'stable')}
                </div>
            </div>

            <!-- 潜力测试系列 -->
            <div class="recommend-section" data-expanded="true">
                <div class="recommend-header-bar" onclick="toggleRecommendSection(this)">
                    <div class="recommend-title">
                        <span class="recommend-tag tag-potential">🧪 潜力测试系列</span>
                        <span class="recommend-subtitle">潜力素材中CTR高且有转化 → 低耗高效，值得放量测试</span>
                        <span class="recommend-count">${(data.potential || []).length} 条</span>
                    </div>
                    <span class="recommend-toggle">▼</span>
                </div>
                <div class="recommend-body">
                    ${renderRecommendTable(data.potential || [], 'potential')}
                </div>
            </div>
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="error-box">加载失败: ${e.message}</div>`;
    }
}

function toggleRecommendSection(header) {
    const section = header.closest('.recommend-section');
    const body = section.querySelector('.recommend-body');
    const toggle = header.querySelector('.recommend-toggle');
    const isExpanded = section.dataset.expanded === 'true';
    
    if (isExpanded) {
        body.style.display = 'none';
        toggle.textContent = '▶';
        section.dataset.expanded = 'false';
    } else {
        body.style.display = '';
        toggle.textContent = '▼';
        section.dataset.expanded = 'true';
    }
}

function renderRecommendTable(items, type) {
    if (!items || items.length === 0) {
        return `<div class="empty" style="padding:30px"><p>暂无推荐素材</p></div>`;
    }

    return `<div class="table-wrap"><table>
        <thead><tr>
            <th>排名</th><th>分级</th><th>素材名称</th><th>审核状态</th><th>消耗</th><th>展示</th><th>点击</th>
            <th>点击率</th><th>转化数</th><th>转化成本</th><th>状态</th>
        </tr></thead>
        <tbody>${items.map((m, idx) => `<tr>
            <td><span class="rank-badge rank-${idx < 3 ? idx + 1 : ''}">${idx + 1}</span></td>
            <td>${gradeBadge(m.grade || '-', m.is_potential, m.is_quality_grade, m.is_poor_grade)}</td>
            <td class="td-name" title="${m.material_name || ''}">${m.material_name || '-'}</td>
            <td>${reviewStatusBadge(m.review_status)}</td>
            <td>${fmtCost(m.cost)}</td>
            <td>${fmt(m.show)}</td>
            <td>${fmt(m.click)}</td>
            <td>${m.ctr}%</td>
            <td>${fmt(m.conversion)}</td>
            <td>${fmt(m.conversion_cost)}</td>
            <td>${m.status || '-'}</td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}

// ========== 数据导入 ==========
async function renderImport() {
    const el = document.getElementById('pageContent');
    if (!S.pid) {
        el.innerHTML = '<div class="empty"><h3>请先选择项目</h3><p>选择项目后再导入数据</p></div>';
        return;
    }

    el.innerHTML = `
    <div class="card">
        <div class="card-title">导入素材数据</div>
        <div class="upload-zone" id="uploadZone" ondragover="event.preventDefault()" ondrop="handleDrop(event)">
            <p>📥 拖拽CSV/Excel文件到此处，或 <a href="javascript:void(0)" onclick="document.getElementById('fileInput').click()">点击上传</a></p>
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
    const form = new FormData();
    form.append('file', file);
    form.append('project_id', S.pid || '');
    try {
        const data = await fetch('/api/import', { method: 'POST', body: form }).then(r => r.json());
        document.getElementById('importResult').innerHTML = `
            <div class="success-box">✅ 导入成功！共导入 ${data.rows_imported || data.count || 0} 条素材
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

// ========== 演员BD分析 ==========
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
            <div class="card"><div class="card-title">演员分析</div>
            <div class="table-wrap"><table><thead><tr><th>演员</th><th>素材数</th><th>消耗</th><th>转化</th><th>转化成本</th><th>点击率</th></tr></thead>
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
            <div class="card-title">分级规则设置</div>
            <div class="rule-hint">
                <p><strong>分级判定逻辑（基于消耗+转化数+转化成本）：</strong></p>
                <ul>
                    <li><span class="gb gb-S">S</span> 消耗占项目前10% + 转化数≥3 → 核心跑量素材</li>
                    <li><span class="gb gb-A">A</span> 消耗占项目前30% + 转化数≥1 → 稳定产出素材</li>
                    <li><span class="gb gb-B">B</span> 有转化但消耗占比不高 → 有待提升</li>
                    <li><span class="gb gb-C">C</span> 低消耗低转化 → 低效素材</li>
                    <li><span class="gb gb-P">P</span> 低消耗但有转化/高CTR/平台优质等信号 → 潜力素材，建议放量测试</li>
                    <li><span class="gb gb-Q">优</span> 消耗>中位数+有转化+成本<中位数 → 优质素材，放量主力</li>
                    <li><span class="gb gb-BD">劣</span> 消耗>中位数+零转化或成本>2倍中位数 → 劣质素材，建议关停</li>
                </ul>
            </div>
            <div class="table-wrap"><table>
            <thead><tr><th>规则名</th><th>S消耗%</th><th>S转化≥</th><th>A消耗%</th><th>A转化≥</th><th>潜力消耗上限</th><th>默认</th><th>操作</th></tr></thead>
            <tbody>${rules.map(r => `<tr>
                <td>${r.name}</td><td>${r.s_cost_pct}</td><td>${r.s_conversion_min}</td>
                <td>${r.a_cost_pct}</td><td>${r.a_conversion_min}</td><td>${r.potential_cost_max}</td>
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
        await api(`/api/grade-rules/${rid}/apply`, { method: 'POST', body: JSON.stringify({ project_id: S.pid }) });
        alert('规则已应用，分级已更新');
        S.overview = null;
        render();
    } catch (e) { alert(e.message); }
}
