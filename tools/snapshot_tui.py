"""Render one frame of dashboard/terminal_ui.py to a PNG (for posts / READMEs)."""
import html, io, pathlib, re, sys
from contextlib import redirect_stdout

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "dashboard"))
import terminal_ui  # noqa: E402

COLORS = {"30": "#0b0f0b", "31": "#ff5f5f", "32": "#39ff7a", "33": "#ffd75f", "34": "#5fafff", "35": "#d787ff",
          "36": "#5fffff", "37": "#e8ffe8", "90": "#4f7a5a", "92": "#7dffb0", "96": "#9ffff0", "97": "#ffffff"}


def ansi_to_html(text):
    out, color = [], None
    for part in re.split(r"(\x1b\[[0-9;?]*[A-Za-z])", text):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            codes = m.group(1).split(";")
            if codes == [""] or "0" in codes:
                color = None
            for c in codes:
                if c in COLORS:
                    color = COLORS[c]
                elif c.startswith("38") and len(codes) >= 5 and codes[1] == "2":
                    color = "#%02x%02x%02x" % tuple(int(x) for x in codes[2:5])
            continue
        if part.startswith("\x1b"):
            continue
        if part:
            esc = html.escape(part)
            out.append(f'<span style="color:{color}">{esc}</span>' if color else esc)
    return "".join(out)


def main(out_png):
    buf = io.StringIO()
    with redirect_stdout(buf):
        terminal_ui.render_frame()
    body = ansi_to_html(buf.getvalue())
    page = f"""<html><body style="margin:0;background:#050805">
<pre style="margin:0;padding:28px 34px;font:15px/1.35 Consolas,'Cascadia Mono',monospace;color:#39ff7a;background:#050805;display:inline-block">{body}</pre>
</body></html>"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        pg.set_content(page)
        pg.locator("pre").screenshot(path=out_png)
        b.close()
    print(out_png)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "tui_snapshot.png"))
