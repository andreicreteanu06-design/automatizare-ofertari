import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', r => r.fulfill({json:{enabled:false,user:null}}));
  await page.route('**/api/diagnostics', r => r.fulfill({json:{ok:true,services:[]}})); await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });

test.beforeEach(async ({ page }) => {
  await page.route('**/api/emails/accounts', r => r.fulfill({ json: [{ provider: 'google', configured: false }, { provider: 'microsoft', configured: false }] }));
});

test('persistent conversation survives reload and submits version plus idempotency key', async ({ page }) => {
  let row = null;
  const payloads = [];
  await page.route('**/api/conversations', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: row ? [row] : [] });
    row = { id: '11111111-1111-4111-8111-111111111111', version: 0, messages: [], references: [], ...route.request().postDataJSON() };
    return route.fulfill({ json: row });
  });
  await page.route('**/api/conversations/*', route => route.fulfill({ json: row }));
  await page.route('**/api/chat', route => {
    const p = route.request().postDataJSON();
    payloads.push(p);
    expect(p.conversation_id).toBe(row.id);
    expect(p.version).toBe(row.version);
    expect(p.request_id).toMatch(/^[a-f0-9-]{36}$/);
    expect(p.live_web).toBe(payloads.length > 1);
    const data = { answer: 'Cod: PART123; Masa: 12 kg [FT:1]', citations: [{ cite: '[FT:1]', doc_id: 'FT', page: 1 }], exact: [], grounded: true, verification_status: 'verified_excerpts', version: ++row.version, attempts: [{ attempt: 1 }] };
    if (p.live_web) Object.assign(data, { evidence_status: 'unconfirmed', web_research: { pages: [{ url: 'https://supplier.example', access_status: 'blocked', stale: true, retrieved_at: '2026-10-14T10:00:00Z' }] } });
    row.messages.push({ role: 'user', text: p.query }, { role: 'assistant', data });
    return route.fulfill({ json: data });
  });
  await page.goto('/#offers');
  await page.getByRole('button', { name: 'Chat tehnic', exact: true }).click();
  await page.getByText('Setări de căutare', { exact: false }).click();
  await page.getByLabel('Proiect', { exact: true }).fill('Tren A');
  await page.getByLabel('Întrebare tehnică').fill('Masa PART123?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.answer-text')).toContainText('12 kg');
  await page.reload();
  await page.getByRole('button', { name: 'Chat tehnic', exact: true }).click();
  await expect(page.locator('.answer-text')).toContainText('12 kg');
  await page.getByText('Setări de căutare', { exact: false }).click();
  await expect(page.getByLabel('Proiect', { exact: true })).toHaveValue('Tren A');
  await page.getByLabel('Întrebare tehnică').fill('Și lungimea?');
  await page.getByRole('checkbox', { name: 'Cautare Live' }).check();
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.answer-text')).toHaveCount(2);
  await expect(page.getByText('Date tehnice:', { exact: false })).toContainText('neconfirmate');
  await page.getByText('Acces web și actualitate', { exact: true }).click();
  await expect(page.getByText('COPIE ISTORICĂ', { exact: false })).toBeVisible();
  expect(payloads[1].version).toBe(1);
  expect(payloads[1].request_id).not.toBe(payloads[0].request_id);
  await page.getByRole('button', { name: 'Conversație nouă', exact: true }).click();
  await expect(page.locator('.answer-text')).toHaveCount(0);
  await page.getByRole('navigation', { name: 'Conversații salvate' }).getByRole('button', { name: /Masa PART123/ }).click();
  await expect(page.locator('.answer-text')).toHaveCount(2);
});

test('explicit correction is saved against the answer and consulted on repeat', async ({ page }) => {
  const cid = '11111111-1111-4111-8111-111111111111';
  let row = null, corrected = false, requests = 0, target;
  await page.route('**/api/conversations', r => {
    if (r.request().method() === 'GET') return r.fulfill({ json: row ? [row] : [] });
    row = { id: cid, project: 'General', title: 'Masa PART123?', version: 0, messages: [], references: [] };
    return r.fulfill({ json: row });
  });
  await page.route('**/api/conversations/' + cid, r => r.fulfill({ json: row }));
  await page.route('**/api/conversations/' + cid + '/corrections', r => {
    expect(r.request().postDataJSON()).toEqual({ request_id: target, evidence_ids: ['a'.repeat(24)], note: 'Verifică masa: pasajul ales este greșit.' });
    corrected = true;
    return r.fulfill({ json: { ok: true, id: 'review-1' } });
  });
  await page.route('**/api/chat', r => {
    const p = r.request().postDataJSON(); requests++;
    if (requests === 1) target = p.request_id;
    const data = { answer: corrected ? 'Nu am găsit această informație în documentele interne.' : 'Masa: 12 kg [FT:1]', evidence: corrected ? [] : [{ id: 'a'.repeat(24), doc_id: 'FT', page: 1, page_end: 1, quote: 'Masa: 12 kg' }], citations: [], request_id: p.request_id, version: ++row.version, corrections_applied: corrected ? ['review-1'] : [] };
    row.messages.push({ role: 'user', text: p.query }, { role: 'assistant', data });
    return r.fulfill({ json: data });
  });
  await page.goto('/#chat');
  await page.getByLabel('Întrebare tehnică').fill('Masa PART123?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await page.getByRole('button', { name: 'Corectează răspunsul', exact: true }).click();
  await page.getByLabel('Ce trebuie corectat?').fill('Verifică masa: pasajul ales este greșit.');
  await page.locator('.chat-correction').scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('correction-form.png'), fullPage: true });
  await page.getByRole('button', { name: 'Salvează corecția', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Corecție salvată' })).toBeVisible();
  await page.reload();
  await page.getByLabel('Întrebare tehnică').fill('Masa PART123?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.answer-text').last()).not.toContainText('12 kg');
  await expect(page.getByText('A fost consultată o corecție', { exact: false })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('correction-applied.png'), fullPage: true });
});
