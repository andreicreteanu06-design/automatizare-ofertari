import { test, expect } from '@playwright/test';

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
  await page.getByLabel('Numele expeditorului').fill('Ion');
  await page.getByLabel('Compania expeditorului').fill('Firma');
  await page.locator('.email-layout').getByLabel('Cod articol').fill('P1');
  await page.getByRole('button', { name: 'Generează draftul' }).click();
}

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
