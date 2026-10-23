import { test, expect } from '@playwright/test';
test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}}));

});

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

test('folder can be removed from the technical chat without leaving it', async ({ page }) => {
  let removed = false;
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: true, sources: removed ? [] : [{ id: 'source-1', name: 'Test ofertari', kind: 'upload', status: 'pending', counts: { pending: 1 }, files: [{ path: 'certificat.pdf', status: 'pending' }] }] } }));
  await page.route('**/api/sources/source-1', r => { expect(r.request().method()).toBe('DELETE'); removed = true; return r.fulfill({ json: { ok: true, status: 'removed' } }); });
  await page.goto('/#chat');
  await expect(page.locator('.notebook-sources')).toContainText('certificat.pdf');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Elimină folderul Test ofertari', exact: true }).click();
  await expect(page.locator('.notebook-sources')).not.toContainText('certificat.pdf');
  await expect(page).toHaveURL(/#chat$/);
});

test('service banner recovers automatically after the document worker starts', async ({ page }) => {
  await page.clock.install();
  let active = false;
  await page.route('**/api/diagnostics', r => r.fulfill({ json: { ok: active, services: [{ id: 'source_worker', label: 'Procesarea documentelor', status: active ? 'ok' : 'unavailable', required: false }] } }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: active, sources: [] } }));
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.goto('/#chat');
  await expect(page.locator('.service-status summary')).toHaveText('Unele servicii necesită atenție');
  active = true;
  await page.clock.runFor(30000);
  await expect(page.locator('.service-status summary')).toHaveText('Servicii disponibile');
  await expect(page.locator('.notebook-sources .warning')).toHaveCount(0);
});

test('document can be removed directly in chat and other files remain', async ({ page }) => {
  let removed = false;
  const files = [{ path: 'certificat.pdf', doc_id: 'SRC-first', status: 'indexed' }, { path: 'preturi.pdf', doc_id: 'SRC-second', status: 'indexed' }];
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: true, sources: [{ id: 'source-1', name: 'Test ofertari', kind: 'upload', status: 'ready', counts: { indexed: removed ? 1 : 2 }, files: removed ? [files[1]] : files }] } }));
  await page.route('**/api/sources/source-1/files/SRC-first', r => { expect(r.request().method()).toBe('DELETE'); removed = true; return r.fulfill({ json: { ok: true } }); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#chat');
  page.once('dialog', d => d.accept());
  await page.getByRole('button', { name: 'Elimină documentul certificat.pdf', exact: true }).click();
  await expect(page.locator('.notebook-sources')).not.toContainText('certificat.pdf');
  await expect(page.locator('.notebook-sources')).toContainText('preturi.pdf');
  await expect(page.locator('.notebook-sources')).toContainText('Test ofertari');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('individual-remove-mobile.png'), fullPage: true });
});
