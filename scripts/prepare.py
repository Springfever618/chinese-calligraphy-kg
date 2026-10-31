"""清洗采集结果，生成实体表 data/entities.json、规则抽取结果 data/rule_triples.json，
以及交给大模型判断的候选句 data/candidates.json。用法：python3 -I scripts/prepare.py
"""
import collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from text_rules import *

RAW = "data/raw/"
pages = [json.loads(l) for l in open(RAW + "pages.jsonl", encoding="utf-8")]
extra = [json.loads(l) for l in open(RAW + "pages_extra.jsonl", encoding="utf-8")]
wd = json.load(open(RAW + "wikidata.json", encoding="utf-8"))
CLAIMS, LABELS = wd["claims"], wd["labels"]

people, works, scripts, concepts = {}, {}, {}, {}
stats = collections.Counter()
for p in pages:
    text, cats, c = p["text"], p["categories"], CLAIMS.get(p["qid"] or "", {})
    if "书法家" in p["kinds"]:
        cat_ok = any(re.search("書法家|书法家", x) for x in cats)
        lead_ok = CALLIG.search(text[:500])
        is_person = "性别" in c or "出生" in c or re.search(r"^[^。]{0,30}（[^）]{0,30}(年|\?|？|—|-)", text[:80])
        if not is_person or p["title"] in SCRIPT_NAMES or name_of(p["title"], text) in SCRIPT_NAMES:
            stats["丢弃：不是人物"] += 1; continue
        if not (cat_ok or lead_ok):
            stats["丢弃：与书法无关"] += 1; continue
        dyn = dynasties(cats)
        if not dyn and any(FOREIGN.search(x) for x in cats):
            stats["丢弃：外国人物"] += 1; continue
        living = "在世人物" in cats
        people[p["title"]] = {"name": name_of(p["title"], text), "title": p["title"], "qid": p["qid"], "text": text, "dynasties": dyn, "living": living, "categories": cats}
    elif "作品" in p["kinds"]:
        if any(FOREIGN.search(x) for x in cats) or not re.search(r"(帖|碑|铭|序|谱|志|稿|颂)", p["title"]):
            stats["丢弃：作品噪声"] += 1; continue
        works[p["title"]] = {"name": name_of(p["title"], text), "title": p["title"], "qid": p["qid"], "text": text}
for e in extra:
    if not e.get("title"):
        stats["补采未找到"] += 1; continue
    lead = e["text"][:300]
    if e["kinds"] == ["作品"]:
        if e["seed"] not in lead and e["seed"] not in e["title"]:
            stats["补采跳转到其他条目"] += 1; continue
        works.setdefault(e["title"], {"name": e["seed"], "title": e["title"], "qid": e["qid"], "text": e["text"]})
        works[e["title"]]["name"] = e["seed"]
    elif e["kinds"] == ["书体"]:
        if e["seed"] == e["title"] or e["seed"] in lead[:60]:
            scripts[e["seed"]] = {"name": e["seed"], "title": e["title"], "qid": e["qid"], "text": e["text"]}
    else:
        concepts[e["title"]] = {"name": e["seed"], "title": e["title"], "qid": e["qid"], "text": e["text"]}

names = collections.Counter(v["name"] for v in people.values())
gaz = {}
for k, v in sorted(people.items(), key=lambda kv: len(kv[1]["text"])):  # 重名时取正文最长的条目（通常是著名书家）
    if len(v["name"]) >= 2:
        gaz[v["name"]] = k
work_gaz = {v["name"]: k for k, v in works.items()}

triples, master_c, work_c = [], [], []


def add(s, p, o, method, evidence, source):
    triples.append({"s": s, "p": p, "o": o, "method": method, "evidence": evidence, "source": source})


for title, v in people.items():
    url_src = title
    for d in v["dynasties"]:
        add(title, "朝代", d, "分类映射", "", url_src)
    for s in sentences(v["text"]):
        others = [n for n in gaz if n in s and gaz[n] != title]
        if (others and CUE_MASTER.search(s)) or CUE_STRICT.search(s):
            master_c.append({"id": len(master_c), "person": v["name"], "title": title, "sentence": s[:220], "names": others[:6]})
        hit = [x for x in SCRIPT_NAMES if x in s]
        if hit and re.search(r"(工|精|善|擅|长于|尤|以.{0,6}著|能|尤工|兼工)", s) and len(s) < 260:
            for x in hit:
                add(title, "擅长书体", x, "规则", s, url_src)
        titles = [t for t in TITLE.findall(s)]
        for t in titles:
            if t in work_gaz:
                work_c.append({"person": v["name"], "title": title, "sentence": s[:220], "work": t, "kind": "已知作品"})
            elif CUE_WORK.search(s) and not CUE_BOOK.search(s) and WORK_END.search(t):
                work_c.append({"person": v["name"], "title": title, "sentence": s[:220], "work": t, "kind": "新作品"})

for title, v in works.items():
    lead = v["text"][:600]
    for s in sentences(lead):
        for x in SCRIPT_NAMES:
            if x in s:
                add(title, "书体", x, "规则", s, title)
                break

json.dump({"people": people, "works": works, "scripts": scripts, "concepts": concepts}, open("data/entities.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(triples, open("data/rule_triples.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
for i, w in enumerate(work_c):
    w["id"] = i
json.dump({"master": master_c, "work": work_c}, open("data/candidates.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(dict(stats))
print("人物", len(people), "在世", sum(v["living"] for v in people.values()), "作品", len(works), "书体", len(scripts), "概念", len(concepts))
print("朝代", collections.Counter(d for v in people.values() for d in v["dynasties"]).most_common())
print("无朝代人物", sum(1 for v in people.values() if not v["dynasties"]))
print("规则三元组", collections.Counter((t["p"]) for t in triples))
print("候选句：师承", len(master_c), "作品", len(work_c), "字符", sum(len(x["sentence"]) for x in master_c), sum(len(x["sentence"]) for x in work_c))
print("重名", [k for k, c in names.items() if c > 1][:20])
print("作品", [v["name"] for v in works.values()][:70])