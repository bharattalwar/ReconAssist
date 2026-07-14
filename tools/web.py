import os
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()

_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def web_search(query: str, max_results: int = 3):
    """Plain function: search the public web, return a clean list of hits."""
    resp = _client.search(query, max_results=max_results)
    return [
        {"title": r["title"], "url": r["url"], "content": r["content"]}
        for r in resp.get("results", [])
    ]

if __name__ == "__main__":
    hits = web_search("What does GAAP say about recording a bank fee difference?")
    for h in hits:
        print(h["title"], "—", h["url"])