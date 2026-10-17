# Ofertare B2B — React + Tailwind CSS + Vite

Interfață în română pentru API-ul descris în `../API_DOCS.md`. Chat-ul salvează conversațiile în Postgres și le restaurează după reîncărcare printr-un cookie HttpOnly. Ofertele și formularul e-mail păstrează starea doar în memoria paginii. Nu se salvează prețuri sau mesaje în localStorage.

## Design și navigare

Pagina `/` este landing-ul SculptureHero din referința furnizată, cu particule WebGL2, teme light/dark și imagine statică atunci când WebGL nu este disponibil. Linkurile `/#chat`, `/#offers` și `/#email` deschid direct zonele de lucru. Revenirea la landing prin logo păstrează formularele în memoria paginii.

Chat-ul folosește BranchingReasoningChatInput, conectat la API-ul existent: istoricul, citările, tabelele de prețuri și opțiunea Live Web sunt păstrate. Cardurile reprezintă încercările efectiv raportate în `attempts`; nu sunt afișate scoruri inventate, răspunsuri demonstrative sau progres simulat. Textul întrebării rămâne disponibil după o eroare.

Componentele reutilizabile sunt în `src/components/ui`, conform aliasului `@/components/ui` din Vite și TypeScript. `components.json` configurează structura compatibilă shadcn; nu este necesară regenerarea proiectului prin CLI. Fișierele existente JSX coexistă cu noile TSX, verificate prin `npm run typecheck`. Stilurile comune sunt în `src/styles.css`, iar stilurile SculptureHero în fișierul CSS de lângă componentă.

Imaginile și fonturile sunt servite local. Nu sunt introduse excepții în CSP-ul Nginx; `assetsInlineLimit: 0` evită fonturile inline blocate de politica existentă. Atribuire: [UI_ATTRIBUTION.md](UI_ATTRIBUTION.md).

## Pornire prin Docker (recomandată)

Din rădăcina proiectului, după configurarea serviciilor backend și a variabilelor din `.env`:

```powershell
docker compose --profile ui --profile mail up -d --build
```

Deschide `http://127.0.0.1:8080`. Nu este necesar Node.js sau npm pe host. Docker compilează aplicația în etapa `node:20-alpine`, apoi copiază doar rezultatul `dist` în imaginea finală `nginx:alpine`. Configurația Nginx este montată din `infra/nginx/default.conf`, cu proxy-ul `/api` și headerele de securitate existente. Profilul `ui` activează frontend-ul; profilul `mail` activează serviciile de e-mail.

## Dezvoltare locală (opțională)

Doar pentru dezvoltare în afara containerelor: Node.js 20.19+ sau 22.12+ compatibil cu Vite 8 și npm.

```powershell
cd frontend
npm ci
npm run dev
```

Deschide adresa afișată de Vite (implicit `http://127.0.0.1:5173`). Toate cererile merg la `/api`. Proxy-ul Vite le transmite către Nginx la `http://127.0.0.1:8080`, care elimină prefixul `/api` înainte de a apela backend-ul. Poți configura ținta în `frontend/.env.local`, folosind `.env.example` ca model. Ținta trebuie să accepte prefixul `/api`.

## Distribuire în rețeaua izolată

Build-ul Docker necesită acces la imaginile de bază și la registrul npm sau la mirror-uri interne. Aplicația compilată nu necesită internet, Node, CDN, fonturi externe sau servicii externe în browser.

```powershell
docker compose --profile ui build frontend
docker compose --profile ui up -d frontend
```

Fișierele compilate sunt incluse în imagine, fără montarea directorului `dist` de pe host. Pentru o mașină complet izolată, transferă imaginile deja construite folosind `docker save` / `docker load` și pornește serviciile cu `--no-build`. Politica CSP din `infra/nginx/default.conf` rămâne activă.

## Comportament

- Chat: `/chat`, citări randate ca text React cu document/pagină și metadate, prețuri `exact`, avertismente pentru rezultate neverificate. API-ul folosește istoricul conversației pentru referința articolului, recuperează documentele din nou și returnează numai dovezi extractive. Maximum trei încercări; conflictele și lipsa dovezilor sunt afișate explicit. Referințele și notele de revizuire sunt salvate separat, fără a deveni automat fapte.
- Oferte: toate câmpurile comerciale, costuri, import/AFER, certificate și checklist. Penalitățile sunt fixate la valorile cerute de checklist (5% / săptămână, plafon 30%). Căutarea `/prices` permite alegerea explicită a unei facturi înainte de precompletare. Nu schimbă cantitatea ofertei.
- Exporturile sunt permise doar pentru un calcul al datelor curente cu `compliance.ok === true`. Datele financiare rămân stringuri; toate calculele sunt efectuate de backend. Saga validează separat datele fiscale. Răspunsurile binare sunt salvate prin Blob, cu numele din Content-Disposition când este disponibil.
- Draft: toate cele 10 limbi, RFQ/clarificări, articole dinamice, copiere subiect și mesaj. Nu trimite e-mailuri. Nu transmite automat clientul sau alte date din ofertă.
- Erorile 409/422/502/503 și erorile de rețea apar în interfață. La 409 exporturile se blochează din nou. Un răspuns HTTP 200 HTML este detectat ca o configurare incorectă a proxy-ului.

## Verificare

```powershell
npx playwright install chromium
npm test
npm run build
```

Testele de browser folosesc răspunsuri API simulate și verifică blocarea exporturilor, recalcularea după modificare, selecția prețurilor, fișierele binare, citările, drafturile și erorile. Integrarea reală necesită serviciile backend pornite.

Interfața JavaScript anterioară este păstrată în `legacy/`, împreună cu verificările Python existente pentru aceasta. Nu este inclusă în build-ul React.

Integrarea Tailwind folosește [pluginul oficial pentru Vite](https://tailwindcss.com/docs/installation/using-vite).


## Live Web RAG opțional

`POST /chat` acceptă `live_web: bool = false`. Checkbox-ul „🌍 Căutare Live Web (Perplexity)” activează căutarea externă pentru întrebarea curentă, filtrată prin Egress Guard. Istoricul nu este trimis către căutarea web. Citările web folosesc `[https://...]`; răspunsul include `live_web` și `web_research`. Serviciul Camoufox înlocuiește Playwright MCP. Arhitectură, contracte și limite: [Live Web RAG](../LIVE_WEB.md).
