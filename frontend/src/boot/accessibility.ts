import { defineBoot } from '#q-app/wrappers';

function labelLoadingBars(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>('.q-loading-bar[role="progressbar"]')
    .forEach((bar) => bar.setAttribute('aria-label', 'Cargando página'));
}

export default defineBoot(() => {
  labelLoadingBars();
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes' && record.target instanceof HTMLElement) {
        if (record.target.matches('.q-loading-bar[role="progressbar"]') && !record.target.getAttribute('aria-label')) {
          record.target.setAttribute('aria-label', 'Cargando página');
        }
        continue;
      }
      for (const node of record.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches('.q-loading-bar[role="progressbar"]')) {
          node.setAttribute('aria-label', 'Cargando página');
        }
        labelLoadingBars(node);
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'role', 'aria-label'],
  });
});
