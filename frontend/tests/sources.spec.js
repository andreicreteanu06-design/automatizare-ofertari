import { test, expect } from '@playwright/test';

test('connects only a selected authorized folder and displays indexing status', async ({ page }) => {
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  let connected = false;
  await page.route('**/api/sources', r => {
    if (r.request().method() === 'POST') {
      expect(r.request().headers()['x-source-action']).toBe('1');
      expect(r.request().postDataJSON()).toEqual({ name: 'Technical', kind: 'local', path: 'Technical' });
      connected = true;
      return r.fulfill({ json: { id: 'source-1' } });
    }
    return r.fulfill({ json: { worker_active: true, sources: connected ? [{ id: 'source-1', name: 'Technical', kind: 'local', status: 'pending', counts: {}, files: [] }] : [] } });
  });
  await page.route('**/api/sources/folders?*', r => r.fulfill({ json: { configured: true, folders: [{ name: 'Technical', path: 'Technical' }] } }));
  await page.goto('/#sources');
  await expect(page.getByText('Încărcarea salvează o copie.', { exact: false })).toBeVisible();
  await page.getByText('Conectează un folder monitorizat', { exact: true }).click();
  await page.getByRole('button', { name: 'Conectează', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Sursă adăugată');
  await expect(page.getByText('Folder monitorizat · În așteptare')).toBeVisible();
  await expect(page.getByText('0 documente indexate', { exact: false })).toBeVisible();
});

test('Drive connection validates folder ID and exposes missing worker', async ({ page }) => {
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: false, sources: [] } }));
  await page.goto('/#sources');
  await expect(page.getByText('Monitorizarea nu este activă momentan.', { exact: false })).toBeVisible();
  await page.getByText('Conectează un folder Google Drive', { exact: true }).click();
  await page.getByLabel('Numele sursei Drive').fill('Catalog');
  await page.getByLabel('ID folder Google Drive').fill('https://drive.google.com/folders/123');
  await expect(page.getByRole('button', { name: 'Conectează Google Drive', exact: true })).toBeDisabled();
  await page.getByLabel('ID folder Google Drive').fill('folder12345678');
  await expect(page.getByRole('button', { name: 'Conectează Google Drive', exact: true })).toBeEnabled();
});
