# Prima lansare

## 0. Mută proiectul din OneDrive (obligatoriu)

`./data/` (facturi, fișe tehnice, atașamente e-mail) și `.env` (parole) sunt montate în containere
din folderul proiectului. În OneDrive ar fi **sincronizate în cloud** — exact scurgerea pe care
arhitectura o previne. Mută proiectul, de preferință în WSL2 (și mai rapid pentru Docker):

```powershell
wsl --install -d Ubuntu          # dacă nu există deja
wsl
mkdir -p ~/ofertare && cp -r "/mnt/c/Users/andre/OneDrive/Desktop/automatizare ofertari/." ~/ofertare/
cd ~/ofertare && rm -rf .venv     # venv-ul de Windows nu e util în Linux
```

Apoi șterge copia din OneDrive.

## 1. Docker + memorie

1. Instalează Docker Desktop (backend WSL2).
2. `C:\Users\andre\.wslconfig`:
   ```ini
   [wsl2]
   memory=13GB
   swap=8GB
   ```
   apoi `wsl --shutdown`.

## 2. Modele (pe ext4 în WSL, nu pe C:)

| Model | Unde | Cum |
|---|---|---|
| Qwen3.6-35B-A3B (Colibri) | `~/models/qwen36` | vezi `docs/` din github.com/JustVugg/colibri; verifică cu `coli doctor --model ~/models/qwen36` |
| Laya | `~/models/laya` | `hf download convaiinnovations/laya model.safetensors rl_agent_config.json "encoder/*" "tokenizer/*" --local-dir ~/models/laya` |
| BGE-M3 + Docling | `./data/` | pasul 4 (automat) |

## 3. Configurare

```bash
cp .env.example .env                                  # completează TOT (parole, COLIBRI_MODEL_DIR, COMPANY_*)
cp config/denylist.example.yaml config/denylist.yaml  # numele REALE ale clientului / proiectelor
```
Fără `denylist.yaml` valid, research-gateway refuză să pornească (intenționat).

## 4. Pornire

Frontend-ul este compilat automat într-un build Docker multi-stage (`node:20-alpine` → `nginx:alpine`). Nu este necesar Node.js pe host. Build-ul necesită acces la imaginile de bază și registrul npm sau la mirror-uri interne; pentru rulare complet izolată, transferă imaginile deja construite și folosește `--no-build`.

```bash
docker compose --profile setup run --rm model-fetch   # o singură dată: BGE-M3 + modele Docling
docker compose --profile ui --profile mail up -d --build
```
Deschide **http://127.0.0.1:8080**.

Completează `IMAP_*` în `.env` pentru profilul `mail`. Pentru pornire fără triaj e-mail, omite `--profile mail`; păstrează `--profile ui` pentru interfață.

## 5. Verificări după pornire

```bash
docker compose ps                                          # toate „running” / „healthy”
curl -s 127.0.0.1:8080/api/health                          # {"ok":true}
docker compose exec research-gateway python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/fx/bnr').read()[:120])"
pip install -r requirements-dev.txt && pytest tests/test_memory_16gb.py -s   # bugetul de 16 GB, sub sarcină reală
```

Pune o factură e-Factura (XML/ZIP) în `data/inbox/invoices/` → în ~40 s apare în `processed/`
și e găsită în chat / la „↺” în generatorul de oferte.

## 6. Saga — o verificare unică

Formatul datei și separatorul zecimal din XML-ul Saga nu sunt documentate public. În Saga:
tipărește o factură de ieșire cu „Formular PDF” → copiază XML-ul din `C:\TEMP\Facturi` în
`tests/fixtures/saga/` și rulează `pytest tests/test_saga.py`. Dacă testul trece, importul e sigur.


## Live Web RAG opțional

`POST /chat` acceptă `live_web: bool = false`. Checkbox-ul „🌍 Căutare Live Web (Perplexity)” activează căutarea externă pentru întrebarea curentă, filtrată prin Egress Guard. Istoricul nu este trimis către căutarea web. Citările web folosesc `[https://...]`; răspunsul include `live_web` și `web_research`. Serviciul Camoufox înlocuiește Playwright MCP. Arhitectură, contracte și limite: [Live Web RAG](LIVE_WEB.md).
