# Ofertare B2B

Sistem containerizat pentru căutare în documente interne, calcul și export de oferte (Word, Excel, Saga XML) și generare de drafturi de e-mail multilingve.

## Configurare pe calculatorul clientului

Repository-ul nu include chei API, parole sau un fișier `.env` configurat. Clientul își creează fișierul local din șablon:

```powershell
Copy-Item .env.example .env
Copy-Item config/denylist.example.yaml config/denylist.yaml
```

Pe Linux/WSL, folosește `cp` în loc de `Copy-Item`.

Completează **doar local** în `.env`:

- `POSTGRES_PASSWORD`, `QDRANT_API_KEY`, `SEARXNG_SECRET`: secrete unice pentru instalarea clientului.
- `GEMINI_API_KEY`: cheia proprie a clientului, dacă activează funcționalitatea care o utilizează.
- `COLIBRI_MODEL_DIR`, `LAYA_MODEL_DIR`: căile locale ale modelelor.
- `COMPANY_*`: datele companiei necesare exportului Saga.
- `IMAP_*`: configurația și parola de aplicație pentru căsuța poștală, dacă folosește profilul `mail`.

Completează `config/denylist.yaml` cu termenii interni care nu trebuie să părăsească rețeaua. `.env`, variantele sale locale, denylist-ul real și directorul `data/` sunt excluse din Git. Nu folosi `git add -f` pentru acestea și nu introduce secrete în variabile frontend `VITE_*` (acestea pot deveni publice în JavaScript).

## Pornire

Urmează [ghidul de instalare și pregătire a modelelor](LANSARE.md), apoi rulează din rădăcina proiectului:

```powershell
docker compose --profile ui --profile mail up -d --build
```

Interfața este disponibilă la `http://127.0.0.1:8080`. Build-ul React rulează în Docker; nu este necesar Node.js pe host. Pentru a nu porni triajul e-mail, omite `--profile mail`.

Build-ul inițial necesită acces la imaginile și pachetele folosite sau la mirror-uri interne. Pentru un mediu complet izolat, pregătește și transferă imaginile și modelele înainte de pornire.

## Documentație

- [API](API_DOCS.md)
- [Instalare și lansare](LANSARE.md)
- [Frontend și teste de browser](frontend/README.md)

Fișierele din `tests/fixtures/synthetic/` conțin date fictive de test. Datele reale ale clientului se adaugă numai în directoarele locale excluse din Git.
