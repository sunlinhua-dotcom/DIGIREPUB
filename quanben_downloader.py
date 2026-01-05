import requests
from bs4 import BeautifulSoup
import time
import os
import re
import random
import json

# Configuration
BASE_URL = "https://www.quanben.io"
BOOK_URL = "https://www.quanben.io/n/zhiyeyisheng-kaijuyigeyiliaoxiugaiqi/list.html"
OUTPUT_FILE = "职业医生_开局一个医疗修改器.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Referer": BOOK_URL
}

def quanben_base64(s, staticchars):
    """
    Reverse engineered base64 encoding function from quanben.io.
    """
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

def get_chapter_list():
    print(f"Fetching main page: {BOOK_URL}...")
    try:
        response = requests.get(BOOK_URL, headers=HEADERS)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # 1. Extract initial chapters
        initial_chapters = []
        for ul in soup.find_all('ul', class_='list3'):
            for link in ul.find_all('a'):
                href = link.get('href')
                title = link.get_text(strip=True)
                if href and title:
                    full_url = BASE_URL + href if href.startswith('/') else href
                    initial_chapters.append({'title': title, 'url': full_url})
        
        print(f"Found {len(initial_chapters)} initial chapters.")

        # 2. Extract needed variables for JSONP request
        staticchars_match = re.search(r'staticchars="([^"]+)"', html)
        if not staticchars_match:
            print("Error: Could not find staticchars in HTML.")
            return initial_chapters 

        staticchars = staticchars_match.group(1)

        callback_match = re.search(r"var callback='([^']+)'", html)
        if not callback_match:
             print("Error: Could not find callback variable.")
             return initial_chapters

        callback = callback_match.group(1)

        book_id_match = re.search(r"load_more\('(\d+)'\)", html)
        if not book_id_match:
             print("Error: Could not find book_id.")
             return initial_chapters
        
        book_id = book_id_match.group(1)

        # 3. Construct JSONP URL
        # The JS logic: call 'base64(callback)'
        # IMPORTANT: The JS uses `parseInt(Math.random()*62,10)` which corresponds to `random.randint(0, 61)` in Python.
        encoded_b = quanben_base64(callback, staticchars)
        
        jsonp_url = f"{BASE_URL}/index.php?c=book&a=list.jsonp&callback={callback}&book_id={book_id}&b={encoded_b}"
        print(f"Fetching hidden chapters from JSONP: {jsonp_url}")
        
        # 4. Fetch JSONP with REFERRED
        # Important: Some sites check Referer for AJAX/JSONP
        time.sleep(1)
        jp_response = requests.get(jsonp_url, headers=HEADERS)
        jp_response.raise_for_status()
        jp_text = jp_response.text

        # Debug: Print first 100 chars of response
        # print(f"JSONP Response prefix: {jp_text[:100]}")

        # 5. Extract JSON content
        # usage: a4bb88({"content":"..."})
        # The response might be: a4bb88({...}) or a4bb88( {...} )
        # Let's be more flexible with regex
        json_match = re.search(r'^\s*[\w]+\s*\((.*)\)\s*;?\s*$', jp_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}. Raw: {json_str[:100]}...")
                return initial_chapters

            content_html = data.get('content', '')
            
            # Parse Hidden Content
            content_soup = BeautifulSoup(content_html, 'html.parser')
            hidden_chapters = []
            for link in content_soup.find_all('a'):
                href = link.get('href')
                title = link.get_text(strip=True)
                if href and title:
                    full_url = BASE_URL + href if href.startswith('/') else href
                    hidden_chapters.append({'title': title, 'url': full_url})
            
            print(f"Found {len(hidden_chapters)} hidden chapters.")
            
            # Combine lists
            all_chapters_map = {}
            for ch in initial_chapters + hidden_chapters:
                all_chapters_map[ch['url']] = ch

            def get_chapter_num(c):
                m = re.search(r'/(\d+)\.html', c['url'])
                return int(m.group(1)) if m else 999999

            sorted_chapters = sorted(all_chapters_map.values(), key=get_chapter_num)
            print(f"Total unique chapters after merging: {len(sorted_chapters)}")
            return sorted_chapters

        else:
            print(f"Error: Could not parse JSONP response structure. Response was: {jp_text[:100]}")
            return initial_chapters

    except Exception as e:
        print(f"Failed to get chapter list: {e}")
        return []

def get_chapter_content(chapter_url):
    """
    Fetches the content of a single chapter, handling internal pagination.
    """
    chapter_text = ""
    current_url = chapter_url
    visited_urls = set()
    
    chapter_num_match = re.search(r'/(\d+)\.html', chapter_url)
    chapter_base_num = chapter_num_match.group(1) if chapter_num_match else None

    while current_url:
        if current_url in visited_urls:
            break
        visited_urls.add(current_url)

        try:
            # time.sleep(0.5) # Polite delay
            response = requests.get(current_url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract content
            content_div = soup.find('div', id='content')
            if content_div:
                text = content_div.get_text("\n", strip=True)
                chapter_text += text + "\n"
            
            # Find Next Page
            # Look for <a> containing "下一页"
            next_link = None
            for a in soup.find_all('a'):
                if "下一页" in a.get_text():
                    next_link = a
                    break
            
            if next_link:
                href = next_link.get('href')
                if href and href != 'javascript:void(0)':
                    full_next_url = BASE_URL + href if href.startswith('/') else href
                    
                    # Logic to determine if "Next Page" is still part of THIS chapter or the NEXT chapter.
                    # Usually split pages are like: 123.html -> 123_2.html
                    # Next chapter is: 124.html
                    # So we check if the base ID matches or if it follows the underscore pattern.
                    
                    if chapter_base_num:
                        # Check if next URL contains the same base number (e.g. "87497/1.html" -> "87497/1_2.html")
                        # Or if proper next chapter is different.
                        # Actually, looking at the pattern, it seems split pages might be `1_2.html`?
                        # Let's inspect the href.
                        if f"{chapter_base_num}_" in full_next_url:
                            current_url = full_next_url
                            continue
                        elif full_next_url.endswith(f"/{chapter_base_num}.html"):
                             # Sometimes next link points to self?
                             current_url = None
                        else:
                            # Likely next chapter
                            current_url = None
                    else:
                        current_url = None
                else:
                    current_url = None
            else:
                current_url = None
                
        except Exception as e:
            print(f"  Error fetching {current_url}: {e}")
            break
            
    return chapter_text

def main():
    chapters = get_chapter_list()
    if not chapters:
        print("No chapters found.")
        return

    print(f"Starting download of {len(chapters)} chapters...")
    
    # Prepare output file
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        for i, chapter in enumerate(chapters):
            title = chapter['title']
            url = chapter['url']
            
            print(f"[{i+1}/{len(chapters)}] Downloading: {title}")
            
            content = get_chapter_content(url)
            
            f.write(f"{title}\n\n")
            f.write(content)
            f.write("\n" + "="*30 + "\n\n")
            
            # Flush periodically
            f.flush()
            
    print(f"\nDownload complete! Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
