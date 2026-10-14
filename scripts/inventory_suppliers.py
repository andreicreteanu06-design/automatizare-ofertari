"""Offline candidate inventory. Does not grant authority or make network calls."""
import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def inventory(root):
    root = Path(root).resolve(strict=True)
    candidates, review = [], []
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        if path.suffix.lower() not in ('.csv', '.json', '.xml', '.pdf', '.xlsx'):
            continue
        relative = str(path.relative_to(root))
        if path.stat().st_size > 10_000_000 or path.suffix.lower() in ('.pdf', '.xlsx'):
            review.append({'file': relative, 'reason': 'requires_existing_document_ingestion_or_manual_review'})
            continue
        try:
            if path.suffix.lower() == '.csv':
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    rows = list(csv.DictReader(stream))
            elif path.suffix.lower() == '.json':
                rows = json.loads(path.read_text(encoding='utf-8-sig'))
                rows = rows if isinstance(rows, list) else [rows]
            else:
                raw = path.read_bytes()
                if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                    raise ValueError('DTD not accepted')
                tree = ET.fromstring(raw)
                rows = []
                for supplier in tree.iter():
                    if supplier.tag.split('}')[-1] != 'AccountingSupplierParty':
                        continue
                    values = {e.tag.split('}')[-1]: e.text for e in supplier.iter() if e.text and e.text.strip()}
                    rows.append({'supplier': values.get('RegistrationName') or values.get('Name'), 'website': values.get('WebsiteURI')})
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get('supplier') or row.get('furnizor')
                url = row.get('website') or row.get('url')
                if not name:
                    continue
                host = None
                if isinstance(url, str):
                    parsed = urlsplit(url)
                    if parsed.scheme in ('http', 'https') and not parsed.username and not parsed.password:
                        host = parsed.hostname
                candidates.append({'supplier': str(name)[:200], 'domain_candidate': host,
                                   'source_file': relative, 'review_status': 'unreviewed'})
        except (ValueError, OSError, ET.ParseError, UnicodeError, csv.Error):
            review.append({'file': relative, 'reason': 'unsupported_or_invalid_format'})
    return {'candidates': candidates, 'files_for_review': review,
            'notice': 'Local only. Previous purchases do not establish manufacturer authority. No policy has been changed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('--output', default='data/supplier_candidates.json')
    args = parser.parse_args()
    result = inventory(args.folder)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Inventory saved locally: {output}')
