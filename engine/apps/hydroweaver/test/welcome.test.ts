// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { expect, it, vi } from 'vitest';

it('preserves drafts, allows manual copying, and updates the welcome language', async () => {
  const observe = vi.spyOn(window.MutationObserver.prototype, 'observe');
  let locale = 'en';
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: { getItem: () => locale },
  });
  document.documentElement.lang = 'en';
  document.body.innerHTML = '<div><div class="empty-composer"><textarea></textarea></div></div>';
  const editor = document.querySelector('textarea')!;
  editor.value = 'My existing draft';
  const keydown = vi.fn();
  editor.addEventListener('keydown', keydown);
  document.execCommand = vi.fn(() => false);
  const writeText = vi.fn().mockRejectedValue(new Error('Clipboard denied'));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  window.eval(readFileSync('theme/hydroweaver-welcome.js', 'utf8'));
  const flush = () => new Promise((resolve) => setTimeout(resolve, 50));
  await flush();

  document.querySelector<HTMLButtonElement>('.oa-welcome-card')!.click();
  expect(editor.value).toContain('My existing draft\n\nAssess arsenic-contaminated groundwater');
  expect(keydown).not.toHaveBeenCalled();

  document.querySelectorAll<HTMLButtonElement>('.oa-welcome-cite-btn')[1].click();
  await flush();
  const manualCopy = document.querySelector<HTMLTextAreaElement>('.oa-welcome-cite textarea')!;
  expect(manualCopy.hidden).toBe(false);
  expect(manualCopy.value).toContain('@software{hydroweaver2026,\n  title');
  expect(manualCopy.value).not.toContain('\\n');
  expect(document.querySelector('.oa-welcome-cite [role="status"]')!.textContent).toContain('Could not copy');

  locale = 'zh';
  document.body.append(document.createTextNode('Application language updated'));
  await flush();
  expect(document.querySelector('.oa-welcome-card-title')!.textContent).toContain('地下水砷污染');
  expect(editor.value).toContain('My existing draft');
  observe.mock.instances.forEach((observer) => observer.disconnect());
  observe.mockRestore();
});
