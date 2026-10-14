-- Istoric de prețuri de achiziție din e-Factura (UBL 2.1).
-- Rulat automat de Postgres la prima pornire (volum gol) via /docker-entrypoint-initdb.d.

CREATE TABLE supplier (
    id      serial PRIMARY KEY,
    tax_id  text NOT NULL UNIQUE,          -- CUI fără prefixul RO
    name    text NOT NULL
);

CREATE TABLE invoice (
    id              serial PRIMARY KEY,
    supplier_id     int NOT NULL REFERENCES supplier,
    doc_type        text NOT NULL CHECK (doc_type IN ('invoice', 'credit_note')),
    number          text NOT NULL,
    issue_date      date NOT NULL,
    currency        char(3) NOT NULL,
    payable_amount  numeric(18, 2),
    doc_allowance   numeric(18, 2) NOT NULL DEFAULT 0,
    source_sha256   char(64) NOT NULL UNIQUE,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (supplier_id, doc_type, number)
);

CREATE TABLE invoice_line (
    id              serial PRIMARY KEY,
    invoice_id      int NOT NULL REFERENCES invoice ON DELETE CASCADE,
    line_no         text NOT NULL,
    name            text NOT NULL,
    description     text,
    seller_code     text,
    buyer_code      text,
    std_code        text,
    hs_code         text,
    quantity        numeric(18, 4) NOT NULL,
    unit_code       text,
    unit_price      numeric(18, 6),
    net_unit_price  numeric(18, 6),
    line_amount     numeric(18, 2) NOT NULL,
    vat_percent     numeric(5, 2),
    -- Aceeași normalizare ca extractorul web: fără spații . / - , majuscule.
    seller_code_norm text GENERATED ALWAYS AS (upper(regexp_replace(seller_code, '[\s./-]', '', 'g'))) STORED,
    buyer_code_norm  text GENERATED ALWAYS AS (upper(regexp_replace(buyer_code,  '[\s./-]', '', 'g'))) STORED,
    UNIQUE (invoice_id, line_no)
);

-- Calea „exact-code” din căutarea hibridă: întâi aici, apoi vectorial.
CREATE INDEX invoice_line_seller_code_norm ON invoice_line (seller_code_norm);
CREATE INDEX invoice_line_buyer_code_norm  ON invoice_line (buyer_code_norm);

-- Doar facturi (notele de credit corectează, nu sunt prețuri de achiziție).
CREATE VIEW price_history AS
SELECT l.seller_code, l.seller_code_norm, l.buyer_code, l.buyer_code_norm, l.name,
       s.name AS supplier, s.tax_id AS supplier_tax_id,
       i.number AS invoice_number, i.issue_date, i.currency,
       l.quantity, l.unit_code, l.unit_price, l.net_unit_price, l.hs_code,
       i.doc_allowance <> 0 AS has_doc_allowance
FROM invoice_line l
JOIN invoice i ON i.id = l.invoice_id
JOIN supplier s ON s.id = i.supplier_id
WHERE i.doc_type = 'invoice';
