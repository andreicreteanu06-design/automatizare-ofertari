import { test, expect } from '@playwright/test';

test('organization login gates workspace and shows both providers', async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:true,user:null}}));
  await page.goto('/#chat');
  await expect(page.getByRole('link',{name:'Conectare cu Microsoft 365'})).toHaveAttribute('href','/api/auth/microsoft/login');
  await expect(page.getByRole('link',{name:'Conectare cu Google Workspace'})).toHaveAttribute('href','/api/auth/google/login');
  await expect(page.getByLabel('Întrebare tehnică')).toHaveCount(0);
});

test('offline preview does not claim backend availability', async ({ page }) => {
  await page.route('**/api/**', r => r.fulfill({status:502,body:''}));
  await page.goto('/#chat');
  await expect(page.getByText('Serverul nu este disponibil.', {exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Vezi interfața'}).click();
  await expect(page.locator('.service-status')).toContainText('Server indisponibil');
  await expect(page.getByLabel('Întrebare tehnică')).toBeVisible();
});

test('diagnostics names failed dependencies', async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/conversations', r => r.fulfill({json:[]}));
  await page.route('**/api/emails/accounts', r => r.fulfill({json:[]}));
  await page.route('**/api/sources', r => r.fulfill({json:{sources:[],worker_active:false}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:false,services:[{id:'colibri',label:'Modelul pentru răspunsuri',status:'unavailable',required:true}]}}));
  await page.goto('/#chat');
  await page.getByText('Unele servicii necesită atenție', {exact:true}).click();
  await expect(page.locator('.service-status')).toContainText('Modelul pentru răspunsuri · Indisponibil');
});
