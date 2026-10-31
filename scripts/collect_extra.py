"""补采：书体和名作条目（分类遍历没有收到）、人物的 Wikidata 结构化属性、cnSchema 发布文件。
可重复运行，已有结果会跳过。用法：python3 -I scripts/collect_extra.py <输出目录>
"""
import json, os, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import UA, call, fetch

SCRIPTS = "楷书 行书 草书 隶书 篆书 章草 今草 狂草 小篆 大篆 瘦金体 魏碑 飞白书 馆阁体 甲骨文 金文".split()
WORKS = """兰亭集序 祭侄文稿 黄州寒食诗帖 九成宫醴泉铭 多宝塔碑 玄秘塔碑 颜勤礼碑 麻姑仙坛记 神策军碑 雁塔圣教序 集王圣教序
孔子庙堂碑 皇甫诞碑 化度寺碑 书谱 自叙帖 古诗四帖 蜀素帖 苕溪诗帖 松风阁诗帖 瘗鹤铭 张迁碑 曹全碑 石门颂 礼器碑 乙瑛碑 史晨碑
石鼓文 峄山刻石 泰山刻石 郑文公碑 张猛龙碑 龙门二十品 爨宝子碑 爨龙颜碑 平复帖 伯远帖 快雪时晴帖 中秋帖 三希堂法帖 淳化阁帖
散氏盘 毛公鼎 广艺舟双楫 艺舟双楫 笔阵图 书断 续书谱 丧乱帖 十七帖 洛神赋十三行 宣示表 荐季直表 千字文 急就章 韭花帖 张好好诗
李思训碑 麓山寺碑 胆巴碑 赤壁赋 寒食帖 鸭头丸帖 肚痛帖 石门铭 嵩高灵庙碑 好大王碑 张黑女墓志 崔敬邕墓志""".split()
THEORY = ["书法", "中国书法", "永字八法", "文房四宝", "碑学", "帖学", "馆阁体", "二王", "颜柳", "宋四家", "初唐四大家", "吴门书派", "扬州八怪", "西泠印社", "中国书法家协会"]
WD_PROPS = {"P569": "出生", "P570": "去世", "P19": "出生地", "P20": "去世地", "P21": "性别", "P27": "国籍或朝代", "P106": "职业",
            "P1066": "师从", "P802": "弟子", "P22": "父亲", "P25": "母亲", "P26": "配偶", "P40": "子女", "P3373": "兄弟姐妹",
            "P800": "代表作", "P135": "流派", "P170": "作者", "P571": "创作时间", "P276": "收藏地", "P195": "藏品集", "P186": "材质"}


def pages_extra(out):
    path = os.path.join(out, "pages_extra.jsonl")
    done = {}
    if os.path.exists(path):
        done = {json.loads(l)["seed"]: 1 for l in open(path, encoding="utf-8")}
    with open(path, "a", encoding="utf-8") as f:
        for kind, seeds in (("书体", SCRIPTS), ("作品", WORKS), ("概念", THEORY)):
            for seed in seeds:
                if seed in done:
                    continue
                d = call(action="query", list="search", srsearch=seed, srlimit="1", srnamespace="0")
                exact = call(action="query", titles=seed, redirects="1", converttitles="1")["query"]["pages"][0]
                title = exact["title"] if "missing" not in exact else None
                if not title:
                    print("未找到", seed, "搜索首条：", [x["title"] for x in d["query"]["search"]], flush=True)
                    f.write(json.dumps({"seed": seed, "title": None}, ensure_ascii=False) + "\n")
                    continue
                f.write(json.dumps({"seed": seed, "title": title, "kinds": [kind], **fetch(title)}, ensure_ascii=False) + "\n")
                f.flush()
    return path


def wikidata(out, extra_path):
    ids = set()
    for p in (os.path.join(out, "pages.jsonl"), extra_path):
        for l in open(p, encoding="utf-8"):
            q = json.loads(l).get("qid")
            if q:
                ids.add(q)
    ids = sorted(ids)
    claims, targets = {}, set()

    def wb(batch, props):
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(batch), "props": props, "languages": "zh-cn|zh-hans|zh|en", "format": "json"})
        for attempt in range(6):
            time.sleep(1.2)
            try:
                return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90))["entities"]
            except Exception as e:
                print("重试", repr(e)[:80], flush=True)
                time.sleep(20 * (attempt + 1))
        raise RuntimeError("Wikidata 请求失败")

    for i in range(0, len(ids), 50):
        for q, e in wb(ids[i:i + 50], "claims|labels").items():
            row = {}
            for prop in WD_PROPS:
                vals = []
                for c in e.get("claims", {}).get(prop, []):
                    v = c["mainsnak"].get("datavalue", {}).get("value")
                    if isinstance(v, dict) and "id" in v:
                        vals.append(v["id"]); targets.add(v["id"])
                    elif isinstance(v, dict) and "time" in v:
                        vals.append(v["time"])
                if vals:
                    row[WD_PROPS[prop]] = vals
            claims[q] = row
        print("wikidata", i, flush=True)
    labels = {}
    targets = sorted(targets)
    for i in range(0, len(targets), 50):
        for q, e in wb(targets[i:i + 50], "labels").items():
            ls = e.get("labels", {})
            for lang in ("zh-cn", "zh-hans", "zh", "en"):
                if lang in ls:
                    labels[q] = ls[lang]["value"]
                    break
    json.dump({"claims": claims, "labels": labels}, open(os.path.join(out, "wikidata.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("wikidata 完成", len(claims), len(labels), flush=True)


def cnschema(out):
    base = "https://api.github.com/repos/OpenKG-ORG/cnSchema/contents/data/releases"
    def ls(u):
        return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=40))
    rels = ls(base)
    print("cnSchema 版本", [r["name"] for r in rels], flush=True)
    latest = sorted([r for r in rels if r["type"] == "dir"], key=lambda r: r["name"])[-1]
    d = os.path.join(out, "cnschema"); os.makedirs(d, exist_ok=True)
    for x in ls(latest["url"]):
        print(x["name"], x["type"], x.get("size"), flush=True)
        if x["type"] == "file" and x.get("size", 0) < 30_000_000:
            urllib.request.urlretrieve(x["download_url"], os.path.join(d, os.path.basename(x["name"])))


if __name__ == "__main__":
    out = sys.argv[1]
    cnschema(out)
    wikidata(out, pages_extra(out))
    print("完成", flush=True)
