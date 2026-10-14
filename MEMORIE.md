# Memorie și verificarea dovezilor

## Ce se păstrează

Conversațiile, întrebările, răspunsurile cu dovezi și referințele comentate sunt stocate în Postgres. Restartul backend-ului nu le șterge. Datele depind de volumul `pgdata`; nu folosi `docker compose down -v` dacă vrei să le păstrezi. Un backup al codului pe GitHub nu este un backup al bazei de date.

UI-ul restaurează cea mai recentă conversație și permite alegerea alteia. Lista are maximum 100 conversații, istoricul livrat are ultimele 100 tururi, iar rezolvarea referinței articolului folosește ultimele 12 mesaje. Tururile mai vechi rămân în DB, dar nu sunt încă paginate în UI. O conversație nouă nu preia contextul alteia, chiar dacă au același nume de proiect.

Cookie-ul HttpOnly identifică spațiul browserului; un alt cookie nu poate accesa conversația după UUID. Nu este autentificare enterprise. Un browser comun înseamnă un spațiu comun. Ștergerea cookie-ului nu șterge DB, dar pierde accesul la istoricul asociat. Pentru utilizatori reali, integrarea cu identitatea organizației și politici de retenție rămâne necesară.

## Verificare strictă

1. Se identifică articolul din întrebarea curentă sau din ultima întrebare cu cod a conversației. Se caută din nou în Postgres și Qdrant.
2. Serverul construiește dovezi din rânduri de tabel sau propoziții și păstrează asocierea cu documentul, intervalul de pagini, antetele și codul articolului. Dacă este cerut un cod, dovada trebuie să îl conțină explicit.
3. Modelul poate selecta maximum 8 ID-uri existente. Nu are voie să furnizeze un text cu valori tehnice.
4. Serverul validează selecția și compune răspunsul numai din textul și celulele extrase. Un răspuns liber precum „120 kg” nu poate înlocui celula „12 kg”.
5. Dacă lipsesc dovezi sau selecția este invalidă, se extinde căutarea și se reîncearcă. Limita este de trei încercări; nu există buclă infinită. La eșec se afișează abținerea.

Conflictele pentru proprietățile recunoscute sunt detectate între valorile acelorași coduri, în antete de tabel și în forme textuale simple (de exemplu `masa 12 kg`). Unitățile nu sunt convertite automat: `12 kg` și `12000 g` pot fi semnalate ca valori diferite pentru revizuire. Nu se alege automat între revizii.

Referințele salvate conțin o copie a dovezii și nota utilizatorului. Sunt separate de răspunsuri și nu sunt folosite ca adevăr în prompt. O corecție propusă trebuie verificată în sursă; salvarea ei nu reprezintă aprobare tehnică.

## Limite explicite

- Verificarea demonstrează fidelitatea copiei, nu corectitudinea PDF-ului, a OCR-ului sau relevanța perfectă a selecției. Documentele tehnice critice trebuie revizuite de specialist.
- Datele din desene, formule complexe, celule ambigue, rânduri fără cod explicit și tabele foarte mari pot necesita verificare manuală. Fragmentele care depășesc bugetul sunt omise, nu trunchiate pentru a inventa o asociere.
- Dicționarul de proprietăți și detectorul de conflicte au acoperire limitată. Lipsa unui conflict detectat nu dovedește absența contradicțiilor în întreaga colecție.
- SHA-256-ul PDF-ului este o amprentă a conținutului, nu revizia declarată de producător. Indexările vechi nu au această amprentă; reindexează-le. Intervalele de pagini ale tabelelor nu identifică precis celula pe pagină.
- Tabelele consecutive se îmbină numai când antetele coincid. Continuările fără antet nu sunt presupuse compatibile.
- OCR-ul este disponibil explicit prin `python -m app.ingest.pdf ... --ocr`; watcher-ul nu îl activează automat. PDF-urile fără conținut extras sunt respinse pentru revizuire.
- Modelul nu se auto-antrenează pe conversații. Răspunsurile istorice și notele nu înlocuiesc documentele.

## Actualizare Docker și baze existente

```bash
docker compose --profile ui --profile mail up -d --build
```

Schema `backend/db/002_memory.sql` se aplică la inițializarea unei baze noi. Pentru volume existente, backend-ul aplică idempotent aceeași schemă la prima accesare a memoriei, sub un lock tranzacțional. Utilizatorul DB trebuie să poată crea tabele și indexuri; nu sunt șterse date existente. Dacă DB nu este disponibilă, API-ul returnează 503, fără a pretinde că mesajul a fost salvat.

La HTTPS, setează `COOKIE_SECURE=true` în mediul backend-ului. Configurația locală implicită folosește HTTP pe loopback și `SameSite=Strict`.

## Verificare

```bash
python -m pytest tests/test_chat_api.py tests/test_memory_api.py tests/test_pdf_chunking.py
cd frontend
npm test
```

Testele API folosesc servicii RAG și un repository de memorie simulate. Pentru a verifica SQL-ul, persistența între instanțe și scrierile concurente în Postgres real, setează `TEST_MEMORY_DATABASE_URL` către o bază de test dedicată și rulează:

```bash
python -m pytest tests/test_memory_postgres.py
```

Evaluarea cu modelele reale și fișe tehnice etichetate trebuie efectuată în instalarea clientului înainte de folosirea rezultatelor în decizii tehnice.


## Live Web RAG opțional

`POST /chat` acceptă `live_web: bool = false`. Checkbox-ul „🌍 Căutare Live Web (Perplexity)” activează căutarea externă pentru întrebarea curentă, filtrată prin Egress Guard. Istoricul nu este trimis către căutarea web. Citările web folosesc `[https://...]`; răspunsul include `live_web` și `web_research`. Serviciul Camoufox înlocuiește Playwright MCP. Arhitectură, contracte și limite: [Live Web RAG](LIVE_WEB.md).
