(() => {
  const csrf = document.querySelector('meta[name=csrf-token]').content;
  const toasts = document.getElementById('toasts');
  const toast = (msg, kind = 'success') => { const t = document.createElement('div'); t.className = `toast t-${kind}`; t.setAttribute('role', 'status'); t.textContent = msg; toasts.append(t); fade(t); };
  const fade = t => setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 450); }, 4200);
  toasts.querySelectorAll('.toast').forEach(fade);
  // mobile nav
  const burger = document.querySelector('[data-nav]'), nav = document.getElementById('nav');
  burger?.addEventListener('click', () => burger.setAttribute('aria-expanded', nav.classList.toggle('open')));
  // skeleton -> image fade
  document.querySelectorAll('.skel').forEach(box => { const im = box.querySelector('img'); const done = () => box.classList.add('loaded');
    if (!im || im.complete) done(); else { im.addEventListener('load', done); im.addEventListener('error', done); } });
  // ajax add-to-cart (works without JS too: normal POST + redirect)
  document.querySelectorAll('form[data-ajax]').forEach(f => f.addEventListener('submit', async e => {
    e.preventDefault(); const btn = f.querySelector('button'); btn.disabled = true;
    try {
      const r = await fetch(f.action, { method: 'POST', body: new FormData(f), headers: { 'X-Requested-With': 'fetch', 'X-CSRFToken': csrf } });
      const d = await r.json(); toast(d.ok ? 'Added to cart' : d.msg, d.ok ? 'success' : 'error');
      if (d.ok) { const c = document.getElementById('cart-count'); c.textContent = d.count; c.animate([{ transform: 'scale(1.5)' }, { transform: 'scale(1)' }], 250); }
    } catch { toast('Connection problem. Try again.', 'error'); } finally { btn.disabled = false; }
  }));
  document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));
  document.querySelectorAll('[data-print]').forEach(b => b.addEventListener('click', () => print()));
  document.querySelectorAll('input[type=file][data-preview]').forEach(i => i.addEventListener('change', () => {
    const f = i.files[0]; if (f && f.size > 5 * 1024 * 1024) { toast('Image is over 5 MB.', 'error'); i.value = ''; } }));
})();
