# Live Web RAG

În Chat tehnic, opțiunea **🌍 Căutare Live Web (Perplexity)** este dezactivată implicit. Activarea ei trimite numai întrebarea curentă către gateway; istoricul conversației, documentele interne și prețurile din facturi nu sunt anexate cererii externe. Întrebarea însăși poate conține informații sensibile: configurează `config/denylist.yaml` înainte de utilizare.

## Flux

`React → backend /chat → research-gateway /live-research → Egress Guard → SearXNG → stealth-browser (Camoufox) → dovezi → Colibri`

Gateway-ul verifică întrebarea înainte de căutare, selectează primele trei URL-uri publice distincte permise și programează extragerea lor asincron. Browserul rulează câte o instanță pentru a limita consumul de memorie. Rezultatul combinat, inclusiv etichetele URL, este limitat la 10.000 de caractere. Paginile indisponibile sunt raportate separat, fără detalii interne ale excepțiilor.

Camoufox returnează HTML și textul vizibil din `document.body.innerText`. Nu păstrează profiluri sau cookie-uri între cereri. Nu garantează trecerea protecțiilor Cloudflare/DataDome; paginile care refuză accesul pot rămâne indisponibile.

## Contracte

Backend `POST /chat` acceptă `{"query":"Masa PART123?","live_web":true}` și câmpurile opționale de conversație documentate în [API_DOCS.md](API_DOCS.md). Răspunsul include `live_web`, `web_research`, `evidence` și citări `[https://...]`. Dovezile web au URL-ul ca `doc_id`, tipul `web`, momentul preluării și amprenta textului.

Gateway `POST /live-research` acceptă `{"query":"Masa PART123?"}` și returnează `{"sources":[{"url":"https://furnizor.example/produs","text":"..."}],"text":"...","errors":[],"blocked_urls":0}`. Refuzul Egress Guard produce HTTP 403; indisponibilitatea căutării produce 502. Eșecurile individuale ale paginilor sunt incluse în `errors`.

Browser `POST /fetch` acceptă `{"url":"https://furnizor.example/produs"}` și returnează `{"url":"URL final","html":"...","text":"..."}`. Refuzurile sunt 403, erorile de navigare 502, timeout-urile 504. Navigarea are un buget de 50 secunde, iar cererea cu așteptarea unui loc are maximum 160 secunde.

## Protecții și limite

URL-urile inițiale, cererile interceptate de browser și URL-ul final sunt verificate prin Egress Guard; indisponibilitatea verificării blochează accesul. Proxy-ul local browserului rezolvă DNS, respinge IP-urile private/rezervate și răspunsurile DNS mixte, apoi conectează direct IP-ul validat, pentru a evita o a doua rezolvare DNS. Sunt permise numai HTTP(S), porturile 80/443; descărcările, service workers și WebRTC sunt dezactivate. Aceste controale aplicative nu înlocuiesc un firewall de ieșire sau izolarea sistemului gazdă.

Conținutul web este tratat ca sursă neîncrezătoare. Colibri selectează ID-uri de dovezi, iar serverul redă fragmentele originale și citările; nu acceptă valori tehnice inventate într-un răspuns liber. Fidelitatea față de text nu garantează adevărul sursei, actualitatea, extragerea corectă a unui tabel sau detectarea tuturor contradicțiilor. Nu se rezolvă automat CAPTCHA și nu se autentifică pe site-uri.

## Instalare și verificare

`stealth-browser` este construit din `stealth_browser/Dockerfile`, folosește rețeaua `egress`, limita de memorie `1.5g` și nu publică porturi pe host. Gateway-ul îl apelează prin `STEALTH_BROWSER_URL=http://stealth-browser:8000`. Protocolul MCP a fost eliminat din gateway.

```bash
docker compose --profile ui --profile mail up -d --build
```

Build-ul descarcă pachetele, browserul Camoufox și bibliotecile Firefox. Într-un mediu fără acces extern sunt necesare imagini pregătite anterior; cercetarea live necesită conectivitate externă controlată.

Testele automate verifică filtrarea, limitele, citările și contractele folosind simulări. Pornirea efectivă Camoufox, consumul de memorie și compatibilitatea cu furnizorii trebuie verificate pe instalarea Docker a clientului. Documentația proiectului Camoufox: [instalare](https://camoufox.com/python/installation/), [API Python](https://camoufox.com/python/usage/).
