/**
 * 记忆管理页面的 JavaScript
 */

let allMemories = [];

// 页面加载时获取记忆
document.addEventListener('DOMContentLoaded', loadMemories);

// 加载所有记忆
async function loadMemories() {
    try {
        const resp = await fetch('/api/memories');
        const data = await resp.json();
        allMemories = data.memories || [];
        document.getElementById('stats').textContent = '共 ' + allMemories.length + ' 条记忆';
        filterAndSort();
    } catch(e) {
        showMsg('err', '加载失败：' + e.message);
    }
}

// 格式化时间
function fmtTime(s) {
    if (!s) return '-';
    return s;
}

// 渲染表格
function renderTable(mems) {
    const tbody = document.getElementById('tbody');
    tbody.innerHTML = mems.map(m => 
        '<tr data-id="' + m.id + '">' +
        '<td class="check-col"><input type="checkbox" class="mem-check" value="' + m.id + '"></td>' +
        '<td class="id-col">' + m.id + '</td>' +
        '<td class="content-cell"><textarea class="content-input" id="c_' + m.id + '">' + escHtml(m.content) + '</textarea></td>' +
        '<td><input type="number" class="importance-input" id="i_' + m.id + '" value="' + m.importance + '" min="1" max="10"></td>' +
        '<td class="source-col">' + (m.source_session || '-') + '</td>' +
        '<td class="time-col">' + fmtTime(m.created_at) + '</td>' +
        '<td class="actions">' +
            '<button class="btn-green" onclick="saveMem(' + m.id + ')">保存</button>' +
            '<button class="btn-red" onclick="delMem(' + m.id + ')">删除</button>' +
        '</td>' +
        '</tr>'
    ).join('');
}

// HTML 转义
function escHtml(s) {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// 筛选和排序
function filterAndSort() {
    const q = document.getElementById('searchBox').value.trim().toLowerCase();
    const sort = document.getElementById('sortSelect').value;
    const dateVal = document.getElementById('dateFilter').value;
    
    let mems = allMemories;
    
    // 关键词筛选
    if (q) {
        mems = mems.filter(m => m.content.toLowerCase().includes(q));
    }
    
    // 日期筛选
    if (dateVal) {
        mems = mems.filter(m => m.created_at && fmtTime(m.created_at).slice(0, 10) === dateVal);
    }
    
    // 排序
    mems = [...mems].sort((a, b) => {
        if (sort === 'id-desc') return b.id - a.id;
        if (sort === 'id-asc') return a.id - b.id;
        if (sort === 'imp-desc') return b.importance - a.importance || b.id - a.id;
        if (sort === 'imp-asc') return a.importance - b.importance || a.id - b.id;
        return 0;
    });
    
    renderTable(mems);
    
    // 更新统计
    const parts = [];
    if (q || dateVal) {
        parts.push('筛选到 ' + mems.length + ' / ' + allMemories.length + ' 条');
        if (dateVal) parts.push('日期: ' + dateVal);
    } else {
        parts.push('共 ' + allMemories.length + ' 条记忆');
    }
    document.getElementById('stats').textContent = parts.join('  ');
}

// 清除日期筛选
function clearDateFilter() {
    document.getElementById('dateFilter').value = '';
    filterAndSort();
}

// 保存单条记忆
async function saveMem(id) {
    const content = document.getElementById('c_' + id).value;
    const importance = parseInt(document.getElementById('i_' + id).value);
    
    try {
        const resp = await fetch('/api/memories/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content, importance})
        });
        const data = await resp.json();
        if (data.error) {
            showMsg('err', '❌ ' + data.error);
        } else {
            showMsg('ok', '✅ 已保存 #' + id);
            loadMemories();
        }
    } catch(e) {
        showMsg('err', '❌ ' + e.message);
    }
}

// 删除单条记忆
async function delMem(id) {
    if (!confirm('确定删除 #' + id + '？此操作不可撤销。')) return;
    
    try {
        const resp = await fetch('/api/memories/' + id, { method: 'DELETE' });
        const data = await resp.json();
        if (data.error) {
            showMsg('err', '❌ ' + data.error);
        } else {
            showMsg('ok', '✅ 已删除 #' + id);
            loadMemories();
        }
    } catch(e) {
        showMsg('err', '❌ ' + e.message);
    }
}

// 批量保存
async function batchSave() {
    const rows = document.querySelectorAll('#tbody tr');
    if (rows.length === 0) {
        showMsg('err', '没有记忆可保存');
        return;
    }
    
    const updates = [];
    rows.forEach(row => {
        const id = parseInt(row.dataset.id);
        const cEl = document.getElementById('c_' + id);
        const iEl = document.getElementById('i_' + id);
        if (cEl && iEl) {
            updates.push({
                id,
                content: cEl.value,
                importance: parseInt(iEl.value)
            });
        }
    });
    
    if (!confirm('确定保存全部 ' + updates.length + ' 条记忆的修改？')) return;
    
    try {
        const resp = await fetch('/api/memories/batch-update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({updates: updates})
        });
        const data = await resp.json();
        if (data.error) {
            showMsg('err', '❌ ' + data.error);
        } else {
            showMsg('ok', '✅ 已保存 ' + data.updated + ' 条');
            loadMemories();
        }
    } catch(e) {
        showMsg('err', '❌ ' + e.message);
    }
}

// 批量删除
async function batchDelete() {
    const checked = [...document.querySelectorAll('.mem-check:checked')].map(c => parseInt(c.value));
    
    if (checked.length === 0) {
        showMsg('err', '请先勾选要删除的记忆');
        return;
    }
    
    if (!confirm('确定删除选中的 ' + checked.length + ' 条记忆？此操作不可撤销。')) return;
    
    try {
        const resp = await fetch('/api/memories/batch-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ids: checked})
        });
        const data = await resp.json();
        if (data.error) {
            showMsg('err', '❌ ' + data.error);
        } else {
            showMsg('ok', '✅ 已删除 ' + data.deleted + ' 条');
            loadMemories();
        }
    } catch(e) {
        showMsg('err', '❌ ' + e.message);
    }
}

// 全选/取消全选
function toggleAll() {
    const val = event.target.checked;
    document.querySelectorAll('.mem-check').forEach(c => c.checked = val);
    document.getElementById('selectAll').checked = val;
    document.getElementById('selectAllHead').checked = val;
}

// 显示消息
function showMsg(cls, text) {
    const el = document.getElementById('msg');
    el.className = 'msg ' + cls;
    el.textContent = text;
    setTimeout(() => {
        el.textContent = '';
        el.className = '';
    }, 4000);
}
