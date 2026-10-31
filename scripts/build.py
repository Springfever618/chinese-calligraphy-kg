"""合并 Wikidata、规则和大模型结果，生成 cnSchema 扩展、JSON-LD 图谱、带证据的三元组和统计。
用法：python3 -I scripts/build.py
"""
import collections, csv, hashlib, json, os, random, re, urllib.parse

E = json.load(open("data/entities.json", encoding="utf-8"))
C = json.load(open("data/candidates.json", encoding="utf-8"))
RULES = json.load(open("data/rule_triples.json", encoding="utf-8"))
WD = json.load(open("data/raw/wikidata.json", encoding="utf-8"))
LW = json.load(open("data/llm_works.json", encoding="utf-8"))
CLAIMS, LABELS = WD["claims"], WD["labels"]
# 补采的名家（见 prepare_famous.py），判读结果和原有结果分开存放
FAMOUS_WD = json.load(open("data/raw/wikidata_famous.json", encoding="utf-8"))
CLAIMS.update(FAMOUS_WD["claims"]); LABELS.update(FAMOUS_WD["labels"])
FAMOUS = json.load(open("data/entities_famous.json", encoding="utf-8"))
E["people"].update(FAMOUS)
CF = json.load(open("data/candidates_famous.json", encoding="utf-8"))
RULES += json.load(open("data/rule_triples_famous.json", encoding="utf-8"))
LWF = json.load(open("data/llm_works_famous.json", encoding="utf-8"))
CNS = {x["name"] for x in json.load(open("data/raw/cnschema/cns-core.jsonld", encoding="utf-8"))["@graph"]}

NS = "urn:cn-calligraphy-kg:"
NAME_FIX = {"文壁": "文徵明", "贝子溥伒": "溥伒", "陈泽仁出生于1941年": "陈泽仁", "玄烨": "康熙帝", "宋徽宗赵佶": "宋徽宗", "唐玄宗李隆基": "唐玄宗", "南唐元宗李璟": "李璟",
            "汉章帝刘炟": "汉章帝", "齐高帝萧道成": "萧道成", "成哲亲王永瑆": "永瑆", "二等镇国将军溥佺": "溥佺", "贝子溥僩": "溥僩", "释弘一": "李叔同", "管道昇": "管道升", "梁𪩘": "梁巘", "欧阳脩": "欧阳修"}
ALIAS = {"卫夫人": "卫铄", "杜操": "杜度", "王湘绮": "王闿运", "弘一法师": "李叔同", "文征明": "文徵明"}
SCRIPTS = ["楷书", "行书", "草书", "隶书", "篆书", "章草", "今草", "狂草", "小篆", "大篆", "瘦金体", "魏碑", "飞白书", "馆阁体", "甲骨文", "金文"]
SCRIPT_NEAR = re.compile(r"(工|精|善|擅|擅长|长于|尤工|兼工|专攻|以)[^，。；]{0,8}(" + "|".join(SCRIPTS) + ")")

SCHEMA = {
    "classes": [("Calligrapher", "书法家", "Person", "以书法创作、研究或传授著称的人物"),
                ("CalligraphyWork", "书法作品", "CreativeWork", "碑刻、法帖、墨迹、摩崖、铭文等书法作品"),
                ("ScriptStyle", "书体", "Thing", "楷书、行书、草书、隶书、篆书等书写体式"),
                ("Dynasty", "朝代或时期", "Thing", "人物所属的朝代或历史时期")],
    "properties": [("studiedUnder", "师从", "Calligrapher", "Person", "确有授受关系的老师"),
                   ("emulated", "取法", "Calligrapher", "Person", "学习、效法的前代书家，不要求亲自受教"),
                   ("relationDomain", "师承领域", "Statement", "Text", "书法、篆刻、绘画、书画、学术或其他"),
                   ("skilledInScript", "擅长书体", "Calligrapher", "ScriptStyle", "人物擅长的书体"),
                   ("writtenInScript", "作品书体", "CalligraphyWork", "ScriptStyle", "作品采用的书体"),
                   ("inDynasty", "所属朝代", "Person", "Dynasty", "人物所属朝代或时期"),
                   ("calligrapher", "书写者", "CalligraphyWork", "Person", "作品的书写者"),
                   ("compiler", "编者", "CalligraphyWork", "Person", "丛帖的编选者"),
                   ("workForm", "作品形制", "CalligraphyWork", "Text", "碑刻、摩崖、丛帖、青铜器铭文等"),
                   ("heldBy", "收藏地", "CalligraphyWork", "Text", "作品或原物的现藏地")],
}

nodes, statements, name_ids = {}, [], {}


def mint(key):
    return NS + "e" + hashlib.sha1(key.encode()).hexdigest()[:12]


def page_url(title):
    return "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def node(kind, name, qid=None, title=None):
    name = ALIAS.get(name, NAME_FIX.get(name, name))
    key = "人物:" + name if kind in ("Calligrapher", "Person") else f"{kind}:{name}"
    if key in name_ids:
        if kind == "Calligrapher":
            nodes[name_ids[key]]["@type"] = kind
        return nodes[name_ids[key]]
    uid = NS + qid if qid else mint(key)
    n = nodes.setdefault(uid, {"@id": uid, "@type": kind, "name": name})
    if qid:
        n["sameAs"] = "http://www.wikidata.org/entity/" + qid
    if title:
        n["url"] = page_url(title)
    name_ids[key] = uid
    return n


def state(s, p, o, method, evidence="", source="", **extra):
    statements.append({"s": s["@id"], "sName": s["name"], "p": p, "o": o["@id"] if isinstance(o, dict) else o,
                       "oName": o["name"] if isinstance(o, dict) else o, "method": method, "evidence": evidence, "source": source, **extra})


def year(t):
    m = re.match(r"([+-])0*(\d+)-", t)
    return None if not m else (-int(m.group(2)) if m.group(1) == "-" else int(m.group(2)))


# 导语括号里的生卒年，如“（303年—361年）”“（前258年—前207年）”“（？—前208年）”
LIFE = re.compile(r"^[^（(，。]{1,12}\s*[（(](?:[^（）()，。]{0,12}[，：:])?\s*(前|公元前)?\s*(\d{2,4}年|？|\?)[^（）()—–－\-~至]{0,8}\s*[—–－\-~至]+\s*(前|公元前)?\s*(\d{2,4}年|？|\?)")


def intro_life(lead):
    m = LIFE.match(lead)
    if not m:
        return None, None
    b = None if not m.group(2)[0].isdigit() else int(m.group(2)[:-1]) * (-1 if m.group(1) else 1)
    d = None if not m.group(4)[0].isdigit() else int(m.group(4)[:-1]) * (-1 if m.group(3) else 1)
    return b, d


CN_LEAD = re.compile(r"中国|中华|台湾|香港|[秦汉晋隋唐宋元明清]朝|[秦汉晋隋唐宋元明清]代|东晋|西晋|北宋|南宋|南朝|北朝|三国|民国")


def in_scope(v):
    """书法家须是中文语境人物：排除外文名、作品条目，以及既无朝代又无中国线索的条目。"""
    n = v["name"]
    if re.search(r"[A-Za-z《》]", n) or not re.search(r"[\u4e00-\u9fff]", n) or v["text"].lstrip().startswith("《"):
        return False
    return bool(v["dynasties"]) or "·" not in n or bool(CN_LEAD.search(v["text"][:300]))


out_of_scope = [k for k, v in E["people"].items() if not in_scope(v)]
E["people"] = {k: v for k, v in E["people"].items() if in_scope(v)}
# 重名的不同人物不能合并：正文最长者保留原名，其余用条目括注区分，如“王铎（唐朝）”
same_name = collections.defaultdict(list)
for title, v in E["people"].items():
    same_name[v["name"]].append(title)
for name, titles in same_name.items():
    for title in sorted(titles, key=lambda t: -len(E["people"][t]["text"]))[1:]:
        m = re.search(r"[(（]([^)）]+)[)）]", title)
        E["people"][title]["name"] = f"{name}（{m.group(1) if m else title}）"
by_title, date_conflicts, odd_life = {}, [], []
for title, v in E["people"].items():
    n = node(v.get("kind", "Calligrapher"), v["name"], v["qid"], title)
    by_title[title] = n
    c = CLAIMS.get(v["qid"] or "", {})
    v["_birth"] = year(c["出生"][0]) if c.get("出生") else None
    v["_death"] = year(c["去世"][0]) if c.get("去世") else None
    # Wikidata 常有多个候选年份且顺序不定，导语写明时以导语为准
    ib, id_ = intro_life(v["text"].split("\n")[0])
    if (ib is not None and v["_birth"] not in (None, ib)) or (id_ is not None and v["_death"] not in (None, id_)):
        date_conflicts.append((v["name"], v["_birth"], v["_death"], ib, id_))
    v["_birth"] = ib if ib is not None else v["_birth"]
    v["_death"] = id_ if id_ is not None else v["_death"]
    if v["_birth"] is not None and v["_death"] is not None and not 10 <= v["_death"] - v["_birth"] <= 110:
        odd_life.append((v["name"], v["_birth"], v["_death"]))  # 两个来源拼出的寿命不合理，都不采用
        v["_birth"], v["_death"] = None, None
    if v["_birth"] is not None:
        n["birthDate"] = v["_birth"]
    if v["_death"] is not None:
        n["deathDate"] = v["_death"]
    if c.get("性别"):
        n["gender"] = {"男性": "男", "女性": "女", "male": "男", "female": "女"}.get(LABELS.get(c["性别"][0]), LABELS.get(c["性别"][0]))
    if c.get("出生地") and c["出生地"][0] in LABELS:
        n["birthPlace"] = LABELS[c["出生地"][0]]
    lead = v["text"].split("\n")[0][:300]
    n["description"] = lead
    alias = re.findall(r"[，（、]字([^，。、）；\s]{1,5})", lead[:120]) + re.findall(r"[，、]号([^，。、）；\s]{1,6})", lead[:120])
    if alias:
        n["alternateName"] = sorted(set(alias))
    n["isLiving"] = bool(v["living"])
    for d in v["dynasties"]:
        state(n, "inDynasty", node("Dynasty", d), "维基分类映射", "", page_url(title))

people_year = {v["name"]: (v["_birth"], v["_death"]) for v in E["people"].values()}
people_year.update({NAME_FIX.get(v["name"], v["name"]): (v["_birth"], v["_death"]) for v in E["people"].values()})

# Wikidata 师承；在世人物不收录亲属关系
QID_TO_NODE = {v["qid"]: by_title[k] for k, v in E["people"].items() if v["qid"]}
FAMILY = {"父亲": "parent", "母亲": "parent", "配偶": "spouse", "子女": "children", "兄弟姐妹": "sibling"}
for title, v in E["people"].items():
    c = CLAIMS.get(v["qid"] or "", {})
    n = by_title[title]
    for t in c.get("师从", []):
        if t in LABELS and not re.search(r"[A-Za-z]", LABELS[t]):
            state(n, "studiedUnder", node("Person", LABELS[t], t), "Wikidata", "", n["sameAs"], domain="未标注")
    for t in c.get("弟子", []):
        if t in LABELS and not re.search(r"[A-Za-z]", LABELS[t]):
            state(node("Person", LABELS[t], t), "studiedUnder", n, "Wikidata", "", n["sameAs"], domain="未标注")
    if not v["living"]:
        for k, p in FAMILY.items():
            for t in c.get(k, []):
                if t in QID_TO_NODE and t != v["qid"]:  # 只保留收录书法家之间的亲属关系
                    state(n, p, QID_TO_NODE[t], "Wikidata", "", n["sameAs"])

# 大模型师承
dropped = []
master_lines = [(line, C["master"]) for line in open("data/llm_master.txt", encoding="utf-8")]
master_lines += [(line, CF["master"]) for line in open("data/llm_master_famous.txt", encoding="utf-8")]
for line, cands in master_lines:
    if line.startswith("#") or not line.strip():
        continue
    i, teachers, students, rel, domain = line.strip().split("|")
    x = next(c for c in cands if c["id"] == int(i))
    if x["title"] not in by_title:
        continue
    subj = by_title[x["title"]]
    for t in teachers.split(","):
        for st in students.split(","):
            tn = subj if t == "@" else node("Person", t)
            sn = subj if st == "@" else node("Person", st)
            if tn is sn:
                continue
            ty, sy = people_year.get(tn["name"], (None, None)), people_year.get(sn["name"], (None, None))
            if rel == "师从" and ty[0] is not None and sy[1] is not None and ty[0] > sy[1]:
                dropped.append((tn["name"], sn["name"], x["sentence"]))
                continue
            state(sn, "studiedUnder" if rel == "师从" else "emulated", tn, "大模型判读", x["sentence"], page_url(x["title"]), domain=domain)

# 作品
for title, v in E["works"].items():
    if v["name"] in LW["drop_works"]:
        continue
    n = node("CalligraphyWork", v["name"], v["qid"], title)
    n["description"] = v["text"].split("\n")[0][:300]
    k = LW["known"].get(v["name"], {})
    src, ev = page_url(title), v["text"].split("\n")[0][:160]
    if k.get("书写者"):
        state(n, "calligrapher", node("Person", k["书写者"]), "大模型判读", ev, src)
    if k.get("编者"):
        state(n, "compiler", node("Person", k["编者"]), "大模型判读", ev, src)
    if k.get("书体"):
        state(n, "writtenInScript", node("ScriptStyle", k["书体"]), "大模型判读", ev, src)
    if k.get("类型"):
        state(n, "workForm", k["类型"], "大模型判读", ev, src)
    if k.get("收藏地"):
        state(n, "heldBy", k["收藏地"], "大模型判读", ev, src)
accepted = [x for x in C["work"] if x["id"] in set(LW["accepted_candidate_ids"])] + [x for x in CF["work"] if x["id"] in set(LWF["accepted_candidate_ids"])]
for x in accepted:
    if x["title"] not in by_title:
        continue
    n = node("CalligraphyWork", x["work"])
    state(n, "calligrapher", by_title[x["title"]], "大模型判读", x["sentence"], page_url(x["title"]))

# 书体
for s, v in E["scripts"].items():
    n = node("ScriptStyle", s, v["qid"], v["title"])
    n["description"] = v["text"].split("\n")[0][:300]
for s, person in LWF["script_creators"].items():  # 书体条目导语写明的创立者，规则抽不到
    v = E["scripts"][s]
    state(node("Person", person), "skilledInScript", node("ScriptStyle", s), "大模型判读", v["text"].split("\n")[0][:160], page_url(v["title"]))
for r in RULES:
    if r["p"] == "擅长书体" and r["s"] in by_title:
        for m in SCRIPT_NEAR.finditer(r["evidence"]):
            if m.group(2) == r["o"]:
                state(by_title[r["s"]], "skilledInScript", node("ScriptStyle", r["o"]), "规则", r["evidence"], page_url(r["s"]))
                break

seen, uniq = set(), []
for s in statements:
    k = (s["s"], s["p"], s["o"])
    if k not in seen:
        seen.add(k); uniq.append(s)
statements = uniq

for s in statements:
    n = nodes[s["s"]]
    n.setdefault(s["p"], [])
    v = {"@id": s["o"]} if s["o"].startswith(NS) else s["o"]
    if v not in n[s["p"]]:
        n[s["p"]].append(v)

os.makedirs("output", exist_ok=True); os.makedirs("schema", exist_ok=True); os.makedirs("evaluation", exist_ok=True)
base_missing = [c for _, _, c, _ in SCHEMA["classes"] if c not in CNS]
reused = [p for p in ["name", "alternateName", "description", "url", "sameAs", "birthDate", "deathDate", "birthPlace", "gender", "parent", "spouse", "children", "sibling"] if p in CNS]
context = {"@vocab": "http://cnschema.org/", "shufa": NS + "schema/", "xsd": "http://www.w3.org/2001/XMLSchema#", "url": {"@type": "@id"}, "sameAs": {"@type": "@id"}}
for c, *_ in SCHEMA["classes"]:
    context[c] = "shufa:" + c
for p, _, _, rng, _ in SCHEMA["properties"]:
    context[p] = {"@id": "shufa:" + p, "@type": "@id"} if rng not in ("Text",) else "shufa:" + p
for p in ("parent", "spouse", "children", "sibling"):
    context[p] = {"@id": "http://cnschema.org/" + p, "@type": "@id"}
context["isLiving"] = "shufa:isLiving"
schema_graph = [{"@id": "shufa:" + c, "@type": "rdfs:Class", "rdfs:label": zh, "rdfs:subClassOf": {"@id": "http://cnschema.org/" + base}, "rdfs:comment": d} for c, zh, base, d in SCHEMA["classes"]]
schema_graph += [{"@id": "shufa:" + p, "@type": "rdf:Property", "rdfs:label": zh, "rdfs:comment": d, "domainName": dom, "rangeName": rng} for p, zh, dom, rng, d in SCHEMA["properties"]]
json.dump({"@context": {"shufa": NS + "schema/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "domainName": "shufa:domainName", "rangeName": "shufa:rangeName"}, "@graph": schema_graph},
          open("schema/calligraphy-schema.jsonld", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# 师承陈述单独成节点（RDF 具体化），使领域、方法和证据句可以用 SPARQL 查询
context.update({"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "evidence": "shufa:evidence", "extractionMethod": "shufa:extractionMethod", "evidenceSource": {"@id": "shufa:evidenceSource", "@type": "@id"},
                "statedSubject": {"@id": "rdf:subject", "@type": "@id"}, "statedPredicate": {"@id": "rdf:predicate", "@type": "@id"}, "statedObject": {"@id": "rdf:object", "@type": "@id"}})
stmt_nodes = []
for s in statements:
    if s["p"] in ("studiedUnder", "emulated"):
        x = {"@id": mint("陈述:" + s["s"] + s["p"] + s["o"]), "@type": "rdf:Statement", "statedSubject": s["s"], "statedPredicate": NS + "schema/" + s["p"], "statedObject": s["o"],
             "relationDomain": s.get("domain") or "未标注", "extractionMethod": s["method"]}
        if s["evidence"]:
            x["evidence"] = s["evidence"]
        if s["source"]:
            x["evidenceSource"] = s["source"]
        stmt_nodes.append(x)
json.dump({"@context": context, "@graph": list(nodes.values()) + stmt_nodes}, open("output/calligraphy-kg.jsonld", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
with open("output/statements.tsv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["主语", "关系", "宾语", "领域", "方法", "证据", "来源"])
    for s in statements:
        w.writerow([s["sName"], s["p"], s["oName"], s.get("domain", ""), s["method"], s["evidence"], s["source"]])

random.seed(7)
pool = [s for s in statements if s["method"] in ("大模型判读", "规则") and s["evidence"]]
by = collections.defaultdict(list)
for s in pool:
    by[(s["p"], s["method"])].append(s)
EVAL = "evaluation/待人工标注.csv"
labelled = os.path.exists(EVAL) and any(r["是否正确（填 1 或 0）"].strip() for r in csv.DictReader(open(EVAL, encoding="utf-8-sig")))
if labelled:  # 已有人工标注时不重新抽样，避免覆盖
    print("待人工标注.csv 已有标注，未重新生成")
else:
    with open(EVAL, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["关系", "方法", "主语", "宾语", "证据句", "来源", "是否正确（填 1 或 0）", "备注"])
        for k, v in by.items():
            if k[0] in ("studiedUnder", "emulated", "calligrapher", "skilledInScript"):
                for s in random.sample(v, min(50, len(v))):
                    w.writerow([s["p"], s["method"], s["sName"], s["oName"], s["evidence"], s["source"], "", ""])

stats = {"实体总数": len(nodes), "实体类型": dict(collections.Counter(n["@type"] for n in nodes.values())),
         "关系总数": len(statements), "关系类型": dict(collections.Counter(s["p"] for s in statements)),
         "按方法": dict(collections.Counter(s["method"] for s in statements)),
         "师承领域": dict(collections.Counter(s.get("domain") for s in statements if s["p"] in ("studiedUnder", "emulated"))),
         "补采名家": dict(collections.Counter(v["kind"] for v in FAMOUS.values())), "师承陈述节点": len(stmt_nodes), "生卒年与Wikidata不一致": len(date_conflicts), "生卒年不合理未采用": len(odd_life), "时间校验丢弃": len(dropped), "范围外条目": len(out_of_scope), "复用的cnSchema属性": reused, "父类不在cnSchema": base_missing}
json.dump(stats, open("output/stats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(stats, ensure_ascii=False, indent=1))
print("时间校验丢弃", dropped[:10])
print("生卒年冲突样例", date_conflicts[:15])
print("生卒年不合理", odd_life)
print("范围外样例", out_of_scope[:20])
print("名字可疑", [n["name"] for n in nodes.values() if n["@type"] in ("Calligrapher", "Person") and (len(n["name"]) > 5 or re.search(r"[A-Za-z（(，。]", n["name"]))][:60])
print("孤立书法家", sum(1 for n in nodes.values() if n["@type"] == "Calligrapher" and not any(k in n for k in ("inDynasty", "studiedUnder", "skilledInScript")) and not any(s["o"] == n["@id"] for s in statements)))
print("连接最多", collections.Counter(s["oName"] for s in statements if s["p"] == "studiedUnder").most_common(12))
