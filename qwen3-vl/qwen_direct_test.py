import requests
import os

def check():
    img = "test.jpg"
    if not os.path.exists(img): return print("🚨 缺图片")

    # 测试 Embedding
    print("📡 测试 8010 Embedding...")
    res1 = requests.post("http://localhost:8010/v1/tower/embed", json={"text": "铁塔", "image_path": os.path.abspath(img)})
    print(res1.json().get("embedding")[:3] if "embedding" in res1.json() else res1.text)

    # 测试 Reranker
    print("\n📡 测试 8011 Reranker...")
    res2 = requests.post("http://localhost:8011/v1/tower/rerank", json={"text": "生锈的铁塔", "image_path": os.path.abspath(img)})
    print(res2.json())

if __name__ == "__main__":
    check()
