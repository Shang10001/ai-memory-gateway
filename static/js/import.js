/**
 * 导入记忆页面的 JavaScript
 */

// 切换 Tab
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('panel-' + name).classList.add('active');
    document.getElementById('result').textContent = '';
    document.getElementById('result').className = '';
    document.getElementById('jsonPreview').innerHTML = '';
}

// 文本导入
async function doTextImport() {
    const r = document.getElementById('result');
    const file = document.getElementById('txtFile').files[0];
    const text = document.getElementById('txtInput').value.trim();
    const skip = document.getElementById('skipScore').checked;
    
    let content = '';
    if (file) {
        content = await file.text();
    } else if (text) {
        content = text;
    } else {
        r.className = 'msg err';
        r.textContent = '请先上传文件或输入文本';
        return;
    }
    
    const lines = content.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length === 0) {
        r.className = 'msg err';
        r.textContent = '没有找到有效的记忆条目';
        return;
    }
    
    r.className = 'msg info';
    r.textContent = skip 
        ? '正在导入 ' + lines.length + ' 条记忆...' 
        : '正在为 ' + lines.length + ' 条记忆自动评分，请稍候...';
    
    try {
        const resp = await fetch('/import/text', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lines: lines, skip_scoring: skip})
        });
        const data = await resp.json();
        if (data.error) {
            r.className = 'msg err';
            r.textContent = '❌ ' + data.error;
        } else {
            r.className = 'msg ok';
            r.textContent = '✅ 导入完成！新增 ' + data.imported + ' 条，跳过 ' + data.skipped + ' 条（已存在），总计 ' + data.total + ' 条';
        }
    } catch(e) {
        r.className = 'msg err';
        r.textContent = '❌ 请求失败：' + e.message;
    }
}

// JSON 预览和导入
let pendingJsonData = null;

async function previewJson() {
    const r = document.getElementById('result');
    const p = document.getElementById('jsonPreview');
    const file = document.getElementById('jsonFile').files[0];
    const text = document.getElementById('jsonInput').value.trim();
    
    let jsonStr = '';
    if (file) {
        jsonStr = await file.text();
    } else if (text) {
        jsonStr = text;
    } else {
        r.className = 'msg err';
        r.textContent = '请先上传文件或粘贴 JSON';
        return;
    }
    
    try {
        const parsed = JSON.parse(jsonStr);
        const mems = parsed.memories || [];
        if (mems.length === 0) {
            r.className = 'msg err';
            r.textContent = '❌ 没有找到 memories 字段，请确认这是从 /export/memories 导出的文件';
            p.innerHTML = '';
            return;
        }
        
        pendingJsonData = parsed;
        let html = '<p><b>预览：共 ' + mems.length + ' 条记忆</b></p>';
        const show = mems.slice(0, 10);
        show.forEach(m => {
            html += '<div class="preview-item">权重 ' + (m.importance || '?') + ' | ' + (m.content || '').substring(0, 80) + '</div>';
        });
        if (mems.length > 10) {
            html += '<div class="preview-item" style="color:#999;">...还有 ' + (mems.length - 10) + ' 条</div>';
        }
        html += '<br><button class="btn-green" onclick="confirmJsonImport()">确认导入</button>';
        p.innerHTML = html;
        r.textContent = '';
        r.className = '';
    } catch(e) {
        r.className = 'msg err';
        r.textContent = '❌ JSON 格式错误：' + e.message;
        p.innerHTML = '';
    }
}

async function confirmJsonImport() {
    const r = document.getElementById('result');
    if (!pendingJsonData) {
        r.className = 'msg err';
        r.textContent = '请先预览';
        return;
    }
    
    r.className = 'msg info';
    r.textContent = '导入中...';
    
    try {
        const resp = await fetch('/import/memories', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(pendingJsonData)
        });
        const data = await resp.json();
        if (data.error) {
            r.className = 'msg err';
            r.textContent = '❌ ' + data.error;
        } else {
            r.className = 'msg ok';
            r.textContent = '✅ 导入完成！新增 ' + data.imported + ' 条，跳过 ' + data.skipped + ' 条（已存在），总计 ' + data.total + ' 条';
        }
        document.getElementById('jsonPreview').innerHTML = '';
        pendingJsonData = null;
    } catch(e) {
        r.className = 'msg err';
        r.textContent = '❌ 请求失败：' + e.message;
    }
}
