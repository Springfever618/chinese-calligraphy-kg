# 中国书法知识图谱（初版）

基于中文维基百科和 Wikidata 构建，在 cnSchema 上扩展书法领域概念。规模和统计见 `output/stats.json`。

## 运行应用

第一次运行先安装依赖：

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

启动后打开 http://localhost:8766 ，载入图谱需要几秒：

```bash
.venv/bin/python app/server.py
```

应用只在本机运行，不调用外部接口，有五个页面：

| 页面 | 功能 |
|---|---|
| 问答 | 中文问句经实体链接和意图识别生成 SPARQL，答案只来自图谱，并显示证据句和来源 |
| 检索 | 按人名、字号、作品名和简介关键词检索，点击查看实体详情 |
| 师承网络 | 以某人为中心展开师从和取法网络，可按领域筛选 |
| 分析 | PageRank 影响力排名、最长师承链、各时期人数、时期与书体交叉统计 |
| SPARQL | 直接运行只读查询 |

问答支持师从、弟子、取法、再传、同门、师承谱系、两人关系、作品书写者、书体、形制、收藏地、亲属、生卒年、朝代和书体列表、计数等问法。超出范围时回答无法理解，不猜测；图谱没有记录时说明只是未收录。

问答测试：

```bash
.venv/bin/python app/test_qa.py
```

这些用例是开发时用来防止改坏的，问法已针对它们调过，通过率不能当作问答准确率写进报告。要报告准确率，请另找没参与开发的同学出题测试。

## 文件

| 路径 | 内容 |
|---|---|
| `output/calligraphy-kg.jsonld` | 图谱数据（JSON-LD） |
| `output/statements.tsv` | 每条关系的方法、证据句和来源 |
| `schema/calligraphy-schema.jsonld` | cnSchema 扩展定义 |
| `evaluation/待人工标注.csv` | 抽样 201 条，留作人工评估用，本版本未标注 |
| `data/llm_master.txt`、`data/llm_works.json` | 大模型逐句判读结果 |
| `scripts/` | 采集、清洗和构建脚本 |
| `app/` | 应用：`kg.py` 图谱访问和分析，`qa.py` 问答，`server.py` 服务，`static/` 页面 |

## 重新构建

```bash
python3 -I scripts/prepare.py
```

```bash
python3 -I scripts/prepare_famous.py
```

```bash
python3 -I scripts/build.py
```

修改 `scripts/prepare.py` 后要确认 `data/candidates.json` 的编号没有变化，否则大模型判读结果会对错句子。修改补采名单或 `scripts/prepare_famous.py` 后，同样要确认 `data/candidates_famous.json` 的编号没有变化。

## 抽取方法

| 方法 | 用于 |
|---|---|
| Wikidata | 生卒年、性别、出生地、部分师承和亲属 |
| 维基分类映射 | 所属朝代 |
| 规则 | 擅长书体 |
| 大模型判读 | 师从、取法、作品书写者、作品书体、形制和收藏地 |

大模型判读由 Claude（claude-opus-5-5）逐句完成，没有调用外部接口。人物先经正则筛出候选句，再由模型判断。师从关系还做了生卒年矛盾校验。

生卒年以维基导语括号里写明的为准，导语没有时才用 Wikidata，因为 Wikidata 常有多个候选年份（如王羲之 303 与 321）。两者不一致的条目数见 `stats.json`。重名人物不合并，次要的一位用括注区分，如“王铎（唐朝）”。

师从和取法关系同时以 `rdf:Statement` 节点保存领域、方法、证据句和来源，可以用 SPARQL 查询。

## 已知限制

- 本版本未做人工抽样评估，准确率未知。`evaluation/待人工标注.csv` 留有 201 条抽样，需要时可自行标注。
- 数据只来自中文维基和 Wikidata，没有覆盖百度百科和专业书法文献，召回率有限。
- 师承关系包含学术、绘画等领域，使用时请按 `relationDomain` 筛选。
- 新增的 Person 节点没有消歧，文中提到的同名者会归到正文最长的那位。
- 古文的“隶书”常指今天的楷书，规则抽取没有区分，晋和南北朝的“擅长隶书”可能偏多。
- 分类遍历漏掉的名家按名单单独补采（`scripts/collect_famous.py`），名单由 Claude 依书法史知识拟定。正文和 Wikidata 都没写书法的（如康有为、阮元、梁启超）只收录为普通人物，不标书法家。张雨、沈粲、查士标、周天球、张宗祥、来楚生、丁道护、吴说、陆维钊、俞和等在中文维基查不到对应条目，胡震的条目过短，都未补入，名单之外也可能还有遗漏。
- 应用里的常见称呼表（如卫夫人、苏东坡）只用于理解问题，不属于图谱数据。
- 部分条目的正文本身可能有误。
- 实体 URI 暂用 `urn:cn-calligraphy-kg:`，还不能在浏览器中直接打开，正式发布到 OpenKG 时再换成可访问的地址。
- 在世人物不收录亲属关系。

## 许可

代码（`app/`、`scripts/`）采用 MIT 许可，见 `LICENSE`。

图谱数据、`data/` 下的维基采集内容和证据句来自中文维基百科及其贡献者，遵循 CC BY-SA 4.0，再发布时须署名并以相同协议共享。每条关系的来源页面见 `output/statements.tsv`。Wikidata 数据为 CC0。

cnSchema 的原始文件不随仓库分发。重新构建前，请从 [OpenKG-ORG/cnSchema](https://github.com/OpenKG-ORG/cnSchema) 的 `data/releases` 下载最新版本的 `cns-core.jsonld`，放到 `data/raw/cnschema/`。
