// visibleText(document, { gradientStops = true } = {}) -> { text, dropped, removed }
//
// A visible-text filter for agent page readers: keep only text a sighted
// person could read on the rendered page. Runs in the page (inject it with
// your browser driver's evaluate call). For every text node it asks the
// browser, not the markup:
//   - is any ancestor not rendered (display:none, visibility:hidden,
//     content-visibility, opacity:0)?            -> Element.checkVisibility
//   - is the font smaller than 6 px?
//   - is the text colour within 1.6:1 contrast of the background colour, or
//     of any colour stop of a gradient behind it?
//   - is every line box off the page or clipped to under 2x2 px?
//   - is the centre of every line box covered by another element?
// and finally strips Unicode format characters (category Cf: tag characters
// U+E0000-E007F, zero-width and bidi controls), which render as nothing.
// Comments, <noscript>, <template>, attributes (alt, aria-label, title) and
// <script> never become text nodes in the rendered tree, so they are not
// read at all. The thresholds are a starting point, not a standard.
function visibleText(doc, { gradientStops = true } = {}) {
  const MIN_FONT_PX = 6;
  const MIN_CONTRAST = 1.6;
  const MIN_BOX_PX = 2;
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // The colours behind an element: the first opaque background-color up the
  // tree, plus every colour stop of a CSS gradient found on the way (text the
  // colour of one stop vanishes into that part of the gradient). A url()
  // background image is not inspected; only a pixel check can judge that.
  const backgroundsOf = (el) => {
    const out = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (gradientStops && s.backgroundImage.includes('gradient(')) {
        for (const m of s.backgroundImage.matchAll(/rgba?\([^)]+\)/g)) out.push(parse(m[0]));
      }
      const c = parse(s.backgroundColor);
      if (c && c.a > 0.5) { out.push(c); return out; }
    }
    out.push({ r: 255, g: 255, b: 255, a: 1 });
    return out;
  };
  const contrast = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const W = doc.documentElement.scrollWidth;
  const H = doc.documentElement.scrollHeight;
  const reasons = {};
  let last = '';
  const why = (el, r) => { reasons[r] = (reasons[r] || 0) + 1; last = r; return false; };
  const cache = new Map();
  const cacheWhy = new Map();
  const elementOk = (el) => {
    if (cache.has(el)) { last = cache.get(el) ? '' : cacheWhy.get(el); return cache.get(el); }
    let ok = true;
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true })) ok = why(el, 'not rendered');
    const cs = getComputedStyle(el);
    if (ok && parseFloat(cs.fontSize) < MIN_FONT_PX) ok = why(el, 'font < 6px');
    if (ok) {
      const fg = parse(cs.color);
      if (fg && (fg.a < 0.1 || Math.min(...backgroundsOf(el).map((b) => contrast(fg, b))) < MIN_CONTRAST)) ok = why(el, 'low contrast');
    }
    if (ok) {
      for (let e = el; e && e !== doc.body; e = e.parentElement) {
        const s = getComputedStyle(e);
        if (parseFloat(s.opacity) < 0.1) { ok = why(el, 'transparent'); break; }
        const r = e.getBoundingClientRect();
        if ((s.overflow !== 'visible' || s.clipPath !== 'none' || s.clip !== 'auto') && (r.width < MIN_BOX_PX || r.height < MIN_BOX_PX)) { ok = why(el, 'clipped'); break; }
      }
    }
    cache.set(el, ok);
    cacheWhy.set(el, last);
    return ok;
  };
  const boxVisible = (node, el) => {
    const range = doc.createRange();
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) return why(el, 'no box');
    let onPage = false;
    let uncovered = false;
    for (const r of rects) {
      const x = r.left + r.width / 2 + window.scrollX;
      const y = r.top + r.height / 2 + window.scrollY;
      if (r.right <= 0 || r.bottom <= 0 || r.left >= W || r.top >= H) continue;
      onPage = true;
      const hit = doc.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (hit && (hit === el || el.contains(hit) || hit.contains(el))) { uncovered = true; break; }
    }
    if (!onPage) return why(el, 'off page');
    if (!uncovered) return why(el, 'covered');
    return true;
  };
  const out = [];
  const removed = [];
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  let lastBlock = null;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.data.trim()) continue;
    const el = n.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    if (!elementOk(el) || !boxVisible(n, el)) { removed.push({ reason: last, text: n.data.slice(0, 200) }); continue; }
    const block = el.closest('p,li,h1,h2,h3,h4,h5,h6,td,th,pre,blockquote,figcaption,div,section,article');
    out.push((lastBlock && block !== lastBlock ? '\n' : '') + n.data);
    lastBlock = block;
  }
  const joined = out.join('');
  const formatChars = (joined.match(/\p{Cf}/gu) || []).length;
  const text = joined.replace(/\p{Cf}/gu, '').replace(/[ \t]+/g, ' ');
  return { text, dropped: reasons, removed, formatChars };
}
