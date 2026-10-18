# Punere în funcțiune și verificări

## Ce este implementat, ce trebuie verificat la client

`/health` verifică numai procesul API (liveness). Rămâne verificarea Docker pentru a permite
accesul la diagnostice când un model nu funcționează. `/ready` răspunde 503 când Postgres,
Qdrant sau catalogul de modele Colibri nu răspund. `/diagnostics` afișează separat și gateway-ul
și heartbeat-ul procesării documentelor. Probele au timeout și nu generează răspunsuri AI,
nu contactează furnizori externi și nu afișează URL-uri, parole sau excepții brute.

Un rezultat verde NU certifică OCR, prezența tuturor modelelor embedding, exactitatea
unui răspuns, funcționarea Laya, OAuth sau disponibilitatea BNR/SearXNG/Camoufox.
Un model anunțat de `/v1/models` trebuie testat și prin generare reală.

Din rădăcina proiectului, cu Python 3.12:

```bash
python scripts/preflight.py
docker compose --profile setup run --rm model-fetch
docker compose --profile ui up -d --build
curl --fail http://127.0.0.1:8080/api/ready
```

Nu adăuga `--profile mail` înainte de configurarea IMAP: acest profil citește cutia poștală.
Setează separat modelele Colibri/Laya conform LANSARE.md. Nu copia documente confidențiale
în OneDrive. Preflight nu modifică fișiere și nu afișează valorile secretelor.

## Autentificare Microsoft 365 și Google Workspace

Este separată de OAuth pentru trimiterea e-mailurilor. Autentificarea cere numai
`openid email profile`, fără citirea sau trimiterea mesajelor. Schimburile externe
se fac în research-gateway; backend-ul verifică local sesiunea semnată.
Integrarea utilizează [Authlib pentru Starlette](https://docs.authlib.org/en/v1.5.0/client/starlette.html),
cu PKCE S256, state și verificarea ID tokenului / nonce-ului de către bibliotecă.

În `.env` local:

```dotenv
AUTH_ENABLED=true
AUTH_SESSION_SECRET=
AUTH_GOOGLE_DOMAINS=
AUTH_MICROSOFT_TENANT=
```

Generează un secret aleator de minimum 48 de caractere, diferit de cheile e-mail.
Folosește domeniile Workspace permise, separate prin virgulă, și GUID-ul EXACT al
tenantului Microsoft; `common` nu este acceptat pentru login. Completează și
GOOGLE_CLIENT_ID/SECRET, MICROSOFT_CLIENT_ID/SECRET și MAIL_PUBLIC_URL.
Nu transmite secretele prin chat sau Git.

Înregistrările OAuth trebuie să includă exact aceste redirect URI-uri (ajustează originea):

- `http://127.0.0.1:8080/api/auth/google/callback`
- `http://127.0.0.1:8080/api/auth/microsoft/callback`

Google cere cont cu `email_verified` și `hd` autorizat. Microsoft cere token emis pentru
tenantul configurat. Administratorul Entra trebuie să limiteze accesul aplicației prin
atribuirea utilizatorilor/grupurilor, inclusiv politica pentru invitați.
Pentru acces din rețeaua departamentului configurează HTTPS, `COOKIE_SECURE=true` și originea
HTTPS în MAIL_PUBLIC_URL și în redirect URI-uri. Nu expune portul în LAN fără aceste verificări.

Cu AUTH_ENABLED=true, API-urile de business, documentația API și diagnosticul detaliat
necesită autentificare. `/health`, `/ready` și rutele de login sunt publice.
Operațiile de modificare necesită Origin egal cu MAIL_PUBLIC_URL.
Previzualizarea UI fără backend nu oferă acces la date și nu dezactivează protecția API.

Conversațiile și conexiunile e-mail sunt asociate identității furnizorului, nu browserului.
Conturile Google și Microsoft nu sunt unite automat chiar dacă afișează aceeași adresă.
Conversațiile vechi asociate cookie-ului nu sunt migrate automat. Biblioteca documentelor
rămâne comună angajaților autorizați: această versiune NU implementează roluri de administrator
sau permisiuni distincte pe folder. Toți utilizatorii autentificați au aceleași drepturi de lucru.

Sesiunea expiră după 8 ore. Logout șterge cookie-urile browserului; un cookie copiat anterior
nu poate fi revocat individual înainte de expirare. Rotirea AUTH_SESSION_SECRET revocă toate
sesiunile. Pentru revocare imediată individuală este necesar un registru de sesiuni server-side.
În modul implicit AUTH_ENABLED=false rămâne modul local cu cookie, destinat dezvoltării.

## Backup și restaurare fără suprascriere

Rulează pe un disc criptat, în afara proiectului și a folderelor sincronizate. Arhivele
CONȚIN date de business și `.env`; scriptul nu le criptează singur. Pe Windows configurează
ACL-urile directorului; pe Linux este creat cu mod 0700. Nu publica manifestele/arhivele.
Necesită imaginea locală postgres:17-alpine și Docker. Nu descarcă imagini din rețea.

```bash
python scripts/backup.py backup /mnt/backup-criptat/ofertare-2026-10-18
python scripts/backup.py verify /mnt/backup-criptat/ofertare-2026-10-18
python scripts/backup.py restore /mnt/backup-criptat/ofertare-2026-10-18 --destination /mnt/restaurare/ofertare --prefix ofertare_recovery
```

Backup oprește serviciile proiectului, arhivează volumele Postgres/Qdrant/maildata și
directoarele locale relevante, apoi repornește numai serviciile anterior active, inclusiv
la eșec. Programează o fereastră de mentenanță. Nu permite alți scriitori pe volume/foldere
în această perioadă. Verificarea SHA-256 detectează coruperea, nu înlocuiește proba de restaurare.

Restaurarea refuză volume sau director destinație existente. Creează volume NOI și un
`restore-volumes.json` pentru Docker Compose; nu pornește containere, nu trimite mesaje.
Copiază sursele aplicației în directorul restaurat (fără a suprascrie datele restaurate),
verifică `.env`, căile modelelor și folosește un nume de proiect separat:

```bash
docker compose -p ofertare_recovery -f docker-compose.yml -f restore-volumes.json --profile ui up -d
```

Oprește instanța originală pentru a elibera portul 8080 înainte de această probă.
Folosește ACELEAȘI versiuni de imagini ca la backup pentru datele fizice; fixează digesturile
înainte de producție (unele imagini existente folosesc încă latest). Nu activa mail/drive
într-o probă de restaurare. Modelele/cache-urile și orice CLIENT_DOCUMENTS_PATH extern
nu sunt incluse: păstrează separat modelele și sursele externe.

## Probe de acceptanță înainte de predare

1. Încarcă un PDF sintetic cu o valoare și o pagină cunoscute. Așteaptă status indexed.
2. Cere valoarea în chat. Compară cifra, unitatea, revizia și pagina citată cu originalul.
3. Reîncarcă și reconectează-te în alt browser cu același cont: conversația trebuie recuperată.
4. Folosește alt cont: conversația și conexiunea e-mail nu trebuie să fie vizibile.
5. Modifică PDF-ul din folderul monitorizat: verifică reindexarea și răspunsul pe noua revizie.
6. Testează scanări, tabele, coloane și surse contradictorii cu răspunsuri etalon umane.
7. Verifică Live Web cu o interogare publică și blocarea uneia din denylist.
8. Verifică oferta, apoi importul XML într-o firmă de TEST Saga. Testul XML singur nu
   garantează acceptarea de către versiunea de Saga instalată.
9. Configurează separat OAuth e-mail, verifică destinatarul, confirmă explicit și trimite
   un mesaj de test. Nu există trimitere automată în aceste scripturi.
10. Rulează `pytest tests/test_memory_16gb.py -s` cu stack-ul pornit, apoi măsoară separat
    ingestia PDF simultan cu chatul. Testul existent acoperă Colibri/Laya, nu întregul vârf OCR.
11. Restaurează backup-ul pe un mediu separat și repetă pașii 1–4.

Aceste probe reale rămân de efectuat cu Docker, modelele și conturile clientului.
