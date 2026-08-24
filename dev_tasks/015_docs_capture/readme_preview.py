"""Render README.md to a self-contained HTML preview.

Converts the actual file rather than a parallel copy, so the preview cannot
drift from what ships. Relative image paths are inlined as data URIs, because
a standalone HTML page has no repo to resolve them against — on GitHub the
same markdown resolves them natively.

Handles only the subset the README uses: headings, paragraphs, lists, tables,
fenced code, images, rules, and inline bold/italic/code/links.
"""
import base64
import html
import io
import os
import re

REPO = r"c:/Users/scooter/dev/__projects__/blender_attrviz"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "attrviz_ui_tour.html")


def data_uri(rel):
    with open(os.path.join(REPO, rel), "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def convert(md):
    out, i = [], 0
    lines = md.split("\n")
    pending_figure = False

    def close_para(buf):
        if buf:
            out.append("<p>%s</p>" % inline(" ".join(buf)))
            del buf[:]

    para = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # fenced code
        if stripped.startswith("```"):
            close_para(para)
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(html.escape(lines[i]))
                i += 1
            out.append("<pre>%s</pre>" % "\n".join(code))
            pending_figure = False
            i += 1
            continue

        # markdown image
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m:
            close_para(para)
            out.append('<figure class="fig"><img src="%s" alt="%s">'
                       % (data_uri(m.group(2)), html.escape(m.group(1))))
            pending_figure = True
            i += 1
            continue

        # raw <img ...> with a width
        m = re.match(r'^<img src="([^"]+)"\s+width="(\d+)"\s+alt="([^"]*)">$',
                     stripped)
        if m:
            close_para(para)
            out.append('<figure class="fig narrow"><img src="%s" alt="%s" '
                       'style="max-width:%spx">'
                       % (data_uri(m.group(1)), html.escape(m.group(3)),
                          m.group(2)))
            pending_figure = True
            i += 1
            continue

        # a lone italic line right after an image is its caption
        if pending_figure and stripped.startswith("*"):
            cap = []
            while i < len(lines) and lines[i].strip():
                cap.append(lines[i].strip())
                i += 1
            text = " ".join(cap)
            if text.startswith("*") and text.endswith("*"):
                text = text[1:-1]
            out.append("<figcaption>%s</figcaption></figure>" % inline(text))
            pending_figure = False
            continue

        if pending_figure and not stripped:
            out.append("</figure>")
            pending_figure = False
            i += 1
            continue

        if stripped.startswith("#"):
            close_para(para)
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append("<h%d>%s</h%d>"
                       % (level, inline(stripped[level:].strip()), level))
            i += 1
            continue

        if stripped in ("---", "***"):
            close_para(para)
            out.append("<hr>")
            i += 1
            continue

        # table
        if stripped.startswith("|"):
            close_para(para)
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip()
                             for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body = []
            head = rows[0]
            for r in rows[2:]:
                body.append("<tr>%s</tr>"
                            % "".join("<td>%s</td>" % inline(c) for c in r))
            out.append('<div class="tablewrap"><table><thead><tr>%s</tr>'
                       "</thead><tbody>%s</tbody></table></div>"
                       % ("".join("<th>%s</th>" % inline(c) for c in head),
                          "".join(body)))
            continue

        # lists
        if re.match(r"^[-*] ", stripped) or re.match(r"^\d+\. ", stripped):
            close_para(para)
            ordered = bool(re.match(r"^\d+\. ", stripped))
            items = []
            while i < len(lines):
                s = lines[i].strip()
                if re.match(r"^[-*] ", s) or re.match(r"^\d+\. ", s):
                    items.append(re.sub(r"^([-*]|\d+\.)\s+", "", s))
                elif s and lines[i].startswith("  ") and items:
                    items[-1] += " " + s
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>"
                       % (tag, "".join("<li>%s</li>" % inline(x)
                                       for x in items), tag))
            continue

        if not stripped:
            close_para(para)
            i += 1
            continue

        para.append(stripped)
        i += 1

    close_para(para)
    if pending_figure:
        out.append("</figure>")
    return "\n".join(out)


DARK = """
    --ground:#151412; --surface:#1E1D1B; --surface-2:#26241F;
    --ink:#ECE8E1; --ink-soft:#9E988D; --rule:#332F2A;
    --accent:#FF9147;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 10px 30px rgba(0,0,0,.45);
"""

CSS = """
:root {
  --ground:#F5F3F0; --surface:#FFFFFF; --surface-2:#EFEBE5;
  --ink:#1C1B19; --ink-soft:#57534C; --rule:#DCD6CD;
  --accent:#B8520A;
  --shadow:0 1px 2px rgba(28,27,25,.06),0 8px 24px rgba(28,27,25,.07);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {__DARK__}
}
:root[data-theme="dark"] {__DARK__}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"IBM Plex Serif",Georgia,serif;font-size:17px;line-height:1.68;
  -webkit-font-smoothing:antialiased;padding:0 28px 90px}
h1,h2,h3,figcaption,code,th,pre{font-family:"IBM Plex Sans",system-ui,sans-serif}
h1,h2,h3,p,ul,ol,pre,hr,.tablewrap{max-width:66ch;margin-left:auto;
  margin-right:auto}
h1{font-size:clamp(2.1rem,4.4vw,3rem);font-weight:700;letter-spacing:-.022em;
  line-height:1.08;margin:72px auto .6rem;text-wrap:balance}
h2{font-size:1.5rem;font-weight:600;letter-spacing:-.014em;
  margin:2.6rem auto .9rem;text-wrap:balance}
h3{font-size:1.06rem;font-weight:600;margin:1.9rem auto .5rem}
p{margin:0 auto 1.1rem}
a{color:var(--accent)}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.85em;
  background:var(--surface-2);padding:.1em .38em;border-radius:3px}
pre{background:var(--surface);border:1px solid var(--rule);border-radius:6px;
  padding:15px 17px;overflow-x:auto;font-size:.8rem;line-height:1.6;
  margin:0 auto 1.2rem}
pre code{background:none;padding:0}
hr{border:0;border-top:1px solid var(--rule);margin:2.6rem auto}
ul,ol{margin:0 auto 1.2rem;padding-left:1.15rem}
li{margin-bottom:.45rem}
.fig{margin:26px auto 30px;max-width:1120px}
.fig.narrow{max-width:420px}
.fig img{display:block;width:100%;height:auto;border:1px solid var(--rule);
  border-radius:6px;box-shadow:var(--shadow);background:var(--surface)}
figcaption{margin-top:10px;font-size:.78rem;color:var(--ink-soft);
  text-align:right}
.tablewrap{overflow-x:auto;margin:0 auto 1.5rem}
table{border-collapse:collapse;width:100%;font-size:.93rem;
  font-family:"IBM Plex Sans",sans-serif}
th,td{text-align:left;padding:.6rem .85rem;border-bottom:1px solid var(--rule);
  vertical-align:top}
th{font-size:.71rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-soft);font-weight:600}
td:first-child{white-space:nowrap;font-weight:600}
""".replace("__DARK__", DARK)

md = io.open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
page = (
    "<title>The AttrViz README</title>\n"
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@500;600;700"
    '&family=IBM+Plex+Serif:wght@400;500&display=swap">\n'
    "<style>" + CSS + "</style>\n" + convert(md)
)
io.open(OUT, "w", encoding="utf-8").write(page)
print("wrote %s  %d KB" % (OUT, len(page) // 1024))
