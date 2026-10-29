#!/usr/bin/env python3
"""말 관련 뉴스 수집 → news/news.json + news/img/*.jpg (작게 압축)
GitHub Actions에서 매일 실행."""
import json, os, re, time, hashlib, io, html, datetime as dt
import urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news", "news.json")
IMG = os.path.join(ROOT, "news", "img")
KEEP_DAYS, MAX_ITEMS, NEW_IMG_LIMIT = 30, 120, 40
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

# (칩 태그, 검색어)
QUERIES = [
    ("장제", "장제사"), ("장제", "장제 편자"), ("장제", "말 발굽"),
    ("마사회", "한국마사회"), ("마사회", "렛츠런파크"),
    ("승마", "승마"), ("경마", "경마"), ("말산업", "말산업"),
]
TAG_WORDS = {
    "장제": ["장제", "편자", "발굽", "제철"],
    "마사회": ["마사회", "렛츠런"],
    "승마": ["승마", "승용마", "재활승마"],
    "경마": ["경마", "경주마", "더러브렛"],
    "말산업": ["말산업", "말 산업", "제주마", "마필"],
}
# 동음이의어 등 잡음 제거
BLOCK = ["말레이", "주말", "연말", "월말", "기말", "결말", "말씀", "종말", "막말", "말기", "말일", "경마장 마약"]

def get(url, timeout=15, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(3_000_000)
        return (data, r.geturl()) if binary else (data.decode(r.headers.get_content_charset() or "utf-8", "ignore"), r.geturl())

def rss(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    xml, _ = get(url)
    root = ET.fromstring(xml)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).astimezone(dt.timezone.utc)
        except Exception:
            ts = dt.datetime.now(dt.timezone.utc)
        yield {"title": html.unescape(title), "src": src, "gurl": it.findtext("link") or "", "ts": ts.isoformat()}

def norm(t): return re.sub(r"[^0-9a-zA-Z가-힣]", "", t)[:40]

def decode(gurl):
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(gurl, interval=0.3)
        if r.get("status") and r.get("decoded_url"): return r["decoded_url"]
    except Exception as e:
        print("decode fail", e)
    return gurl

OG = [r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
      r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
      r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)']

def og_image(url):
    page, final = get(url, timeout=12)
    for p in OG:
        m = re.search(p, page[:300000], re.I)
        if m: return urllib.parse.urljoin(final, html.unescape(m.group(1).strip()))
    return None

def save_thumb(img_url, key):
    from PIL import Image, ImageOps
    data, _ = get(img_url, timeout=15, binary=True)
    im = Image.open(io.BytesIO(data)); im = ImageOps.exif_transpose(im).convert("RGB")
    if im.width < 200 or im.height < 120: return None          # 로고·아이콘 수준은 버림
    im = ImageOps.fit(im, (480, 300), Image.LANCZOS)            # 16:10, 작게
    path = os.path.join(IMG, key + ".jpg")
    im.save(path, "JPEG", quality=62, optimize=True, progressive=True)
    return "news/img/" + key + ".jpg"

def tags_for(title, base):
    t = {k for k, ws in TAG_WORDS.items() if any(w in title for w in ws)}
    return sorted(t or {base})

def main():
    os.makedirs(IMG, exist_ok=True)
    try: old = json.load(open(OUT, encoding="utf-8"))["items"]
    except Exception: old = []
    by = {norm(i["title"]): i for i in old}
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    fresh = []
    for tag, q in QUERIES:
        try:
            for it in rss(q):
                if any(b in it["title"] for b in BLOCK): continue
                if dt.datetime.fromisoformat(it["ts"]) < cutoff: continue
                k = norm(it["title"])
                if not k: continue
                if k in by: continue
                it["tags"] = tags_for(it["title"], tag); it["id"] = hashlib.md5(k.encode()).hexdigest()[:10]
                by[k] = it; fresh.append(it)
        except Exception as e:
            print("rss fail", q, e)
        time.sleep(1)
    print("new items:", len(fresh))
    fresh.sort(key=lambda i: i["ts"], reverse=True)
    for n, it in enumerate(fresh):
        it["url"] = decode(it.pop("gurl"))
        if n >= NEW_IMG_LIMIT or "news.google.com" in it["url"]: continue
        try:
            u = og_image(it["url"])
            if u: it["img"] = save_thumb(u, it["id"])
        except Exception as e:
            print("img fail", it["src"], e)
        time.sleep(0.4)
    for it in by.values():
        if "gurl" in it: it["url"] = it.pop("gurl")
        if not it.get("img"): it.pop("img", None)
    items = [i for i in by.values() if dt.datetime.fromisoformat(i["ts"]) >= cutoff]
    items.sort(key=lambda i: i["ts"], reverse=True); items = items[:MAX_ITEMS]
    keep = {os.path.basename(i["img"]) for i in items if i.get("img")}
    for f in os.listdir(IMG):
        if f.endswith(".jpg") and f not in keep: os.remove(os.path.join(IMG, f))
    json.dump({"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "items": items},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("total:", len(items), "imgs:", len(keep))

if __name__ == "__main__":
    main()
