import requests
from urllib.parse import quote

def test_search(name, url, method='GET', data=None):
    try:
        print(f"Testing {name}: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        if method == 'GET':
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, data=data, headers=headers, timeout=10)
        
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Success! Response length:", len(resp.text))
            if "斗破" in resp.text:
                print("Found keyword in response!")
            else:
                print("Keyword not found (might be obfuscated or wrong param)")
        elif resp.status_code == 302 or resp.status_code == 301:
             print(f"Redirect to: {resp.headers.get('Location')}")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)

# 1. Cheyil.cc
# Common Jieqi: /modules/article/search.php?searchkey=...
# Or /search.htm?keyword=...
test_search("Cheyil (Common GET)", "https://www.cheyil.cc/search.php?keyword=" + quote("斗破"))
test_search("Cheyil (Jieqi POST)", "https://www.cheyil.cc/modules/article/search.php", 'POST', {'searchkey': '斗破'})

# 2. Quanben.io
test_search("Quanben (GET)", "https://www.quanben.io/index.php?c=book&a=search&keywords=" + quote("斗破"))

# 3. Hetushu.com
test_search("Hetushu (GET)", "https://www.hetushu.com/search.php?keyword=" + quote("斗破"))

# 4. Piaotian.com
test_search("Piaotian (POST)", "https://www.piaotian.com/modules/article/search.php", 'POST', {'searchkey': '斗破'})
