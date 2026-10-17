import { test, expect } from '@playwright/test';

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
  await expect(page.getByText('O întrebare. Mai multe surse.')).toBeVisible();
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
