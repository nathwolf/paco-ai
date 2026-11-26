/* Shared appearance for the workspace and its embedded settings/meeting pages. */
(() => {
  const choices = ['system', 'light', 'dark'];
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = document.documentElement.dataset.themePreference || 'system';
  function apply(value) {
    if (!choices.includes(value)) return;
    preference = value;
    document.documentElement.dataset.themePreference = value;
    document.documentElement.dataset.theme = value === 'system' ? (media.matches ? 'dark' : 'light') : value;
    const select = document.getElementById('theme-choice');
    if (select) select.value = value;
    if (window === window.top) window.webkit?.messageHandlers?.paco?.postMessage('theme:' + value);
  }
  function children(value) {
    document.querySelectorAll('iframe').forEach(frame => frame.contentWindow?.postMessage({paco: 'theme', value}, location.origin));
  }
  function publish(value) {
    apply(value);
    children(value);
    if (window !== window.top) window.parent.postMessage({paco: 'theme', value}, location.origin);
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.data?.paco !== 'theme' || !choices.includes(event.data.value)) return;
    apply(event.data.value);
    if (window === window.top) children(event.data.value);
  });
  media.addEventListener('change', () => apply(preference));
  apply(preference);
  document.addEventListener('DOMContentLoaded', () => {
    apply(preference);
    const select = document.getElementById('theme-choice');
    if (!select) return;
    select.addEventListener('change', async () => {
      const previous = preference, value = select.value;
      const status = document.getElementById('theme-status');
      select.disabled = true;
      publish(value);
      try {
        const response = await fetch('/api/action', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Paco': '1'}, body: JSON.stringify({action: 'preference', key: 'theme', value})});
        if (!response.ok) throw Error('Could not save the theme. Please try again.');
        status.textContent = 'Theme saved';
      } catch (error) {
        publish(previous);
        status.textContent = error.message;
      } finally {
        select.disabled = false;
      }
    });
  });
})();
