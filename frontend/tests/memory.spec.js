import { test, expect } from '@playwright/test';

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
  await page.getByText('Conversații și proiect', { exact: false }).click();
  await page.getByLabel('Proiect', { exact: true }).fill('Tren A');
  await page.getByLabel('Întrebare tehnică').fill('Masa PART123?');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.answer-text')).toContainText('12 kg');
  await page.reload();
  await page.getByRole('button', { name: 'Chat tehnic', exact: true }).click();
  await expect(page.locator('.answer-text')).toContainText('12 kg');
  await page.getByText('Conversații și proiect', { exact: false }).click();
  await expect(page.getByLabel('Proiect', { exact: true })).toHaveValue('Tren A');
  await page.getByLabel('Întrebare tehnică').fill('Și lungimea?');
  await page.getByRole('checkbox', { name: '🌍 Căutare Live Web (Perplexity)' }).check();
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.answer-text')).toHaveCount(2);
  await expect(page.getByText('Date tehnice:', { exact: false })).toContainText('neconfirmate');
  await page.getByText('Acces web și actualitate', { exact: true }).click();
  await expect(page.getByText('COPIE ISTORICĂ', { exact: false })).toBeVisible();
  expect(payloads[1].version).toBe(1);
  expect(payloads[1].request_id).not.toBe(payloads[0].request_id);
  await page.getByRole('button', { name: 'Conversație nouă', exact: true }).click();
  await expect(page.locator('.answer-text')).toHaveCount(0);
  await page.getByLabel('Conversații salvate').selectOption(row.id);
  await expect(page.locator('.answer-text')).toHaveCount(2);
});
