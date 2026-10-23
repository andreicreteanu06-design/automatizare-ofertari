import { test, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}})); await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });

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
  await expect(page.getByText('Încărcarea din browser salvează o copie.', { exact: false })).toBeVisible();
  await page.getByText('Conectează un folder monitorizat', { exact: true }).click();
  await page.getByRole('button', { name: 'Conectează', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Sursă adăugată');
  await expect(page.getByText('Folder monitorizat · În așteptare')).toBeVisible();
  await expect(page.locator('.source-library').getByText('0 documente indexate', { exact: false })).toBeVisible();
});

test('Drive connection validates folder ID and exposes missing worker', async ({ page }) => {
  await page.route('**/api/conversations', r => r.fulfill({ json: [] }));
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [] }));
  await page.route('**/api/sources', r => r.fulfill({ json: { worker_active: false, sources: [] } }));
  await page.goto('/#sources');
  await expect(page.getByText('Procesarea documentelor este oprită.', { exact: false })).toBeVisible();
  await page.getByText('Conectează un folder Google Drive', { exact: true }).click();
  await page.getByLabel('Numele sursei Drive').fill('Catalog');
  await page.getByLabel('ID folder Google Drive').fill('https://drive.google.com/folders/123');
  await expect(page.getByRole('button', { name: 'Conectează Google Drive', exact: true })).toBeDisabled();
  await page.getByLabel('ID folder Google Drive').fill('folder12345678');
  await expect(page.getByRole('button', { name: 'Conectează Google Drive', exact: true })).toBeEnabled();
});

test('uploaded folder and filenames are visible with worker stopped, before advanced connections', async ({ page }, testInfo) => {
  const folder = testInfo.outputPath('test ofertari');
  await mkdir(path.join(folder, 'tehnice'), { recursive: true });
  await writeFile(path.join(folder, 'tehnice', 'certificat.pdf'), '%PDF-test');
  await writeFile(path.join(folder, 'preturi.csv'), 'cod,pret\nPART123,19.80');
  await writeFile(path.join(folder, 'ignored.exe'), 'unsupported');
  let source;
  const files = [];
  await page.route('**/api/sources', r => {
    if (r.request().method() === 'POST') {
      expect(r.request().postDataJSON()).toEqual({ name: 'test ofertari', kind: 'upload' });
      source = { id: 'source-upload', kind: 'upload', name: 'test ofertari', status: 'pending', counts: {}, files };
      return r.fulfill({ json: { id: source.id } });
    }
    return r.fulfill({ json: { worker_active: false, sources: source ? [source] : [], limits: { file_bytes: 250 * 1024 ** 2, folder_bytes: 100 * 1024 ** 3, files: 50000 } } });
  });
  await page.route('**/api/sources/source-upload/upload?*', r => {
    expect(r.request().headers()['x-source-action']).toBe('1');
    files.push({ path: new URL(r.request().url()).searchParams.get('path'), status: 'pending', doc_id: 'SRC-test' });
    source.counts.pending = files.length;
    return r.fulfill({ json: { ok: true, status: 'pending' } });
  });
  await page.goto('/#sources');
  await expect(page.getByRole('button', { name: 'Încarcă un folder', exact: true })).toBeEnabled();
  await page.getByLabel('Folder de încărcat').setInputFiles(folder);
  const catalog = page.getByRole('region', { name: 'Foldere adăugate' });
  await expect(catalog.getByRole('heading', { name: 'test ofertari', exact: true })).toBeVisible();
  await expect(catalog).toContainText('2 fișiere în bibliotecă · 0 documente indexate');
  await expect(catalog.getByText('test ofertari/tehnice/certificat.pdf', { exact: true })).toBeVisible();
  await expect(catalog.getByText('test ofertari/preturi.csv', { exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('2 fișiere încărcate. 1 fișiere cu alte formate');
  const listing = await catalog.boundingBox();
  const advanced = await page.getByRole('heading', { name: 'Alte surse de documente' }).boundingBox();
  expect(listing.y).toBeLessThan(advanced.y);
  await page.screenshot({ path: testInfo.outputPath('uploaded-folder.png'), fullPage: true });
});

test('cancel removal keeps folder; confirmed removal uses DELETE and removes card', async ({ page }) => {
  let removed = false, calls = 0;
  const source = { id: 'source-1', name: 'Test ofertari', kind: 'upload', status: 'pending', counts: { pending: 1 }, files: [{ path: 'test.pdf', status: 'pending' }] };
  await page.route('**/api/sources', r => r.fulfill({ json: { sources: removed ? [] : [source], worker_active: false } }));
  await page.route('**/api/sources/source-1', r => {
    expect(r.request().method()).toBe('DELETE');
    expect(r.request().headers()['x-source-action']).toBe('1');
    calls++; removed = true;
    return r.fulfill({ json: { ok: true, status: 'removed' } });
  });
  await page.goto('/#sources');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Elimină folderul Test ofertari', exact: true }).click();
  expect(calls).toBe(0);
  await expect(page.getByRole('heading', { name: 'Test ofertari', exact: true })).toBeVisible();
  page.once('dialog', dialog => { expect(dialog.message()).toContain('Originalele de pe calculator rămân păstrate'); return dialog.accept(); });
  await page.getByRole('button', { name: 'Elimină folderul Test ofertari', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Test ofertari', exact: true })).toHaveCount(0);
  expect(calls).toBe(1);
});

test('failed removal retains the folder and shows the error', async ({ page }) => {
  await page.route('**/api/sources', r => r.fulfill({ json: { sources: [{ id: 'source-1', name: 'Technical', kind: 'local', status: 'pending', counts: {}, files: [] }], worker_active: true } }));
  await page.route('**/api/sources/source-1', r => r.fulfill({ status: 503, json: { detail: 'Operația nu este disponibilă momentan.' } }));
  await page.goto('/#sources');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Elimină folderul Technical', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Operația nu este disponibilă momentan.');
  await expect(page.getByRole('heading', { name: 'Technical', exact: true })).toBeVisible();
});
