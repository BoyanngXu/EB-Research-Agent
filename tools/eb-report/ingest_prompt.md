# 晨会入库「一键触发」提示词
# 唯一来源：本文件。改完保存后刷新 Report 页即可生效（按 mtime 缓存，无需重启平台）。

你现在执行「晨会分享记录增量处理」：按 skill
`morning-note-ingest`（C:\Users\<用户名>\.workbuddy\skills\morning-note-ingest\SKILL.md）
定义的流程，把下面目录里的新晨会记录一键入库，并重建板块观点命中回测报告。
若该 skill 未加载，先读它的 SKILL.md 再动手，全程以 SKILL.md 的「关键事实」为准。

【当前状态】（平台读取时的快照，可能已过时；动手前以实际磁盘为准）
- Report 根目录：__ROOT__
- 数据/产物目录：__ANALYSIS__
- 已转 txt：__N_TXT__ 篇；已提取 json：__N_ANNO__ 篇
- 检测到的新晨会文件（__PENDING__ 份）：
__NEW_LIST__

【执行流程】（Python 脚本一律在 C:\Users\<用户名>\Desktop 根目录运行）
1. `python C:\Users\<用户名>\.workbuddy\skills\morning-note-ingest\scripts\detect_new.py`
   重新检测。返回空数组且上面清单也为空 → 直接回我「暂无新晨会」即可结束。
2. kind=="docx" 的先 `docx_to_txt.py <path>` 转 txt（已有 txt 跳过）。
3. 由你精读该 txt 全文，严格按 `__ANALYSIS__/schema.md` 输出**一个 JSON 数组**（每篇 1 个对象），
   写成 `<date>.json`（UTF-8）落到 `__ANALYSIS__/source_txt/`。
   重点填满 `stocks[]` 的 `{name, sector, dir, logic, anchor, quote}`：全篇提及标的宁多勿漏，
   `quote` 必须逐字摘录原文，禁止臆造文档里没有的信息。
4. `merge_record.py <date>.json` 并进《晨会分享分析总表.xlsx》的「标的明细」（同 标的+日期 去重）。
5. 若出现**新标的名**才需要：`python C:\Users\<用户名>\Desktop\fetch_stageA.py`
   与 `python C:\Users\<用户名>\Desktop\fetch_klines.py`（需联网）。旧数据不受影响，
   但缺这两步的新标的进不了图，必须确认它在 resolved_ok.json 有代码、在 _bt_quote_cache_full.json 有行情。
6. `python C:\Users\<用户名>\Desktop\build_report.py`（必做）重建
   `F观点命中回测_板块.html`。**不要**再手工跑 inject_theme.py / patch_board_quote.py
   （其逻辑已并入 build_report.py，重跑不会丢主题分层与原话盒）。

【纪律】
- 唯一数据源是总表「标的明细」sheet；不要另建数据源或改其他 sheet 的结构。
- 前置文件缺失（codemap_qt.json / resolved_ok.json / 4 个指数文件 / _bt_quote_cache_full.json）时，
  先告诉我缺哪个、怎么补，不要带着缺失硬跑。
- 每步跑完确认产物再进下一步；任一步失败就停下说明原因，不要静默跳过或猜着往下走。
- 重建前如需回退，先自己 `copy F观点命中回测_板块.html <时间戳>.bak` 备一份。

【完成后汇报】
- 本次新入库的晨会日期（YYYYMMDD）；
- 新增/更新的标的数，以及哪些标的因缺代码或行情没进图；
- `F观点命中回测_板块.html` 是否已重建、板块数变化、主题命中率与原话盒是否仍在。
