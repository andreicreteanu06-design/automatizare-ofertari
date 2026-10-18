import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}})); await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });

test.beforeEach(async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [{ provider: 'google', configured: false }, { provider: 'microsoft', configured: false }] }));
});

test.beforeEach(async ({ page }) => {
  await page.route('**/api/conversations', route => route.request().method() === 'GET'
    ? route.fulfill({ json: [] })
    : route.fulfill({ json: { id: '11111111-1111-4111-8111-111111111111', version: 0, ...route.request().postDataJSON() } }));
});

const result = ok => ({ fx: { source: 'BNR', date: '2026-10-14', eur_ron: '5.00' }, lines: [{ code: 'P1', price_eur: '10', transport_eur: '0', duty_eur: '0', landed_eur: '10', sale_unit_eur: '12', sale_total_eur: '12', margin_eur: '2' }], total_landed_eur: '10.00', total_sale_eur: '12.00', total_margin_eur: '2.00', margin_on_sale_percent: '16.67', compliance: { ok, failures: ok ? [] : [{ code: 'PRICES_NOT_FIRM', message: 'Prețurile trebuie confirmate.' }] } });
async function fillOffer(page) {
  await page.getByLabel('Număr ofertă', { exact: true }).fill('OF-2026/1');
  await page.getByLabel('Nume client', { exact: true }).fill('Client SA');
  await page.getByLabel('Cod articol', { exact: true }).first().fill('P1');
  await page.getByLabel('Descriere', { exact: true }).first().fill('Piesă');
  await page.getByLabel('Furnizor', { exact: true }).first().fill('Furnizor SRL');
}
test('compliance, snapshot freshness, all binary exports, server 409', async ({ page }) => {
  let ok = false;
  let failExport = false;
  const requests = [];
  await page.route('**/api/offers/calculate', route => {
    const payload = route.request().postDataJSON();
    expect(typeof payload.markup_percent).toBe('string');
    expect(payload.fx_date).toBe(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Bucharest', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()));
    expect(typeof payload.lines[0].quantity).toBe('string');
    expect(payload.lines[0]._id).toBeUndefined();
    return route.fulfill({ json: result(ok) });
  });
  await page.route('**/api/offers/export/*', route => {
    requests.push(route.request().postDataJSON());
    return failExport ? route.fulfill({ status: 409, json: { detail: { error: 'Export refuzat', failures: [{ code: 'CERT_EXPIRED', message: 'Certificat expirat.' }] } } }) : route.fulfill({ contentType: 'application/octet-stream', headers: { 'content-disposition': 'attachment; filename="test.bin"' }, body: Buffer.from([1, 2, 3, 4]) });
  });
  await page.goto('/#offers');
  const word = page.getByRole('button', { name: 'Ofertă Word' });
  await expect(word).toBeDisabled();
  await fillOffer(page);
  await page.getByRole('button', { name: 'Calculează oferta' }).click();
  await expect(page.locator('.failures')).toContainText('Prețurile trebuie confirmate.');
  await expect(word).toBeDisabled();
  ok = true;
  await page.getByRole('button', { name: 'Calculează oferta' }).click();
  await expect(word).toBeEnabled();
  await page.getByLabel('Adaos comercial').fill('25');
  await expect(word).toBeDisabled();
  await page.getByRole('button', { name: 'Calculează oferta' }).click();
  await expect(word).toBeEnabled();
  await page.locator('.saga-options > summary').click();
  await page.getByLabel('CUI / CIF client').fill('RO12345674');
  await page.getByLabel('Serie și număr document').fill('OFT 1');
  for (const name of ['Ofertă Word', 'Calcul intern Excel', 'Import Saga']) {
    const event = page.waitForEvent('download');
    await page.getByRole('button', { name }).click();
    const file = await event;
    expect(file.suggestedFilename()).toBe('test.bin');
    const stream = await file.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    expect(Buffer.concat(chunks)).toEqual(Buffer.from([1, 2, 3, 4]));
    await expect(word).toBeEnabled();
  }
  expect(requests[2].client_cif).toBe('RO12345674');
  expect(requests[2].due_days).toBe(30);
  failExport = true;
  await word.click();
  await expect(page.getByRole('alert')).toContainText('Certificat expirat');
  await expect(word).toBeDisabled();
});
test('invoice selection preserves quantity and decimal precision', async ({ page }) => {
  await page.route('**/api/prices?*', route => route.fulfill({ json: { history: [{ name: 'Suport', supplier: 'Feroparts', invoice_number: 'F1', issue_date: '2026-10-01', net_unit_price: '549.123456', currency: 'EUR' }] } }));
  await page.goto('/#offers');
  await page.getByLabel('Cod articol', { exact: true }).first().fill('3EST-000-123');
  await page.getByLabel('Cantitate', { exact: true }).fill('4');
  await page.getByRole('button', { name: 'Caută preț în facturi' }).click();
  await page.getByRole('button', { name: 'Folosește' }).click();
  await expect(page.getByLabel('Preț / unitate')).toHaveValue('549.123456');
  await expect(page.getByLabel('Cantitate', { exact: true })).toHaveValue('4');
  await expect(page.getByLabel('Descriere', { exact: true }).first()).toHaveValue('Suport');
});
test('chat renders citations, invoice table and untrusted content as text', async ({ page }) => {
  await page.route('**/api/chat', route => route.fulfill({ json: { answer: '12 kg [FT:3] <img src=x onerror=alert(1)>', grounded: false, citations: [{ cite: '[FT:3]', doc_id: 'FT', page: 3, supplier: 'Furnizor', doc_type: 'Fișă tehnică' }], removed_codes: ['UNKNOWN'], exact: [{ seller_code: 'P1', name: 'Piesă', supplier: 'Furnizor', invoice_number: 'F1', issue_date: '2026-10-01', quantity: '4', unit_code: 'H87', unit_price: '555.000000', net_unit_price: '549.000000', currency: 'EUR' }] } }));
  await page.goto('/#offers');
  await page.getByRole('button', { name: 'Chat tehnic' }).click();
  await page.getByLabel('Întrebare tehnică').fill('Detalii P1');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.citation')).toHaveText('FT · p. 3');
  await expect(page.getByText('549.000000 EUR', { exact: true })).toBeVisible();
  await expect(page.locator('.answer-text img')).toHaveCount(0);
  await expect(page.locator('.answer-text')).toContainText('<img');
  await expect(page.getByText('Coduri eliminate ca neverificate: UNKNOWN.')).toBeVisible();
});
test('email clarification payload, translated preview and gateway error', async ({ page }) => {
  let fail = false;
  await page.route('**/api/emails/draft', route => {
    const body = route.request().postDataJSON();
    expect(body.language).toBe('de');
    expect(body.kind).toBe('clarification');
    expect(body.questions).toEqual(['Termen de livrare?']);
    expect(body.client_name).toBeUndefined();
    expect(body.items[0].quantity).toBeNull();
    return fail ? route.fulfill({ status: 503, json: { detail: 'Egress Guard indisponibil' } }) : route.fulfill({ json: { language: 'de', translated: true, subject: 'Technische Anfrage', body: 'Guten Tag\nP1' } });
  });
  await page.goto('/#offers');
  await page.getByRole('button', { name: 'Draft e-mail' }).click();
  await page.getByLabel('Tip e-mail').selectOption('clarification');
  await page.getByLabel('Limba mesajului').selectOption('de');
  await page.locator('.email-layout').getByLabel('Cod articol').fill('P1');
  await page.getByLabel('Întrebări tehnice').fill('Termen de livrare?');
  await page.getByRole('button', { name: 'Generează draftul' }).click();
  await expect(page.getByLabel('Subiect', { exact: true })).toHaveValue('Technische Anfrage');
  await expect(page.getByRole('textbox', { name: 'Mesaj', exact: true })).toHaveValue('Guten Tag\nP1');
  fail = true;
  await page.getByRole('button', { name: 'Generează draftul' }).click();
  await expect(page.getByRole('alert')).toContainText('503');
  await expect(page.locator('.draft-meta')).toContainText('neverificată');
  await expect(page.getByRole('button', { name: 'Trimite e-mailul', exact: true })).toHaveCount(0);
});
test('mobile layout fits viewport and tabs retain state', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#offers');
  await page.getByLabel('Număr ofertă', { exact: true }).fill('OF-1');
  for (const name of ['Chat tehnic', 'Draft e-mail', 'Generator oferte']) {
    await page.getByRole('button', { name, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await expect(page.getByLabel('Număr ofertă', { exact: true })).toHaveValue('OF-1');
  await page.screenshot({ path: test.info().outputPath('mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: test.info().outputPath('desktop.png'), fullPage: true });
});
