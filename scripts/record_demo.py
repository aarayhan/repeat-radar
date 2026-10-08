"""Record the demo video from the deployed app: one MP4 per scene, no audio. A dev tool, not part of the app.

Needs Google Chrome and two dev-only packages (not in requirements.txt):
    uv pip install --python .venv/Scripts/python.exe playwright imageio-ffmpeg

From the repo root:
    python scripts/record_demo.py record --takes 2     # recordings/take1/, take2/: clips, raw videos, log.json
    python scripts/record_demo.py pick [03_ai_mapping=2 ...]   # copy one take per scene to recordings/, join ALL.mp4

A take records three pages: the spreadsheet hook (recordings/hook.html, from the synthetic messy sample), session A
(scenes 1b-5) and a fresh session B (scenes 6-8); waits for the app are cut out. A failed step calls page.pause():
do it by hand (recording continues), then press Resume in the Playwright Inspector; log.json lists such steps.
"""
import csv
import html
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'recordings'
SAMPLE = ROOT / 'app' / 'sample_data' / 'messy_export.csv'
URL = 'https://repeat-radar.streamlit.app/~/+/'
VIEW = {'width': 1920, 'height': 1080}
SCENES = {'01a_hook_spreadsheet': 8, '01b_landing': 7, '02_trust_line': 10, '03_ai_mapping': 35, '04_radar': 20,
          '05_explanation_draft': 20, '06_refusal': 35, '07_evidence': 25, '08_close': 20}   # target seconds
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

CURSOR_JS = """(() => {
  const add = () => {
    if (document.getElementById('rr-cursor')) return;
    const st = document.createElement('style');
    st.textContent = `#rr-cursor{position:fixed;left:-60px;top:-60px;width:24px;height:24px;margin:-12px 0 0 -12px;
      border-radius:50%;background:rgba(230,57,70,.88);border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.35);
      z-index:2147483647;pointer-events:none}
      .rr-ring{position:fixed;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;
      border:3px solid rgba(230,57,70,.95);z-index:2147483646;pointer-events:none;animation:rr-ring .6s ease-out forwards}
      @keyframes rr-ring{to{transform:scale(3.2);opacity:0}}`;
    document.documentElement.appendChild(st);
    const d = document.createElement('div'); d.id = 'rr-cursor'; document.documentElement.appendChild(d);
    addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div'); r.className = 'rr-ring';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();"""
REPLAY_SWEEP = """() => { const s = document.querySelector('.rr-sweep'); if (!s) return;
  s.style.animation = 'none'; void s.offsetWidth; s.style.animation = ''; }"""
SCROLL_TO = """(y) => { const m = document.querySelector('[data-testid="stMain"]'); if (m) m.scrollTo(0, y);
  window.scrollTo(0, y); }"""


class Take:
    """One recorded page. Moves a visible cursor slowly, scrolls smoothly, and notes which parts of the page's video
    belong to which scene; waits for the app are left out (cut ... resume)."""

    def __init__(self, browser, video_dir, log):
        self.ctx = browser.new_context(viewport=VIEW, record_video_dir=str(video_dir), record_video_size=VIEW,
                                       device_scale_factor=1)
        self.ctx.add_init_script(CURSOR_JS)
        self.page = self.ctx.new_page()
        self.t0, self.x, self.y = time.monotonic(), 0.0, 0.0
        self.parts, self.scene, self.since, self.log = [], None, None, log

    # ----- scene timing -----
    def now(self):
        return time.monotonic() - self.t0

    def begin(self, scene):
        print('scene', scene, flush=True)
        self.scene, self.since = scene, self.now()

    def cut(self):
        if self.since is not None:
            self.parts.append((self.scene, self.since, self.now()))
            self.since = None

    def resume(self):
        self.since = self.now()

    def recorded(self):
        done = sum(e - s for sc, s, e in self.parts if sc == self.scene)
        return done + (self.now() - self.since if self.since is not None else 0)

    def end(self):
        """Hold until the scene reaches its target length, then stop its clip."""
        left = SCENES[self.scene] - self.recorded()
        if left > 0:
            self.page.wait_for_timeout(left * 1000)
        self.cut()

    def finish(self):
        video = self.page.video.path()
        self.ctx.close()
        return Path(video), self.parts

    # ----- waiting for the app (not recorded) -----
    def open(self):
        open_app(self.page)

    def busy(self):
        """Streamlit is running a script: its status widget is shown, or parts of the page are greyed out."""
        p = self.page
        return p.locator('[data-testid="stStatusWidget"]').count() > 0 or p.locator('[data-stale="true"]').count() > 0

    def settle(self, text=None, timeout=240):
        """Wait for the text, then until the app has been idle for 2 s in a row (the status widget appears late)."""
        if text:
            self.page.get_by_text(text).first.wait_for(timeout=timeout * 1000)
        end, idle_since = time.monotonic() + timeout, None
        while time.monotonic() < end:
            if self.busy():
                idle_since = None
            elif idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= 2:
                self.page.wait_for_timeout(800)   # charts and tables finish drawing
                return
            self.page.wait_for_timeout(200)
        raise TimeoutError('the app is still running')

    def wait(self, text=None, top=False):
        """Wait for the app with the recording cut, optionally back at the top of the page."""
        self.cut()
        self.step(f'wait for {text or "the app"}', lambda: self.settle(text))
        if top:
            self.page.evaluate(SCROLL_TO, 0)
            self.page.wait_for_timeout(400)
        self.resume()

    def step(self, name, fn):
        try:
            return fn()
        except Exception as e:  # never guess: hand the step to the person at the keyboard
            msg = f'{self.scene}: {name} failed ({type(e).__name__}: {str(e).splitlines()[0][:120]})'
            print('NEEDS HAND:', msg, '- do it in the browser, then press Resume in the Playwright Inspector',
                  flush=True)
            self.log.append(msg)
            self.page.pause()

    # ----- visible movement -----
    def glide(self, x, y, steps=25, ms=24):
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)                  # ease in and out
            self.page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t)
            self.page.wait_for_timeout(ms)
        self.x, self.y = x, y

    def scroll(self, dy, dx=0, step=9, ms=16):
        if self.x < 360 and not dx:                  # wheel over the main area, not the sidebar
            self.glide(960, self.y or 540, steps=12)
        n = max(1, int(max(abs(dy), abs(dx)) / step))
        for _ in range(n):
            self.page.mouse.wheel(dx / n, dy / n)
            self.page.wait_for_timeout(ms)
        self.page.wait_for_timeout(350)

    def scroll_to(self, loc, top=140):
        for _ in range(2):                           # second pass corrects for smooth-scroll lag
            box = loc.first.bounding_box()
            if box and abs(box['y'] - top) > 12:
                self.scroll(box['y'] - top)

    def point(self, loc, steps=25):
        box = loc.first.bounding_box()
        if box['y'] < 70 or box['y'] + box['height'] > VIEW['height'] - 30:
            self.scroll_to(loc, top=VIEW['height'] / 2 - box['height'] / 2)
            box = loc.first.bounding_box()
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        self.glide(x, y, steps)
        return x, y

    def click(self, loc):
        loc.first.wait_for(state='visible', timeout=30000)
        x, y = self.point(loc)
        self.page.wait_for_timeout(600)
        self.page.mouse.click(x, y)

    def hold(self, seconds):
        self.page.wait_for_timeout(seconds * 1000)


# ---------- scenes ----------

def build_hook(path):
    """A plain spreadsheet view of the first 30 rows of the synthetic messy sample (not committed)."""
    with SAMPLE.open(encoding='utf-8', newline='') as f:
        rows = list(csv.reader(f))[:31]
    head = '<th class="n"></th>' + ''.join(f'<th>{html.escape(h)}</th>' for h in rows[0])
    body = ''.join(f'<tr><td class="n">{i}</td>' + ''.join(f'<td>{html.escape(v)}</td>' for v in r) + '</tr>'
                   for i, r in enumerate(rows[1:], 1))
    path.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>messy_export.csv</title><style>
body{{margin:0;font-family:Arial,Helvetica,sans-serif;font-size:28px;background:#fff;color:#222}}
.bar{{position:sticky;left:0;top:0;z-index:3;background:#f7f7f7;border-bottom:1px solid #c8c8c8;padding:10px 18px;
  font-size:20px;color:#555}}
table{{border-collapse:collapse}}
th,td{{border:1px solid #d4d4d4;padding:10px 18px;white-space:nowrap;text-align:left;min-width:190px}}
th{{background:#ececec;font-weight:600;position:sticky;top:45px;z-index:2}}
.n{{background:#ececec;color:#666;text-align:center;min-width:56px;position:sticky;left:0;z-index:1}}
th.n{{z-index:4}}
th:hover,td:hover{{outline:3px solid #1a73e8;outline-offset:-3px}}
</style></head><body><div class="bar">messy_export.csv</div><table><thead><tr>{head}</tr></thead>
<tbody>{body}</tbody></table></body></html>""", encoding='utf-8')
    return path


def hook(t, page_file):
    t.page.goto(page_file.as_uri())
    t.page.wait_for_timeout(800)
    t.glide(70, 80, steps=4)
    t.begin('01a_hook_spreadsheet')
    heads = t.page.locator('thead th')
    for i in range(1, heads.count()):            # pan across the header row, one column name at a time
        box = heads.nth(i).bounding_box()
        if box['x'] + box['width'] > VIEW['width'] - 10:
            t.scroll(0, dx=box['x'] + box['width'] - VIEW['width'] + 40)
            box = heads.nth(i).bounding_box()
        t.glide(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=12, ms=22)
        t.hold(0.15)
    t.scroll(240, step=6, ms=20)                   # then slowly down a few rows
    t.end()


def landing(t):
    t.step('open the app', t.open)
    t.step('load the app', lambda: t.settle('Try the demo'))
    t.glide(1500, 760, steps=4)
    t.begin('01b_landing')
    t.page.evaluate(REPLAY_SWEEP)                 # replay the app's own one-time sweep for this clip
    t.step('glide over the hero', lambda: t.point(t.page.locator('.rr-hero h1'), steps=45))
    t.scroll(220, step=4, ms=20)                   # slow scroll over the hero (if the page is taller than the view)
    t.end()
    t.begin('02_trust_line')
    t.scroll(-220, step=4, ms=20)

    def read_trust():
        box = t.page.locator('.rr-trust').bounding_box()
        y = box['y'] + box['height'] + 14
        t.glide(box['x'], y, steps=20)
        t.glide(box['x'] + box['width'], y, steps=90, ms=30)   # follow the line like a reader
    t.step('read the trust line', read_trust)
    t.end()


def mapping(t):
    p = t.page
    t.begin('03_ai_mapping')
    t.step('open Other samples', lambda: t.click(p.get_by_text('Other samples')))
    p.wait_for_timeout(500)
    sample = p.locator('[data-testid="stSelectbox"]').filter(has_text='Sample file')
    t.step('open the sample list', lambda: t.click(sample.get_by_role('button', name='Open')))
    t.step('choose the messy export', lambda: t.click(p.get_by_role('option', name='Messy export (synthetic)')))
    t.step('load it', lambda: t.click(p.get_by_role('button', name='Use sample data')))
    t.wait('Check that the columns match')
    t.step('show the proposal', lambda: t.scroll_to(p.get_by_text('Check that the columns match'), top=100))

    def rules_column():                          # the table is a canvas: point at its third column, top to bottom
        box = p.locator('[data-testid="stDataFrame"]').first.bounding_box()
        x = box['x'] + box['width'] * 0.83
        t.glide(x, box['y'] + 22, steps=25)
        t.glide(x, box['y'] + box['height'] - 20, steps=45, ms=30)
    t.step('point at the rules column', rules_column)
    t.hold(2.5)
    t.step('start from the LLM proposal', lambda: t.click(p.get_by_text('LLM proposal', exact=True)))
    t.wait()
    product = p.locator('[data-testid="stSelectbox"]').filter(has_text='product')
    t.step('open product', lambda: t.click(product.get_by_role('button', name='Open')))
    t.step('choose Barang', lambda: t.click(p.get_by_role('option', name='Barang', exact=True)))
    t.wait()
    t.step('confirm', lambda: t.click(p.get_by_role('button', name='Confirm mapping')))
    t.wait('Mapping confirmed')
    t.step('show the confirmation', lambda: t.point(p.get_by_text('Mapping confirmed'), steps=30))
    t.end()


def sidebar(t, label):
    t.step(f'open {label}', lambda: t.click(t.page.locator('[data-testid="stSidebar"]').get_by_text(label)))


def radar(t):
    p = t.page
    t.begin('04_radar')
    sidebar(t, '2. Customers')
    t.wait('Who to contact this week', top=True)
    t.step('wait for the radar', lambda: p.locator('.vega-embed').first.wait_for(timeout=60000))

    def tour():
        for card in p.locator('[data-testid="stMetric"]').all()[:4]:
            t.point(card, steps=18)
            t.hold(0.4)
        box = p.locator('.vega-embed').first.bounding_box()
        if box['y'] + box['height'] > VIEW['height'] - 10:
            t.scroll(box['y'] + box['height'] - VIEW['height'] + 30)
            box = p.locator('.vega-embed').first.bounding_box()
        cx, cy, r = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, box['height'] * 0.28
        t.glide(cx + r, cy, steps=25)
        for i in range(1, 49):                     # one slow loop around the rings
            a = i / 48 * 2 * math.pi
            p.mouse.move(cx + r * math.cos(a), cy + r * math.sin(a))
            p.wait_for_timeout(45)
        t.x, t.y = cx + r, cy
    t.step('show the cards and the radar', tour)
    t.end()


def draft(t):
    p = t.page
    t.begin('05_explanation_draft')
    t.step('go to the customer', lambda: t.scroll_to(p.get_by_text('Why this customer, and what to send'), top=90))
    pick = p.locator('[data-testid="stSelectbox"]').filter(has_text='Customer (or click a dot')
    t.step('open the customer list', lambda: t.click(pick.get_by_role('button', name='Open')))
    t.step('choose a due customer', lambda: t.click(p.get_by_role('option').nth(1)))   # list starts with Due now
    t.wait()
    reason = p.locator('[data-testid="stMarkdownContainer"]').filter(has_text='Reason (for you, not in the message)')
    if 'Due:' not in (reason.first.inner_text() if reason.count() else ''):
        t.log.append(f'{t.scene}: the chosen customer is not in the Due now group')
    if not p.get_by_text('Checked by code').count():
        t.log.append(f'{t.scene}: no "Checked by code" note (the draft came from the template)')
    t.step('show the explanation and the draft', lambda: t.scroll_to(p.get_by_text('Explanation source'), top=330))
    note = p.get_by_text('Checked by code')
    t.step('point at the check note', lambda: t.point(note if note.count() else p.get_by_text('Message source'), 40))
    t.end()


def refusal(t):
    p = t.page
    t.step('open the app', t.open)
    t.step('load the app', lambda: t.settle('Try the demo'))
    t.glide(1500, 760, steps=4)
    t.begin('06_refusal')
    t.step('try the demo', lambda: t.click(p.get_by_role('button', name='Try the demo')))
    t.wait('Check that the columns match')
    if p.get_by_text('pick one to start from').count():
        t.step('start from the rules', lambda: t.click(p.get_by_text('Rules proposal', exact=True)))
        t.wait()
    t.step('confirm', lambda: t.click(p.get_by_role('button', name='Confirm mapping')))
    t.wait('Mapping confirmed')
    sidebar(t, '3. Audit')
    t.wait('Why we did not use the model', top=True)
    t.step('read the panel', lambda: t.point(p.get_by_text('Why we did not use the model'), steps=30))
    t.hold(5)
    t.step('show the chart', lambda: t.scroll_to(p.get_by_text('The model and the simple rule, test by test'), 90))

    def bars():
        box = p.locator('.vega-embed').first.bounding_box()
        for f in (0.2, 0.27, 0.5, 0.57, 0.8, 0.87):      # model and simple rule bar of each window
            t.glide(box['x'] + box['width'] * f, box['y'] + box['height'] * 0.3, steps=18)
            t.hold(0.7)
    t.step('point at the bars', bars)
    t.end()


def evidence(t):
    p = t.page
    t.begin('07_evidence')
    sidebar(t, '4. Results on real shop data')
    t.wait('On customers the model never saw', top=True)
    t.hold(2)
    t.step('show the holdout chart', lambda: t.scroll_to(p.get_by_text('On customers the model never saw'), 90))

    def april():
        box = p.locator('.vega-embed').first.bounding_box()
        t.glide(box['x'] + box['width'] * 0.25, box['y'] + box['height'] * 0.72, steps=30)
        t.hold(2)
        t.point(p.get_by_text("the model's win is not conclusive"), steps=30)
    t.step('point at April', april)
    t.end()


def close(t):
    p = t.page
    t.begin('08_close')
    sidebar(t, '1. Upload')
    t.wait('Try the demo', top=True)
    t.cut()                                       # hidden: start lower, so the clip can glide up to the hero
    p.evaluate(SCROLL_TO, 700)
    p.wait_for_timeout(500)
    t.resume()
    t.scroll(-900, step=3, ms=22)
    p.evaluate(REPLAY_SWEEP)
    t.glide(1880, 1050, steps=40)                 # park the cursor out of the way
    t.end()


# ---------- video ----------

def ffmpeg(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)


def cut_clips(video, parts, out_dir):
    spans = {}
    for scene, s, e in parts:
        if e - s > 0.15:
            spans.setdefault(scene, []).append((s, e))
    for scene, ss in spans.items():
        pieces = []
        for i, (s, e) in enumerate(ss):
            piece = out_dir / f'{scene}.part{i}.mp4'
            ffmpeg('-i', video, '-ss', f'{s:.3f}', '-t', f'{e - s:.3f}', '-r', 30, '-c:v', 'libx264',
                   '-pix_fmt', 'yuv420p', '-crf', 18, '-an', piece)
            pieces.append(piece)
        join(pieces, out_dir / f'{scene}.mp4')
        for piece in pieces:
            piece.unlink()


def join(clips, target):
    listing = target.with_suffix('.txt')
    listing.write_text(''.join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding='utf-8')
    ffmpeg('-f', 'concat', '-safe', 0, '-i', listing, '-c', 'copy', target)
    listing.unlink()


def seconds(path):
    return imageio_ffmpeg.count_frames_and_secs(str(path))[1]


def open_app(page):
    """Open the deployed app; the connection to Streamlit Cloud is flaky, so try up to 4 times."""
    for attempt in range(4):
        try:
            return page.goto(URL, wait_until='domcontentloaded', timeout=90000)
        except Exception:
            if attempt == 3:
                raise
            page.wait_for_timeout(5000)


def wake(browser):
    page = browser.new_page(viewport=VIEW)
    open_app(page)
    button = page.get_by_role('button', name=re.compile('get this app back up', re.I))
    try:
        button.wait_for(timeout=8000)
        button.click()
    except Exception:
        pass
    page.get_by_text('Repeat Radar').first.wait_for(timeout=120000)
    page.close()


def record(take_dir):
    take_dir.mkdir(parents=True, exist_ok=True)
    raw, log = take_dir / 'raw', []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=False)
        wake(browser)
        for scenes in ((lambda t: hook(t, build_hook(OUT / 'hook.html'))),
                       (lambda t: [f(t) for f in (landing, mapping, radar, draft)]),
                       (lambda t: [f(t) for f in (refusal, evidence, close)])):
            t = Take(browser, raw, log)
            scenes(t)
            cut_clips(*t.finish(), take_dir)
        browser.close()
    (take_dir / 'log.json').write_text(json.dumps(log, indent=1), encoding='utf-8')
    for scene in SCENES:
        clip = take_dir / f'{scene}.mp4'
        print(f'{take_dir.name} {scene}: {seconds(clip):.1f} s' if clip.exists() else f'{scene}: missing')
    print('needed a hand:', log or 'nothing')


def pick(overrides):
    """Default: take 1 for each scene, unless take 1 needed a hand there and another take did not."""
    logs = {d.name: json.loads((d / 'log.json').read_text(encoding='utf-8'))
            for d in sorted(OUT.glob('take*')) if (d / 'log.json').exists()}
    chosen = []
    for scene in SCENES:
        clean = [k for k, log in logs.items() if not any(m.startswith(scene) for m in log)]
        take = overrides.get(scene) or (clean[0] if clean else next(iter(logs)))
        take = take if str(take).startswith('take') else f'take{take}'
        shutil.copy(OUT / take / f'{scene}.mp4', OUT / f'{scene}.mp4')
        chosen.append(OUT / f'{scene}.mp4')
        print(f'{scene}: {take}, {seconds(OUT / f"{scene}.mp4"):.1f} s')
    join(chosen, OUT / 'ALL.mp4')
    print(f'ALL.mp4: {seconds(OUT / "ALL.mp4"):.1f} s')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'record'
    if cmd == 'record':
        n = int(sys.argv[sys.argv.index('--takes') + 1]) if '--takes' in sys.argv else 2
        start = int(sys.argv[sys.argv.index('--first') + 1]) if '--first' in sys.argv else 1
        for k in range(start, start + n):
            record(OUT / f'take{k}')
    elif cmd == 'pick':
        pick(dict(a.split('=') for a in sys.argv[2:]))
