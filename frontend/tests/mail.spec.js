import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}})); await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });

test.beforeEach(async ({ page }) => {
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [
    { provider: 'google', configured: true, connected: true, email: 'sender@example.com' },
    { provider: 'microsoft', configured: true, connected: false },
  ] }));
  await page.route('**/api/emails/draft', r => r.fulfill({ json: { language: 'ro', subject: 'Cerere P1', body: 'Bună ziua, solicităm P1.', translated: false } }));
});

async function draft(page) {
  await page.goto('/#email');
  await page.locator('.email-layout').getByLabel('Cod articol').fill('P1');
  await page.getByRole('button', { name: 'Generează draftul' }).click();
}

test('company logo is previewed, sent explicitly, and removable', async ({ page }) => {
  await page.goto('/#email');
  await page.getByText('Logo-ul firmei · opțional', { exact: true }).click();
  await page.getByLabel('Alege logo-ul firmei').setInputFiles({ name: 'logo.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg/>') });
  await expect(page.getByRole('alert')).toContainText('PNG sau JPEG');
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Y1sAAAAASUVORK5CYII=', 'base64');
  await page.getByLabel('Alege logo-ul firmei').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: png });
  await expect(page.getByAltText('Logo inclus în e-mail')).toBeVisible();
  await page.locator('.email-layout').getByLabel('Cod articol').fill('P1');
  await page.getByRole('button', { name: 'Generează draftul' }).click();
  await page.getByLabel('Trimite din contul').selectOption('google');
  await page.getByLabel('Destinatar', { exact: true }).fill('buyer@example.com');
  await page.getByRole('checkbox', { name: 'Am verificat destinatarul' }).check();
  let sends = 0;
  await page.route('**/api/emails/send', r => {
    expect(r.request().postDataJSON().logo_base64).toBeTruthy();
    sends++;
    return r.fulfill({ json: { status: 'accepted' } });
  });
  await page.screenshot({ path: test.info().outputPath('email-logo.png'), fullPage: true });
  await page.getByRole('button', { name: 'Trimite e-mailul', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Mesaj acceptat');
  expect(sends).toBe(1);
  await page.getByRole('button', { name: 'Elimină logo-ul' }).click();
  await expect(page.getByAltText('Logo inclus în e-mail')).toHaveCount(0);
  await expect(page.locator('.draft-meta')).toContainText('neverificată');
});

test('instant preview, grounded article selection, and stale draft cannot be sent', async ({ page }) => {
  let generations = 0;
  await page.route('**/api/emails/draft', r => {
    generations++;
    expect(r.request().postDataJSON()).not.toHaveProperty('sender_name');
    return r.fulfill({ json: { language: 'ro', subject: 'Cerere BRG-42', body: 'BRG-42 verificat', translated: false } });
  });
  await page.route('**/api/articles/search?*', r => r.fulfill({ json: { items: [{ seller_code: 'BRG-42', name: 'Rulment motor', unit_code: 'pcs', supplier: 'Supplier', invoice_number: 'F123', issue_date: '2026-01-02', quantity: 999 }] } }));
  await page.route('**/api/chat', r => {
    expect(r.request().postDataJSON().live_web).toBe(false);
    return r.fulfill({ json: { answer: 'Verifică diametrul în fișa tehnică [motor:2].', citations: [{ doc_id: 'motor', page: 2 }], exact: [] } });
  });
  await page.goto('/#email');
  await expect(page.getByLabel('Numele expeditorului')).toHaveCount(0);
  await page.getByText('Nu știi codul? Te ajută asistentul.', { exact: true }).click();
  await page.getByLabel('Denumire articol sau întrebare').fill('rulment');
  await page.getByRole('button', { name: 'Caută în facturi' }).click();
  await expect(page.locator('.article-suggestion')).toContainText('F123');
  await page.getByRole('button', { name: 'Adaugă în e-mail' }).click();
  await expect(page.locator('.email-layout').getByLabel('Cod articol')).toHaveValue('BRG-42');
  await expect(page.locator('.email-layout').getByLabel('Cantitate · opțional')).toHaveValue('');
  await expect(page.getByLabel('Subiect', { exact: true })).toHaveValue('Cerere de ofertă – BRG-42');
  await expect(page.locator('#draft-body')).toHaveValue(/Rulment motor/);
  expect(generations).toBe(0);
  await page.getByLabel('Denumire articol sau întrebare').fill('Ce diametru are rulmentul?');
  await page.getByRole('button', { name: 'Întreabă documentele' }).click();
  await expect(page.locator('.email-assistant-history')).toContainText('motor · p. 2');
  await page.getByRole('button', { name: 'Generează draftul' }).click();
  await expect(page.locator('.draft-meta')).toContainText('verificat');
  await page.locator('.email-layout').getByLabel('Cantitate · opțional').fill('4');
  await expect(page.locator('.draft-meta')).toContainText('neverificată');
  await expect(page.getByRole('button', { name: 'Trimite e-mailul', exact: true })).toHaveCount(0);
  await page.getByLabel('Limba mesajului').selectOption('zh-CN');
  await expect(page.locator('.preview-guidance')).toContainText('Previzualizare în engleză');
  await page.screenshot({ path: test.info().outputPath('email-assistant-preview.png'), fullPage: true });
});

test('provider logos and explicit send with exact preview and no duplicate', async ({ page }) => {
  let sends = 0;
  await page.route('**/api/emails/send', async r => {
    sends++;
    expect(r.request().postDataJSON()).toMatchObject({ provider: 'google', to: 'buyer@example.com', subject: 'Cerere P1', body: 'Bună ziua, solicităm P1.', confirmed: true });
    await r.fulfill({ json: { status: 'accepted' } });
  });
  await draft(page);
  await expect(page.locator('.mail-provider-name svg')).toHaveCount(2);
  const send = page.getByRole('button', { name: 'Trimite e-mailul', exact: true });
  await expect(send).toBeDisabled();
  await page.getByLabel('Trimite din contul').selectOption('google');
  await page.getByLabel('Destinatar', { exact: true }).fill('buyer@example.com');
  await expect(send).toBeDisabled();
  await page.getByRole('checkbox', { name: 'Am verificat destinatarul' }).check();
  expect(sends).toBe(0);
  await send.click();
  await expect(page.getByRole('status')).toContainText('Mesaj acceptat');
  await expect(send).toBeDisabled();
  expect(sends).toBe(1);
  await page.screenshot({ path: test.info().outputPath('email-delivery.png'), fullPage: true });
});

test('uncertain delivery disables resend and explains verification', async ({ page }) => {
  await page.route('**/api/emails/send', r => r.abort());
  await draft(page);
  await page.getByLabel('Trimite din contul').selectOption('google');
  await page.getByLabel('Destinatar', { exact: true }).fill('buyer@example.com');
  await page.getByRole('checkbox', { name: 'Am verificat destinatarul' }).check();
  await page.getByRole('button', { name: 'Trimite e-mailul', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Rezultat neconfirmat');
  await expect(page.getByRole('button', { name: 'Trimite e-mailul', exact: true })).toBeDisabled();
});

test('unconfigured providers are clear and mobile fits', async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [{ provider: 'google', configured: false }, { provider: 'microsoft', configured: false }] }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#email');
  await expect(page.getByRole('button', { name: 'Conectează cu Google' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Conectează cu Microsoft' })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('Microsoft connect opens authorization while retaining the generated draft', async ({ page, context }) => {
  let connected = false;
  await page.route('**/api/emails/accounts/microsoft/connect', r => {
    connected = true;
    return r.fulfill({ json: { url: 'http://127.0.0.1:5175/oauth-test' } });
  });
  await context.route('**/oauth-test', r => r.fulfill({ contentType: 'text/html', body: '<p>Provider authorization test</p>' }));
  await draft(page);
  const opened = context.waitForEvent('page');
  await page.getByRole('button', { name: 'Conectează cu Microsoft' }).click();
  const popup = await opened;
  await expect(popup).toHaveURL(/oauth-test/);
  expect(connected).toBe(true);
  await expect(page.getByLabel('Subiect', { exact: true })).toHaveValue('Cerere P1');
  await popup.close();
});

test('unconfigured account shows exact missing settings and setup without exposing secrets', async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [{ provider: 'google', configured: false, setup: { missing_settings: ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'], invalid_settings: [], redirect_uri: 'http://127.0.0.1:8080/api/emails/accounts/google/callback' } }, { provider: 'microsoft', configured: false }] }));
  await page.goto('/#email');
  await page.getByText('Configurează Google', { exact: true }).click();
  await expect(page.locator('.mail-setup').first()).toContainText('GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET');
  await expect(page.locator('.mail-setup').first()).toContainText('http://127.0.0.1:8080/api/emails/accounts/google/callback');
  await expect(page.locator('.mail-setup').first()).toContainText('python3 scripts/configure_email.py --provider google');
  await expect(page.getByRole('button', { name: 'Conectează cu Google', exact: true })).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath('oauth-setup.png'), fullPage: true });
});

test('unreachable mail service is reported separately from unconfigured OAuth', async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ status: 503, json: { detail: 'Serviciul e-mail nu răspunde.' } }));
  await page.goto('/#email');
  await expect(page.locator('.mail-accounts')).toContainText('Disponibilitatea conectării nu a putut fi verificată.');
  await expect(page.locator('.mail-accounts')).toContainText('Serviciul e-mail nu răspunde.');
});
