# -*- coding: utf-8 -*-
"""晨会分享 docx -> txt（每行 `序号\\t段落文本`，UTF-8）。

纯标准库实现（zipfile + ElementTree），不依赖 python-docx，因为沙箱解释器
的依赖集不固定（managed 3.13.12 是空的，Doubao 沙箱才有 openpyxl 等）。

用法:
  python docx2txt.py <Report根目录> [--out <txt输出目录>] [--force] [--limit N]

默认只处理还没有对应 txt 的文件（增量）；--force 则全部重抽。
"""
import os
import sys
import zipfile
import argparse
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PREFIX = "晨会分享"


def _para_text(p):
    """拼一个 <w:p> 内的文字，处理 <w:t> / <w:tab/> / <w:br/>。"""
    parts = []
    for node in p.iter():
        tag = node.tag
        if tag == W + "t":
            parts.append(node.text or "")
        elif tag == W + "tab":
            parts.append("\t")
        elif tag == W + "br":
            parts.append("\n")
    # 压缩空白但保留中文间的单空格
    return "".join(parts).replace("\r", " ").strip()


def docx_paragraphs(path):
    """返回该 docx 的非空段落列表。"""
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                return []
            xml = z.read("word/document.xml")
    except Exception as exc:
        print("  !! 打不开 %s: %s" % (os.path.basename(path), exc))
        return []
    try:
        root = ET.fromstring(xml)
    except Exception as exc:
        print("  !! 解析失败 %s: %s" % (os.path.basename(path), exc))
        return []
    body = root.find(W + "body")
    if body is None:
        return []
    out = []
    for p in body.iter(W + "p"):
        t = _para_text(p)
        if t:
            out.append(t)
    return out


def find_docx(root_dir):
    """找晨会分享*.docx，跳过 Word 临时锁文件（~$ 开头）。"""
    items = []
    for name in sorted(os.listdir(root_dir)):
        if not name.lower().endswith(".docx"):
            continue
        if name.startswith("~$") or name.startswith("~"):
            continue
        if not name.startswith(PREFIX):
            continue
        items.append(os.path.join(root_dir, name))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="Report 根目录（放晨会分享*.docx 的地方）")
    ap.add_argument("--out", default="", help="txt 输出目录，默认 <src>/_analysis/source_txt")
    ap.add_argument("--force", action="store_true", help="已存在也重新抽取")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=不限）")
    args = ap.parse_args()

    src = args.src
    out_dir = args.out or os.path.join(src, "_analysis", "source_txt")
    os.makedirs(out_dir, exist_ok=True)

    files = find_docx(src)
    if not files:
        print("未找到 %s*.docx（src=%s）" % (PREFIX, src))
        return 1
    print("发现 %d 份晨会 docx" % len(files))

    done = skipped = failed = 0
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        dst = os.path.join(out_dir, stem + ".txt")
        if os.path.exists(dst) and not args.force:
            skipped += 1
            continue
        paras = docx_paragraphs(path)
        if not paras:
            print("  -- 无正文，跳过: %s" % stem)
            failed += 1
            continue
        with open(dst, "w", encoding="utf-8") as fh:
            for i, t in enumerate(paras, 1):
                fh.write("%d\t%s\n" % (i, t))
        done += 1
        print("  ++ %s -> %d 段" % (stem, len(paras)))
        if args.limit and done >= args.limit:
            print("(达到 --limit %d，停止)" % args.limit)
            break

    print("完成: 新增 %d / 跳过 %d / 失败 %d -> %s" % (done, skipped, failed, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
