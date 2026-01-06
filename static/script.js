let currentTaskId = null;
let pollInterval = null;

// Global element references (moved from inside startDownload for broader use)
const urlInput = document.getElementById('urlInput');
const downloadBtn = document.getElementById('downloadBtn');
const progressBar = document.getElementById('progressBar');
const percentText = document.getElementById('percentText');
const statusText = document.getElementById('statusText');
const progressStats = document.getElementById('progressStats');
const progressArea = document.getElementById('progressArea');
const terminalWindow = document.getElementById('terminalWindow');
const logOutput = document.getElementById('logOutput');
const pauseBtn = document.getElementById('pauseBtn');
const resumeBtn = document.getElementById('resumeBtn');

function handleInputKey(e) {
    if (e.key === 'Enter') handleMainAction();
}

function handleMainAction() {
    const val = urlInput.value.trim();
    if (!val) return;

    // Detection: Is it a URL?
    if (val.startsWith('http')) {
        startDownload(); // Existing logic
    } else {
        searchNovels(val); // New Search Logic
    }
}

let searchPollInterval = null;

async function searchNovels(keyword) {
    const resultsArea = document.getElementById('searchResults');
    const resultsList = document.getElementById('resultsList');

    resultsArea.classList.remove('hidden');

    // Clear previous results but keep structure
    document.getElementById('searchLogs').innerHTML = '<div>> 初始化全网检索引擎...</div>';
    document.getElementById('resultsList').innerHTML = ''; // Clear list

    try {
        const response = await fetch('/api/search/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword })
        });
        const data = await response.json();

        if (data.task_id) {
            if (searchPollInterval) clearInterval(searchPollInterval);
            searchPollInterval = setInterval(() => pollSearch(data.task_id), 500);
        }
    } catch (e) {
        document.getElementById('searchLogs').innerHTML += `<div style="color: #ef4444">> 启动搜索失败: ${e.message}</div>`;
    }
}

async function pollSearch(taskId) {
    try {
        const response = await fetch(`/api/search/progress/${taskId}`);
        const data = await response.json();

        // Update Logs
        const logsDiv = document.getElementById('searchLogs');
        if (data.logs) {
            logsDiv.innerHTML = data.logs.map(l => {
                let color = '#94a3b8';
                if (l.includes('✅')) color = '#10b981';
                if (l.includes('❌')) color = '#ef4444';
                if (l.includes('⚠️')) color = '#f59e0b';
                return `<div style="color: ${color}; margin-bottom: 2px;">${l}</div>`;
            }).join('');
            logsDiv.scrollTop = logsDiv.scrollHeight;
        }

        // Render Progressive Results
        if (data.results && data.results.length > 0) {
            // DEBUG: Print to logs so user sees it
            // if (data.status !== 'done') logsDiv.innerHTML += `<div style="color: #60a5fa;">[Debug] 收到 ${data.results.length} 条数据...</div>`;
            renderSearchResults(data.results);
        }

        if (data.status === 'done') {
            clearInterval(searchPollInterval);
            // One final render to be safe
            renderSearchResults(data.results);
        }
    } catch (e) {
        // Visible error for user
        const logsDiv = document.getElementById('searchLogs');
        if (logsDiv) {
            logsDiv.innerHTML += `<div style="color: #ef4444; margin-top:4px;">> ⚠️ 连接中断 (任务ID过期)，请重新点击Go搜索</div>`;
            logsDiv.scrollTop = logsDiv.scrollHeight;
        }
        if (searchPollInterval) clearInterval(searchPollInterval);
    }
}

function renderSearchResults(books) {
    // Debug to UI Terminal (Right Panel) so user can see JS is working
    updateLog(`[UI debug] 接收到 ${books ? books.length : 0} 个结果，正在渲染列表...`);

    const container = document.getElementById('resultsList');
    if (!container) {
        console.error("Missing resultsList container");
        return;
    }

    container.classList.remove('hidden');
    container.style.display = 'block'; // Force display
    container.innerHTML = '';

    // Add Counter Header
    if (books && books.length > 0) {
        try {
            const stats = document.createElement('div');
            stats.className = 'results-stats-bar';
            stats.innerHTML = `
                <span>✅ 已找到 ${books.length} 本相关书籍</span>
                <span style="font-size:0.75rem; opacity:0.8">滚动查看 ▼</span>
            `;
            container.appendChild(stats);

            books.forEach((book, index) => {
                try {
                    const div = document.createElement('div');
                    div.className = 'search-result-item';

                    // Special Handling for Captcha/Error items
                    if (book.is_captcha) {
                        div.style.background = 'rgba(239, 68, 68, 0.15)';
                        div.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                        div.innerHTML = `
                             <div style="flex: 1; padding-right: 10px;">
                                <div style="font-weight: bold; color: #fca5a5; font-size: 0.95rem;">${book.title || '验证提示'}</div>
                                <div style="font-size: 0.8rem; color: #fecaca; margin-top: 4px;">${book.snippet || '需要人工验证'}</div>
                            </div>
                            <div style="background: #ef4444; color: #fff; padding: 6px 12px; border-radius: 6px; font-size: 0.85rem; white-space: nowrap;">
                                去验证
                            </div>
                        `;
                        div.onclick = () => window.open(book.url, '_blank');
                        container.appendChild(div);
                        return;
                    }

                    // Metadata badges
                    let metaHtml = `<div style="font-size: 0.8rem; color: #cbd5e1; margin-top: 4px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">`;

                    if (book.author && book.author !== '未知') {
                        metaHtml += `<span style="color: #60a5fa;">👤 ${book.author}</span>`;
                    }

                    metaHtml += `<span style="opacity: 0.5">|</span> <span style="color: #fbbf24;">${book.source || '未知源'}</span>`;

                    if (book.is_completed) {
                        metaHtml += `<span style="background: #10b981; color: white; padding: 1px 5px; border-radius: 3px; font-size: 0.65rem;">完结</span>`;
                    }

                    if (book.latest && book.latest.length > 0 && book.latest !== '未知') {
                        metaHtml += `<span style="opacity: 0.5">|</span> <span style="font-size: 0.75rem; color: #94a3b8; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${book.latest}</span>`;
                    }

                    metaHtml += `</div>`;

                    div.innerHTML = `
                        <div style="flex: 1; overflow: hidden; padding-right: 10px;">
                            <div style="font-weight: bold; font-size: 1rem; color: #fff; margin-bottom: 2px;">${book.title || '无标题'}</div>
                            ${metaHtml}
                        </div>
                        <div style="background: #2563eb; color: #fff; padding: 6px 12px; border-radius: 6px; font-size: 0.85rem; white-space: nowrap; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                            下载
                        </div>
                    `;
                    div.onclick = () => selectBook(book.url);
                    container.appendChild(div);
                } catch (e) {
                    console.error("Error rendering item", index, e);
                }
            });
        } catch (e) {
            console.error("Error in render loop", e);
            container.innerHTML = `<div style="color:red">渲染错误: ${e.message}</div>`;
        }
    } else {
        container.innerHTML = '<div style="text-align: center; padding: 2rem; color: #64748b;">(暂无结果...)</div>';
    }
}

function selectBook(url) {
    urlInput.value = url;
    closeSearch();
    startDownload();
}

function closeSearch() {
    document.getElementById('searchResults').classList.add('hidden');
}

function startDownload() {
    const url = urlInput.value.trim();
    if (!url) {
        alert("请输入有效的网址！");
        return;
    }

    // Reset UI
    downloadBtn.disabled = true;
    document.querySelector('#downloadBtn .btn-text').textContent = '启动中...';
    progressArea.classList.remove('hidden');
    terminalWindow.classList.remove('hidden');
    document.getElementById('downloadActionArea').classList.add('hidden');
    document.getElementById('controlArea').classList.remove('hidden');

    // Clear log
    logOutput.innerHTML = '';

    fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url })
    })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                resetBtn();
            } else {
                currentTaskId = data.task_id;
                pollInterval = setInterval(pollProgress, 1000);
                updateLog("Task started. Initializing downloader...");
            }
        })
        .catch(err => {
            console.error(err);
            alert("Failed to start download.");
            resetBtn();
        });
}

function controlTask(action) {
    if (!currentTaskId) return;

    fetch(`/api/control/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: currentTaskId })
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'paused') {
                document.getElementById('pauseBtn').classList.add('hidden');
                document.getElementById('resumeBtn').classList.remove('hidden');
            } else if (data.status === 'resumed') {
                document.getElementById('resumeBtn').classList.add('hidden');
                document.getElementById('pauseBtn').classList.remove('hidden');
            }
        });
}

function pollProgress() {
    if (!currentTaskId) return;

    fetch(`/api/progress/${currentTaskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                clearInterval(pollInterval);
                // Don't alert, just stop sometimes server restart kills tasks
                resetBtn();
                return;
            }

            // Update Progress
            const percent = data.percent || 0;
            const current = data.current || 0;
            const total = data.total || 0;

            document.getElementById('progressBar').style.width = percent + '%';
            document.getElementById('percentText').textContent = percent + '%';

            if (total > 0) {
                const success = data.success || 0;
                const fail = data.fail || 0;
                document.getElementById('progressStats').innerHTML =
                    `${current} / ${total} <span style="color:#10b981;margin-left:8px">✔${success}</span> <span style="color:#ef4444">✘${fail}</span>`;
            }

            // Update Log - Fix Duplicates Check
            if (data.log) {
                const logBox = document.getElementById('logOutput');
                const newMsg = `> ${data.log}`;
                // Check strictly against the formatted message in the DOM
                if (!logBox.lastElementChild || logBox.lastElementChild.textContent !== newMsg) {
                    updateLog(data.log);
                    document.getElementById('statusText').textContent = data.log.length > 25 ? "下载中..." : data.log;
                }
            }

            // Update Button State
            if (data.control === 'paused') {
                document.getElementById('pauseBtn').classList.add('hidden');
                document.getElementById('resumeBtn').classList.remove('hidden');

                // Show Partial Download Link
                if (data.filename) {
                    const linkArea = document.getElementById('downloadActionArea');
                    const linkBtn = document.getElementById('finalDownloadLink');
                    linkBtn.href = `/api/download/${data.filename}`;
                    linkBtn.querySelector('.btn-text').textContent = '保存当前进度';
                    linkArea.classList.remove('hidden');
                }

            } else {
                document.getElementById('resumeBtn').classList.add('hidden');
                document.getElementById('pauseBtn').classList.remove('hidden');

                // Hide Download Link if running (unless done, which is handled below)
                if (data.status !== 'done') {
                    document.getElementById('downloadActionArea').classList.add('hidden');
                }
            }

            // Show/Hide Retry Button logic
            if (data.has_failed) {
                document.getElementById('retryBtn').classList.remove('hidden');
            } else {
                document.getElementById('retryBtn').classList.add('hidden');
            }

            // Check Status
            if (data.status === 'done') {
                clearInterval(pollInterval);
                finishTask(data.filename, data.has_failed);
            } else if (data.status === 'error') {
                clearInterval(pollInterval);
                document.getElementById('statusText').textContent = "出错";
                document.getElementById('statusText').style.color = "#ef4444";
                document.getElementById('controlArea').classList.add('hidden');
                resetBtn();
            }
        })
        .catch(err => {
            console.error("Polling error", err);
        });
}

function updateLog(msg) {
    const logBox = document.getElementById('logOutput');
    const newMsg = `> ${msg}`;

    // Feature: Consolidate "Scanning" logs to prevent spam
    if (msg.includes('(扫描中...)') && logBox.lastElementChild && logBox.lastElementChild.textContent.includes('(扫描中...)')) {
        logBox.lastElementChild.textContent = newMsg;
        return;
    }

    const div = document.createElement('div');
    div.classList.add('log-line');
    div.textContent = newMsg;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
}

function retryFailed() {
    if (!currentTaskId) return;

    // UI update
    document.getElementById('retryBtn').disabled = true;
    document.querySelector('#retryBtn .btn-text').textContent = '补录中...';
    document.getElementById('downloadActionArea').classList.add('hidden'); // Hide download link during retry
    document.getElementById('controlArea').classList.remove('hidden'); // Show pause/resume

    // Resume polling just in case
    if (!pollInterval) pollInterval = setInterval(pollProgress, 1000);

    fetch(`/api/retry_failed/${currentTaskId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            console.log("Retry started");
        });
}

function finishTask(filename, hasFailed) {
    document.querySelector('#downloadBtn .btn-text').textContent = '完成';
    document.getElementById('downloadBtn').style.background = '#10b981';
    document.getElementById('controlArea').classList.add('hidden');

    // Show download link
    const linkArea = document.getElementById('downloadActionArea');
    const linkBtn = document.getElementById('finalDownloadLink');
    linkBtn.href = `/api/download/${filename}`;
    // Text is already set in HTML, no need to override unless needed
    // linkBtn.querySelector('.btn-text').textContent = '保存 TXT'; 
    linkArea.classList.remove('hidden');

    // Grid layout adjustments
    linkArea.style.display = 'flex';

    if (hasFailed) {
        document.getElementById('retryBtn').disabled = false;
        document.getElementById('retryBtn').classList.remove('hidden');
        document.querySelector('#retryBtn span:last-child').textContent = '补录漏章';
    } else {
        document.getElementById('retryBtn').classList.add('hidden');
    }

    updateLog("Task Completed!");
}

function resetBtn() {
    const btn = document.getElementById('downloadBtn');
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = '立即下载';
    document.getElementById('downloadBtn').style.background = 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)';
}
