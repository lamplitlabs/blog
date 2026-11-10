// In-page render pipelines for scripts/markdown-image-exfil/bench.py.
//
// The bench serves one page per (reply, pipeline). The page defines
//   window.__CASE = { html, md_html_off, pipe, allow: [hosts] }
// and loads this file, which puts the model reply into #reply the way the
// named pipeline does, then exposes window.__measure() for the driver.
//
// Pipelines (the defence a chat UI applies between the markdown renderer and the DOM):
//   innerhtml      markdown-it (html: true) -> el.innerHTML
//   html_off       markdown-it (html: false) -> el.innerHTML
//   regex_strip    markdown images removed from the source with a regex, then as innerhtml
//   detached_filter parse into a detached <div> with innerHTML, drop <img> whose src host is
//                  not allowlisted, move the rest into the page
//   sethtml        el.setHTML(html) with the browser's default Sanitizer
//   sethtml_img    el.setHTML(html) with the default Sanitizer plus <img src alt title>
//   inert_allowlist <template>.setHTML with an explicit element list (img and a included),
//                  then every <img> whose src host is not allowlisted becomes its alt text
//   csp            innerhtml under the response header
//                  Content-Security-Policy: default-src 'self'; img-src 'self' <cdn>; ...
//   csp_inert      csp header + inert_allowlist
(function () {
  const C = window.__CASE;
  const out = document.getElementById('reply');
  const allowed = (url) => {
    try {
      const u = new URL(url, location.href);
      return (u.protocol === 'http:' || u.protocol === 'https:') && C.allow.includes(u.host);
    } catch (e) {
      return false;
    }
  };
  const SAFE = new Sanitizer({
    elements: ['p', 'br', 'em', 'strong', 'code', 'pre', 'ul', 'ol', 'li', 'blockquote', 'hr',
      'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
      { name: 'a', attributes: ['href', 'title'] },
      { name: 'img', attributes: ['src', 'alt', 'title'] }],
  });
  const withImg = () => {
    const s = new Sanitizer();
    s.allowElement({ name: 'img', attributes: ['src', 'alt', 'title'] });
    return s;
  };
  const inert = (html) => {
    const t = document.createElement('template');
    t.setHTML(html, { sanitizer: SAFE });
    for (const img of t.content.querySelectorAll('img')) {
      if (!allowed(img.getAttribute('src') || '')) {
        img.replaceWith(document.createTextNode('[image blocked: ' + (img.getAttribute('alt') || 'no alt') + ']'));
      }
    }
    return t.content;
  };
  const t0 = performance.now();
  switch (C.pipe) {
    case 'innerhtml':
    case 'regex_strip':
    case 'csp':
      out.innerHTML = C.html;
      break;
    case 'html_off':
      out.innerHTML = C.md_html_off;
      break;
    case 'detached_filter': {
      const d = document.createElement('div');
      d.innerHTML = C.html; // the parse itself starts image requests
      for (const img of d.querySelectorAll('img')) if (!allowed(img.getAttribute('src') || '')) img.remove();
      out.replaceChildren(...d.childNodes);
      break;
    }
    case 'sethtml':
      out.setHTML(C.html);
      break;
    case 'sethtml_img':
      out.setHTML(C.html, { sanitizer: withImg() });
      break;
    case 'inert_allowlist':
    case 'csp_inert':
      out.replaceChildren(inert(C.html));
      break;
    default:
      throw new Error('unknown pipeline ' + C.pipe);
  }
  const ms = performance.now() - t0;
  window.__measure = () => {
    const imgs = [...out.querySelectorAll('img')];
    return {
      ms,
      dom_imgs: imgs.length,
      loaded_imgs: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
      links: [...out.querySelectorAll('a[href]')].map((a) => a.href),
      html_len: out.innerHTML.length,
    };
  };
})();
