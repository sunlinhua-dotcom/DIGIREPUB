import requests
from bs4 import BeautifulSoup
import uuid

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cookie': 'BIDUPSID=' + str(uuid.uuid4())
}

def check_baidu():
    print("Checking Baidu...")
    try:
        url = "https://www.baidu.com/s?wd=斗破苍穹 目录"
        resp = requests.get(url, headers=headers, timeout=5)
        if "安全验证" in resp.text:
            print("❌ Baidu: BLOCKED (Security Check)")
        else:
            print(f"✅ Baidu: OK ({len(resp.text)} bytes)")
    except Exception as e:
        print(f"❌ Baidu: Error {e}")

def check_bing():
    print("Checking Bing...")
    try:
        url = "https://www.bing.com/search?q=斗破苍穹 目录"
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"✅ Bing: OK ({len(resp.text)} bytes)")
    except Exception as e:
        print(f"❌ Bing: Error {e}")

def check_sogou():
    print("Checking Sogou...")
    try:
        url = "https://www.sogou.com/web?query=斗破苍穹 目录"
        resp = requests.get(url, headers=headers, timeout=5)
        if "验证码" in resp.text or "antispider" in resp.url:
             print("❌ Sogou: BLOCKED")
        else:
             print(f"✅ Sogou: OK ({len(resp.text)} bytes)")
    except Exception as e:
        print(f"❌ Sogou: Error {e}")

check_baidu()
check_bing()
check_sogou()
