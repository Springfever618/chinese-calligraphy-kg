"""图谱访问层：载入 JSON-LD，提供实体链接、检索、SPARQL、路径和网络分析。"""
import collections, csv, json, os, re, threading

from rdflib import Graph

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = "urn:cn-calligraphy-kg:"
PREFIXES = """PREFIX cns: <http://cnschema.org/>
PREFIX shufa: <urn:cn-calligraphy-kg:schema/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""
REL_LABEL = {"studiedUnder": "师从", "emulated": "取法", "skilledInScript": "擅长书体", "writtenInScript": "书体", "inDynasty": "所属朝代",
             "calligrapher": "书写者", "compiler": "编者", "workForm": "形制", "heldBy": "收藏地", "parent": "父母", "children": "子女",
             "sibling": "兄弟姐妹", "spouse": "配偶"}
REVERSE_LABEL = {"studiedUnder": "弟子", "emulated": "被取法", "calligrapher": "作品", "compiler": "编选", "skilledInScript": "擅长此体者",
                 "writtenInScript": "此体作品", "inDynasty": "人物"}
TYPE_LABEL = {"Calligrapher": "书法家", "Person": "人物", "CalligraphyWork": "作品", "ScriptStyle": "书体", "Dynasty": "朝代"}
LOCAL_RELS = ("studiedUnder", "emulated", "skilledInScript", "writtenInScript", "inDynasty", "calligrapher", "compiler", "parent", "children", "sibling", "spouse")
LINEAGE = ("studiedUnder", "emulated")
# 常见通称和异体写法，只用于把用户输入对应到实体，不写入图谱
COMMON_NAMES = {"卫夫人": "卫铄", "赵孟頫": "赵孟𫖯", "赵孟俯": "赵孟𫖯", "赵松雪": "赵孟𫖯", "钟繇": "锺繇", "文征明": "文徵明", "文衡山": "文徵明", "王右军": "王羲之", "右军": "王羲之", "书圣": "王羲之",
                "王大令": "王献之", "颜鲁公": "颜真卿", "柳诚悬": "柳公权", "苏东坡": "苏轼", "东坡": "苏轼", "黄山谷": "黄庭坚", "山谷": "黄庭坚", "米南宫": "米芾", "米襄阳": "米芾",
                "董香光": "董其昌", "弘一法师": "李叔同", "赵佶": "宋徽宗", "李隆基": "唐玄宗", "赵构": "宋高宗", "弘历": "乾隆帝", "玄烨": "康熙帝", "武曌": "武则天", "王阳明": "王守仁", "梁武帝": "萧衍", "梁简文帝": "萧纲", "欧阳脩": "欧阳修", "释弘一": "李叔同", "弘一": "李叔同", "朱耷": "八大山人", "郑板桥": "郑燮", "吴让之": "吴熙载", "怀素和尚": "怀素", "傅青主": "傅山", "邓完白": "邓石如", "杜操": "杜度", "欧阳率更": "欧阳询"}


class KG:
    def __init__(self):
        doc = json.load(open(os.path.join(ROOT, "output/calligraphy-kg.jsonld"), encoding="utf-8"))
        self.nodes = {n["@id"]: n for n in doc["@graph"] if n["@type"] != "rdf:Statement"}
        self.graph = Graph().parse(os.path.join(ROOT, "output/calligraphy-kg.jsonld"), format="json-ld")
        self.lock = threading.Lock()  # rdflib 的查询不保证线程安全
        self.stats = json.load(open(os.path.join(ROOT, "output/stats.json"), encoding="utf-8"))
        self.by_name = collections.defaultdict(list)
        self.by_alias = collections.defaultdict(list)
        for n in self.nodes.values():
            self.by_name[n["name"]].append(n)
            for a in n.get("alternateName", []):
                if len(a) >= 2:
                    self.by_alias[a].append(n)
        for common, name in COMMON_NAMES.items():
            if name in self.by_name and common not in self.by_name:
                self.by_alias[common] = self.by_name[name]
        self.evidence = {}
        with open(os.path.join(ROOT, "output/statements.tsv"), encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                self.evidence[(r["主语"], r["关系"], r["宾语"])] = r
        self.out = collections.defaultdict(list)
        self.into = collections.defaultdict(list)
        for n in self.nodes.values():
            for p in REL_LABEL:
                for v in n.get(p, []):
                    target = v["@id"] if isinstance(v, dict) else None
                    self.out[n["@id"]].append((p, target, v))
                    if target:
                        self.into[target].append((p, n["@id"]))
        self.names_longest = sorted(set(self.by_name) | set(self.by_alias), key=len, reverse=True)
        self.analysis = self._analyse()

    # ---------- 基础 ----------
    def sparql(self, query):
        with self.lock:
            res = self.graph.query(PREFIXES + query)
            return [{str(k): (str(v) if v is not None else None) for k, v in zip(res.vars, row)} for row in res]

    def brief(self, n):
        return {"id": n["@id"], "name": n["name"], "type": n["@type"], "typeLabel": TYPE_LABEL.get(n["@type"], n["@type"]),
                "description": (n.get("description") or "")[:120], "dynasty": [self.nodes[d["@id"]]["name"] for d in n.get("inDynasty", [])],
                "life": self.life(n)}

    @staticmethod
    def fmt_year(y):
        return "不详" if y is None else (f"公元前{-y}年" if y < 0 else f"{y}年")

    def life(self, n):
        if n.get("birthDate") is None and n.get("deathDate") is None:
            return ""
        return f"{self.fmt_year(n.get('birthDate'))}—{self.fmt_year(n.get('deathDate'))}"

    def ev(self, s, p, o):
        return self.evidence.get((s, p, o))

    # ---------- 实体链接 ----------
    def link(self, text):
        """最长匹配：正式名优先于字号。返回 [(提及, 候选节点列表)]，重叠的短提及被长提及覆盖。"""
        text = text.replace("《", "").replace("》", "")
        found, taken = [], [False] * len(text)
        for name in self.names_longest:
            if len(name) < 2:
                continue
            start = text.find(name)
            while start >= 0:
                end = start + len(name)
                if not any(taken[start:end]):
                    taken[start:end] = [True] * len(name)
                    found.append((start, name, self.by_name.get(name) or self.by_alias[name]))
                start = text.find(name, end)
        return [(name, cands) for _, name, cands in sorted(found, key=lambda x: x[0])]

    # ---------- 检索 ----------
    def search(self, q, type_filter=None, limit=30):
        q = q.strip().replace("《", "").replace("》", "")
        if not q:
            return []
        terms = [COMMON_NAMES.get(t, t) for t in re.split(r"\s+", q) if t]
        scored = []
        for n in self.nodes.values():
            if type_filter and n["@type"] != type_filter:
                continue
            aliases = n.get("alternateName", [])
            desc = n.get("description") or ""
            score = 0
            for t in terms:
                if n["name"] == t:
                    s = 100
                elif t in aliases:
                    s = 80
                elif n["name"].startswith(t):
                    s = 60
                elif t in n["name"]:
                    s = 50
                elif any(t in a for a in aliases):
                    s = 40
                elif t in desc:
                    s = 15 + min(desc.count(t), 5)
                else:
                    s = 0
                if s == 0:
                    score = 0  # 多个词时要求都命中
                    break
                score += s
            if score:
                # 同分时优先关系多的实体，著名书家排在前面
                scored.append((score, len(self.out[n["@id"]]) + len(self.into[n["@id"]]), n))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]["name"]))
        return [dict(self.brief(n), score=s) for s, _, n in scored[:limit]]

    # ---------- 实体详情 ----------
    def entity(self, uid):
        n = self.nodes.get(uid)
        if not n:
            return None
        rels = []
        for p, target, v in self.out[uid]:
            name = self.nodes[target]["name"] if target else v
            e = self.ev(n["name"], p, name) or {}
            rels.append({"predicate": p, "label": REL_LABEL[p], "direction": "out", "id": target, "name": name, "domain": e.get("领域", ""),
                         "method": e.get("方法", ""), "evidence": e.get("证据", ""), "source": e.get("来源", "")})
        for p, sid in self.into[uid]:
            name = self.nodes[sid]["name"]
            e = self.ev(name, p, n["name"]) or {}
            rels.append({"predicate": p, "label": REVERSE_LABEL.get(p, REL_LABEL[p]), "direction": "in", "id": sid, "name": name, "domain": e.get("领域", ""),
                         "method": e.get("方法", ""), "evidence": e.get("证据", ""), "source": e.get("来源", "")})
        out = self.brief(n)
        out.update({"description": n.get("description") or "", "alternateName": n.get("alternateName", []), "gender": n.get("gender"), "birthPlace": n.get("birthPlace"),
                    "url": n.get("url"), "sameAs": n.get("sameAs"), "relations": rels})
        return out

    # ---------- 师承网络 ----------
    def _lineage_edges(self, domains=None):
        for n in self.nodes.values():
            for p in LINEAGE:
                for v in n.get(p, []):
                    t = self.nodes[v["@id"]]
                    domain = (self.ev(n["name"], p, t["name"]) or {}).get("领域") or "未标注"
                    if domains and domain not in domains:
                        continue
                    yield n["@id"], t["@id"], p, domain

    def network(self, center=None, depth=2, domains=None, limit=160):
        edges = list(self._lineage_edges(domains))
        adj = collections.defaultdict(list)
        for s, o, p, d in edges:
            adj[s].append(o)
            adj[o].append(s)
        if center:
            keep, frontier = {center}, [center]
            for _ in range(depth):
                nxt = []
                for x in frontier:
                    for y in adj[x]:
                        if y not in keep and len(keep) < limit:
                            keep.add(y)
                            nxt.append(y)
                frontier = nxt
        else:
            keep = {k for k, _ in sorted(adj.items(), key=lambda kv: -len(kv[1]))[:limit]}
        nodes = [{"id": k, "name": self.nodes[k]["name"], "type": self.nodes[k]["@type"], "degree": len(adj[k]), "center": k == center} for k in keep]
        links = [{"source": s, "target": o, "predicate": p, "label": REL_LABEL[p], "domain": d} for s, o, p, d in edges if s in keep and o in keep]
        return {"nodes": nodes, "links": links}

    def path(self, a, b, domains=None, predicates=LINEAGE):
        """无向最短路径，按师承关系走；同时给出每一步的方向和证据。"""
        adj = collections.defaultdict(list)
        for s, o, p, d in self._lineage_edges(domains):
            if p not in predicates:
                continue
            adj[s].append((o, p, "out", d))
            adj[o].append((s, p, "in", d))
        prev, queue = {a: None}, collections.deque([a])
        while queue:
            x = queue.popleft()
            if x == b:
                break
            for y, p, direction, d in adj[x]:
                if y not in prev:
                    prev[y] = (x, p, direction, d)
                    queue.append(y)
        if b not in prev:
            return None
        steps, x = [], b
        while prev[x]:
            y, p, direction, d = prev[x]
            s, o = (y, x) if direction == "out" else (x, y)
            sn, on = self.nodes[s]["name"], self.nodes[o]["name"]
            e = self.ev(sn, p, on) or {}
            steps.append({"student": sn, "studentId": s, "teacher": on, "teacherId": o, "label": REL_LABEL[p], "domain": d, "evidence": e.get("证据", ""), "source": e.get("来源", "")})
            x = y
        return steps[::-1]

    # ---------- 挖掘分析 ----------
    def _analyse(self, domains=("书法", "书画", "篆刻", "未标注")):
        edges = [(s, o) for s, o, _, _ in self._lineage_edges(domains)]
        members = {x for e in edges for x in e}
        outgoing = collections.defaultdict(set)  # 学生 -> 老师
        incoming = collections.defaultdict(set)  # 老师 -> 学生
        for s, o in edges:
            outgoing[s].add(o)
            incoming[o].add(s)
        # PageRank：影响沿“学生 -> 老师”流动
        rank = {x: 1 / len(members) for x in members}
        damping = 0.85
        for _ in range(50):
            sink = sum(rank[x] for x in members if not outgoing[x])
            nxt = {x: (1 - damping) / len(members) + damping * sink / len(members) for x in members}
            for s in members:
                for o in outgoing[s]:
                    nxt[o] += damping * rank[s] / len(outgoing[s])
            rank = nxt
        top = sorted(members, key=lambda x: -rank[x])[:15]
        influence = [{"id": x, "name": self.nodes[x]["name"], "pagerank": round(rank[x], 4), "students": len(incoming[x]),
                      "dynasty": [self.nodes[d["@id"]]["name"] for d in self.nodes[x].get("inDynasty", [])]} for x in top]
        # 最长师承链（去环）
        best, memo = [], {}

        def longest(x, stack):
            if x in memo:
                return memo[x]
            result = [x]
            for o in sorted(outgoing[x]):
                if o not in stack:
                    tail = longest(o, stack | {o})
                    if len(tail) + 1 > len(result):
                        result = [x] + tail
            memo[x] = result
            return result

        for x in sorted(members):  # 排序：并列最长时每次启动结果相同
            c = longest(x, {x})
            if len(c) > len(best):
                best = c
        # 弱连通分量
        parent = {x: x for x in members}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for s, o in edges:
            parent[find(s)] = find(o)
        sizes = collections.Counter(find(x) for x in members)
        # 朝代人数与朝代 × 书体
        order = ["商朝", "战国", "秦朝", "汉朝", "三国", "晋朝", "南北朝", "隋朝", "唐朝", "五代十国", "宋朝", "辽金", "元朝", "明朝", "清朝", "中华民国", "中华人民共和国", "台湾", "香港"]
        dynasty_count = collections.Counter()
        cross = collections.Counter()
        script_count = collections.Counter()
        for n in self.nodes.values():
            if n["@type"] != "Calligrapher":
                continue
            ds = [self.nodes[d["@id"]]["name"] for d in n.get("inDynasty", [])]
            ss = [self.nodes[d["@id"]]["name"] for d in n.get("skilledInScript", [])]
            dynasty_count.update(ds)
            script_count.update(ss)
            for d in ds:
                for s in ss:
                    cross[(d, s)] += 1
        scripts = [s for s, _ in script_count.most_common(8)]
        dynasties = [d for d in order if dynasty_count[d]]
        return {"influence": influence, "longestChain": [{"id": x, "name": self.nodes[x]["name"]} for x in best],
                "domainsUsed": list(domains), "lineageNodes": len(members), "lineageEdges": len(set(edges)),
                "components": len(sizes), "largestComponent": max(sizes.values()) if sizes else 0,
                "dynastyCount": [{"name": d, "count": dynasty_count[d]} for d in dynasties],
                "scripts": scripts, "cross": [{"dynasty": d, "script": s, "count": cross[(d, s)]} for d in dynasties for s in scripts]}
