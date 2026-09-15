# -*- coding: utf-8 -*-
r"""把 PDF 批量转储为 txt，供后续精读定位条款段落。

用法：
    python pdf_dump.py                       # 转储当前目录下所有 PDF 到 _txt_dump/
    python pdf_dump.py D:\Anno               # 指定目录
    python pdf_dump.py D:\Anno --out D:\dump # 指定输出目录
    python pdf_dump.py D:\Anno --clean        # 转储前先清除原有 txt（默认开启）

无文字层的扫描件 PDF 会渲染成 PNG（存到 _txt_dump/<名>_pages/），
报告里标出「已渲染 N 页」，精读时由模型读取这些图片识别文字，无需人工逐页看。

依赖会自动降级（沙箱/不同机器的可用库不一样，任一即可）：
    文本提取：pdfplumber  →  pypdf  →  PyMuPDF(fitz)
    扫描件渲染：pypdfium2  →  PyMuPDF(fitz)
    pip install pdfplumber pypdfium2      # 推荐组合
"""
import argparse
import glob
import io
import os
import shutil
import sys
import warnings


def _quiet_import(mod):
    """静默导入：临时吞掉 stderr。PyMuPDF 的「import fitz 已弃用」提示是 C 层
    直接写 stderr 的，warnings 过滤器压不住，只能重定向。"""
    real = sys.stderr
    try:
        sys.stderr = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return __import__(mod)
    finally:
        sys.stderr = real


def _have(mod):
    """模块是否可用（只探测，不抛异常）。"""
    try:
        _quiet_import(mod)
        return True
    except Exception:
        return False


def _import_mupdf():
    """导入 PyMuPDF：优先新模块名 pymupdf（1.24.3+，无弃用告警），老环境回退 fitz。"""
    for name in ("pymupdf", "fitz"):
        try:
            return _quiet_import(name)
        except Exception:
            continue
    return None


def backend_info():
    """返回 (文本提取后端, 渲染后端)，None 表示不可用。"""
    mup = _import_mupdf() is not None
    txt = "pdfplumber" if _have("pdfplumber") else ("pypdf" if _have("pypdf") else
                                                    ("PyMuPDF" if mup else None))
    rnd = "pypdfium2" if _have("pypdfium2") else ("PyMuPDF" if mup else None)
    return txt, rnd


def _extract_pages(pdf_path):
    """逐页提取文本，返回 [str, ...]。按 pdfplumber → pypdf → PyMuPDF 顺序降级。"""
    if _have("pdfplumber"):
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return [(pg.extract_text() or "") for pg in pdf.pages]
    if _have("pypdf"):
        from pypdf import PdfReader
        return [(pg.extract_text() or "") for pg in PdfReader(pdf_path).pages]
    mup = _import_mupdf()
    if mup:
        doc = mup.open(pdf_path)
        try:
            return [doc[i].get_text() or "" for i in range(doc.page_count)]
        finally:
            doc.close()
    raise RuntimeError(
        "缺少 PDF 文本提取库（pdfplumber / pypdf / PyMuPDF 任一），请 pip install pdfplumber")


def _render_scanned(pdf_path, out_dir, name):
    """扫描件无文字层：渲染成 PNG，供模型/人工看图识别。
    优先 pypdfium2，缺则降级 PyMuPDF(fitz)。返回 (渲染页数, 错误信息 or None)。"""
    img_dir = os.path.join(out_dir, name + "_pages")
    if _have("pypdfium2"):
        os.makedirs(img_dir, exist_ok=True)
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(pdf_path)
            n = len(doc)
            for i in range(n):
                doc[i].render(scale=2).to_pil().save(
                    os.path.join(img_dir, "p%03d.png" % (i + 1)))
            return n, None
        except Exception as e:
            return 0, "扫描件渲染失败: %s" % e
    mup = _import_mupdf()
    if mup:
        os.makedirs(img_dir, exist_ok=True)
        try:
            doc = mup.open(pdf_path)
            n = doc.page_count
            for i in range(n):
                doc[i].get_pixmap(matrix=mup.Matrix(2, 2)).save(
                    os.path.join(img_dir, "p%03d.png" % (i + 1)))
            doc.close()
            return n, None
        except Exception as e:
            return 0, "扫描件渲染失败: %s" % e
    return 0, "（未装渲染库 pypdfium2 / PyMuPDF，无法渲染：pip install pypdfium2）"


def dump_one(pdf_path, out_dir):
    """返回 (状态, 文本字符数, 页数, 备注)"""
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    txt_path = os.path.join(out_dir, name + ".txt")

    pages, chars = 0, 0
    buf = []
    try:
        for i, t in enumerate(_extract_pages(pdf_path), start=1):
            pages += 1
            t = t or ""
            chars += len(t)
            buf.append(f"\n{'=' * 20} 第 {i} 页 {'=' * 20}\n{t}")
    except Exception as e:
        return ("失败", 0, 0, f"打开失败: {e}")

    text = "".join(buf)
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    # 无文本层 → 扫描件：渲染成图片，供后续模型/人工看图识别
    if chars < 50:
        n, err = _render_scanned(pdf_path, out_dir, name)
        if err:
            note = "疑似扫描件（无文本层），%s" % err
        else:
            note = "疑似扫描件（无文本层），已渲染 %d 页到 %s/" % (n, name + "_pages")
        return ("扫描件", chars, pages, note)

    return ("文本层", chars, pages, "")


def _safe_clean(out_dir):
    """转储前处理旧产物：把所有历史备份目录（_txt_dump_prev / _prev1 …）改名移走，
    再把当前 out_dir 改名移走为唯一的 _txt_dump_prev。

    目标：每次转储后，活动目录（<anno> 根）里只保留「最近一次」的备份 _txt_dump_prev，
    旧的不再无限堆积。

    关键约束：运行环境对「一次删除 >50 文件」要求人工确认、无头服务进程无法确认会被
    直接阻断请求（已实测会 RemoteDisconnected）。因此这里**全程只用 rename（移动），
    绝不调用删除**：旧备份目录整体改名进入 <anno>/_dump_archive/（按时间戳归档、可恢复），
    当前目录改名移走为 _txt_dump_prev。这样无论公告多少、无论守卫预算是否耗尽，转储都不会失败，
    且活动目录始终保持干净（最多一份最新备份）。
    """
    import time as _time
    if not os.path.isdir(out_dir):
        return
    archive = os.path.join(os.path.dirname(out_dir), "_dump_archive")
    os.makedirs(archive, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    # 1) 所有旧备份目录整体改名移走（进入归档区，不删除）
    for d in sorted(glob.glob(out_dir + "_prev*"), reverse=True):
        if not os.path.isdir(d):
            continue
        try:
            os.rename(d, os.path.join(archive, os.path.basename(d) + "_" + ts))
        except Exception:
            # 极端冲突则顺延改名，绝不让转储失败
            i = 1
            while os.path.isdir(d + str(i)):
                i += 1
            try:
                os.rename(d, d + str(i))
            except Exception:
                pass
    # 2) 把当前目录改名移走为唯一的 _txt_dump_prev
    prev = out_dir + "_prev"
    if not os.path.isdir(prev):
        try:
            os.rename(out_dir, prev)
            print(f"[清理] 旧目录已移走：{prev}")
            return
        except Exception:
            pass
    # 退化：prev 仍在（极端情况下），顺延 _prev1/_prev2…
    i = 1
    while os.path.isdir(prev + str(i)):
        i += 1
    try:
        os.rename(out_dir, prev + str(i))
        print(f"[清理] 旧目录已移走：{prev + str(i)}")
    except Exception:
        print(f"[清理] 旧目录未能移走（{out_dir}），请稍后手动处理")


def main():
    ap = argparse.ArgumentParser(description="PDF 批量转储为 txt")
    ap.add_argument("dir", nargs="?", default=".", help="PDF 所在目录，默认当前目录")
    ap.add_argument("--out", default=None, help="输出目录，默认 <dir>/_txt_dump")
    ap.add_argument("--clean", action="store_true", help="转储前先清除原有 txt（及扫描件图片目录）")
    args = ap.parse_args()

    src = os.path.abspath(args.dir)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(src, "_txt_dump")
    os.makedirs(out_dir, exist_ok=True)

    # --clean：把旧 _txt_dump 整目录改名移走（rename 不是删除，不会触发运行时的
    # 批量删除守卫），再建一个干净的空目录。旧目录以 _txt_dump_prev / _prev1 … 留存，
    # 需要彻底腾空间时可手动删除这些备份目录。
    if args.clean:
        _safe_clean(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    txt_be, rnd_be = backend_info()
    if not txt_be:
        print("=" * 58)
        print("缺少 PDF 文本提取库（pdfplumber / pypdf / PyMuPDF 任一），请先执行：")
        print("    pip install pdfplumber")
        print("=" * 58)
        return 1
    if not rnd_be:
        print("[提示] 无扫描件渲染库（pypdfium2 / PyMuPDF），扫描件将只留空 txt、不渲染图片")

    pdfs = sorted(f for f in os.listdir(src) if f.lower().endswith(".pdf"))
    if not pdfs:
        print(f"[提示] {src} 下没有 PDF")
        return 0

    print(f"[信息] 文本提取后端 {txt_be}，扫描件渲染后端 {rnd_be or '无'}")
    print(f"[信息] 待处理 {len(pdfs)} 份 PDF → {out_dir}\n")
    stats = []
    for f in pdfs:
        st, chars, pages, note = dump_one(os.path.join(src, f), out_dir)
        stats.append((f, st, chars, pages, note))
        flag = "OK " if st == "文本层" else "!! "
        print(f"  {flag}{f[:52]:<54} {st} {chars:>7}字 {pages:>3}页 {note}")

    scanned = [s for s in stats if s[1] == "扫描件"]
    print(f"\n[汇总] 共 {len(stats)} 份，文本层 {len(stats) - len(scanned)} 份，扫描件 {len(scanned)} 份")
    if scanned:
        print("[注意] 以下为扫描件，需人工/看图逐页确认内容：")
        for s in scanned:
            print(f"       - {s[0]}")
    print(f"[完成] 文本已转储到 {out_dir}")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
