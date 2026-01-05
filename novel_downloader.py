import requests
from bs4 import BeautifulSoup
import time
import os

# Configuration
BASE_URL = "https://www.cheyil.cc"
BOOK_URL = "https://www.cheyil.cc/book/1187702/"
OUTPUT_FILE = "重生08_豆包成了我的外挂.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}

def get_chapter_list():
    """Fetches the list of chapters from the main book page."""
    print(f"Fetching chapter list from {BOOK_URL}...")
    try:
        response = requests.get(BOOK_URL, headers=HEADERS)
        response.raise_for_status()
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Select the chapter list container
        # Based on research: <div class="chapterlist mt10"><div class="all"><ul><li><a href="...">...</a></li></ul></div></div>
        chapter_list_div = soup.find('div', class_='chapterlist')
        if not chapter_list_div:
            print("Error: Could not find chapter list container.")
            return []
            
        all_chapters_div = chapter_list_div.find('div', class_='all')
        if not all_chapters_div:
            # Fallback if 'all' div is missing, though structure seemed to have it
            all_chapters_div = chapter_list_div
            
        chapters = []
        for link in all_chapters_div.find_all('a'):
            href = link.get('href')
            title = link.get_text(strip=True)
            if href and title:
                full_url = BASE_URL + href if href.startswith('/') else href
                chapters.append({'title': title, 'url': full_url})
                
        print(f"Found {len(chapters)} chapters.")
        return chapters
    except Exception as e:
        print(f"Failed to get chapter list: {e}")
        return []

def get_chapter_content(chapter_url, next_chapter_start_url=None):
    """
    Fetches the content of a single chapter, handling internal pagination.
    Returns the combined text of the chapter.
    """
    chapter_text = ""
    current_url = chapter_url
    page_count = 0
    
    while current_url:
        page_count += 1
        # print(f"  DEBUG: Fetching page {page_count}: {current_url}")
        try:
            time.sleep(0.5) # Polite delay
            response = requests.get(current_url, headers=HEADERS)
            response.raise_for_status()
            # Auto-detect encoding or force utf-8 if needed. The site meta says utf-8.
            response.encoding = 'utf-8' 
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract content
            content_div = soup.find('div', id='chaptercontent')
            if content_div:
                # Remove any unwanted elements like "本章未完" notices if they are in p tags
                # Inspecting the HTML, '本章未完' might be in a p tag or outside. 
                # We will get all paragraph text.
                paragraphs = content_div.find_all('p')
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    # Simple filter for common pagination noise
                    if "本章未完" in text or "请点击下一页" in text or "没钱又任性提示您" in text:
                        continue
                    chapter_text += "    " + text + "\n\n"
            else:
                print(f"  Warning: No content found at {current_url}")
        
            # Find next page link
            # Structure: <div class="readpage"><a rel="next" href="...">下一页</a></div>
            next_link = soup.find('a', rel='next')
            if next_link:
                href = next_link.get('href')
                next_full_url = BASE_URL + href if href.startswith('/') else href
                
                # Check termination conditions
                # 1. Next link is effectively empty or same page (unlikely but safe to check)
                if not href or href == '#' or href == 'javascript:void(0)':
                   current_url = None
                # 2. Next link goes back to index/cover page (often happens at end of chapter)
                elif "book/1187702/" == href or href.endswith("book/1187702/"): # loose check
                   current_url = None
                # 3. Next link points to the START of the NEXT chapter 
                # (Some sites link 'Next Page' to the next chapter at the end of the current one)
                elif next_chapter_start_url and next_full_url == next_chapter_start_url:
                    current_url = None
                # 4. Heuristic: Usually paginated URLs look like .../123.html, .../123_2.html
                # If we are seemingly jumping to a completely different ID, it might be next chapter
                else:
                    current_url = next_full_url
            else:
                current_url = None
                
        except Exception as e:
            print(f"  Error fetching {current_url}: {e}")
            break
            
    return chapter_text

def main():
    chapters = get_chapter_list()
    if not chapters:
        return

    # Prepare output file
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        total_chapters = len(chapters)
        for i, chapter in enumerate(chapters):
            title = chapter['title']
            url = chapter['url']
            
            print(f"[{i+1}/{total_chapters}] Downloading: {title}")
            
            # Determine the URL of the next chapter to help the pagination logic know when to stop
            next_chapter_url = None
            if i + 1 < len(chapters):
                next_chapter_url = chapters[i+1]['url']
            
            content = get_chapter_content(url, next_chapter_url)
            
            f.write(f"{title}\n\n")
            f.write(content)
            f.write("\n" + "="*20 + "\n\n")
            
    print(f"\nDownload complete! Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
