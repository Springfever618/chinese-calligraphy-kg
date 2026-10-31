"""处理补采的名家：生成 data/entities_famous.json、data/rule_triples_famous.json 和待判读的 data/candidates_famous.json。
结果单独存放，不改动 candidates.json 的编号。旧条目里提到新增人物的句子也会进入候选。
用法：python3 -I scripts/prepare_famous.py
"""
import collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from text_rules import *

OLD = json.load(open("data/entities.json", encoding="utf-8"))["people"]
OLD_C = json.load(open("data/candidates.json", encoding="utf-8"))
WORKS = json.load(open("data/entities.json", encoding="utf-8"))["works"]
LOOSE = [(n, p) for n, p in DYNASTY if n not in ("商朝", "周朝")]


def period(cats):
    """名家条目常不在书法家分类里（如“北宋皇帝”），只要分类带朝代名就算。"""
    return [n for n, p in LOOSE if any(re.search(f"({p})", c) for c in cats)]


WD = json.load(open("data/raw/wikidata_famous.json", encoding="utf-8"))
people, dropped, existed, basis_count = {}, [], [], collections.Counter()
for line in open("data/raw/pages_famous.jsonl", encoding="utf-8"):
    e = json.loads(line)
    if not e.get("title"):
        dropped.append((e["seed"], "未找到条目")); continue
    if e["title"] in OLD:
        existed.append(e["seed"]); continue
    if "消歧义" in "".join(e["categories"]) or not e["text"] or "可以指" in e["text"][:30]:
        dropped.append((e["seed"], "消歧义页")); continue
    if len(e["text"]) < 100:
        dropped.append((e["seed"], "条目过短")); continue
    # 书法家类型要有来源：正文提到书法，或 Wikidata 职业含书法家。都没有的只收录为普通人物
    occupation = [WD["labels"].get(x) for x in WD["claims"].get(e["qid"] or "", {}).get("职业", [])]
    basis = "正文" if CALLIG.search(e["text"]) else "Wikidata职业" if "书法家" in occupation else None
    basis_count[basis or "无来源，收录为人物"] += 1
    people[e["title"]] = {"name": e["seed"], "title": e["title"], "qid": e["qid"], "text": e["text"], "dynasties": period(e["categories"]), "living": "在世人物" in e["categories"], "categories": e["categories"], "kind": "Calligrapher" if basis else "Person"}

work_gaz = {v["name"]: k for k, v in WORKS.items()}
gaz = {}
for k, v in sorted({**OLD, **people}.items(), key=lambda kv: len(kv[1]["text"])):
    if len(v["name"]) >= 2:
        gaz[v["name"]] = k
new_names = {v["name"] for v in people.values()}
seen = {x["sentence"] for x in OLD_C["master"]}
triples, master_c, work_c = [], [], []

for title, v in people.items():
    for s in sentences(v["text"]):
        others = [n for n in gaz if n in s and gaz[n] != title]
        if ((others and CUE_MASTER.search(s)) or CUE_STRICT.search(s)) and s[:220] not in seen:
            seen.add(s[:220])
            master_c.append({"id": len(master_c), "person": v["name"], "title": title, "sentence": s[:220], "names": others[:6]})
        hit = [x for x in SCRIPT_NAMES if x in s]
        if hit and re.search(r"(工|精|善|擅|长于|尤|以.{0,6}著|能|尤工|兼工)", s) and len(s) < 260:
            for x in hit:
                triples.append({"s": title, "p": "擅长书体", "o": x, "method": "规则", "evidence": s, "source": title})
        for t in TITLE.findall(s):
            if t in work_gaz or (CUE_WORK.search(s) and not CUE_BOOK.search(s) and WORK_END.search(t)):
                work_c.append({"id": len(work_c), "person": v["name"], "title": title, "sentence": s[:220], "work": t, "kind": "已知作品" if t in work_gaz else "新作品"})
for title, v in OLD.items():
    for s in sentences(v["text"]):
        hit = [n for n in new_names if n in s and n != v["name"]]
        if hit and CUE_MASTER.search(s) and s[:220] not in seen:
            seen.add(s[:220])
            master_c.append({"id": len(master_c), "person": v["name"], "title": title, "sentence": s[:220], "names": hit[:6]})

json.dump(people, open("data/entities_famous.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(triples, open("data/rule_triples_famous.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
json.dump({"master": master_c, "work": work_c}, open("data/candidates_famous.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print("新增", len(people), dict(basis_count), "已有", existed, "丢弃", dropped)
print("仅人物", [v["name"] for v in people.values() if v["kind"] == "Person"])
print("无朝代", [v["name"] for v in people.values() if not v["dynasties"]])
print("候选：师承", len(master_c), "作品", len(work_c), "规则", len(triples))
