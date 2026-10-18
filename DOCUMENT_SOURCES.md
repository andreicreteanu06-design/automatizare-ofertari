# Documentele clientului și Google Drive

În **Documentele mele**, încărcarea unui folder salvează o copie. Browserul nu
urmărește modificările ulterioare ale originalului. Pentru actualizare automată,
administratorul setează în `.env` variabila `CLIENT_DOCUMENTS_PATH` la un director
existent (de exemplu `C:/DocumenteClient` sau `/srv/documente-client`). Subfolderele
sale apar în selectorul aplicației. Montarea Docker este read-only.

```bash
docker compose --profile ui --profile mail up -d --build
```

Serviciul `source-watch` pornește automat. Necesită modelele locale de embeddings
și Docling pregătite conform LANSARE.md. Verifică sursele la aproximativ 30 de secunde
între procesări. Documentele mari pot dura minute; cadența nu garantează acces
instantaneu. Starea documentelor este afișată în interfață.

Formate: PDF, DOCX, XLSX, TXT, MD, CSV. Limitele inițiale configurabile în `.env`:
- `SOURCE_MAX_FILE_MB=250`: MiB per fișier, pentru încărcare, monitorizare și Drive (1–1024).
- `SOURCE_MAX_FOLDER_GB=100`: GiB per folder încărcat prin browser (1–10000).
- `SOURCE_MAX_FILES=50000`: documente per sursă locală/încărcată și intrări Drive (1–1000000).

Interfața citește limitele efective din `/sources`; după schimbarea configurației,
recreează containerele. Nginx are un plafon de 1 GiB per cerere și transmite corpul
în flux către backend. Încărcarea se scrie pe disc temporar și se publică atomic;
amprentele SHA-256 sunt calculate în blocuri de 1 MiB.

Pentru digitalizarea unui departament, folosește foldere monitorizate pe discul/NAS-ul
clientului: nu dublează arhiva prin browser și nu aplică plafonul de volum al copiilor
încărcate. Discul disponibil, limita per fișier și numărul maxim de documente rămân relevante.
Limitele sunt praguri de admitere, nu o garanție de debit: fiecare document este procesat
secvențial în subproces (timeout 30 minute, memorie container 5 GiB). PDF-urile scanate
mari pot necesita împărțire pe volume. Nu s-a efectuat un benchmark cu 50.000 de documente;
inventarierea și verificarea amprentelor unei arhive mari pot prelungi ciclurile.
Fișierele ascunse și legăturile simbolice sunt omise. Textul și CSV sunt citite ca
UTF-8, fără garanția reconstrucției tabelelor. Paginarea Office/text nu este identică
cu paginile unui PDF original.

Fișierele modificate se reindexează; cele șterse sunt retrase din căutările noi.
Amprenta fișierului este verificată la recuperarea dovezilor. Sursele gestionate
nu sunt folosite dacă monitorul este oprit sau documentul nu mai este disponibil.
Mesajele istorice nu sunt rescrise automat. Biblioteca este comună instalației,
fără ACL per folder sau autentificare enterprise; utilizați doar spațiul autorizat.

## Google Drive

Integrarea rulează `@googleworkspace/cli@0.22.5` în Docker, fără Node.js pe host,
cu operațiile Drive list/get/export. Nu încarcă documentele locale în Google.
Google Docs se exportă PDF, Sheets XLSX. Scurtăturile nu sunt urmărite. Limita este
`SOURCE_MAX_FILES` intrări/sursă (50.000 implicit, inclusiv directoarele). Sincronizarea verifică la 60 de secunde între cicluri, după
care începe indexarea locală.

Administratorul configurează Google Drive API și un cont de serviciu dedicat,
fără delegare de domeniu, cu acces Viewer doar la folderele aprobate. Cheia JSON
se salvează local în `secrets/google-drive.json`, exclus din Git. Alternativ, se
poate folosi exportul OAuth documentat de gws cu permisiunea `drive.readonly`.
Tokenul de trimitere Gmail nu acordă acces Drive. Completați local denylist.yaml.

```bash
docker compose --profile ui --profile mail --profile drive up -d --build
```

În aplicație, selectați Conectează un folder Google Drive și introduceți numele
local și ID-ul de după `/folders/` din URL. Așteptați indexarea documentelor.

Containerul `drive-sync` este exclusiv pe egress, iar indexarea rămâne internă.
Egress Guard verifică parametrii externi. Către Google pleacă ID-uri și parametri
Drive, nu numele locale de proiect. Transferul intern folosește `drive-mirror`.
Inventarierea eșuată păstrează copia anterioară, dar o exclude din căutare până la
restabilirea sincronizării. Copiile fără confirmare de peste 10 minute sunt excluse.
Profilul Drive are nevoie de internet și nu este complet air-gapped.

[Documentația Workspace CLI](https://github.com/googleworkspace/cli#authentication)
descrie autentificarea; proiectul nu este suportat oficial de Google. Testele
folosesc răspunsuri simulate. Conectarea și descărcarea reală trebuie verificate
cu acreditările clientului în mediul său.

## API și administrare

- `GET /sources`: surse, stări, numere de documente, ultimele 50 fișiere și heartbeat.
- `GET /sources/folders?path=`: subfoldere din rădăcina autorizată.
- `POST /sources`: JSON `{name, kind: local|upload|drive, path}`, răspuns `{id}`.
- `POST /sources/{id}/upload?path=folder/fisier.pdf`: corp binar fără multipart.

POST necesită headerul `X-Source-Action: 1`, same-origin. Nu este expus întregul
disc. Interfața nu oferă încă ștergerea surselor. Includeți `data/source-state`,
`source-uploads`, `drive-config` și `drive-mirror` în procedura locală de backup.
