import os
import re
import time
import json
import random
import threading
import uuid
import requests
from flask import Flask, render_template, request, jsonify, send_file, Response
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests.exceptions import SSLError, ReadTimeout, ConnectionError, ChunkedEncodingError

app = Flask(__name__)

@app.route('/api/retry_failed/<task_id>', methods=['POST'])
def retry_failed(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
        
    tdata = tasks[task_id]
    
    # We need access to the downloader instance. 
    # Current limitation: 'downloader' variable in 'start_download' is local.
    # We need to store downloader instance in a global dict to access it for retry.
    if task_id not in downloaders:
        return jsonify({'error': 'Downloader instance lost. Please restart task.'}), 400
        
    downloader = downloaders[task_id]
    
    # Reset status
    tdata['status'] = 'running'
    tdata['log'] = '准备开始补录...'
    
    # Start thread
    thread = threading.Thread(target=downloader.retry_run)
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'ok'})

# Configuration
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Global State
tasks = {}
downloaders = {} # New global to store instances
active_urls = set()
active_urls_lock = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}

# --- Utility Functions ---

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def quanben_base64(s, staticchars):
    encodechars = ""
    for char in s:
        num0 = staticchars.find(char)
        if num0 == -1:
            code = char
        else:
            code = staticchars[(num0 + 3) % 62]
        
        num1 = random.randint(0, 61)
        num2 = random.randint(0, 61)
        encodechars += staticchars[num1] + code + staticchars[num2]
    return encodechars

# --- Universal Downloader Classes ---

class BaseDownloader:
    def __init__(self, start_url, task_id):
        self.start_url = start_url
        self.task_id = task_id
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.domain = urlparse(start_url).netloc
        self.log_messages = []
        self.current_chapter_real_title = None # To store title found during fetch
        self.last_log_msg = None
        self.failed_chapters = [] # Store failed chapters for manual retry

    def log(self, msg):
        # Deduplication Check
        if msg == self.last_log_msg:
            return
        self.last_log_msg = msg
        
        if self.task_id in tasks:
            tasks[self.task_id]['log'] = msg
        print(f"> {msg}")
        self.log_messages.append(msg)

    def get_with_retry(self, url, retries=5):
        """Standardized retry wrapper for ALL requests"""
        for i in range(retries):
            try:
                resp = self.session.get(url, timeout=15) # Increased timeout
                resp.raise_for_status()
                # Basic content check
                if len(resp.content) < 500 and resp.status_code == 200:
                     raise ValueError("Content too short (possible block page)")
                return resp
            except (SSLError, ReadTimeout, ConnectionError, ChunkedEncodingError, ValueError) as e:
                wait_time = (i + 1) * 3  # 3s, 6s, 9s, 12s, 15s
                self.log(f"网络波动 ({str(e)[:50]}...)，{wait_time}秒后重试...")
                time.sleep(wait_time)
            except Exception as e:
                # Other errors, just retry slowly
                time.sleep(5)
        return None

    def update_progress(self, current, total):
        if self.task_id in tasks:
            percent = int(current / total * 100) if total > 0 else 0
            tasks[self.task_id]['percent'] = percent
            tasks[self.task_id]['current'] = current
            tasks[self.task_id]['total'] = total

    def match(url):
        return False

    def get_chapter_list(self):
        raise NotImplementedError

    def get_chapter_content(self, url):
        raise NotImplementedError

    def check_control(self):
        while True:
            task = tasks.get(self.task_id)
            if not task: return False
            if task['control'] == 'paused':
                if task['status'] != 'paused':
                    task['status'] = 'paused'
                    self.log("任务已暂停...")
                time.sleep(1)
            else:
                if task['status'] == 'paused':
                    task['status'] = 'running'
                    self.log("任务继续...")
                return True

    def run(self):
        try:
            self.log(f"开始分析页面: {self.start_url}")
            chapters = self.get_chapter_list()
            
            # File Setup
            book_title = clean_filename(chapters[0].get('book_name', 'Unknown_Novel'))
            filename = f"{book_title}.txt"
            self.filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            
            # Temp dir for individual chapters (essential for correct order patching)
            self.chapters_dir = os.path.join(DOWNLOAD_FOLDER, self.task_id)
            if not os.path.exists(self.chapters_dir):
                os.makedirs(self.chapters_dir)

            tasks[self.task_id]['filename'] = filename
            
            total = len(chapters)
            tasks[self.task_id]['total'] = total
            self.log(f"发现 {total} 章 (含自动修补)，准备下载到: {filename}")
            
            # Start Download Loop
            self.download_chapters(chapters)
            
            # Final Assembly
            self.assemble_novel(chapters)
            
            # Final Status Update
            self.log(f"下载任务结束！成功: {tasks[self.task_id]['success']}, 失败: {tasks[self.task_id]['fail']}")
            tasks[self.task_id]['status'] = 'done'
            tasks[self.task_id]['percent'] = 100
            
            # Cleanup temp files? Maybe keep them for a bit or clean on app start.
            # shutil.rmtree(self.chapters_dir) 
        
        except Exception as e:
            self.log(f"发生错误: {str(e)}")
            self.cleanup_error()
        finally:
            with active_urls_lock:
                if self.start_url in active_urls:
                    active_urls.remove(self.start_url)

    def assemble_novel(self, chapters):
        """Combine all individual chapter files into the final TXT in order"""
        self.log("正在合并文件，确保章节顺序...")
        try:
            with open(self.filepath, 'w', encoding='utf-8') as outfile:
                outfile.write(f"Book: {chapters[0].get('book_name', 'Unknown')}\nSource: {self.start_url}\n\n")
                
                for i in range(len(chapters)):
                    chap_path = os.path.join(self.chapters_dir, f"{i:05d}.txt")
                    if os.path.exists(chap_path):
                        with open(chap_path, 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
            self.log("合并完成！")
        except Exception as e:
            self.log(f"合并文件失败: {e}")

    def download_chapters(self, chapters):
        """Separate method to handle the download loop, reusable for retries"""
        total = tasks[self.task_id].get('total', len(chapters)) # Use existing total if available
        
        for i, chapter in enumerate(chapters):
            # Check control - Handle Pause with Assembly
            while True:
                task = tasks.get(self.task_id)
                if not task: break
                
                if task['control'] == 'paused':
                    if task['status'] != 'paused':
                        task['status'] = 'paused'
                        self.log("任务已暂停... (正在生成临时文件)")
                        self.assemble_novel(chapters) 
                        self.log("已暂停。可下载当前进度。")
                    time.sleep(1)
                else:
                    if task['status'] == 'paused':
                        task['status'] = 'running'
                        self.log("任务继续...")
                    break
            
            if not tasks.get(self.task_id): break # Task killed

            title = chapter['title']
            url = chapter['url']
            
            # Check if already downloaded (for retry or resume logic if we implemented persistence)
            chap_path = os.path.join(self.chapters_dir, f"{i:05d}.txt")
            if os.path.exists(chap_path) and not chapter in self.failed_chapters:
                # Already exists and not marked for retry? Skip.
                # But wait, 'download_chapters' is called with full list in 'run', 
                # or partial list in 'retry'.
                # Logic: If running full list, check existence.
                # If content is valid? 
                pass 

            # Only log if we are actually downloading
            if not os.path.exists(chap_path) or chapter in self.failed_chapters:
                 self.log(f"正在处理: {title}")
                 
                 # Fetch content
                 self.current_chapter_real_title = None
                 content = self.get_chapter_content(url)
                 
                 # Anti-bot
                 if not chapter in self.failed_chapters: # Don't sleep as much on manual retry?
                    time.sleep(random.uniform(0.5, 1.5))

                 if content == "404":
                     self.log(f"章节不存在 (404)，已跳过: {title}")
                     continue

                 # Handling Failures
                 if not content.strip():
                     self.log(f"下载失败，加入补录列表: {title}")
                     if chapter not in self.failed_chapters:
                        tasks[self.task_id]['fail'] += 1
                        self.failed_chapters.append(chapter) 
                        tasks[self.task_id]['has_failed'] = True 
                     continue
                 
                 # Success
                 final_title = self.current_chapter_real_title if self.current_chapter_real_title else title
                 
                 # Write to individual file
                 with open(chap_path, 'w', encoding='utf-8') as f:
                     f.write(f"{final_title}\n\n")
                     f.write(content)
                     f.write("\n" + "="*30 + "\n\n")
                 
                 # If it was a retry, remove from failed list logic handled in retry_run
                 if chapter not in self.failed_chapters:
                    tasks[self.task_id]['success'] += 1
                 
                 # Update percentage
                 # Recalculate based on files present? 
                 # Simplify: just increment. 
                 self.update_progress(i + 1, total)

    def retry_run(self):
        """Method to restart downloading only failed chapters"""
        if not self.failed_chapters:
            self.log("没有需要补录的章节。")
            return

        retry_list = self.failed_chapters[:]
        self.failed_chapters = [] 
        tasks[self.task_id]['fail'] = 0 
        tasks[self.task_id]['has_failed'] = False
        
        self.log(f"开始补录 {len(retry_list)} 个章节...")
        
        # We need the full chapter list for assembly ordering!
        # Accessing it via self.get_chapter_list() is expensive/wrong.
        # We should store the full list in self.all_chapters
        if hasattr(self, 'all_chapters'):
             self.download_chapters(retry_list) # This will overwrite specific files
             self.assemble_novel(self.all_chapters) # Re-assemble EVERYTHING
        else:
             self.log("错误：找不到原始章节列表，无法排序合并。")
        
        self.log(f"补录完成！当前失败数: {len(self.failed_chapters)}")
        tasks[self.task_id]['status'] = 'done'

    def cleanup_error(self):
        tasks[self.task_id]['status'] = 'error'
        with active_urls_lock:
            if self.start_url in active_urls:
                active_urls.remove(self.start_url)


class CheyilDownloader(BaseDownloader):
    @staticmethod
    def match(url):
        return 'cheyil.cc' in url

    def get_chapter_list(self):
        response = self.get_with_retry(self.start_url)
        if not response:
             self.log("致命错误：无法访问目录页")
             return []
        
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try Meta OG:TITLE first
        book_title = "Unknown_Book"
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            book_title = meta_title['content']
        elif soup.find('h1'):
            book_title = soup.find('h1').get_text(strip=True)

        chapter_list_div = soup.find('div', class_='chapterlist')
        all_chapters_div = chapter_list_div.find('div', class_='all') if chapter_list_div else None
        target_div = all_chapters_div if all_chapters_div else (chapter_list_div or soup)

        chapters = []
        for link in target_div.find_all('a'):
            href = link.get('href')
            title = link.get_text(strip=True)
            if href and title and ('book' in href or href.endswith('.html')):
                full_url = urljoin(self.start_url, href)
                chapters.append({'title': title, 'url': full_url, 'book_name': book_title})
        return chapters

    def get_chapter_content(self, url):
        text_buffer = ""
        current_url = url
        visited = set()
        
        while current_url:
            if current_url in visited: break
            visited.add(current_url)

            try:
                resp = self.get_with_retry(current_url)
                if not resp:
                    self.log(f"章节获取失败（重试耗尽）: {current_url}")
                    break
                    
                resp.encoding = 'utf-8'
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                content_div = soup.find('div', id='chaptercontent')
                if content_div:
                    for p in content_div.find_all('p'):
                        txt = p.get_text(strip=True)
                        if "本章未完" not in txt and "请点击下一页" not in txt:
                            text_buffer += "    " + txt + "\n\n"
                            
                next_link = soup.find('a', rel='next')
                if next_link:
                    href = next_link.get('href')
                    full_next = urljoin(current_url, href)
                    if not href or href == '#' or 'book' in href and href.endswith('/'):
                        current_url = None
                    elif self.start_url.strip('/') == full_next.strip('/'):
                         current_url = None
                    elif '_' in href and href.split('_')[0] in current_url:
                        current_url = full_next
                    else:
                        current_url = None 
                else:
                    current_url = None
            except Exception as e:
                self.log(f"获取章节内容失败: {e}")
                break
        return text_buffer


class QuanbenDownloader(BaseDownloader):
    @staticmethod
    def match(url):
        return 'quanben.io' in url

    def get_chapter_list(self):
        self.session.headers.update({'Referer': self.start_url})
        response = self.session.get(self.start_url)
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Title
        book_title = "Unknown_Book"
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            book_title = meta_title['content']
        else:
            h1 = soup.find('h1', itemprop="name headline")
            if h1: book_title = h1.get_text(strip=True)

        # 1. Scrape all visible chapters
        chapters_raw = {}
        for ul in soup.find_all('ul', class_='list3'):
            for link in ul.find_all('a'):
                href = link.get('href')
                title = link.get_text(strip=True)
                if href and title:
                    full_url = urljoin(self.start_url, href)
                    chapters_raw[full_url] = {'title': title, 'url': full_url, 'book_name': book_title}

        # 2. JSONP Logic (Keep existing logic to get hidden ones)
        try:
            staticchars_m = re.search(r'staticchars="([^"]+)"', html)
            callback_m = re.search(r"var callback='([^']+)'", html)
            book_id_m = re.search(r"load_more\('(\d+)'\)", html)
            
            if staticchars_m and callback_m and book_id_m:
                staticchars = staticchars_m.group(1)
                callback = callback_m.group(1)
                book_id = book_id_m.group(1)
                encoded_b = quanben_base64(callback, staticchars)
                
                jsonp_url = f"https://www.quanben.io/index.php?c=book&a=list.jsonp&callback={callback}&book_id={book_id}&b={encoded_b}"
                time.sleep(0.5)
                jp_resp = self.session.get(jsonp_url)
                
                json_match = re.search(r'^\s*[\w]+\s*\((.*)\)\s*;?\s*$', jp_resp.text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(1))
                    content_soup = BeautifulSoup(data.get('content', ''), 'html.parser')
                    for link in content_soup.find_all('a'):
                        href = link.get('href')
                        title = link.get_text(strip=True)
                        if href and title:
                            full = urljoin(self.start_url, href)
                            chapters_raw[full] = {'title': title, 'url': full, 'book_name': book_title}
        except Exception as e:
            self.log(f"JSONP部分获取失败 (不影响查漏补缺): {e}")

        # 3. Gap Filling / ID Traversal
        # Parse all IDs found
        known_ids = {}
        min_id = 999999999
        max_id = 0
        
        base_url_pattern = None # Store a sample pattern e.g., https://www.quanben.io/n/bookid/

        for url, ch in chapters_raw.items():
            m = re.search(r'/(\d+)\.html', url)
            if m:
                cid = int(m.group(1))
                known_ids[cid] = ch
                if cid < min_id: min_id = cid
                if cid > max_id: max_id = cid
                if not base_url_pattern:
                    base_url_pattern = url.rsplit('/', 1)[0] + '/'

        if max_id == 0 or not base_url_pattern:
            self.log("无法解析章节ID，仅下载已识别章节。")
            return sorted(chapters_raw.values(), key=lambda x: x['url'])

        self.log(f"ID范围解析: {min_id} - {max_id}. 开始查漏补缺...")
        
        final_list = []
        for i in range(min_id, max_id + 1):
            if i in known_ids:
                final_list.append(known_ids[i])
            else:
                # Missing ID! Construct probe
                probe_url = f"{base_url_pattern}{i}.html"
                final_list.append({
                    'title': f'第 {i} 章 (扫描中...)',
                    'url': probe_url,
                    'book_name': book_title,
                    'probe': True
                })
        
        return final_list

    def get_chapter_content(self, url):
        text_buffer = ""
        current_url = url
        visited = set()
        
        base_match = re.search(r'/(\d+)\.html', url)
        base_id = base_match.group(1) if base_match else None

        while current_url:
            if current_url in visited: break
            visited.add(current_url)

            # Smart Retry with Exponential Backoff
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    resp = self.session.get(current_url, timeout=15)
                    
                    # 404 is normal for gaps, don't retry, just return empty
                    if resp.status_code == 404:
                        return "404" 
                    
                    # Blocked/Rate Limited?
                    if resp.status_code in [403, 429, 500, 502, 503]:
                        wait_time = (attempt + 1) * 5 # 5s, 10s, 15s...
                        self.log(f"服务器繁忙 ({resp.status_code})，等待 {wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue

                    if resp.status_code == 200:
                        # Success? Let's check invalid content
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        content_div = soup.find('div', id='content')
                        
                        if not content_div:
                            # Maybe generic?
                            if len(resp.text) < 500: # Suspiciously short page
                                self.log(f"内容疑似无效，重试中... ({attempt+1}/{max_retries})")
                                time.sleep(2)
                                continue
                            else:
                                # Generic parsing logic could go here, but for Quanben specific:
                                pass
                        break # Valid 200 OK
                except Exception as e:
                    wait_time = (attempt + 1) * 3
                    self.log(f"网络波动 ({e})，{wait_time}秒后重试...")
                    time.sleep(wait_time)
            
            else: # Loop finished without break = Failed all retries
                self.log(f"放弃章节: {current_url} (多次重试失败)")
                return "" # Real Fail

            # ... (Parsing logic remains similar)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            if current_url == url:
                h1 = soup.find('h1')
                if h1: self.current_chapter_real_title = h1.get_text(strip=True)

            content_div = soup.find('div', id='content')
            if content_div:
                for s in content_div(['script', 'style']):
                    s.decompose()
                text_buffer += content_div.get_text("\n", strip=True) + "\n"
            
            # Pagination Logic
            next_page = None
            for a in soup.find_all('a'):
                if "下一页" in a.get_text():
                    next_page = a
                    break
            
            if next_page:
                href = next_page.get('href')
                if href and href != 'javascript:void(0)':
                    full_next = urljoin(current_url, href)
                    if base_id and f"{base_id}_" in full_next:
                            current_url = full_next
                    else:
                            current_url = None
                else:
                        current_url = None
            else:
                current_url = None

        return text_buffer


class GenericDownloader(BaseDownloader):
    @staticmethod
    def match(url):
        return True 

    def get_chapter_list(self):
        resp = self.session.get(self.start_url)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        book_title = "Unknown_Book"
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            book_title = meta_title['content']
        elif soup.title:
            book_title = soup.title.get_text(strip=True).split('_')[0].split('-')[0]
            
        links = soup.find_all('a')
        chapter_candidates = []
        for link in links:
            href = link.get('href')
            txt = link.get_text(strip=True)
            if href and txt and len(txt) > 2:
                if any(char.isdigit() for char in txt):
                    full = urljoin(self.start_url, href)
                    chapter_candidates.append({'title': txt, 'url': full, 'book_name': book_title})
        
        seen = set()
        unique = []
        for c in chapter_candidates:
            if c['url'] not in seen:
                unique.append(c)
                seen.add(c['url'])
                
        if len(unique) > 10:
            return unique
        return []

    def get_chapter_content(self, url):
        try:
            resp = self.session.get(url, timeout=10)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            if url == self.start_url: # Update title check
                 if soup.title: self.current_chapter_real_title = soup.title.get_text(strip=True)

            divs = soup.find_all('div')
            best_div = None
            max_len = 0
            
            for d in divs:
                txt = d.get_text(strip=True)
                if len(txt) > max_len:
                    if d.find('script') or d.find('style'):
                         continue
                    max_len = len(txt)
                    best_div = d
            
            if best_div:
                return best_div.get_text("\n\n", strip=True)
            return ""
        except:
            return ""

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # 2. Concurrency Control & Rejoin Logic
    with active_urls_lock:
        if url in active_urls:
            # Try to find the existing running task for this URL
            for tid, tdata in tasks.items():
                if tdata.get('url') == url and tdata['status'] in ['running', 'paused']:
                    return jsonify({'task_id': tid, 'message': 'Rejoined existing task'})
            
            # If we are here, maybe it's in active_urls but not in running tasks (zombie?), clean it
            active_urls.remove(url)

        active_urls.add(url)

    task_id = str(uuid.uuid4())
    
    # Select Downloader
    if 'quanben.io' in url:
        downloader = QuanbenDownloader(url, task_id)
    elif 'cheyil.cc' in url:
        downloader = CheyilDownloader(url, task_id)
    else:
        downloader = GenericDownloader(url, task_id)

    downloaders[task_id] = downloader   
    
    tasks[task_id] = {
        'url': url,
        'status': 'running',
        'control': 'running',
        'percent': 0,
        'current': 0,
        'total': 0,
        'success': 0,
        'fail': 0,
        'log': 'Task Initialized...',
        'filename': None
    }

    thread = threading.Thread(target=downloader.run)
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id})

@app.route('/api/progress/<task_id>')
def get_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)

@app.route('/api/control/<action>', methods=['POST'])
def control_task(action):
    data = request.json
    task_id = data.get('task_id')
    task = tasks.get(task_id)
    if not task:
         return jsonify({'error': 'Task not found'}), 404
    
    if action == 'pause':
        task['control'] = 'paused'
        return jsonify({'status': 'paused'})
    elif action == 'resume':
        task['control'] = 'running'
        return jsonify({'status': 'resumed'})
    
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/download/<filename>')
def download_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(path):
        # Force octet-stream to prevent browser from previewing text
        return send_file(path, as_attachment=True, mimetype='application/octet-stream')
    return "File not found", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=3000)
