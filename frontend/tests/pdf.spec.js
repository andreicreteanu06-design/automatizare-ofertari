import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => { await page.route('**/api/sources', r => r.fulfill({ json: { sources: [], worker_active: true } })); });
import { readFile } from 'node:fs/promises';
test('PDFCraft starts locally inside the isolated editor', async ({ page }) => {
  test.setTimeout(90000);
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  page.on('console', m=> { if(m.type()==='error') console.log(m.text()); });
  await page.route('**/api/conversations', r=>r.fulfill({json:[]}));
  await page.route('**/api/emails/accounts', r=>r.fulfill({json:[]}));
  await page.goto('/#pdf');
  await page.getByRole('button',{name:'Deschide editorul PDF'}).click();
  const frame=page.frameLocator('iframe[title="Editor PDFCraft"]');
  await expect(frame.locator('canvas')).toBeVisible();
  await expect.poll(()=>frame.locator('canvas').getAttribute('width'),{timeout:60000}).not.toBeNull();
  await page.screenshot({path:'test-results/pdf-editor.png',fullPage:true});
  expect(errors).toEqual([]);
  const chooserPromise = page.waitForEvent('filechooser');
  await frame.locator('canvas').click({position:{x:95,y:20}});
  const chooser = await chooserPromise;
  const parts=['%PDF-1.4\n']; const offsets=[0];
  const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> >>'];
  for(let i=0;i<objects.length;i++){ offsets.push(Buffer.byteLength(parts.join(''))); parts.push(`${i+1} 0 obj\n${objects[i]}\nendobj\n`); }
  const xref=Buffer.byteLength(parts.join('')); parts.push('xref\n0 4\n0000000000 65535 f \n');
  offsets.slice(1).forEach(n=>parts.push(String(n).padStart(10,'0')+' 00000 n \n'));
  parts.push(`trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
  await chooser.setFiles({name:'editor-test.pdf',mimeType:'application/pdf',buffer:Buffer.from(parts.join(''))});
  await expect.poll(()=>errors.length).toBe(0);
  const saved = page.waitForEvent('download');
  await frame.locator('canvas').press('Control+s');
  const download = await saved;
  expect(download.suggestedFilename()).toBe('editor-test.pdf');
  expect((await readFile(await download.path())).subarray(0,5).toString()).toBe('%PDF-');
  await page.screenshot({path:'test-results/pdf-document.png',fullPage:true});
});
