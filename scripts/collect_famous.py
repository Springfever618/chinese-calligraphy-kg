"""补采名家：分类遍历漏掉的书法史重要人物。名单由 Claude 依书法史知识拟定，不是从数据源得到的。
可重复运行，已有结果会跳过。用法：python3 -I scripts/collect_famous.py <输出目录>
"""
import json, os, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import UA, call, fetch
from collect_extra import WD_PROPS

SEEDS = """王导 崔浩 郑道昭 贺知章 武则天 宋高宗 陆游 范成大 姜夔 文天祥 赵孟坚 鲜于枢 虞集 杨维桢 倪瓒 吴镇 张雨 柯九思 宋濂 解缙 沈粲 唐寅 陈淳
八大山人 石涛 查士标 乾隆帝 桂馥 梁启超 陆机 杜牧 朱熹 沈周 康熙帝 阮元 康有为 李叔同 章太炎 罗振玉 陆维钊 潘天寿 蔡羽 周天球 何震 陈洪绶 顾炎武
陈鸿寿 黄慎 高凤翰 汪士慎 李鱓 孙星衍 陈介祺 张宗祥 吴湖帆 来楚生 嵇康 王廙 谢安 萧衍 萧纲 丁道护 李白 贯休 钱俶 欧阳修 司马光 王安石 文同 吴说
张孝祥 管道升 危素 陶宗仪 徐有贞 王守仁 张凤翼 孙承泽 周亮工 朱彝尊 汪由敦 梁巘 姚鼐 胡震""".split()
# 同名条目或消歧义页要指定条目名
TITLES = {"吴镇": "吴镇 (元朝画家)", "陈淳": "陳淳 (畫家)", "陆维钊": "陆维钊 (画家)", "何震": "何震 (明朝)", "张凤翼": "张凤翼 (戏曲家)"}


def wikidata(ids):
    claims, targets, labels = {}, set(), {}

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
        for q, e in wb(ids[i:i + 50], "claims").items():
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
    targets = sorted(targets)
    for i in range(0, len(targets), 50):
        for q, e in wb(targets[i:i + 50], "labels").items():
            ls = e.get("labels", {})
            for lang in ("zh-cn", "zh-hans", "zh", "en"):
                if lang in ls:
                    labels[q] = ls[lang]["value"]
                    break
    return {"claims": claims, "labels": labels}


def main(out):
    path = os.path.join(out, "pages_famous.jsonl")
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["seed"] for l in open(path, encoding="utf-8")}
    with open(path, "a", encoding="utf-8") as f:
        for seed in SEEDS:
            if seed in done:
                continue
            page = call(action="query", titles=TITLES.get(seed, seed), redirects="1", converttitles="1")["query"]["pages"][0]
            if "missing" in page:
                print("未找到", seed, flush=True)
                f.write(json.dumps({"seed": seed, "title": None}, ensure_ascii=False) + "\n")
                continue
            f.write(json.dumps({"seed": seed, "title": page["title"], **fetch(page["title"])}, ensure_ascii=False) + "\n")
            f.flush()
    ids = sorted({json.loads(l).get("qid") for l in open(path, encoding="utf-8")} - {None})
    json.dump(wikidata(ids), open(os.path.join(out, "wikidata_famous.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("完成", len(ids), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
