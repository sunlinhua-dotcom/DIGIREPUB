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
            print("Success!")
            # Save snippet to see if it worked
            with open(f"search_result_{name.split()[0]}.html", "w") as f:
                f.write(resp.text[:5000]) # First 5k chars
        else:
             print(f"Failed.")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)

# Hetushu found URL
test_search("Hetushu", "https://www.hetushu.com/book/search.php?wdse=" + quote("斗破"))
