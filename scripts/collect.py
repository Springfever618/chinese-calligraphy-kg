"""采集中文维基的书法条目：按分类遍历，保存简体正文、分类和 Wikidata 编号。
支持中断续跑：已保存的页面会跳过。用法：python3 -I scripts/collect.py <输出目录>
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

API = "https://zh.wikipedia.org/w/api.php"
UA = "KG-course-project/0.1 (student coursework)"
ROOTS = {"Category:中国书法家": ("书法家", 3), "Category:书法家": ("书法家", 1),
         "Category:中国书法": ("书法", 3), "Category:书法作品": ("作品", 2), "Category:碑帖": ("作品", 2),
         "Category:法帖": ("作品", 2), "Category:书体": ("书体", 2)}
GAP = 1.2


def call(**params):
    params.update(format="json", formatversion="2", maxlag="5")
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        time.sleep(GAP)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            data = json.load(urllib.request.urlopen(req, timeout=60))
            if data.get("error", {}).get("code") != "maxlag":
                return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(15 * (attempt + 1))
    raise RuntimeError("请求多次失败：" + url)


def members(cat):
    cont = {}
    while True:
        d = call(action="query", list="categorymembers", cmtitle=cat, cmlimit="500",
                 cmtype="page|subcat", cmnamespace="0|14", **cont)
        yield from d.get("query", {}).get("categorymembers", [])
        if "continue" not in d:
            return
        cont = {"cmcontinue": d["continue"]["cmcontinue"]}


def crawl():
    pages, seen = {}, set()
    for root, (kind, depth) in ROOTS.items():
        stack = [(root, 0)]
        while stack:
            cat, level = stack.pop()
            if cat in seen:
                continue
            seen.add(cat)
            for m in members(cat):
                if m["ns"] == 14 and level < depth:
                    stack.append((m["title"], level + 1))
                elif m["ns"] == 0:
                    pages.setdefault(m["title"], {"title": m["title"], "pageid": m["pageid"], "kinds": [], "from": []})
                    if kind not in pages[m["title"]]["kinds"]:
                        pages[m["title"]]["kinds"].append(kind)
                    pages[m["title"]]["from"].append(cat)
    return pages


def fetch(title):
    d = call(action="query", prop="extracts|pageprops|categories", titles=title, explaintext="1", redirects="1",
             variant="zh-cn", ppprop="wikibase_item", cllimit="100", clshow="!hidden")
    p = d["query"]["pages"][0]
    return {"text": p.get("extract", ""), "qid": p.get("pageprops", {}).get("wikibase_item"),
            "categories": [c["title"].split(":", 1)[1] for c in p.get("categories", [])]}


def main(out):
    os.makedirs(out, exist_ok=True)
    index = os.path.join(out, "index.json")
    if os.path.exists(index):
        pages = json.load(open(index, encoding="utf-8"))
    else:
        pages = crawl()
        json.dump(pages, open(index, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("候选页面", len(pages), flush=True)
    path = os.path.join(out, "pages.jsonl")
    done = set()
    if os.path.exists(path):
        done = {json.loads(line)["title"] for line in open(path, encoding="utf-8")}
    with open(path, "a", encoding="utf-8") as f:
        for i, (title, meta) in enumerate(pages.items()):
            if title in done:
                continue
            f.write(json.dumps({**meta, **fetch(title)}, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(i, title, flush=True)
    print("完成", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
