import { test, expect } from '@playwright/test';

test('notebook shows indexed folders, citation passages, and explicit live mode', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: true, sources: [{ id: 's1', name: 'Fișe motoare', status: 'ready', counts: { indexed: 1 }, files: [{ path: 'motor.pdf', doc_id: 'SRC-motor', status: 'indexed' }] }] } }));
  await page.route('**/api/conversations', r => r.fulfill({ json: r.request().method() === 'GET' ? [] : { id: '11111111-1111-4111-8111-111111111111', version: 0, project: 'General' } }));
  const calls = [];
  await page.route('**/api/chat', r => {
    const body = r.request().postDataJSON(); calls.push(body);
    return r.fulfill({ json: { version: calls.length, live_web: body.live_web, answer: 'Masa: 12 kg [SRC-motor:2]', citations: [{ cite: '[SRC-motor:2]', doc_id: 'SRC-motor', page: 2 }], evidence: [{ id: 'e1', doc_id: 'SRC-motor', page: 2, quote: 'Masa motorului: 12 kg.' }], ...(body.live_web ? { web_research: { sources: [{ url: 'https://example.com/spec' }], pages: [] } } : {}) } });
  });
  await page.goto('/#chat');
  await expect(page.locator('.notebook-sources')).toContainText('motor.pdf');
  await expect(page.locator('.notebook-mode')).toContainText('internetul este oprit');
  await page.getByLabel('Întrebare tehnică').fill('Care este masa motorului?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await page.locator('.citation').click();
  await expect(page.locator('.notebook-evidence blockquote')).toContainText('12 kg');
  expect(calls[0].live_web).toBe(false);
  await page.getByLabel('Cautare Live').check();
  await page.getByLabel('Întrebare tehnică').fill('Există date publice pentru acest motor?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls[1].live_web).toBe(true);
  expect(calls[1]).not.toHaveProperty('documents');
  await page.setViewportSize({ width: 1800, height: 1050 });
  await page.screenshot({ path: 'test-results/notebook-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const frame = await page.locator('.technical-chat').boundingBox();
  const composer = await page.locator('[data-composer]').boundingBox();
  expect(composer.x).toBeGreaterThanOrEqual(frame.x);
  expect(composer.x + composer.width).toBeLessThanOrEqual(frame.x + frame.width);
  await page.screenshot({ path: 'test-results/notebook-mobile.png', fullPage: true });
});
