# -*- coding: utf-8 -*-
"""重型解析worker：平台服务用标准库跑，凡是依赖第三方库（openpyxl / pdfplumber）
的解析活儿都丢给这个脚本，由「能用那个解释器」来执行。

用法：
    python parse.py request.json      # 结果 JSON 打到 stdout

request.json: {"op": "read_xlsx", "path": "...", ...}
只依赖标准库 + 可选 pdfplumber；缺库时返回结构化错误，前端据此提示一键安装。
"""
import datetime
import json
import os
import sys
import zipfile

MAX_ROWS_DEFAULT = 500
MAX_COLS_DEFAULT = 40


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def cell_value(v):
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return int(v)
        return round(v, 6)
    if isinstance(v, (int, bool)):
        return v
    return str(v)


def need(mod, pip_name):
    raise RuntimeError("MISSING_DEP:%s:%s" % (mod, pip_name))


# --------------------------------------------------------------------------
# op: read_xlsx
# --------------------------------------------------------------------------
def read_xlsx(req):
    try:
        import openpyxl
    except ImportError:
        need("openpyxl", "openpyxl")

    path = req["path"]
    want_sheet = req.get("sheet")
    max_rows = int(req.get("max_rows", MAX_ROWS_DEFAULT))
    max_cols = int(req.get("max_cols", MAX_COLS_DEFAULT))
    header_row = int(req.get("header_row", 1))

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets = wb.sheetnames
    name = want_sheet if want_sheet in sheets else sheets[0]
    ws = wb[name]

    rows = []
    for i, r in enumerate(ws.iter_rows(values_only=True), start=1):
        if i > max_rows:
            break
        rows.append([cell_value(c) for c in r[:max_cols]])
    total = ws.max_row or len(rows)
    wb.close()

    headers = rows[header_row - 1] if rows and header_row <= len(rows) else []
    body = rows[header_row:] if header_row <= len(rows) else rows
    return {
        "sheets": sheets, "sheet": name, "headers": headers,
        "rows": body, "total_rows": total,
        "truncated": total > max_rows,
    }


# --------------------------------------------------------------------------
# op: read_docx —— 纯标准库（docx 就是 zip + xml）
# --------------------------------------------------------------------------
def _xml_text(xml):
    import re
    xml = xml.replace("</w:p>", "\n")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    import html
    return html.unescape(xml)


def read_docx(req):
    path = req["path"]
    max_chars = int(req.get("max_chars", 200000))
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        core = ""
        if "docProps/core.xml" in names:
            core = z.read("docProps/core.xml").decode("utf-8", "replace")
    text = _xml_text(xml)
    paras = [p.strip() for p in text.split("\n")]
    paras = [p for p in paras if p]
    title = paras[0] if paras else os.path.splitext(os.path.basename(path))[0]

    import re
    m = re.search(r"<dc:creator>(.*?)</dc:creator>", core)
    author = m.group(1) if m else ""
    return {"title": title, "author": author, "paragraphs": paras,
            "text": "\n".join(paras)[:max_chars],
            "chars": sum(len(p) for p in paras)}


# --------------------------------------------------------------------------
# op: read_pdf / pdf_meta
# --------------------------------------------------------------------------
def _pdf_text(path, max_pages, max_chars):
    try:
        import pdfplumber
    except ImportError:
        need("pdfplumber", "pdfplumber")
    buf, pages, chars = [], 0, 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            if max_pages and i > max_pages:
                break
            t = page.extract_text() or ""
            pages += 1
            chars += len(t)
            buf.append("\n===== 第 %d 页 =====\n%s" % (i, t))
    return "".join(buf), pages, chars


def read_pdf(req):
    path = req["path"]
    max_pages = int(req.get("max_pages", 0)) or None
    max_chars = int(req.get("max_chars", 300000))
    try:
        import pdfplumber
    except ImportError:
        need("pdfplumber", "pdfplumber")
    text, pages, chars = _pdf_text(path, max_pages, max_chars)
    meta = {}
    try:
        with pdfplumber.open(path) as pdf:
            meta = {k: str(v) for k, v in (pdf.metadata or {}).items()}
            total_pages = len(pdf.pages)
    except Exception:
        total_pages = pages
    return {"text": text[:max_chars], "pages": pages, "total_pages": total_pages,
            "chars": chars, "scanned": chars < 50, "meta": meta}


def pdf_meta(req):
    """批量取 PDF 元信息（页数/字数/是否扫描件/创建时间），不返回正文。"""
    paths = req["paths"]
    try:
        import pdfplumber
    except ImportError:
        need("pdfplumber", "pdfplumber")
    out = []
    for p in paths:
        item = {"path": p, "name": os.path.basename(p), "ok": True}
        try:
            with pdfplumber.open(p) as pdf:
                pages = len(pdf.pages)
                chars = 0
                for pg in pdf.pages[:5]:
                    chars += len(pg.extract_text() or "")
                md = pdf.metadata or {}
                item.update({
                    "pages": pages,
                    "chars": chars,
                    "scanned": chars < 50,
                    "created": str(md.get("CreationDate", "")),
                    "title": str(md.get("Title", "")),
                    "size": os.path.getsize(p),
                })
        except Exception as e:
            item.update({"ok": False, "error": str(e)})
        out.append(item)
    return {"items": out}


# --------------------------------------------------------------------------
OPS = {"read_xlsx": read_xlsx, "read_docx": read_docx,
       "read_pdf": read_pdf, "pdf_meta": pdf_meta, "ping": lambda r: {"ok": True}}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: parse.py request.json"},
                         ensure_ascii=False))
        return 1
    with open(sys.argv[1], encoding="utf-8") as fh:
        req = json.load(fh)
    op = req.get("op")
    try:
        if op not in OPS:
            raise RuntimeError("未知操作：%s" % op)
        data = OPS[op](req)
        data["ok"] = True
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("MISSING_DEP:"):
            _, mod, pip_name = msg.split(":", 2)
            data = {"ok": False, "error": "missing_dep", "module": mod, "pip": pip_name}
        else:
            data = {"ok": False, "error": msg}
    except Exception as e:
        import traceback
        data = {"ok": False, "error": str(e), "trace": traceback.format_exc()}
    sys.stdout.write(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
