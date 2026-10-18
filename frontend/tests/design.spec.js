import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}})); await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });

test.beforeEach(async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [{ provider: 'google', configured: false }, { provider: 'microsoft', configured: false }] }));
});

test('depth surfaces and reference chat render with server document limits', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true, limits: { file_bytes: 250 * 1024 ** 2, folder_bytes: 100 * 1024 ** 3, files: 50000 } } }));
  for (const section of ['chat', 'sources', 'offers']) {
    await page.goto(`/#${section}`);
    await page.evaluate(() => document.fonts.ready);
    if (section === 'sources') {
      await expect(page.getByText('Până la 250 MB', { exact: false })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Încarcă un folder', exact: true })).toBeEnabled();
    }
    if (section === 'chat') {
      const heading = await page.locator('.chat-hero-content').boundingBox();
      const composer = await page.locator('[data-composer]').boundingBox();
      expect(Math.abs((heading.x + heading.width / 2) - (composer.x + composer.width / 2))).toBeLessThan(2);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/depth-${section}.png`, fullPage: true });
  }
});

test('landing is local, theme works, navigation preserves the offer', async ({ page }) => {
  const external = [];
  page.on('request', r => { if (!r.url().startsWith('http://127.0.0.1:5175') && !r.url().startsWith('data:')) external.push(r.url()); });
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Informația prinde formă.' })).toBeVisible();
  await expect(page.locator('.sh-fallback')).toHaveJSProperty('complete', true);
  await page.getByRole('button', { name: 'Activează tema întunecată' }).click();
  await expect(page.getByRole('button', { name: 'Activează tema luminoasă' })).toBeVisible();
  await page.getByRole('link', { name: 'Creează o ofertă' }).click();
  await page.getByLabel('Număr ofertă', { exact: true }).fill('OF-DESIGN');
  await page.locator('.brand').click();
  await page.getByRole('link', { name: 'Începe o conversație' }).click();
  await expect(page.getByRole('heading', { name: 'Documentele tale. Răspunsuri cu surse.' })).toBeVisible();
  await page.getByRole('button', { name: 'Generator oferte', exact: true }).click();
  await expect(page.getByLabel('Număr ofertă', { exact: true })).toHaveValue('OF-DESIGN');
  expect(external).toEqual([]);
});

test('mobile landing and chat fit with reduced motion and no WebGL', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => { const get = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function(type, ...args) { return type.startsWith('webgl') ? null : get.call(this, type, ...args); }; });
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.goto('/');
  await expect(page.locator('.sh-root')).toHaveAttribute('data-gl', 'off');
  await expect.poll(() => page.locator('.sh-fallback').evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: 'test-results/landing-mobile.png', fullPage: true });
  await page.getByRole('link', { name: 'Începe o conversație' }).click();
  await expect(page.getByLabel('Întrebare tehnică')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: 'test-results/chat-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Date tehnice', exact: true }).click();
  await expect(page.getByLabel('Întrebare tehnică')).toHaveValue('Care sunt specificațiile tehnice pentru ');
  await expect(page.getByLabel('Întrebare tehnică')).toBeFocused();
  await expect(page.locator('.message.user')).toHaveCount(0);
});

test('chat cards use backend attempts without demo scores and retain failed drafts', async ({ page }) => {
  await page.route('**/api/conversations', route => route.request().method() === 'GET'
    ? route.fulfill({ json: [] }) : route.fulfill({ json: { id: '11111111-1111-4111-8111-111111111111', version: 0, project: 'General' } }));
  let fail = true;
  await page.route('**/api/chat', route => fail ? route.fulfill({ status: 503, json: { detail: 'Indisponibil temporar' } }) : route.fulfill({ json: {
    answer: 'Masa PART123: 12 kg [FT:1]', citations: [{ cite: '[FT:1]', doc_id: 'FT', page: 1 }], version: 1,
    verification_status: 'verified_excerpts', attempts: [{ attempt: 1, outcome: 'insufficient_evidence' }, { attempt: 2, outcome: 'verified_excerpts' }],
  } }));
  await page.goto('/#chat');
  await page.getByLabel('Întrebare tehnică').fill('Masa PART123?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.getByText('Indisponibil temporar')).toBeVisible();
  await expect(page.getByLabel('Întrebare tehnică')).toHaveValue('Masa PART123?');
  fail = false;
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('[data-branch-heading]')).toHaveText('Dovezi selectate: Căutare 2');
  await page.locator('[data-approaches-toggle]').click();
  await expect(page.getByText('Dovezile nu au fost suficiente.', { exact: true })).toBeVisible();
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/chat-answered.png', fullPage: true });
});
