(() => {
  const form = document.getElementById('appearance-form');
  if (!form) return;
  function update() {
    const enabled = document.getElementById('id_appearance_enabled').checked;
    const colour = document.getElementById('id_overlay_colour').value;
    const opacity = Math.max(65, Math.min(100, Number(document.getElementById('id_overlay_opacity').value))) / 100;
    const preview = document.getElementById('appearance-preview');
    preview.hidden = !enabled;
    document.getElementById('preview-note').textContent = enabled ? 'Background preview only; exhibition layouts control content placement.' : 'The original presentation background will be used.';
    const rgb = colour.slice(1).match(/../g).map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    preview.style.color = rgb.reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0) > .179 ? '#000' : '#fff';
    const layer = document.getElementById('preview-overlay');
    layer.style.backgroundColor = colour;
    layer.style.opacity = opacity;
    document.getElementById('preview-copy').style.backgroundColor = colour;
    const chooser = document.getElementById('id_background_image-chooser');
    const chosen = chooser?.querySelector('.chosen img');
    const image = document.getElementById('preview-image');
    image.hidden = !chosen || chooser.classList.contains('blank');
    if (!image.hidden) image.src = chosen.src;
  }
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  const chooser = document.getElementById('id_background_image-chooser');
  if (chooser) {
    let chooserWasBlank = chooser.classList.contains('blank');
    new MutationObserver(() => {
      const chooserIsBlank = chooser.classList.contains('blank');
      if (chooserWasBlank && !chooserIsBlank) {
        document.getElementById('id_appearance_enabled').checked = true;
      }
      chooserWasBlank = chooserIsBlank;
      update();
    }).observe(chooser, {subtree:true, childList:true, attributes:true});
  }
  update();
})();
