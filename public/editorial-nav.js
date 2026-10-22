/* Shared disclosure navigation: pointer, keyboard and mobile accordion. */
(() => {
  const isEnglish = document.documentElement.lang === 'en';
  const header = document.querySelector('.editorial-header');
  if (!header) return;
  const mobile = header.querySelector('.nav-toggle');
  const links = header.querySelector('.editorial-links');
  const groups = [...header.querySelectorAll('.nav-sections')];
  const small = matchMedia('(max-width: 640px)');
  const hover = matchMedia('(hover: hover)');
  function setOpen(group, open) {
    const toggle = group.querySelector('.section-toggle');
    const menu = group.querySelector('.section-menu');
    group.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    menu.inert = !open;
  }
  function closeAll(except = null) {
    groups.forEach(group => { if (group !== except) setOpen(group, false); });
  }
  function setMobile(open) {
    links.classList.toggle('is-open', open);
    mobile.setAttribute('aria-expanded', String(open));
    mobile.setAttribute('aria-label', open ? (isEnglish ? 'Close navigation' : '关闭导航') : (isEnglish ? 'Open navigation' : '打开导航'));
    if (!open) closeAll();
  }
  const path = location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/';
  header.querySelectorAll('.section-menu a').forEach(a => {
    if (a.getAttribute('href') === path) a.setAttribute('aria-current', 'page');
  });
  groups.forEach(group => {
    const toggle = group.querySelector('.section-toggle');
    const menu = group.querySelector('.section-menu');
    setOpen(group, false);
    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      closeAll(group); setOpen(group, open);
    });
    group.addEventListener('pointerenter', () => {
      if (hover.matches && !small.matches) { closeAll(group); setOpen(group, true); }
    });
    group.addEventListener('pointerleave', () => {
      if (hover.matches && !small.matches && !group.contains(document.activeElement)) setOpen(group, false);
    });
    toggle.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown') { event.preventDefault(); closeAll(group); setOpen(group, true); menu.querySelector('a').focus(); }
    });
  });
  mobile.addEventListener('click', () => setMobile(mobile.getAttribute('aria-expanded') !== 'true'));
  header.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const openGroup = groups.find(group => group.classList.contains('is-open'));
      if (openGroup) { const toggle = openGroup.querySelector('.section-toggle'); setOpen(openGroup, false); toggle.focus(); }
      else { setMobile(false); mobile.focus(); }
    }
  });
  header.addEventListener('focusout', event => {
    groups.forEach(group => { if (!group.contains(event.relatedTarget)) setOpen(group, false); });
  });
  document.addEventListener('click', event => { if (!header.contains(event.target)) setMobile(false); });
  small.addEventListener('change', () => setMobile(false));
})();
