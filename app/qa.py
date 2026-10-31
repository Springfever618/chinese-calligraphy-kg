"""问答：实体链接 + 意图识别 -> SPARQL 模板 -> 执行并组织答案。不调用大模型，答案只来自图谱。"""
import re

from kg import REL_LABEL

DYNASTY_ALIAS = {"商代": "商朝", "殷商": "商朝", "战国时期": "战国", "秦代": "秦朝", "汉代": "汉朝", "东汉": "汉朝", "西汉": "汉朝", "三国时期": "三国", "晋代": "晋朝", "东晋": "晋朝", "西晋": "晋朝",
                 "南朝": "南北朝", "北朝": "南北朝", "隋代": "隋朝", "唐代": "唐朝", "五代": "五代十国", "宋代": "宋朝", "北宋": "宋朝", "南宋": "宋朝", "辽代": "辽金", "金代": "辽金",
                 "元代": "元朝", "明代": "明朝", "清代": "清朝", "民国": "中华民国", "近代": "中华民国", "当代": "中华人民共和国", "新中国": "中华人民共和国",
                 "商": "商朝", "秦": "秦朝", "汉": "汉朝", "晋": "晋朝", "隋": "隋朝", "唐": "唐朝", "宋": "宋朝", "元": "元朝", "明": "明朝", "清": "清朝"}
SINGLE_DYNASTY = re.compile(r"^(?:请问)?([商秦汉晋隋唐宋元明清])(?=[朝代的有人]|[^一-鿿]|擅|书)")
PEOPLE = ("Calligrapher", "Person")
CALLI_DOMAINS = ("书法", "书画", "篆刻", "未标注")
WORK = ("CalligraphyWork",)


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


class QA:
    def __init__(self, kg):
        self.kg = kg

    def _result(self, intent, answer, sparql=None, items=None, entities=None, note=None, status="ok"):
        return {"status": status, "intent": intent, "answer": answer, "sparql": sparql, "items": items or [], "entities": entities or [], "note": note}

    def _names(self, items, limit=12, unit="项"):
        names = [i["name"] for i in items]
        return "、".join(names[:limit]) + (f" 等 {len(names)} {unit}" if len(names) > limit and unit else ("等" if len(names) > limit else ""))

    def _item(self, row, subject=None, predicate=None, inverse=False):
        name = row["name"]
        item = {"name": name, "id": row.get("id")}
        if predicate and subject:
            key = (name, predicate, subject) if inverse else (subject, predicate, name)
            e = self.kg.ev(*key)
            if e:
                item.update(domain=e["领域"], method=e["方法"], evidence=e["证据"], source=e["来源"])
        return item

    def _relation(self, intent, subject, predicate, inverse, phrase, empty_hint=""):
        s = esc(subject["name"])
        pred = ("shufa:" if predicate not in ("parent", "children", "sibling", "spouse") else "cns:") + predicate
        if inverse:
            q = f'SELECT DISTINCT ?id ?name WHERE {{ ?x cns:name "{s}" . ?id {pred} ?x ; cns:name ?name . }} ORDER BY ?name'
        else:
            q = f'SELECT DISTINCT ?id ?name WHERE {{ ?x cns:name "{s}" ; {pred} ?id . ?id cns:name ?name . }} ORDER BY ?name'
        items = [self._item(r, subject["name"], predicate, inverse) for r in self.kg.sparql(q)]
        ent = [self.kg.brief(subject)]
        if not items:
            return self._result(intent, f"图谱里没有{subject['name']}的{phrase}记录。{empty_hint}这只说明图谱未收录，不代表事实上没有。", q, [], ent, status="empty")
        return self._result(intent, f"{subject['name']}的{phrase}：{self._names(items)}。", q, items, ent)

    def _literal(self, intent, subject, predicate, phrase):
        s = esc(subject["name"])
        q = f'SELECT DISTINCT ?value WHERE {{ ?x cns:name "{s}" ; shufa:{predicate} ?value . }}'
        rows = self.kg.sparql(q)
        ent = [self.kg.brief(subject)]
        if not rows:
            return self._result(intent, f"图谱里没有{subject['name']}的{phrase}记录。这只说明图谱未收录，不代表事实上没有。", q, [], ent, status="empty")
        items = []
        for r in rows:
            e = self.kg.ev(subject["name"], predicate, r["value"]) or {}
            items.append({"name": r["value"], "evidence": e.get("证据", ""), "method": e.get("方法", ""), "source": e.get("来源", "")})
        return self._result(intent, f"{subject['name']}的{phrase}：{self._names(items)}。", q, items, ent)

    def _dynasty(self, question, mentioned):
        for name, cands in mentioned:
            if cands[0]["@type"] == "Dynasty":
                return name
        for alias in sorted(DYNASTY_ALIAS, key=len, reverse=True):
            if len(alias) >= 2 and alias in question:
                return DYNASTY_ALIAS[alias]
        m = SINGLE_DYNASTY.match(question)
        return DYNASTY_ALIAS[m.group(1)] if m else None

    def answer(self, question):
        raw = question.strip()
        q = raw.replace("？", "").replace("?", "").replace("《", "").replace("》", "").strip()
        if not q:
            return self._result("空问题", "请输入问题。", status="unknown")
        mentioned = self.kg.link(q)
        # 字号重名时要求澄清，除非同一句里有更明确的实体
        ambiguous = [(m, c) for m, c in mentioned if len(c) > 1]
        if ambiguous:
            m, c = ambiguous[0]
            return self._result("需要澄清", f"“{m}”对应多个实体：{'、'.join(x['name'] for x in c)}。请用正式名称再问一次。", entities=[self.kg.brief(x) for x in c], status="ambiguous")
        ents = [c[0] for m, c in mentioned]
        people = [e for e in ents if e["@type"] in PEOPLE]
        works = [e for e in ents if e["@type"] in WORK]
        scripts = [e for e in ents if e["@type"] == "ScriptStyle"]
        dynasty = self._dynasty(q, mentioned)

        # 两人关系
        if len(people) >= 2 and re.search(r"关系|联系|有关|渊源|路径|怎么连|如何连", q):
            return self._between(people[0], people[1])

        if people:
            r = self._person(q, people[0])
            if r:
                return r
        if works:
            r = self._work(q, works[0])
            if r:
                return r
        r = self._listing(q, dynasty, scripts)
        if r:
            return r
        rest = q
        for m, _ in mentioned:
            rest = rest.replace(m, "")
        if ents and (len(re.sub(r"[的吗呢啊]", "", rest)) == 0 or re.fullmatch(r"(是什么|是什么意思|是谁|的?简介|介绍一?下?)", rest)):  # 只输入名字或问“是什么”时给出简介
            return self._about(ents[0])
        hits = self.kg.search(q, limit=5)
        return self._result("无法理解", "这个问题超出了当前支持的问法，我不会猜测答案。可以换成下方示例的问法，或查看相关实体。", entities=hits, status="unknown")

    # ---------- 人物 ----------
    def _person(self, q, p):
        n = p["name"]
        if re.search(r"(老师|师父|师傅|恩师|师长)的(老师|师父|师傅)|师祖|师公", q):
            return self._two_hop(p)
        if re.search(r"(学生|弟子|徒弟|门生)的(学生|弟子|徒弟|门生)|再传|徒孙", q):
            return self._two_hop_down(p)
        if re.search(r"谱系|师承链|师承脉络|传承脉络|师承关系链|一脉", q):
            return self._ancestry(p)
        if re.search(r"同门|师兄|师弟|师姐|师妹|同学", q):
            return self._fellow(p)
        if re.search(r"(谁|哪些人|哪几位|什么人).{0,6}(师从|师承|拜|跟|向|从学)|学生|弟子|徒弟|门生|门人|传人|教过|收过|教了", q) or re.search(r"(师从|师承|拜师于?|受教于|跟随?)" + re.escape(n) + r".{0,6}(谁|哪些|有|的人)", q):
            return self._relation("弟子", p, "studiedUnder", True, "弟子")
        if re.search(r"(谁|哪些人|哪些书法家|什么人|哪几位).{0,6}(取法|学习?过?|效法|师法|临摹|受.{0,2}影响)|影响了(谁|哪些)", q) or re.search(r"(取法|效法|师法|学)" + re.escape(n) + r".{0,4}(谁|哪些|有|的人)", q):
            return self._relation("被取法", p, "emulated", True, "取法者")
        if re.search(r"取法|效法|师法|临摹|受.{0,4}影响|学[的过了]?(谁|哪)", q):
            return self._relation("取法", p, "emulated", False, "取法对象")
        if re.search(r"老师|师父|师傅|师从|师承|拜师|师事|跟(谁|随)|受教|向谁学|从谁学|谁教|谁是.*师|学的书法|学书", q):
            return self._relation("师从", p, "studiedUnder", False, "老师", "可以再查这位书家的取法对象。")
        if re.search(r"代表作|作品|名作|写过|写了|书写了|有什么帖|有哪些帖|法帖|碑帖|著名.*(帖|碑)", q):
            return self._relation("作品", p, "calligrapher", True, "作品")
        if re.search(r"擅长|善于|精于|工于|书体|字体|写什么体|什么体|哪种体", q):
            return self._relation("擅长书体", p, "skilledInScript", False, "擅长书体")
        if re.search(r"朝代|哪个朝|什么朝|哪朝|什么时代|哪个时代|什么时期|哪个时期|哪代|什么年代", q):
            return self._relation("所属朝代", p, "inDynasty", False, "所属朝代")
        if re.search(r"父亲|母亲|父母|爸爸|妈妈|家长", q):
            return self._relation("亲属", p, "parent", False, "父母")
        if re.search(r"儿子|女儿|子女|孩子|后代", q):
            return self._relation("亲属", p, "children", False, "子女（只收录图谱内的书法家）")
        if re.search(r"兄弟|姐妹|哥哥|弟弟|姐姐|妹妹", q):
            return self._relation("亲属", p, "sibling", False, "兄弟姐妹（只收录图谱内的书法家）")
        if re.search(r"妻子|丈夫|配偶|夫人|老婆|老公", q):
            return self._relation("亲属", p, "spouse", False, "配偶（只收录图谱内的书法家）")
        if re.search(r"生卒|活了|寿命|享年|在世", q):
            return self._life(p)
        if re.search(r"(哪年|何年|什么时候|何时|哪一年).{0,3}(出生|生)|(出生|生于).{0,3}(哪年|何年|什么时候|何时|哪一年)|生年", q):
            return self._field(p, "birthDate", "出生年份")
        if re.search(r"(哪年|何年|什么时候|何时|哪一年).{0,3}(去世|逝世|死|卒)|(去世|逝世|卒于|死于).{0,3}(哪年|何年|什么时候|何时|哪一年)|卒年", q):
            return self._field(p, "deathDate", "去世年份")
        if re.search(r"哪里人|何处人|籍贯|出生地|哪儿人|生于哪里|生在哪|出生在|哪人", q):
            return self._field(p, "birthPlace", "出生地")
        if re.search(r"字什么|字号|别名|别号|号什么|又名|又称", q):
            return self._aliases(p)
        if re.search(r"是谁|简介|介绍|什么人|生平|谁是", q) or q == n:
            return self._about(p)
        return None

    def _field(self, p, field, phrase):
        q = f'SELECT ?value WHERE {{ ?x cns:name "{esc(p["name"])}" ; cns:{field} ?value . }}'
        rows = self.kg.sparql(q)
        ent = [self.kg.brief(p)]
        if not rows:
            return self._result(phrase, f"图谱里没有{p['name']}的{phrase}记录。这只说明图谱未收录，不代表事实上没有。", q, [], ent, status="empty")
        v = rows[0]["value"]
        if field in ("birthDate", "deathDate"):
            v = self.kg.fmt_year(int(v))
        return self._result(phrase, f"{p['name']}的{phrase}：{v}。", q, [{"name": v}], ent)

    def _life(self, p):
        q = f'SELECT ?birth ?death WHERE {{ ?x cns:name "{esc(p["name"])}" . OPTIONAL {{ ?x cns:birthDate ?birth }} OPTIONAL {{ ?x cns:deathDate ?death }} }}'
        life = self.kg.life(p)
        if not life:
            return self._result("生卒年", f"图谱里没有{p['name']}的生卒年记录。", q, [], [self.kg.brief(p)], status="empty")
        return self._result("生卒年", f"{p['name']}的生卒年：{life}。", q, [], [self.kg.brief(p)])

    def _aliases(self, p):
        q = f'SELECT ?alias WHERE {{ ?x cns:name "{esc(p["name"])}" ; cns:alternateName ?alias . }}'
        rows = self.kg.sparql(q)
        if not rows:
            return self._result("字号", f"图谱里没有{p['name']}的字号记录。", q, [], [self.kg.brief(p)], status="empty")
        return self._result("字号", f"{p['name']}的字号：{'、'.join(r['alias'] for r in rows)}。", q, [{"name": r["alias"]} for r in rows], [self.kg.brief(p)])

    def _about(self, e):
        d = e.get("description")
        q = f'SELECT ?description WHERE {{ ?x cns:name "{esc(e["name"])}" ; cns:description ?description . }}'
        if not d:
            why = "这个人物是作为其他人物的老师或学生被提到的。" if e["@type"] in PEOPLE else f"可以问“{e['name']}有哪些书法家”。"
            return self._result("简介", f"图谱收录了{e['name']}，但没有简介。{why}", q, [], [self.kg.brief(e)], status="empty")
        return self._result("简介", d, q, [], [self.kg.brief(e)])

    def _two_hop(self, p):
        s = esc(p["name"])
        q = f'''SELECT DISTINCT ?midName ?id ?name WHERE {{
  ?x cns:name "{s}" ; shufa:studiedUnder ?mid .
  ?mid cns:name ?midName ; shufa:studiedUnder ?id .
  ?id cns:name ?name .
}}'''
        rows = self.kg.sparql(q)
        if not rows:
            return self._result("师祖", f"图谱里没有{p['name']}老师的老师记录。", q, [], [self.kg.brief(p)], status="empty")
        items = [{"name": r["name"], "id": r["id"], "via": r["midName"]} for r in rows]
        return self._result("师祖", "；".join(f"{r['name']}（经{r['midName']}）" for r in rows[:12]) + f"，是{p['name']}老师的老师。", q, items, [self.kg.brief(p)])

    def _two_hop_down(self, p):
        s = esc(p["name"])
        q = f'''SELECT DISTINCT ?midName ?id ?name WHERE {{
  ?x cns:name "{s}" .
  ?mid shufa:studiedUnder ?x ; cns:name ?midName .
  ?id shufa:studiedUnder ?mid ; cns:name ?name .
}}'''
        rows = self.kg.sparql(q)
        if not rows:
            return self._result("再传弟子", f"图谱里没有{p['name']}的再传弟子记录。", q, [], [self.kg.brief(p)], status="empty")
        items = [{"name": r["name"], "id": r["id"], "via": r["midName"]} for r in rows]
        return self._result("再传弟子", f"{p['name']}的再传弟子：" + "；".join(f"{r['name']}（经{r['midName']}）" for r in rows[:12]) + "。", q, items, [self.kg.brief(p)])

    def _ancestry(self, p):
        s = esc(p["name"])
        q = f'''SELECT DISTINCT ?id ?name WHERE {{
  ?x cns:name "{s}" ; shufa:studiedUnder+ ?id .
  ?id cns:name ?name .
}}'''
        items = [{"name": r["name"], "id": r["id"]} for r in self.kg.sparql(q)]
        if not items:
            return self._result("师承谱系", f"图谱里没有{p['name']}的师承记录。", q, [], [self.kg.brief(p)], status="empty")
        return self._result("师承谱系", f"沿师从关系向上追溯，{p['name']}的师承前辈有：{self._names(items)}。", q, items, [self.kg.brief(p)])

    def _fellow(self, p):
        s = esc(p["name"])
        q = f'''SELECT DISTINCT ?id ?name ?teacherName WHERE {{
  ?x cns:name "{s}" ; shufa:studiedUnder ?t .
  ?t cns:name ?teacherName .
  ?id shufa:studiedUnder ?t ; cns:name ?name .
  FILTER(?id != ?x)
}} ORDER BY ?teacherName'''
        rows = self.kg.sparql(q)
        if not rows:
            return self._result("同门", f"图谱里没有{p['name']}的同门记录。", q, [], [self.kg.brief(p)], status="empty")
        items = [{"name": r["name"], "id": r["id"], "via": r["teacherName"]} for r in rows]
        return self._result("同门", f"{p['name']}的同门：" + "；".join(f"{r['name']}（同师{r['teacherName']}）" for r in rows[:12]) + (f" 等 {len(rows)} 人。" if len(rows) > 12 else "。"), q, items, [self.kg.brief(p)])

    def _between(self, a, b):
        # 先只走师从，走不通再加入取法：实际授受比共同取法某人更有意义
        steps = self.kg.path(a["@id"], b["@id"], CALLI_DOMAINS, ("studiedUnder",))
        if steps is None:
            steps = self.kg.path(a["@id"], b["@id"], CALLI_DOMAINS)
        ents = [self.kg.brief(a), self.kg.brief(b)]
        note = "路径用广度优先搜索计算，不是 SPARQL。优先只走师从关系，走不通再加入取法；只用书法、书画、篆刻和未标注领域，方向不限，所以相连不等于两人有直接授受。"
        if steps is None:
            return self._result("两人关系", f"图谱的师承网络里，{a['name']}和{b['name']}之间没有连通路径。这只说明图谱未收录，不代表事实上没有关系。", None, [], ents, note, "empty")
        if not steps:
            return self._result("两人关系", f"这是同一个人：{a['name']}。", None, [], ents, note)
        text = "；".join(f"{s['student']}{s['label']}{s['teacher']}" for s in steps)
        items = [{"name": f"{s['student']} → {s['teacher']}", "domain": s["domain"], "evidence": s["evidence"], "source": s["source"], "label": s["label"]} for s in steps]
        return self._result("两人关系", f"{a['name']}和{b['name']}在师承网络里经 {len(steps)} 步相连：{text}。", None, items, ents, note)

    # ---------- 作品 ----------
    def _work(self, q, w):
        if re.search(r"谁写|谁书|谁的|作者|书写者|书家|出自谁|哪位|何人", q):
            return self._relation("作品书写者", w, "calligrapher", False, "书写者")
        if re.search(r"谁编|编者|谁编选|谁主持|编选", q):
            return self._relation("作品编者", w, "compiler", False, "编者")
        if re.search(r"书体|字体|什么体|哪种体", q):
            return self._relation("作品书体", w, "writtenInScript", False, "书体")
        if re.search(r"藏在|藏于|收藏|现藏|在哪|哪里|何处|哪个博物馆", q):
            return self._literal("作品收藏地", w, "heldBy", "收藏地")
        if re.search(r"形制|类型|什么类|是碑|是帖|属于", q):
            return self._literal("作品形制", w, "workForm", "形制")
        if re.search(r"是什么|简介|介绍", q) or q == w["name"]:
            return self._about(w)
        return None

    # ---------- 列表和计数 ----------
    def _listing(self, q, dynasty, scripts):
        held = re.search(r"(北京故宫博物院|台北故宫博物院|西安碑林|上海博物馆|岱庙)", q)
        count = bool(re.search(r"多少|几位|几个|几人|数量", q))
        if held and re.search(r"作品|藏|哪些", q):
            return self._list_query("收藏地列表", f'?id shufa:heldBy "{held.group(1)}" ; a shufa:CalligraphyWork ; cns:name ?name .', f"{held.group(1)}收藏的作品", count, f"图谱里收藏地记录很少（共 15 条），结果不代表{held.group(1)}的全部藏品。")
        is_work = bool(re.search(r"作品|碑|帖|名作", q))
        script = scripts[0]["name"] if scripts else None
        clauses, label = [], ""
        if is_work and (script or re.search(r"有哪些|多少|几", q)):
            clauses.append("?id a shufa:CalligraphyWork ; cns:name ?name .")
            if script:
                clauses.append(f'?id shufa:writtenInScript ?s . ?s cns:name "{script}" .')
                label = f"{script}作品"
            else:
                label = "作品"
            return self._list_query("作品列表", "\n  ".join(clauses), label, count)
        if dynasty or script or re.search(r"书法家|书家", q):
            if not re.search(r"有哪些|哪些|有谁|谁|列出|列举|多少|几位|几个|几人|数量|书法家|书家", q):
                return None
            clauses.append("?id a shufa:Calligrapher ; cns:name ?name .")
            if dynasty:
                clauses.append(f'?id shufa:inDynasty ?d . ?d cns:name "{dynasty}" .')
                label += dynasty
            if script:
                clauses.append(f'?id shufa:skilledInScript ?s . ?s cns:name "{script}" .')
                label += f"擅长{script}的"
            label += "书法家"
            note = "擅长书体由规则从正文抽取，只覆盖正文明确写出的人物，结果偏少。" if script else None
            return self._list_query("书法家列表", "\n  ".join(clauses), label, count, note)
        return None

    def _list_query(self, intent, where, label, count, note=None):
        q = f"SELECT DISTINCT ?id ?name WHERE {{\n  {where}\n}} ORDER BY ?name"
        items = [{"name": r["name"], "id": r["id"]} for r in self.kg.sparql(q)]
        if not items:
            return self._result(intent, f"图谱里没有符合条件的{label}。这只说明图谱未收录，不代表事实上没有。", q, [], [], note, "empty")
        # 按关系数量排序，让著名人物靠前
        items.sort(key=lambda i: -(len(self.kg.out[i["id"]]) + len(self.kg.into[i["id"]])))
        unit = "位" if "书法家" in label else "件"
        if count:
            return self._result(intent + "计数", f"图谱收录的{label}共 {len(items)} {unit}。", q, items, [], note)
        return self._result(intent, f"图谱收录的{label}共 {len(items)} {unit}，包括：{self._names(items, unit='')}。", q, items, [], note)
