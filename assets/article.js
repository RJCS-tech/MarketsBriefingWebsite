/* Reading progress bar + table-of-contents scrollspy for briefing pages. */
(function () {
  var bar = document.getElementById('progressBar');
  var links = Array.prototype.slice.call(document.querySelectorAll('#toc a'));
  var sections = links
    .map(function (a) { return document.querySelector(a.getAttribute('href')); })
    .filter(Boolean);

  function onScroll() {
    if (bar) {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
    }
    if (!sections.length) return;
    // Active = the last section whose top has passed a third of the viewport.
    var line = window.innerHeight / 3;
    var active = 0;
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].getBoundingClientRect().top <= line) active = i;
    }
    links.forEach(function (a, i) {
      a.classList.toggle('is-active', i === active);
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();
})();
