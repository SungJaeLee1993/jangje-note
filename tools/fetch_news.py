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

DEBUG = []
def decode(gurl):
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(gurl, interval=0.3)
        if (r.get("status") or r.get("success")) and r.get("decoded_url"): return r["decoded_url"]
        DEBUG.append("decode: " + str(r)[:300])
    except Exception as e:
        DEBUG.append("decode exc: " + repr(e)[:300])
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

PRIORITY = ["장제", "마사회", "말산업", "승마", "경마"]   # 앞일수록 먼저
PICK = 30          # 저장 개수 (홈엔 앞 5개, 더보기에 전체)
IMG_N = 15

def rank(it): return min(PRIORITY.index(t) for t in it["tags"])

# ---- 같은 사건 중복 판별 (핵심 단어 기준) ----
STOP=set("한국마사회 마사회 렛츠런파크 렛츠런 말산업 말 馬 경마 승마 개최 모집 참가자 시행 서울 부산 부산경남 부경 제주 지사 본부 지원 행사 체험 확대 국내 한국 특별한 하루 위한 나선다 선사 대상 생중계 안방서 즐긴다 까지 부터 올해 최고 세계적 세계 함께 하는 통해 위해 진행 운영 실시 성료 마련 기념 관련 대회 경주 이어 등 및 첫 새 년 월 일".split())
JOSA=re.compile(r"(으로|에서|까지|부터|에게|과|와|은|는|이|가|을|를|의|에|로|도|만|서)$")
def toks(t):
    t=re.sub(r"[\[\(][^\]\)]*[\]\)]"," ",t)
    out=set()
    for w in re.findall(r"[가-힣A-Za-z0-9]+",t):
        w=JOSA.sub("",w) if len(w)>2 else w
        m=re.fullmatch(r"(\d+)(월|일|개|명|승|회|번|연승|경주|억|만)?",w)
        if m:
            if m.group(2) in ("월","일") or len(m.group(1))>=2: out.add(m.group(1)+(m.group(2) if m.group(2) in ("월","일") else "#"))
            continue
        if len(w)<2 or w in STOP: continue
        out.add(w)
    return out
DF={}
def bgr(x,y):
    f=lambda t:{t[i:i+2] for i in range(len(t)-1)}
    A,B=f(re.sub(r"[^가-힣A-Za-z0-9]","",x)),f(re.sub(r"[^가-힣A-Za-z0-9]","",y))
    return len(A&B)/max(1,min(len(A),len(B)))
def match(a,b,ta="",tb=""):
    hit=[x for x in a for y in b if x==y or (len(x)>=2 and len(y)>=2 and (x.startswith(y) or y.startswith(x)) and min(len(x),len(y))>=2)]
    hit=set(hit); word=[h for h in hit if not h[0].isdigit()]   # 숫자·날짜는 다른 단어와 함께일 때만
    return (len(hit)>=2 and (word or any(h.endswith("#") for h in hit))) or any(len(h)>=3 for h in word) or (any(DF.get(h,0)<=DFMAX for h in word) and bgr(ta,tb)>=0.15)
DFMAX=8
def dedupe(items,pool=None):
    global DFMAX
    DF.clear(); P=pool or items
    for x in P:
        for w in toks(x["title"]): DF[w]=DF.get(w,0)+1
    DFMAX=max(8,len(P)//20)
    kept=[];ks=[]
    for it in items:
        k=toks(it["title"])
        if any(match(k,o,it["title"],ot) for o,ot in ks): it["_dup"]=True; continue
        kept.append(it); ks.append((k,it["title"]))
    return kept

def main():
    os.makedirs(IMG, exist_ok=True)
    try: old = {i["id"]: i for i in json.load(open(OUT, encoding="utf-8"))["items"]}
    except Exception: old = {}
    now = dt.datetime.now(dt.timezone.utc)
    cands, seen = [], set()
    for tag, q in QUERIES:
        try:
            for it in rss(q):
                if any(b in it["title"] for b in BLOCK): continue
                k = norm(it["title"])
                if not k or k in seen: continue
                seen.add(k)
                it["tags"] = tags_for(it["title"], tag); it["id"] = hashlib.md5(k.encode()).hexdigest()[:10]
                cands.append(it)
        except Exception as e:
            DEBUG.append("rss fail " + q + " " + repr(e)[:200])
        time.sleep(1)
    age = lambda i: now - dt.datetime.fromisoformat(i["ts"])
    pool = [i for i in cands if age(i) <= dt.timedelta(days=3)]
    if len(pool) < PICK: pool = cands
    pool.sort(key=lambda i: (rank(i), -dt.datetime.fromisoformat(i["ts"]).timestamp()))
    picked = dedupe(pool, cands)[:PICK]
    print("candidates:", len(cands), "picked:", [(p["tags"], p["title"][:20]) for p in picked])
    for n, it in enumerate(picked):
        prev = old.get(it["id"])
        if prev and "news.google.com" not in prev.get("url", "") :
            it["url"] = prev["url"]
            if prev.get("img") and os.path.exists(os.path.join(ROOT, prev["img"])): it["img"] = prev["img"]; it.pop("gurl", None); continue
        else:
            it["url"] = decode(it["gurl"])
        it.pop("gurl", None)
        if n >= IMG_N or "news.google.com" in it["url"]: continue
        try:
            u = og_image(it["url"])
            if u: it["img"] = save_thumb(u, it["id"])
        except Exception as e:
            DEBUG.append("img: " + it["src"] + " " + repr(e)[:200])
        time.sleep(0.4)
    keep = {os.path.basename(i["img"]) for i in picked if i.get("img")}
    for f in os.listdir(IMG):
        if f.endswith(".jpg") and f not in keep: os.remove(os.path.join(IMG, f))
    json.dump({"updated": now.isoformat(), "items": picked},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(ROOT, "news", "_debug.txt"), "w").write("\n".join(DEBUG[:30]))
    print("imgs:", len(keep))

if __name__ == "__main__":
    main()
