# Conectare Google / Microsoft și trimitere e-mail

Secțiunea **Draft e-mail** oferă două butoane cu logo-uri locale, contul expeditor,
destinatarul, previzualizarea și confirmarea explicită a trimiterii. Nu trimite
automat după generare. Mesajele sunt text simplu, către un singur destinatar,
fără atașamente/CC/BCC în această versiune.

## Configurare la client

Administratorul înregistrează o aplicație OAuth la fiecare furnizor dorit.
Utilizatorul se conectează apoi prin buton, în pagina furnizorului; aplicația nu
cere parola căsuței. Toate valorile de mai jos rămân exclusiv în `.env` local.

```dotenv
MAIL_PUBLIC_URL=http://127.0.0.1:8080
MAIL_SERVICE_KEY=
MAIL_TOKEN_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT=common
```

Generează separat cheile folosind imaginea gateway-ului (nu necesită Python pe host):

```bash
docker compose build research-gateway
docker compose run --rm --no-deps research-gateway python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose run --rm --no-deps research-gateway python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Prima valoare este `MAIL_SERVICE_KEY`, a doua `MAIL_TOKEN_KEY`. Nu publica valorile
sau ieșirea acestor comenzi. Păstrează cheia de criptare pentru restaurarea
volumului `maildata`; schimbarea ei face tokenurile existente ilizibile.

- **Google Cloud:** activează Gmail API, configurează ecranul de consimțământ și
  un OAuth client de tip **Web application**. Redirect URI exact:
  `http://127.0.0.1:8080/api/emails/accounts/google/callback`.
  Scope-uri: `openid`, `email`, `https://www.googleapis.com/auth/gmail.send`.
  Configurează utilizatorii de test sau publicarea/verificarea aplicației conform
  politicilor Google. Politicile organizației pot limita consimțământul.
- **Microsoft Entra:** înregistrează aplicația cu platformă **Web**, nu SPA,
  client secret și tipurile de conturi acceptate. Redirect URI exact:
  `http://127.0.0.1:8080/api/emails/accounts/microsoft/callback`.
  Permisiuni delegate: `User.Read`, `Mail.Send`, `offline_access`.
  `MICROSOFT_TENANT` poate fi ID-ul tenantului, `organizations`, `consumers` sau
  `common`, în concordanță cu înregistrarea. Administratorul poate impune aprobarea.

Pentru o adresă de rețea folosește HTTPS, actualizează `MAIL_PUBLIC_URL`, ambele
redirect URI-uri și `COOKIE_SECURE=true`. Originea trebuie să coincidă cu cea din
browser. Configurația implicită funcționează doar pe calculatorul care publică
portul Docker pe loopback. În dezvoltare configurează originea serverului Vite
cu proxy `/api`; `vite preview` nu oferă acel proxy.

```bash
docker compose --profile ui --profile mail up -d --build
```

Accesează aplicația, conectează contul, autorizează-l în tabul furnizorului și revino
în tabul mesajului. Conturile se actualizează la revenirea în fereastră; există și
buton de reîmprospătare. Generează mesajul, alege expeditorul, completează destinatarul,
verifică previzualizarea și bifează confirmarea înainte de **Trimite e-mailul**.

## Arhitectură și limite

Browser → Nginx → backend intern → research-gateway → Gmail API / Microsoft Graph.
Backend-ul rămâne fără acces direct la internet. Gateway-ul deține tokenurile
criptate Fernet în SQLite, în volumul Docker `maildata`, fără acces la Postgres.
Configurarea OAuth este opțională; fără chei, drafturile funcționează și butoanele
de conectare indică lipsa configurării.

OAuth folosește state de unică folosință, expirare la 10 minute și PKCE S256.
Conturile sunt legate de un cookie HttpOnly SameSite=Lax separat, necesar revenirii
de la furnizor. API-ul intern de e-mail cere `MAIL_SERVICE_KEY`; mutațiile din browser
cer JSON și validează Origin. Tokenurile nu sunt trimise browserului, LLM-ului sau
în logurile de acces. Logarea accesului API este dezactivată pentru a nu salva coduri
OAuth. Nu activa logarea URL-urilor callback în proxy-uri suplimentare.

Cookie-ul reprezintă accesul la contul conectat în profilul de browser, **nu un sistem
de utilizatori/roluri**. Nu utiliza același profil de browser pentru persoane diferite.
Pentru publicare în LAN sunt necesare identități/autentificare la nivel de aplicație.
Deconectarea șterge tokenurile locale și autorizările în curs; pentru revocarea
consimțământului la furnizor folosește setările contului Google/Microsoft.

Egress Guard verifică expeditorul, destinatarul, subiectul și corpul final înainte
de orice cerere de trimitere. O regulă denylist blocantă nu poate fi ocolită din UI.
Acest filtru determinist nu garantează detectarea oricărei informații confidențiale.
Modul e-mail necesită internet către furnizor: nu este un mod complet air-gapped.

ID-ul fiecărei trimiteri este rezervat persistent înaintea apelului extern. Repetarea
aceluiași ID și mesaj nu produce o nouă trimitere. Timeout-ul sau căderea procesului
lasă rezultatul „neconfirmat”; verifică **Trimise** înainte de a genera și trimite
un mesaj nou. „Acceptat de furnizor” nu înseamnă livrare confirmată în inbox.

**Citirea și repartizarea:** aceste butoane cer acces pentru trimitere și identitate,
nu pentru citirea căsuței. Modulul IMAP existent continuă să descarce și să clasifice
atașamente, cu propria configurație `IMAP_*`. Conectarea OAuth nu îl configurează
automat și nu adaugă repartizare pe angajați sau citirea corpurilor mesajelor.

## API și verificare

- `GET /emails/accounts`: disponibilitate și adresa contului, fără tokenuri.
- `POST /emails/accounts/{google|microsoft}/connect`: URL de autorizare.
- `GET /emails/accounts/{provider}/callback`: schimb cod → token, revenire în UI.
- `POST /emails/accounts/{provider}/disconnect`: elimină conectarea locală.
- `POST /emails/send`: `provider`, `request_id` UUID, `to`, `subject`, `body`,
  `confirmed: true`; rezultat `accepted`, `rejected` sau `unknown`.

Teste cu transport simulat: OAuth/PKCE, state legat de browser, respingere replay,
criptare, refresh, izolare proprietar, Egress Guard, mesaj trimis exact, idempotency,
timeout și interfață. Testele nu trimit e-mailuri reale. Verificarea reală necesită
configurarea OAuth și un cont autorizat la client.

Referințe: [Google OAuth web server](https://developers.google.com/identity/protocols/oauth2/web-server),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes),
[Microsoft authorization code + PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow),
[Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail).


## Logo în mesaj

Opțiunea „Logo-ul firmei” acceptă PNG/JPEG de maximum 512 KiB și 1024×1024 pixeli.
Logo-ul este păstrat în formularul curent, fără stocare permanentă; reîncărcarea paginii
îl elimină. Interfața îl previzualizează și îl recodifică PNG. Modificarea lui anulează
draftul validat. Copierea în clipboard copiază numai textul.

`POST /emails/send` acceptă opțional `logo_base64` (fără prefix data-URL).
Gateway-ul validează imaginea, o recodifică fără metadata și o include în identitatea
cererii pentru idempotency. Gmail primește plain text + HTML/related cu imagine CID;
Microsoft primește HTML și fileAttachment inline cu același contentId. Textul este
escapat HTML. Nu se folosesc URL-uri externe pentru imagine și nu se trimit imagini
fără confirmarea explicită a mesajului. Afișarea depinde și de clientul destinatarului.

Egress Guard verifică textul și adresele; nu efectuează OCR pe logo. Utilizatorul
verifică imaginea înainte de trimitere. Testele verifică payload-urile furnizorilor
cu transport HTTP simulat, fără trimiterea unor e-mailuri reale.
