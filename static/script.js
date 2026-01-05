let currentTaskId = null;
let pollInterval = null;

function startDownload() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) {
        alert("请输入有效的网址！");
        return;
    }

    // Reset UI
    document.getElementById('downloadBtn').disabled = true;
    document.querySelector('#downloadBtn .btn-text').textContent = '启动中...';
    document.getElementById('progressArea').classList.remove('hidden');
    document.getElementById('terminalWindow').classList.remove('hidden');
    document.getElementById('downloadActionArea').classList.add('hidden');
    document.getElementById('controlArea').classList.remove('hidden');

    // Clear log
    document.getElementById('logOutput').innerHTML = '';

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

            // Check Status
            if (data.status === 'done') {
                clearInterval(pollInterval);
                finishTask(data.filename);
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

function finishTask(filename) {
    document.querySelector('#downloadBtn .btn-text').textContent = '完成';
    document.getElementById('downloadBtn').style.background = '#10b981';
    document.getElementById('controlArea').classList.add('hidden');

    // Show download link
    const linkArea = document.getElementById('downloadActionArea');
    const linkBtn = document.getElementById('finalDownloadLink');
    linkBtn.href = `/api/download/${filename}`;
    linkArea.classList.remove('hidden');

    updateLog("Task Completed Successfully!");
}

function resetBtn() {
    const btn = document.getElementById('downloadBtn');
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = '立即下载';
    document.getElementById('downloadBtn').style.background = 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)';
}
