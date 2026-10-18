// Local, unverified preview. Sending always uses the guarded backend draft.
export function emailPreview(form, questions) {
  const ro = form.language === 'ro';
  const items = form.items.filter(i => i.code || i.description);
  const codes = items.slice(0, 3).map(i => i.code || '…').join(', ') || '…';
  const rfq = form.kind === 'rfq';
  const subject = `${ro ? (rfq ? 'Cerere de ofertă' : 'Clarificări tehnice') : (rfq ? 'Request for quotation' : 'Technical clarification')} – ${codes}${items.length > 3 ? ' …' : ''}`;
  const greeting = form.contact_name ? (ro ? `Stimate/Stimată ${form.contact_name},` : `Dear ${form.contact_name},`) : (ro ? 'Stimată doamnă/Stimate domn,' : 'Dear Sir or Madam,');
  const intro = rfq ? (ro ? 'Vă rugăm să ne transmiteți oferta dumneavoastră pentru următoarele articole:' : 'We kindly request your quotation for the following items:') : (ro ? 'Am dori să clarificăm următoarele aspecte tehnice privind:' : 'We would like to clarify the following technical points regarding:');
  const lines = items.map((i, n) => `${n + 1}. ${[i.code || '…', i.description, i.quantity && `${ro ? 'Cantitate' : 'Qty'}: ${i.quantity} ${i.unit}`].filter(Boolean).join(' – ')}`).join('\n') || (ro ? 'Adaugă un articol în formular.' : 'Add an item to the form.');
  const ask = rfq ? (ro ? 'Vă rugăm să includeți: prețul unitar și moneda, termenul de livrare, condițiile de livrare (Incoterms), cantitatea minimă de comandă, țara de origine și codul vamal (HS), precum și valabilitatea ofertei.' : 'Please include: unit price and currency, delivery lead time, delivery terms (Incoterms), minimum order quantity, country of origin and customs tariff (HS) code, and the validity of your offer.') : `${ro ? 'Întrebări' : 'Questions'}:\n${questions.split('\n').filter(q => q.trim()).map((q, i) => `${i + 1}. ${q.trim()}`).join('\n')}`;
  const date = form.reply_by ? `\n\n${ro ? 'Vă rugăm să ne răspundeți până la' : 'Please reply by'} ${form.reply_by.split('-').reverse().join('.')}.` : '';
  return { subject, body: `${greeting}\n\n${intro}\n\n${lines}\n\n${ask}${date}\n\n${ro ? 'Cu stimă,' : 'Kind regards,'}` };
}
