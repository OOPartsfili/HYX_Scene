"""Build the two offline manuals from their canonical Markdown sources.

Run from any directory: python tools/build_manuals.py [--check]
This tool reads documentation only and never connects to CARLA.
"""
from __future__ import annotations

import argparse
import html
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

try:
    import markdown
except ImportError:
    raise SystemExit("Install optional docs dependencies: python -m pip install -r requirements-docs.txt")


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "scene_studio" / "web"
FIGURES = json.loads((DOCS / "manual-figures.json").read_text(encoding="utf-8"))
MANUALS = (
    ("user-manual.md", "guide.html", "用户手册", "操作流程 · 实验记录 · 环境对照"),
    ("developer-maintenance-manual.md", "maintenance.html", "开发维护手册", "实现架构 · 数据约束 · 测试与交接"),
)

CSS = """
:root{color-scheme:light;--ink:#203239;--muted:#587078;--line:#d7e2e3;--green:#086b58;--paper:#fff;--bg:#f3f6f5}
*{box-sizing:border-box}html{scroll-padding-top:90px}body{margin:0;color:var(--ink);background:var(--bg);font:16px/1.85 "Microsoft YaHei","Noto Sans CJK SC",sans-serif}
a{color:var(--green);text-underline-offset:3px}a:hover{text-decoration-thickness:2px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #cb9619;outline-offset:4px}
.topbar{position:sticky;top:0;z-index:5;min-height:64px;padding:12px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px;background:#153d35;color:white;border-bottom:1px solid #295046}
.brand{font-weight:700;letter-spacing:.04em}.topbar a{color:#f0fff7;text-decoration:none}.actions{display:flex;align-items:center;gap:20px;font-size:14px}.actions button{font:inherit;padding:5px 12px;border:1px solid #72998d;border-radius:6px;background:transparent;color:white;cursor:pointer}
.layout{max-width:1510px;margin:auto;display:grid;grid-template-columns:275px minmax(0,1fr);gap:38px;padding:30px 32px 80px}.sidebar{position:sticky;top:92px;align-self:start;max-height:calc(100vh - 118px);overflow-y:auto;padding-right:14px;scrollbar-width:thin}
.manual-switch{display:grid;gap:8px;margin-bottom:22px}.manual-switch a{padding:8px 12px;border-radius:6px;text-decoration:none;border:1px solid var(--line);font-size:14px}.manual-switch a[aria-current=page]{background:#e0eee7;color:#154c3d;font-weight:bold;border-color:#b4cfbd}
.toc-title,summary{font-size:13px;color:var(--muted);font-weight:bold;letter-spacing:.08em}.toc ul{padding:0;margin:12px 0;list-style:none}.toc li{margin:5px 0;line-height:1.6}.toc a{display:block;text-decoration:none;font-size:13px;padding:5px 10px;border-left:2px solid transparent;color:var(--muted)}.toc a:hover,.toc a.active{color:var(--green);background:#e9f0eb;border-left-color:var(--green)}
.article-shell{min-width:0;background:var(--paper);padding:34px 46px 50px;border:1px solid var(--line);border-radius:10px;box-shadow:0 5px 24px #173d3510}.kicker{color:var(--green);font-size:13px;font-weight:bold;letter-spacing:.07em;margin:0 0 6px}.subtitle{color:var(--muted);font-size:14px;margin:0 0 24px}
h1{font-size:32px;line-height:1.4;letter-spacing:-.025em;margin:10px 0 22px}h2{font-size:24px;line-height:1.5;margin:52px 0 20px;padding-top:24px;border-top:2px solid #c7dbcf}h3{font-size:19px;line-height:1.5;margin:28px 0 14px}p{margin:14px 0}li{margin:8px 0}ol,ul{padding-left:1.6em}li>p{margin:7px 0}strong{font-weight:700;color:#153f34}
code{font: .9em/1.7 Consolas,"Microsoft YaHei",monospace;background:#eef3f0;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{padding:20px 22px;border-radius:8px;background:#183931;color:#edf7ef;overflow-x:auto;font-size:14px;line-height:1.8}pre code{background:none;color:inherit;padding:0;overflow-wrap:normal;white-space:pre}blockquote{margin:20px 0;padding:8px 18px;border-left:4px solid #92b99c;background:#f0f7f1}
.table-scroll{overflow-x:auto;margin:22px 0;border:1px solid var(--line);border-radius:7px}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.8}th,td{padding:12px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{background:#e9f1ed;color:#234d3e;font-weight:700}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#fafcfb}td:first-child{min-width:110px}td code{font-size:13px}a[data-repo-path]{cursor:help;color:#294f48;text-decoration:underline dotted;font-family:Consolas,"Microsoft YaHei",monospace}
.doc-footer{border-top:1px solid var(--line);padding-top:22px;margin-top:50px;color:var(--muted);font-size:13px}.mobile-toc{display:none}.source-note{font-size:13px;color:var(--muted)}.skip{position:fixed;left:12px;top:-70px;padding:8px;background:#fff;z-index:20}.skip:focus{top:8px}
.manual-figure{margin:25px 0 32px;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:#f8fbf9}.shot-button{display:block;width:100%;padding:0;border:0;background:#17202b;cursor:zoom-in;position:relative;text-align:left}.shot-canvas{position:relative;display:block;width:100%;line-height:0}.shot-canvas img{display:block;width:100%;height:auto}.shot-mark{position:absolute;border:2px solid #ffd15c;border-radius:4px;box-shadow:0 0 0 1px #152c35aa;pointer-events:none}.shot-mark b{position:absolute;left:-8px;top:-9px;display:grid;place-items:center;width:23px;height:23px;background:#ffd15c;color:#162936;border-radius:50%;font:bold 13px/1 sans-serif;box-shadow:0 1px 4px #0007}.zoom-hint{position:absolute;right:8px;bottom:8px;padding:4px 9px;background:#10281eed;color:white;border-radius:5px;font:12px/1.6 sans-serif}.manual-figure figcaption{padding:12px 16px 3px;font-size:14px;font-weight:bold;color:#224b3b}.shot-legend{list-style:none;counter-reset:step;padding:2px 16px 10px!important;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:3px 20px;font-size:13px;line-height:1.7}.shot-legend li{counter-increment:step;position:relative;padding-left:28px;margin:5px 0}.shot-legend li:before{content:counter(step);position:absolute;left:0;top:2px;display:grid;place-items:center;width:20px;height:20px;background:#f4cc6b;color:#253e30;border-radius:50%;font-weight:bold}
.shot-dialog{width:96vw;max-width:1500px;max-height:94vh;padding:0;border:1px solid #577d6c;border-radius:10px;background:#13251f;color:#fff}.shot-dialog::backdrop{background:#071811d9}.viewer-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 16px;font-size:14px}.viewer-toolbar button{padding:7px 13px;border:1px solid #88ac99;border-radius:5px;background:#294a3b;color:#fff;cursor:pointer}.viewer-pan{overflow:auto;max-height:calc(94vh - 105px);background:#111b25}.viewer-pan .shot-canvas{margin:auto}.viewer-pan.original .shot-canvas{width:var(--original-width,1280px);max-width:none}.viewer-note{margin:0;padding:8px 16px;font-size:12px;color:#ccdfd2}
@media(max-width:760px){.shot-legend{grid-template-columns:1fr}.shot-mark{border-width:1px}.shot-mark b{width:18px;height:18px;font-size:11px;left:-5px;top:-6px}.viewer-toolbar{font-size:12px;flex-wrap:wrap}.zoom-hint{font-size:10px}}
@media print{.shot-button{break-inside:avoid}.manual-figure{break-inside:avoid}.zoom-hint,.shot-dialog{display:none}.shot-mark{border-color:#9b6600}.shot-legend{font-size:9pt}}
@media(min-width:1600px){.article-shell{padding-left:62px;padding-right:62px}}
@media(max-width:1000px){.layout{grid-template-columns:220px minmax(0,1fr);gap:22px;padding:24px 20px 60px}.article-shell{padding:28px}.topbar{padding:12px 20px}h1{font-size:28px}}
@media(max-width:760px){.topbar{position:static;padding:12px 16px;flex-wrap:wrap;gap:8px}.brand{font-size:15px}.actions{gap:16px;font-size:13px}.layout{display:block;padding:16px 12px 40px}.sidebar{position:static;max-height:none;padding:0}.sidebar>.toc-title,.sidebar>.toc{display:none}.manual-switch{grid-template-columns:1fr 1fr;gap:8px;margin:0 0 14px}.manual-switch a{font-size:13px;padding:8px}.mobile-toc{display:block;border:1px solid var(--line);padding:10px 14px;border-radius:6px;margin-bottom:14px}.article-shell{padding:22px 18px}.kicker{font-size:11px}h1{font-size:26px}h2{font-size:22px;margin-top:38px}h3{font-size:18px}body{font-size:15px}table{min-width:540px}pre{padding:14px;font-size:12px}html{scroll-padding-top:16px}}
@media print{body{background:#fff;color:#000;font-size:10.5pt;line-height:1.65}.topbar,.sidebar,.skip{display:none}.layout{display:block;padding:0;max-width:none}.article-shell{padding:0;border:none;box-shadow:none}.subtitle,.kicker{font-size:9pt}h1{font-size:24pt}h2{font-size:17pt;margin-top:24pt;padding-top:12pt;break-after:avoid}h3{font-size:13pt;break-after:avoid}pre{white-space:pre-wrap;background:#f1f4f1;color:#111}pre code{white-space:pre-wrap}table{min-width:0;font-size:9pt}thead{display:table-header-group}tr{break-inside:avoid}.table-scroll{overflow:visible;border:0}a{color:#000;text-decoration:none}.doc-footer{font-size:9pt}}
"""


class LinkAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


def rewrite_links(content: str, source: Path) -> str:
    """Keep manual navigation; show repository code references without dead URLs."""
    manual_pages = {item[0]: item[1] for item in MANUALS}

    def replace(match):
        href = html.unescape(match.group(1))
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path or href.startswith("/"):
            return match.group(0)
        target = (source.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(ROOT) or not target.is_file():
            raise ValueError(f"Invalid repository reference in {source.name}: {href}")
        if target.parent == DOCS and target.name in manual_pages:
            suffix = f"#{parsed.fragment}" if parsed.fragment else ""
            return f'href="{html.escape(manual_pages[target.name] + suffix, quote=True)}"'
        relative = target.relative_to(ROOT).as_posix()
        safe = html.escape(relative, quote=True)
        return f'data-repo-path="{safe}" title="仓库文件：{safe}；请在 Markdown 源文档中打开"'

    return re.sub(r'href="([^"]+)"', replace, content)


def render_figures(content: str, source: Path) -> str:
    def replace(match):
        attrs=dict(re.findall(r'(\w+)="([^"]*)"',match.group(1)))
        ref=html.unescape(attrs.get('src',''))
        target=(source.parent/unquote(urlsplit(ref).path)).resolve()
        if not target.is_relative_to(WEB/'manual-assets') or not target.is_file():
            raise ValueError(f'Missing or unsupported manual screenshot: {ref}')
        metadata=FIGURES['figures'].get(target.name)
        if metadata is None:raise ValueError(f'Missing screenshot annotations: {target.name}')
        width,height=metadata.get('width',FIGURES['width']),metadata.get('height',FIGURES['height'])
        marks=[];legend=[]
        for index,(x,y,w,h,label) in enumerate(metadata['marks'],1):
            if not (0<=x<x+w<=width and 0<=y<y+h<=height):raise ValueError(f'Annotation outside screenshot: {target.name}')
            marks.append(f'<span class="shot-mark" aria-hidden="true" style="left:{100*x/width:.3f}%;top:{100*y/height:.3f}%;width:{100*w/width:.3f}%;height:{100*h/height:.3f}%"><b>{index}</b></span>')
            legend.append(f'<li>{html.escape(label)}</li>')
        caption=html.escape(html.unescape(attrs.get('alt','操作截图')))
        image_path=html.escape(target.relative_to(WEB).as_posix(),quote=True)
        return f'<figure class="manual-figure"><button class="shot-button" type="button" aria-label="放大：{caption}"><span class="shot-canvas" style="--original-width:{width}px"><img src="{image_path}" alt="{caption}" width="{width}" height="{height}" loading="lazy">{"".join(marks)}</span><span class="zoom-hint">点击放大 · 可看原始尺寸</span></button><figcaption>{caption}</figcaption><ol class="shot-legend">{"".join(legend)}</ol></figure>'
    return re.sub(r'<p><img\s+([^>]+?)\s*/?></p>',replace,content)


def render(source_name: str, page_name: str, label: str, subtitle: str) -> str:
    source = DOCS / source_name
    raw = source.read_text(encoding="utf-8")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": {"toc_depth": "2-2"}})
    article = rewrite_links(md.convert(raw), source)
    article = render_figures(article, source)
    article = article.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")
    switches = "".join(
        f'<a href="{page}"' + (' aria-current="page"' if page == page_name else '') + f'>{name}</a>'
        for _, page, name, _ in MANUALS
    )
    note = '<p class="source-note">源码文件名是仓库索引；需要打开源码时，请使用项目内 Markdown 手册的链接。</p>' if page_name == "maintenance.html" else ""
    output = f'''<!doctype html>
<!-- Generated by tools/build_manuals.py from docs/{source_name}. Edit the Markdown source. -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="HYX Scene Studio {label}：{subtitle}"><title>{label} · HYX Scene Studio</title><style>{CSS}</style></head>
<body><a class="skip" href="#content">跳到正文</a>
<header class="topbar"><span class="brand">HYX SCENE STUDIO <span aria-hidden="true"> / </span> 文档</span><div class="actions"><a href="/">返回编辑器</a><button type="button" onclick="window.print()">打印 / 存为 PDF</button></div></header>
<div class="layout"><aside class="sidebar" aria-label="手册导航"><nav class="manual-switch">{switches}</nav><div class="toc-title">本页目录</div>{md.toc}<details class="mobile-toc"><summary>展开本页目录</summary>{md.toc}</details></aside>
<main id="content" class="article-shell"><p class="kicker">HYX SCENE STUDIO · {label}</p><p class="subtitle">{subtitle}</p>{article}
<footer class="doc-footer">文档源文件：<code>docs/{source_name}</code><br>实现说明基线：2026-10-10；四相机与导出功能复测：2026-10-19。生成网页由同一份正文维护。{note}</footer></main></div>
<dialog id="shot-viewer" class="shot-dialog" aria-labelledby="viewer-title"><div class="viewer-toolbar"><span id="viewer-title">操作截图</span><div><button id="viewer-size" type="button">原始尺寸</button> <button id="viewer-close" type="button" autofocus>关闭 ×</button></div></div><div class="viewer-pan"></div><p class="viewer-note">黄色框与编号对应图下步骤。原始尺寸可横向、纵向滚动；按 Esc 关闭。</p></dialog>
<script>
const viewer = document.getElementById('shot-viewer');
const pan = viewer.querySelector('.viewer-pan');
const sizeButton = document.getElementById('viewer-size');
let sourceButton = null;
document.querySelectorAll('.shot-button').forEach(button => button.addEventListener('click', () => {{
  sourceButton = button;
  pan.replaceChildren(button.querySelector('.shot-canvas').cloneNode(true));
  pan.classList.remove('original');
  sizeButton.textContent = '原始尺寸';
  document.getElementById('viewer-title').textContent = button.closest('figure').querySelector('figcaption').textContent;
  viewer.showModal();
}}));
sizeButton.addEventListener('click', () => {{
  const original = pan.classList.toggle('original');
  sizeButton.textContent = original ? '适应窗口' : '原始尺寸';
}});
document.getElementById('viewer-close').addEventListener('click', () => viewer.close());
viewer.addEventListener('close', () => {{pan.replaceChildren(); if(sourceButton) sourceButton.focus();}});
const headings = document.querySelectorAll('main h2[id]');
if ('IntersectionObserver' in window) {{
  const observer = new IntersectionObserver(entries => {{
    const visible = entries.filter(entry => entry.isIntersecting);
    if (!visible.length) return;
    const id = visible[0].target.id;
    document.querySelectorAll('.toc a').forEach(link => link.classList.toggle('active', decodeURIComponent(link.hash.slice(1)) === id));
  }}, {{rootMargin: '-8% 0px -75% 0px'}});
  headings.forEach(heading => observer.observe(heading));
}}
</script></body></html>
'''
    audit = LinkAudit()
    audit.feed(output)
    if audit.h1_count != 1:
        raise ValueError(f"Expected one top-level title: {source}")
    if len(audit.ids) != len(set(audit.ids)):
        raise ValueError(f"Duplicate HTML id in {page_name}")
    for href in audit.links:
        if href.startswith("#") and unquote(href[1:]) not in audit.ids:
            raise ValueError(f"Missing heading anchor in {page_name}: {href}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated HTML differs; do not write files.")
    args = parser.parse_args()
    outputs = [(WEB / page, render(source, page, label, subtitle)) for source, page, label, subtitle in MANUALS]
    stale = []
    for path, content in outputs:
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"Built {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("Manual pages need rebuilding: " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.check:
        print("Both manual pages match their Markdown sources; local references and anchors are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
