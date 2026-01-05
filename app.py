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

app = Flask(__name__)

# Configuration
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Global State
tasks = {}
active_urls = set() # Concurrency control
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

    def log(self, message):
        print(f"[{self.task_id}] {message}")
        if self.task_id in tasks:
            tasks[self.task_id]['log'] = message
        self.log_messages.append(message)

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
            
            if not chapters:
                self.log("未找到章节，请检查链接是否正确。")
                self.cleanup_error()
                return

            book_title = clean_filename(chapters[0].get('book_name', 'Unknown_Novel'))
            filename = f"{book_title}.txt"
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            tasks[self.task_id]['filename'] = filename
            
            total = len(chapters)
            tasks[self.task_id]['total'] = total
            self.log(f"发现 {total} 章 (含自动修补)，准备下载到: {filename}")
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"Book: {book_title}\nSource: {self.start_url}\n\n")

            for i, chapter in enumerate(chapters):
                if not self.check_control():
                    break

                title = chapter['title']
                url = chapter['url']
                is_probe = chapter.get('probe', False)
                
                self.log(f"正在下载 [{i+1}/{total}]: {title}")
                
                # Fetch content
                self.current_chapter_real_title = None
                content = self.get_chapter_content(url)
                
                # Handling Probes or Failures
                if not content.strip():
                    self.log(f"章节无效或为空，跳过: {url}")
                    continue
                
                # Use real title if we found one (especially for probes)
                final_title = self.current_chapter_real_title if self.current_chapter_real_title else title
                
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write(f"{final_title}\n\n")
                    f.write(content)
                    f.write("\n" + "="*30 + "\n\n")
                
                self.update_progress(i + 1, total)
            
            self.log("下载完成！")
            tasks[self.task_id]['status'] = 'done'
            tasks[self.task_id]['percent'] = 100
        
        except Exception as e:
            self.log(f"发生错误: {str(e)}")
            self.cleanup_error()
        finally:
            with active_urls_lock:
                if self.start_url in active_urls:
                    active_urls.remove(self.start_url)

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
        response = self.session.get(self.start_url)
        response.raise_for_status()
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
                resp = self.session.get(current_url, timeout=10)
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

            try:
                for attempt in range(3):
                    try:
                        resp = self.session.get(current_url, timeout=10)
                        if resp.status_code == 200: break
                        if resp.status_code == 404: 
                            self.log(f"页面不存在 (404): {current_url}")
                            return "" # Stop if 404
                    except:
                        time.sleep(1)
                else: 
                    self.log(f"加载超时: {current_url}")
                    return ""

                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Update title if it's the first page
                if current_url == url:
                    h1 = soup.find('h1')
                    if h1:
                        self.current_chapter_real_title = h1.get_text(strip=True)

                content_div = soup.find('div', id='content')
                if content_div:
                    for s in content_div(['script', 'style']):
                        s.decompose()
                    text_buffer += content_div.get_text("\n", strip=True) + "\n"
                
                # Check for same-chapter pagination
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
            except Exception as e:
                self.log(f"Err fetching content: {e}")
                break
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

    # Concurrency Check
    with active_urls_lock:
        if url in active_urls:
             return jsonify({'error': '该小说正在下载中，请勿重复提交！'}), 409
        active_urls.add(url)

    task_id = str(uuid.uuid4())
    
    if CheyilDownloader.match(url):
        downloader = CheyilDownloader(url, task_id)
        downloader.session.headers.update(HEADERS)
    elif QuanbenDownloader.match(url):
        downloader = QuanbenDownloader(url, task_id)
    else:
        downloader = GenericDownloader(url, task_id)

    tasks[task_id] = {
        'status': 'running',
        'control': 'running',
        'percent': 0,
        'current': 0,
        'total': 0,
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
        return send_file(path, as_attachment=True)
    return "File not found", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=3000)
