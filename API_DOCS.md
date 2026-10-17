# API_DOCS.md — Documentația Completă a API-ului Backend

> **Bază URL (Docker):** `http://localhost:8000` (Nginx reverse-proxy → FastAPI)
>
> **Content-Type:** `application/json` (dacă nu se specifică altfel)
>
> **Valori monetare:** transmise ca **string** (`"555.000000"`, `"102.7000"`) pentru a evita pierderea de precizie la serializarea Decimal → float.

---

## Cuprins

1. [`GET /health`](#1-get-health)
2. [`POST /chat`](#2-post-chat) — RAG cu citări anti-halucinație
3. [`GET /prices`](#3-get-prices) — Istoricul de prețuri din facturi
4. [`POST /offers/calculate`](#4-post-offerscalculate) — Calcul cost total + checklist
5. [`POST /offers/export/docx`](#5-post-offersexportdocx) — Descărcare ofertă Word
6. [`POST /offers/export/xlsx`](#6-post-offersexportxlsx) — Descărcare calcul intern Excel
7. [`POST /offers/export/saga`](#7-post-offersexportsaga) — Export XML pentru Saga
8. [`POST /emails/draft`](#8-post-emailsdraft) — Draft-uri multilingve pentru furnizori
9. [Modele comune (Pydantic)](#9-modele-comune-pydantic)
10. [Coduri de eroare și comportamente speciale](#10-coduri-de-eroare-și-comportamente-speciale)

---

## 1. `GET /health`

Verificare rapidă — backend-ul este viu.

**Response `200`:**
```json
{ "ok": true }
```

---

## 2. `POST /chat` — memorie și verificare extractivă

Chat-ul selectează dovezi din documente și afișează exclusiv textul/rândurile copiate de server. Modelul returnează ID-uri de dovezi, nu valori tehnice sau răspuns liber. Vechiul post-procesor de coduri rămâne disponibil ca utilitar, dar nu este controlul de siguranță al endpoint-ului.

### Request

```json
{
  "query": "Care este masa pentru 3EST000123?",
  "k": 5,
  "conversation_id": "11111111-1111-4111-8111-111111111111",
  "version": 0,
  "request_id": "22222222-2222-4222-8222-222222222222"
}
```

`query`: 1–1000 caractere; `k`: 1–10, implicit 5. Pentru apeluri fără memorie, omite ultimele trei câmpuri. Pentru conversații persistente, toate trei sunt necesare: UUID-ul conversației, versiunea citită și un UUID unic per întrebare. Refolosește `request_id` când reîncerci aceeași cerere după o eroare de rețea. Același ID cu altă întrebare este respins.

### Response

Câmpurile `answer`, `grounded`, `citations`, `codes`, `exact`, `removed_codes`, `removed_citations` sunt păstrate. Listele `removed_*` sunt goale în noul flux: răspunsurile libere sau ID-urile invalide sunt respinse integral.

Câmpuri noi:

| Câmp | Semnificație |
|---|---|
| `verification_status` | `verified_excerpts`, `insufficient_evidence` sau `conflict` |
| `verification_scope` | Limitele verificării: fidelitate față de textul extras, nu certificarea documentului sau a OCR-ului |
| `evidence[]` | `id`, `doc_id`, `page`, `page_end`, `quote`, `fields`, `source_revision`, `supplier`, `doc_type`, `properties`, `codes` |
| `conflicts[]` | Cod/proprietate, valori diferite și ID-urile dovezilor conflictuale |
| `attempts[]` | Numărul încercării, `k` și rezultatul verificării |
| `conversation_id`, `version` | Prezente după salvarea unui tur persistent |

`source_revision` este amprenta SHA-256 a PDF-ului, nu numărul de revizie declarat de producător. Este absentă pentru indexările vechi; reindexează fișierele pentru a o popula. Pentru fragmente pe mai multe pagini, `page` este începutul intervalului și `page_end` finalul, nu localizarea exactă a celulei.

`grounded: true` înseamnă că răspunsul conține dovezi copiate din sursele recuperate. Nu înseamnă că documentul este actual, corect sau că răspunsul este exhaustiv. `grounded` este `false` pentru abținere și conflicte. Tabelul `exact` păstrează separat prețurile din facturi, cu sumele ca stringuri.

Bucla are maximum trei încercări, crește `k` până la 10 și extinde determinist termenii tehnici cunoscuți. Nu folosește valori inventate de LLM pentru o nouă căutare. Fiecare generare este limitată la 240 secunde, iar fluxul RAG la 800 secunde. Nu există auto-antrenare.

### Memoria conversațiilor

- `POST /conversations`, body: `{"project":"Proiect A","title":"Suport boghiu"}` — creează o conversație și cookie-ul `ofertare_workspace` (`HttpOnly`, `SameSite=Strict`, valabil un an).
- `GET /conversations` — ultimele 100 conversații ale spațiului browserului.
- `GET /conversations/{uuid}` — proiect, titlu, versiune, ultimele 100 tururi (întrebare+răspuns) și ultimele 100 referințe salvate.
- `POST /conversations/{uuid}/references`, body: `{"evidence_id":"<ID de 24 caractere hex din răspuns>","note":"Observație de revizuire"}` — salvează o dovadă deja prezentă în conversație și o notă de maximum 1000 caractere. Notele și corecțiile propuse nu sunt folosite ca fapte de către model.

Conversațiile sunt izolate prin cookie-ul browserului și ID-ul conversației. Numele proiectului organizează conversațiile; nu este un mecanism de autentificare sau ACL. Pentru o implementare multiutilizator este necesară integrarea unei autentificări reale. Pierderea cookie-ului pierde accesul din acel browser; datele rămân în Postgres. Browserul păstrează doar cookie-ul, nu conversațiile în localStorage.

La o întrebare fără cod, se caută ultimul cod explicit din ultimele 12 mesaje ale conversației curente. Afirmațiile asistentului și notițele nu intră în baza de dovezi; documentele sunt recuperate din nou. Dacă referința este ambiguă, utilizatorul trebuie să specifice codul.

### Erori

- `401`: lipsește cookie-ul unui apel la memoria persistentă.
- `404`: conversația nu aparține spațiului browserului sau nu există.
- `409`: versiune veche / cereri concurente / reutilizarea ID-ului pentru altă întrebare. Reîncarcă istoricul.
- `422`: parametri sau referință invalidă.
- `502`: serviciu RAG indisponibil.
- `503`: Postgres/memoria persistentă indisponibilă; nu se pretinde salvarea datelor.
- `504`: bugetul global de timp al verificării a expirat.

---

## 3. `GET /prices`

Caută istoricul de prețuri din facturi (tabelul `price_history`) pentru un cod de piesă. Folosit pentru a precomputa datele de ofertare.

### Query Parameters

| Parametru | Tip    | Obligatoriu | Validare                     | Descriere                  |
|-----------|--------|-------------|------------------------------|----------------------------|
| `code`    | string | da          | `min_length=2, max_length=64` | Codul piesei (fuzzy match) |

**Exemplu request:**
```
GET /prices?code=3EST-000-123
```

### Response `200`

| Câmp      | Tip              | Descriere                                         |
|-----------|------------------|---------------------------------------------------|
| `code`    | string           | Codul cerut (exact cum a fost trimis)             |
| `history` | array of object  | Rânduri `price_history`, cele mai recente întâi    |

Fiecare obiect din `history` are aceeași structură ca elementele din `exact` (vezi [POST /chat](#2-post-chat)), cu valorile `Decimal` serializate ca string.

**Exemplu response:**
```json
{
  "code": "3EST-000-123",
  "history": [
    {
      "seller_code": "3EST-000-123",
      "buyer_code": "INT-00042",
      "name": "Suport boghiu",
      "supplier": "FEROPARTS SRL",
      "invoice_number": "FDX-2026/0147",
      "issue_date": "2026-09-15",
      "currency": "EUR",
      "quantity": "4",
      "unit_code": "H87",
      "unit_price": "555.000000",
      "net_unit_price": "549.000000",
      "hs_code": "86079910",
      "has_doc_allowance": true
    }
  ]
}
```

---

## 4. `POST /offers/calculate`

Calcul intern de cost total livrat (landed cost), preț de vânzare și marjă, plus starea checklist-ului de conformitate. **Neblocant** — se returnează chiar dacă checklist-ul eșuează (doar `compliance.ok` va fi `false`).

### Request Body — modelul `Offer`

Vezi [secțiunea 9 (Modele comune)](#9-modele-comune-pydantic) pentru schema completă.

**Exemplu request:**
```json
{
  "offer_number": "OF-2026/045",
  "client_name": "Client Feroviar SA",
  "offer_date": "2026-10-13",
  "markup_percent": "20",
  "currency": "EUR",
  "firm_prices": true,
  "spare_parts_years": 30,
  "spare_parts_reference": "Scrisoare Feroparts 12/2026",
  "include_penalty_clause": true,
  "certificates": [
    { "supplier": "Feroparts SRL", "standard": "ISO/TS 22163", "number": "IRIS-123", "valid_until": "2027-05-01" },
    { "supplier": "BOLT  INC", "standard": "ISO 9001", "number": "Q-9", "valid_until": "2026-10-13" }
  ],
  "lines": [
    {
      "code": "3EST000123", "description": "Suport boghiu", "supplier": "Feroparts SRL",
      "manufacturer": "Knorr-Bremse", "quantity": "4", "unit_price": "555",
      "price_currency": "EUR", "transport_cost": "40", "transport_currency": "EUR"
    },
    {
      "code": "DIN933-M12X40", "description": "Surub M12x40", "supplier": "Bolt Inc",
      "quantity": "10", "unit_price": "100", "price_currency": "usd",
      "transport_cost": "500", "transport_currency": "RON",
      "duty_rate_percent": "2.7", "imported": true, "afer_agreement": "AT-0123/2025"
    }
  ]
}
```

### Response `200`

| Câmp                     | Tip    | Descriere                                               |
|--------------------------|--------|---------------------------------------------------------|
| `fx.source`              | string | Întotdeauna `"BNR"`                                     |
| `fx.date`                | string | Data cursului (ISO 8601): `"2026-10-13"`                |
| `fx.eur_ron`             | string | Cursul EUR/RON: `"5.0000"`                              |
| `lines`                  | array  | Câte un obiect per linie                                |
| `lines[].code`           | string | Codul produsului                                        |
| `lines[].price_eur`      | string | Preț achiziție EUR/buc                                  |
| `lines[].transport_eur`  | string | Transport EUR/buc                                       |
| `lines[].duty_eur`       | string | Taxă vamală EUR/buc                                     |
| `lines[].landed_eur`     | string | Cost total livrat EUR/buc                               |
| `lines[].sale_unit_eur`  | string | Preț vânzare EUR/buc (rotunjit la cent)                 |
| `lines[].sale_total_eur` | string | Total vânzare EUR pe linie                              |
| `lines[].margin_eur`     | string | Marja EUR pe linie                                      |
| `total_landed_eur`       | string | Totalul costurilor livrate                              |
| `total_sale_eur`         | string | Totalul vânzării                                        |
| `total_margin_eur`       | string | Totalul marjei                                          |
| `margin_on_sale_percent` | string | Marja reală raportată la vânzare (≠ adaos)              |
| `compliance.ok`          | bool   | `true` dacă toate cerințele sunt îndeplinite            |
| `compliance.failures`    | array  | Lista eșecurilor (poate fi goală)                       |
| `compliance.failures[].code`    | string | Codul eșecului (ex: `"AFER_MISSING"`)            |
| `compliance.failures[].message` | string | Mesajul explicativ                                |

**Exemplu response:**
```json
{
  "fx": { "source": "BNR", "date": "2026-10-13", "eur_ron": "5.0000" },
  "lines": [
    {
      "code": "3EST000123",
      "price_eur": "555.0000", "transport_eur": "10.0000", "duty_eur": "0.0000",
      "landed_eur": "565.0000", "sale_unit_eur": "678.00",
      "sale_total_eur": "2712.00", "margin_eur": "452.00"
    },
    {
      "code": "DIN933-M12X40",
      "price_eur": "90.0000", "transport_eur": "10.0000", "duty_eur": "2.7000",
      "landed_eur": "102.7000", "sale_unit_eur": "123.24",
      "sale_total_eur": "1232.40", "margin_eur": "205.40"
    }
  ],
  "total_landed_eur": "3287.00",
  "total_sale_eur": "3944.40",
  "total_margin_eur": "657.40",
  "margin_on_sale_percent": "16.67",
  "compliance": {
    "ok": true,
    "failures": []
  }
}
```

**Exemplu cu checklist eșuat (`compliance.ok: false`):**
```json
{
  "compliance": {
    "ok": false,
    "failures": [
      { "code": "PRICES_NOT_FIRM", "message": "prețurile trebuie confirmate ca ferme" }
    ]
  }
}
```

### Coduri de eroare

| HTTP | Condiție                               |
|------|----------------------------------------|
| 422  | Validare Pydantic eșuată (monedă invalidă, cantitate ≤ 0 etc.) sau lipsă curs BNR pentru o monedă |
| 502  | Research-gateway (curs BNR) indisponibil |

---

## 5. `POST /offers/export/docx`

Generează oferta comercială pentru client ca fișier Word (.docx). **Blocant**: dacă checklist-ul de conformitate eșuează, exportul este refuzat cu `409`.

### Request Body — modelul `Offer`

Identic cu [POST /offers/calculate](#4-post-offerscalculate).

### Response `200` (fișier binar)

| Header               | Valoare                                                    |
|----------------------|------------------------------------------------------------|
| `Content-Type`       | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `Content-Disposition`| `attachment; filename="oferta_OF-2026_045.docx"`           |

Body: conținutul binar al fișierului `.docx`.

### Response `409` (checklist eșuat)

```json
{
  "detail": {
    "error": "checklist de conformitate nevalidat — export refuzat",
    "failures": [
      { "code": "PENALTY_CLAUSE", "message": "clauza de penalități trebuie inclusă: 5%/săptămână, maximum 30%" },
      { "code": "CURRENCY_NOT_EUR", "message": "oferta trebuie exprimată în EUR, nu RON" }
    ]
  }
}
```

> **Important:** Calculul BNR și generarea documentului **nu au loc** dacă checklist-ul eșuează — optimizare care evită un apel inutil la research-gateway.

---

## 6. `POST /offers/export/xlsx`

Generează calculul intern confidențial ca fișier Excel (.xlsx) cu 3 foi: „Calcul intern", „Curs BNR", „Checklist". **Blocant** ca și `/docx`.

### Request Body — modelul `Offer`

Identic cu [POST /offers/calculate](#4-post-offerscalculate).

### Response `200` (fișier binar)

| Header               | Valoare                                                    |
|----------------------|------------------------------------------------------------|
| `Content-Type`       | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `Content-Disposition`| `attachment; filename="calcul_intern_OF-2026_045.xlsx"`    |

Body: conținutul binar al fișierului `.xlsx`.

### Response `409` (checklist eșuat)

Identic cu [POST /offers/export/docx](#5-post-offersexportdocx).

---

## 7. `POST /offers/export/saga`

Generează un fișier XML pentru importul în Saga C la „Ieșiri" (Diverse → Import date). Prețurile sunt convertite în RON la cursul BNR al ofertei. Include TVA.

### Request Body — modelul `SagaExportIn` (extends `Offer`)

Toate câmpurile din `Offer`, plus:

| Câmp              | Tip    | Obligatoriu | Validare                      | Descriere                              |
|-------------------|--------|-------------|-------------------------------|----------------------------------------|
| `client_cif`      | string | da          | `min_length=2, max_length=20` | CUI/CIF client (validare cifră control)|
| `document_number` | string | da          | `min_length=1, max_length=30` | Serie + nr. document Saga              |
| `document_date`   | date \| null | nu     | ISO 8601, default: `offer_date` | Data documentului fiscal             |
| `due_days`        | int    | nu          | `ge=0, le=365`, default `30`  | Zile scadență                          |
| `vat_percent`     | string | nu          | `ge=0, le=100`, default `"21"`| Cota TVA (21% = standard RO)           |

**Exemplu request:**
```json
{
  "offer_number": "OF-2026/045",
  "client_name": "Client Feroviar SA",
  "offer_date": "2026-10-13",
  "markup_percent": "20",
  "currency": "EUR",
  "firm_prices": true,
  "spare_parts_years": 30,
  "spare_parts_reference": "Scrisoare Feroparts 12/2026",
  "include_penalty_clause": true,
  "certificates": [
    { "supplier": "Feroparts SRL", "standard": "ISO/TS 22163", "number": "IRIS-123", "valid_until": "2027-05-01" },
    { "supplier": "BOLT  INC", "standard": "ISO 9001", "number": "Q-9", "valid_until": "2026-10-13" }
  ],
  "lines": [
    {
      "code": "3EST000123", "description": "Suport boghiu", "supplier": "Feroparts SRL",
      "manufacturer": "Knorr-Bremse", "quantity": "4", "unit_price": "555",
      "price_currency": "EUR", "transport_cost": "40", "transport_currency": "EUR"
    },
    {
      "code": "DIN933-M12X40", "description": "Surub M12x40", "supplier": "Bolt Inc",
      "quantity": "10", "unit_price": "100", "price_currency": "usd",
      "transport_cost": "500", "transport_currency": "RON",
      "duty_rate_percent": "2.7", "imported": true, "afer_agreement": "AT-0123/2025"
    }
  ],
  "client_cif": "RO12345674",
  "document_number": "OFT 0147",
  "vat_percent": "21"
}
```

### Response `200` (fișier XML)

| Header               | Valoare                                                        |
|----------------------|----------------------------------------------------------------|
| `Content-Type`       | `application/xml`                                              |
| `Content-Disposition`| `attachment; filename="F_RO12345674_OFT-0147_13102026.xml"`    |

**Structura XML (exemplu):**
```xml
<?xml version='1.0' encoding='utf-8'?>
<Facturi>
  <Factura>
    <Antet>
      <FurnizorNume>Ofertant SRL</FurnizorNume>
      <FurnizorCIF>RO12345674</FurnizorCIF>
      <FurnizorNrRegCom>J40/1/2020</FurnizorNrRegCom>
      <FurnizorTara>RO</FurnizorTara>
      <FurnizorLocalitate>Bucuresti</FurnizorLocalitate>
      <FurnizorJudet></FurnizorJudet>
      <FurnizorAdresa></FurnizorAdresa>
      <FurnizorBanca></FurnizorBanca>
      <FurnizorIBAN>RO49AAAA1B31007593840000</FurnizorIBAN>
      <ClientNume>Client Feroviar SA</ClientNume>
      <ClientCIF>RO12345674</ClientCIF>
      <FacturaNumar>OFT 0147</FacturaNumar>
      <FacturaData>13.10.2026</FacturaData>
      <FacturaScadenta>12.11.2026</FacturaScadenta>
      <FacturaTaxareInversa>Nu</FacturaTaxareInversa>
      <FacturaTVAIncasare>Nu</FacturaTVAIncasare>
      <FacturaInformatiiSuplimentare>Conform oferta OF-2026/045. Curs BNR 13.10.2026: 1 EUR = 5.0000 RON</FacturaInformatiiSuplimentare>
      <FacturaMoneda>RON</FacturaMoneda>
    </Antet>
    <Detalii>
      <Continut>
        <Linie>
          <LinieNrCrt>1</LinieNrCrt>
          <Descriere>Suport boghiu</Descriere>
          <CodArticolFurnizor>3EST000123</CodArticolFurnizor>
          <UM>BUC</UM>
          <Cantitate>4</Cantitate>
          <Pret>3390.0000</Pret>
          <Valoare>13560.00</Valoare>
          <ProcTVA>21</ProcTVA>
          <TVA>2847.60</TVA>
        </Linie>
        <Linie>
          <LinieNrCrt>2</LinieNrCrt>
          <Descriere>Surub M12x40</Descriere>
          <CodArticolFurnizor>DIN933-M12X40</CodArticolFurnizor>
          <UM>BUC</UM>
          <Cantitate>10</Cantitate>
          <Pret>616.2000</Pret>
          <Valoare>6162.00</Valoare>
          <ProcTVA>21</ProcTVA>
          <TVA>1294.02</TVA>
        </Linie>
      </Continut>
    </Detalii>
  </Factura>
</Facturi>
```

### Coduri de eroare

| HTTP | Condiție                                                    |
|------|-------------------------------------------------------------|
| 409  | Checklist de conformitate eșuat (ca la docx/xlsx)           |
| 422  | CUI client invalid (cifra de control greșită sau format incorect) |
| 502  | Research-gateway (curs BNR) indisponibil                    |
| 503  | Variabile de mediu `COMPANY_CIF` / `COMPANY_NAME` nesetate |

---

## 8. `POST /emails/draft`

Generează un draft de e-mail către furnizor (cerere de ofertă sau clarificări tehnice), multilingv. Limbile `ro` și `en` sunt **deterministe** (șablon fix, fără LLM). Celelalte limbi sunt traduse de Colibri din versiunea engleză, apoi verificate de Egress Guard.

### Request Body — modelul `EmailDraftIn`

| Câmp             | Tip                     | Obligatoriu | Validare                          | Descriere                                                   |
|------------------|-------------------------|-------------|-----------------------------------|-------------------------------------------------------------|
| `kind`           | `"rfq"` \| `"clarification"` | da    |                                   | Tip e-mail                                                  |
| `language`       | string                  | da          | Una din: `ro`, `en`, `de`, `fr`, `it`, `es`, `pl`, `cs`, `hu`, `tr`, `bg`, `zh-CN`, `zh-TW`, `ja`, `ko`, `pt`, `nl`, `el`, `sk`, `sl`, `hr`, `sr`, `uk`, `sv`, `da`, `no`, `fi` | Limba draftului |
| `contact_name`   | string                  | nu          | `max_length=100`, default `""`    | Numele persoanei de contact                                 |
| `items`          | array                   | da          | `min_length=1, max_length=50`     | Lista de articole                                           |
| `items[].code`   | string                  | da          | `min_length=1, max_length=64`     | Codul piesei                                                |
| `items[].description` | string             | nu          | `max_length=300`, default `""`    | Descrierea articolului                                      |
| `items[].quantity`     | string \| null      | nu          | `gt=0`                           | Cantitate (Decimal ca string)                               |
| `items[].unit`         | string              | nu          | `max_length=20`, default `"pcs"` | Unitate de măsură                                           |
| `questions`      | array of string         | nu          | `max_length=10`, default `[]`     | Întrebări (obligatorii dacă `kind="clarification"`)         |
| `reply_by`       | date \| null            | nu          | ISO 8601                          | Termen limită de răspuns                                    |
| `sender_name`    | string                  | da          | `min_length=1, max_length=100`    | Numele expeditorului                                        |
| `sender_company` | string                  | da          | `min_length=1, max_length=200`    | Compania expeditorului                                      |

> **⚠️ Nu există câmp `client_name` sau `project`.** Acesta este intenționat: e-mailurile către furnizori **nu au voie** să conțină numele clientului sau al proiectului. Egress Guard blochează orice astfel de divulgare.

**Exemplu request (RFQ în română):**
```json
{
  "kind": "rfq",
  "language": "ro",
  "contact_name": "Hans Weber",
  "sender_name": "Ion Popescu",
  "sender_company": "Ofertant SRL",
  "items": [
    { "code": "3EST000123", "description": "Suport boghiu", "quantity": "4", "unit": "buc" },
    { "code": "DIN933-M12X40", "description": "Surub", "quantity": "250" }
  ],
  "reply_by": "2026-10-20"
}
```

**Exemplu request (clarificare în engleză):**
```json
{
  "kind": "clarification",
  "language": "en",
  "contact_name": "Hans Weber",
  "sender_name": "Ion Popescu",
  "sender_company": "Ofertant SRL",
  "items": [
    { "code": "3EST000123", "description": "Suport boghiu", "quantity": "4", "unit": "buc" }
  ],
  "questions": [
    "Is the bracket hot-dip galvanized?",
    "Weld class per EN 15085?"
  ]
}
```

### Response `200`

| Câmp         | Tip    | Descriere                                                |
|--------------|--------|----------------------------------------------------------|
| `language`   | string | Limba draftului (echo)                                   |
| `translated` | bool   | `false` pt `ro`/`en` (deterministic); `true` pt restul   |
| `subject`    | string | Subiectul e-mailului                                     |
| `body`       | string | Corpul e-mailului (text, nu HTML)                        |

**Exemplu response (RFQ, română):**
```json
{
  "language": "ro",
  "translated": false,
  "subject": "Cerere de ofertă – 3EST000123, DIN933-M12X40",
  "body": "Stimate/Stimată Hans Weber,\n\nVă rugăm să ne transmiteți oferta dumneavoastră pentru următoarele articole:\n\n1. 3EST000123 – Suport boghiu – Cantitate: 4 buc\n2. DIN933-M12X40 – Surub – Cantitate: 250 pcs\n\nVă rugăm să includeți: prețul unitar și moneda, termenul de livrare, condițiile de livrare (Incoterms), cantitatea minimă de comandă, țara de origine și codul vamal (HS), precum și valabilitatea ofertei.\n\nVă rugăm să ne răspundeți până la 20.10.2026.\n\nCu stimă,\nIon Popescu\nOfertant SRL"
}
```

### Coduri de eroare

| HTTP | Condiție                                                                |
|------|-------------------------------------------------------------------------|
| 422  | Validare eșuată (ex: `kind="clarification"` fără `questions`)          |
| 422  | Traducerea a alterat codurile — draft respins (`missing_codes`, `invented_codes`) |
| 422  | Text blocat de Egress Guard (date interne / nume client): `{"error": "text blocat de Egress Guard (date interne / nume client)", "rules": ["term#0"]}` |
| 502  | Colibri indisponibil (doar pt limbi ≠ ro/en)                           |
| 503  | Egress Guard (research-gateway) indisponibil — fail-closed              |

---

## 9. Modele comune (Pydantic)

### `OfferLine`

| Câmp                | Tip         | Default       | Validare               | Descriere                                     |
|---------------------|-------------|---------------|------------------------|-----------------------------------------------|
| `code`              | string      | —             | `min=1, max=64`        | Cod piesă                                     |
| `description`       | string      | —             | `min=1, max=500`       | Descrierea articolului                        |
| `supplier`          | string      | —             | `min=1, max=200`       | Furnizor                                      |
| `manufacturer`      | string      | `""`          | `max=200`              | Producător (opțional)                         |
| `quantity`          | string      | —             | `gt=0`                 | Cantitate (Decimal)                           |
| `unit`              | string      | `"BUC"`       | `min=1, max=10`        | Unitate de măsură (BUC, KG, M etc.)          |
| `unit_price`        | string      | —             | `ge=0`                 | Preț de achiziție / unitate (Decimal)         |
| `price_currency`    | string      | —             | regex `^[A-Za-z]{3}$`  | Moneda prețului (EUR, USD, RON etc.)          |
| `transport_cost`    | string      | `"0"`         | `ge=0`                 | Cost transport TOTAL pe linie (Decimal)       |
| `transport_currency`| string      | `"EUR"`       | regex `^[A-Za-z]{3}$`  | Moneda transportului                          |
| `duty_rate_percent` | string      | `"0"`         | `ge=0, le=100`         | Taxă vamală % (0 = origine UE)               |
| `imported`          | bool        | `false`       |                        | Produs din afara României → necesită AFER     |
| `afer_agreement`    | string\|null| `null`        | `max=100`              | Nr. agrement tehnic AFER                      |

### `SupplierCertificate`

| Câmp          | Tip    | Validare                            | Descriere                      |
|---------------|--------|-------------------------------------|--------------------------------|
| `supplier`    | string | `min=1, max=200`                    | Furnizor                       |
| `standard`    | string | `"ISO/TS 22163"` sau `"ISO 9001"`  | Standardul certificării        |
| `number`      | string | `min=1, max=100`                    | Nr. certificat                 |
| `valid_until` | date   | ISO 8601                            | Validitate                     |

### `Offer`

| Câmp                       | Tip                      | Default    | Validare        | Descriere                                |
|----------------------------|--------------------------|------------|-----------------|------------------------------------------|
| `offer_number`             | string                   | —          | `min=1, max=50` | Nr. ofertei                              |
| `client_name`              | string                   | —          | `min=1, max=200`| Numele clientului                        |
| `offer_date`               | date                     | —          | ISO 8601        | Data ofertei                             |
| `validity_days`            | int                      | `30`       | `ge=1, le=365`  | Valabilitate (zile)                      |
| `fx_date`                  | date \| null             | `null`     | ISO 8601        | Data cursului BNR (default: offer_date)  |
| `markup_percent`           | string                   | —          | `ge=0, le=1000` | Adaos peste costul total livrat (Decimal)|
| `delivery_terms`           | string                   | `"DAP"`    | `max=100`       | Incoterms                                |
| `currency`                 | string                   | `"EUR"`    |                 | Moneda ofertei (trebuie EUR pt checklist)|
| `firm_prices`              | bool                     | `false`    |                 | Prețuri ferme                            |
| `spare_parts_years`        | int                      | `0`        | `ge=0`          | Disponibilitate piese schimb (ani)       |
| `spare_parts_reference`    | string                   | `""`       | `max=200`       | Referința confirmării piese schimb       |
| `include_penalty_clause`   | bool                     | `false`    |                 | Include clauza de penalități             |
| `penalty_percent_per_week` | string                   | `"5"`      |                 | Penalitate %/săptămână (Decimal)         |
| `penalty_cap_percent`      | string                   | `"30"`     |                 | Plafon penalitate % (Decimal)            |
| `certificates`             | array of SupplierCertificate | `[]`  |                 | Certificatele furnizorilor               |
| `lines`                    | array of OfferLine       | —          | `min=1, max=500`| Liniile ofertei                          |

### Checklist de conformitate (coduri de eșec)

| Cod                | Condiție blocantă                                                              |
|--------------------|--------------------------------------------------------------------------------|
| `AFER_MISSING`     | Produs din import fără agrement tehnic AFER                                   |
| `CERT_MISSING`     | Furnizor fără certificat ISO/TS 22163 sau ISO 9001                            |
| `CERT_EXPIRED`     | Certificatul furnizorului a expirat înainte de data ofertei                   |
| `SPARE_PARTS_30Y`  | Lipsește confirmarea pieselor de schimb pt minimum 30 de ani (cu referință)    |
| `PENALTY_CLAUSE`   | Clauza de penalități trebuie inclusă: 5%/săptămână, maximum 30%              |
| `CURRENCY_NOT_EUR` | Oferta trebuie exprimată în EUR                                               |
| `PRICES_NOT_FIRM`  | Prețurile trebuie confirmate ca ferme                                         |

---

## 10. Coduri de eroare și comportamente speciale

### Erori globale

| HTTP | Descriere                                                                      |
|------|--------------------------------------------------------------------------------|
| 422  | Validare Pydantic (câmpuri lipsă, tipuri greșite, constrângeri depășite)       |
| 409  | Checklist de conformitate eșuat — export refuzat (doar `/export/*`)            |
| 502  | Serviciu upstream indisponibil (Colibri LLM sau research-gateway/curs BNR)    |
| 503  | Egress Guard indisponibil (fail-closed: niciun draft nu este returnat)         |
| 503  | Variabile de mediu `COMPANY_*` nesetate (doar `/export/saga`)                 |

### Comportamente speciale

- **Verificare extractivă (`/chat`):** LLM-ul selectează numai ID-uri de dovezi. Serverul copiază pasajele/celulele originale și respinge selecțiile invalide. După maximum trei încercări răspunde cu dovezi, abținere sau conflict. Fidelitatea față de textul extras nu certifică OCR-ul sau corectitudinea documentului; vezi secțiunea 2.
- **Egress Guard (`/emails/draft`):** Textul final (subiect + corp) trece prin `/guard/check` pe research-gateway. Dacă apare un termen din denylist (ex: nume client, proiect), draftul nu este returnat. Fail-closed: dacă guard-ul este indisponibil → `503`.
- **Monede:** Backend-ul nu are acces direct la internet. Cursul BNR este obținut prin `research-gateway /fx/bnr`. Toate sumele sunt convertite intern la EUR via FxSnapshot.
- **Decimal ca string:** Toate valorile monetare sunt serializate ca string JSON pentru a preveni pierderea de precizie (ex: `"549.000000"` în loc de `549.0`).


## Live Web RAG opțional

Răspunsul include și `evidence_status` (`confirmed`, `unconfirmed`, `contradictory`), `technical_claims`, `missing_properties`, `automatic_offer_eligible=false` și `requires_human_review=true`. `web_research.access_status` și `web_research.pages` descriu accesul și copiile istorice (`stale`, `retrieved_at`). Aceste câmpuri sunt distincte de `verification_status`, care verifică fidelitatea citării. Criterii: [SOURCE_QUALITY.md](SOURCE_QUALITY.md).

`POST /chat` acceptă `live_web: bool = false`. Checkbox-ul „🌍 Căutare Live Web (Perplexity)” activează căutarea externă pentru întrebarea curentă, filtrată prin Egress Guard. Istoricul nu este trimis către căutarea web. Citările web folosesc `[https://...]`; răspunsul include `live_web` și `web_research`. Serviciul Camoufox înlocuiește Playwright MCP. Arhitectură, contracte și limite: [Live Web RAG](LIVE_WEB.md).

## Conectare și trimitere e-mail

Endpoint-urile OAuth și `POST /emails/send` sunt documentate în [EMAIL_CONNECT.md](EMAIL_CONNECT.md). Trimiterea necesită confirmare explicită și verificare Egress Guard; `accepted` indică acceptarea de către furnizor, nu livrarea.
Biblioteca de documente: endpoint-urile /sources și configurarea sincronizării sunt descrise în [DOCUMENT_SOURCES.md](DOCUMENT_SOURCES.md).
