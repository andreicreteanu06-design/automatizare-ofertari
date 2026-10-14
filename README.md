# 🏭 B2B Quoting & ERP Automation System (Local AI & Controlled Egress)

Sistem de automatizare a departamentului de ofertare B2B, proiectat pentru industria feroviară. Proiectul integrează inteligență artificială generativă locală (LLM), baze de date vectoriale (RAG) și exporturi pentru ERP-ul Saga Software, într-o **arhitectură cu procesare internă izolată și acces extern separat** pentru protejarea datelor comerciale sensibile.

Backend-ul, bazele de date și modelele AI nu au acces direct la internet. Configurația completă include însă servicii conectate pentru cercetare web, cursuri valutare și e-mail: este o arhitectură cu acces extern controlat, nu un sistem complet air-gapped. Separarea rețelelor și filtrele aplicative reduc riscul de divulgare; nu constituie o garanție de „scurgere zero”.

## 💼 Contextul de Business

Ofertarea pentru clienți feroviari Tier-1 presupune corelarea fișelor tehnice cu istoricul facturilor, calculul prețului folosind cursuri valutare și respectarea unor cerințe blocante de conformitate: agremente AFER, certificate ISO/TS 22163 sau ISO 9001, disponibilitatea pieselor de schimb și clauze de penalități.

Sistemul automatizează etapele repetitive, de la preluarea și clasificarea atașamentelor până la calculul ofertei, generarea documentelor și pregătirea importului contabil. Obiectivul este reducerea timpului de ofertare și a erorilor de transcriere; câștigul efectiv de timp depinde de documente, configurația hardware și validarea în mediul clientului.

## 🛡️ Arhitectura de Securitate (Zero Trust)

Sistemul este containerizat cu Docker și folosește separarea serviciilor și verificări explicite ale datelor, în trei rețele distincte:

* **`internal` (Fără acces web direct):** Backend FastAPI, Postgres, Qdrant și modelele AI locale configurate prin Colibri (Qwen3.6-35B-A3B și Laya). Rețeaua este declarată cu `internal: true`.
* **`egress` (Servicii cu acces extern):** SearXNG, Camoufox (`stealth-browser`), serviciul IMAP `mail-fetch` și descărcarea inițială a modelelor prin profilul `setup`. `research-gateway`, conectat la `internal` și `egress`, intermediază cercetarea web și obținerea cursului BNR. Interogările de cercetare și URL-urile procesate de gateway sunt verificate de modulul determinist **Egress Guard**; acesta este un filtru aplicativ, nu un firewall pentru întregul trafic al rețelei.
* **`edge`:** Expune interfața React prin Nginx, pe `127.0.0.1:8080`. Nginx este conectat și la `internal` pentru proxy-ul `/api` și aplică headerele de securitate, inclusiv Content Security Policy. Frontend-ul este compilat într-un build Docker multi-stage; Node.js nu este necesar pe host.

Preluarea e-mailurilor și clasificarea lor rulează în servicii separate: `mail-fetch` are acces la `egress`, iar `mail-classify` doar la `internal`. Transferul atașamentelor se face printr-un director de carantină pe disc, fără o conexiune de rețea între cele două servicii. Aceasta este o separare logică, nu o barieră fizică.

Egress Guard folosește o listă locală de termeni și expresii interzise. Configurația lipsă, goală sau cu placeholder-e necompletate împiedică inițializarea sa; drafturile de e-mail sunt refuzate dacă verificarea nu este disponibilă. Protecția depinde de configurarea corectă a regulilor și de controalele de acces ale infrastructurii.

## ✨ Funcționalități Tehnice Principale

* **Ingestie Automată & Triaj E-mail:** Facturile e-Factura XML/ZIP sunt recunoscute determinist și procesate în Postgres. Laya, un clasificator bazat pe ModernBERT, clasifică celelalte atașamente; cazurile incerte sunt păstrate pentru revizuire. Fișele tehnice PDF sunt parsate cu Docling și indexate în Qdrant pentru căutare semantică.
* **Chat RAG Anti-Halucinație:** Răspunsurile includ citări în formatul `[doc_id:pagina]`. O buclă limitată la trei încercări recuperează dovezi, iar modelul selectează doar ID-uri; serverul copiază pasajele și valorile din surse. ID-urile inventate și răspunsurile libere sunt respinse; valorile contradictorii detectate sunt semnalate. Această verificare nu certifică OCR-ul, actualitatea sau corectitudinea documentului. Prețurile identificate în facturi sunt afișate separat de răspunsul generat.
* **ERP Integration (Saga Software):** Motorul de calcul al costului total livrat (*Landed Cost*) include achiziția, transportul, taxele vamale, conversia valutară și adaosul comercial. Generează oferta Word, calculul intern Excel și XML-ul destinat importului în Saga la „Ieșiri”. Exporturile sunt blocate dacă checklist-ul de conformitate eșuează; compatibilitatea cu instalarea Saga a clientului trebuie verificată conform ghidului de lansare.
* **Șabloane E-mail Multilingve:** Cererile de ofertă (RFQ) și clarificările tehnice sunt disponibile în 10 limbi. Româna și engleza folosesc șabloane deterministe; celelalte limbi sunt traduse prin LLM-ul local. Codurile articolelor sunt verificate, iar Egress Guard blochează mesajele care conțin termeni interziși, inclusiv numele clientului final dacă este configurat în denylist. Aplicația generează drafturi, fără trimitere automată.

**Memorie persistentă:** conversațiile și referințele de revizuire sunt salvate în Postgres și pot fi reluate după reîncărcarea paginii. Proiectele organizează conversațiile în spațiul browserului, identificat printr-un cookie HttpOnly. Nu există încă autentificare pe conturi; notele utilizatorului nu devin automat fapte pentru răspunsuri. Detalii și limite: [MEMORIE.md](MEMORIE.md).

## 🚀 Instalare și Rulare la Client

Instalarea este destinată unei infrastructuri controlate de client, cu Docker și modele stocate local, preferabil pe Linux/WSL2. Repository-ul nu include chei API, parole sau documente comerciale reale; fixture-urile de facturi sunt sintetice, iar fixture-ul BNR conține date publice.

1. **Configurarea mediului:**

   Creează fișierele locale din șabloane, din rădăcina proiectului:

   ```bash
   cp .env.example .env
   cp config/denylist.example.yaml config/denylist.yaml
   ```

   Completează **doar local** în `.env`:

   * `POSTGRES_USER`, `POSTGRES_PASSWORD`, `QDRANT_API_KEY` și `SEARXNG_SECRET`: credențiale și secrete proprii instalării.
   * `COLIBRI_MODEL_DIR` și `LAYA_MODEL_DIR`: căile modelelor locale pregătite conform [LANSARE.md](LANSARE.md).
   * `COMPANY_*`: datele companiei pentru exportul Saga.
   * `IMAP_*`: configurația căsuței poștale și parola de aplicație, dacă activezi profilul `mail`.
   * `GEMINI_API_KEY`: câmp opțional rezervat integrării Gemini; configurația actuală nu îl cere pentru fluxurile locale.

   Completează `config/denylist.yaml` cu termenii și expresiile care nu trebuie să părăsească rețeaua. Înlocuiește placeholder-ele din șablon cu valorile reale, păstrate exclusiv la client.

   **Excluderi Git:** `.env`, variantele locale `.env.*` (cu excepția șabloanelor `.env.example`), `config/denylist.yaml`, directorul `data/` și exporturile comerciale sunt excluse prin `.gitignore`. Nu le adăuga forțat cu `git add -f`. Nu introduce chei în variabile frontend `VITE_*`, deoarece acestea pot ajunge în JavaScript-ul livrat browserului.

2. **Descărcarea modelelor (o singură dată):**

   După configurarea mediului, descarcă BGE-M3 și modelele Docling:

   ```bash
   docker compose --profile setup run --rm model-fetch
   ```

   Modelele Qwen și Laya se pregătesc separat în directoarele configurate la pasul anterior; serviciul `model-fetch` nu le descarcă.

3. **Pornirea sistemului:**

   ```bash
   docker compose --profile ui --profile mail up -d --build
   ```

   Interfața este disponibilă la `http://127.0.0.1:8080`. Pentru a rula fără triajul de e-mailuri, omite parametrul `--profile mail`. Frontend-ul este construit și servit integral în containere, prin configurația Nginx a proiectului.

   **Build și conectivitate:** construirea imaginilor și pregătirea modelelor necesită acces la sursele de pachete și imagini sau la mirror-uri interne. Pentru instalare fără acces extern, transferă în prealabil imaginile și modelele și pornește cu `--no-build`. Funcțiile care folosesc IMAP, cercetarea web și cursurile BNR necesită în continuare conectivitatea aferentă; simplul transfer al imaginilor nu le face disponibile offline.

**Live Web RAG opțional:** toggle-ul din chat activează căutarea SearXNG și extragerea Camoufox pentru maximum trei pagini publice. Întrebarea curentă trece prin Egress Guard; dovezile web sunt citate prin URL. Detalii, limite și contracte: [LIVE_WEB.md](LIVE_WEB.md).

## 📚 Documentație suplimentară

- [TECHNICAL_INTEGRATIONS.md](TECHNICAL_INTEGRATIONS.md) — Pint, reranking local opțional și proveniența structurală Docling.

- [SOURCE_QUALITY.md](SOURCE_QUALITY.md) — Confirmarea valorilor, detectarea paginilor blocate și inventarul local al furnizorilor.

- [API_DOCS.md](API_DOCS.md) — Structura completă a API-ului de backend, modele de date, exporturi și coduri de eroare.
- [LANSARE.md](LANSARE.md) — Ghid pas cu pas pentru prima lansare, pregătirea modelelor și verificarea integrării Saga.
- [Frontend README](frontend/README.md) — Arhitectura SPA, configurarea proxy-ului și testele de browser.
