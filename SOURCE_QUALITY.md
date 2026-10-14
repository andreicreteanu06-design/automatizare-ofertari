# Acces web, proveniență și confirmarea datelor

`access_status` descrie accesul: `accessible`, `blocked`, `timeout`, `unavailable` sau `partial` pentru un lot. `evidence_status` descrie separat informația: `confirmed`, `unconfirmed`, `contradictory`. `verification_status=verified_excerpts` indică numai fidelitatea citatului, nu confirmarea specificației.

## Ce înseamnă confirmat

Pentru valorile structurate sunt necesare codul exact, producătorul, varianta, revizia, condițiile, o valoare cu unitate de dimensiunea potrivită și autoritatea sursei configurată local. Un cod cu sufix diferit nu corespunde. Câmpurile lipsă rămân necunoscute; nu sunt completate de LLM. `technical_claims` păstrează valoarea, unitatea, identitatea, citatul, sursa, revizia, data preluării și motivele neconfirmării. Proprietățile cerute, dar absente, apar în `missing_properties`.

Sursa trebuie să fie producătorul configurat sau să existe concordanță între distribuitori autorizați din grupuri editoriale diferite și cu texte diferite. Copiile identice nu contează drept confirmări independente. Amprenta textului nu detectează toate republicările; independența grupurilor trebuie verificată de administrator. Conflictele blochează confirmarea; conversiile între unități și alegerea automată a reviziei câștigătoare nu sunt implementate. Această politică conservatoare poate marca și diferențe legitime drept conflicte.

`confirmed` înseamnă îndeplinirea criteriilor documentare implementate, nu certificarea adevărului. `automatic_offer_eligible` rămâne `false` și `requires_human_review` este `true`. Chat-ul nu transferă automat date web în ofertă. Revizuirea umană rămâne necesară, inclusiv pentru prețuri, stoc și valabilitate comercială.

## Configurația surselor clientului

Implicit `config/source_policy.example.json` are lista goală: niciun domeniu nu este declarat oficial automat. Creează local `config/source_policy.json`, exclus din Git, și setează `SOURCE_POLICY_FILE=./config/source_policy.json` în `.env`:

```json
{
  "domains": {
    "manufacturer.example": {
      "role": "manufacturer",
      "manufacturer": "Example Manufacturer",
      "publisher_group": "example-manufacturer"
    }
  }
}
```

Exemplul este fictiv. Folosește numai domenii confirmate; rolul alternativ este `authorized_distributor`. `manufacturer` trebuie să corespundă câmpului din document. Domeniul este potrivit exact, fără moștenirea încrederii de către subdomenii sau redirecționări. Producătorii sunt prioritizați înaintea distribuitorilor și surselor secundare în primele 30 rezultate SearXNG analizate. Se descarcă maximum trei pagini.

Nu este necesară o listă inițială de furnizori. Scriptul `scripts/inventory_suppliers.py` inventariază offline folderele cu istoric: CSV/JSON cu `supplier`/`furnizor` și `website`/`url`, precum și furnizorii din facturi XML UBL. PDF-urile, XLSX și formatele necunoscute sunt listate pentru ingestie/revizuire, fără deducerea automată a domeniului. Numele fișierelor și candidații rămân locali. Faptul că s-a comandat anterior nu acordă autoritate.

Exemplu Linux/WSL2 fără Python pe host, din rădăcina repository-ului:

```bash
docker run --rm --network none \
  -v "$PWD/scripts:/tools:ro" \
  -v "/cale/istoric-client:/input:ro" \
  -v "$PWD/data:/output" \
  python:3.12-slim python /tools/inventory_suppliers.py /input --output /output/supplier_candidates.json
```

Imaginea trebuie descărcată anterior. Revizuiește candidații, verifică site-ul și relația cu producătorul, apoi completează politica locală. Fișele PDF se introduc prin fluxul existent de ingestie internă; acest inventar nu implementează OCR separat. Nu există încă un conector API specific unui furnizor: implementarea lui necesită contractul API și accesul autorizat al clientului. Nu trimite parole/tokenuri în chat și nu le pune în politica de domenii.

## Pagini blocate și copii istorice

Gateway-ul detectează prin reguli paginile CAPTCHA, verificările de browser și autentificarea, inclusiv la HTTP 200. Regulile sunt euristice și nu acoperă orice pagină. Nu încearcă rezolvarea automată CAPTCHA sau ocolirea autentificării. Fiecare URL are o singură tentativă per cerere; browserul începe navigări la minimum două secunde distanță și rulează o singură instanță. Gateway-ul procesează maximum două cercetări live simultan, cu buget de timp și cel mult trei pagini per cercetare.

Cache-ul procesului păstrează cel mult 100 de pagini, maximum 24 ore, și dispare la restart. Se folosește numai după un eșec al preluării curente, păstrând `retrieved_at` original și `stale=true`; UI afișează „COPIE ISTORICĂ”. Accesibilitatea anterioară nu înseamnă verificare tehnică. O copie istorică nu poate obține `confirmed`. Nu există fallback automat dacă serviciul de căutare nu funcționează, deoarece nu există URL-uri curente validate pentru cererea respectivă.

## Evaluare

`tests/test_research_quality.py` conține cazuri sintetice etichetate explicit: pagini blocate, coduri cu sufix diferit, unități incompatibile, identitate incompletă, contradicții, copii duplicate, redirecționări și cache istoric. Aceste teste nu sunt un benchmark pe fișele reale ale clientului. La instalare trebuie pregătit local un set verificat manual din documentele sale; măsurați separat rata de acces, potrivirea identității, exactitatea valorilor/unităților și cazurile în care sistemul confirmă greșit.

## Evaluarea camofox-browser

Am analizat [jo-inc/camofox-browser](https://github.com/jo-inc/camofox-browser), în special README, Dockerfile și server.js. Este un server Node bazat tot pe Camoufox, cu API REST pentru sesiuni, extragere și autentificare interactivă. Poate fi evaluat pentru conturi autorizate când acestea există, dar nu validează specificațiile produselor. Nu a fost introdus ca dependență: înlocuirea serviciului actual necesită integrarea explicită a Egress Guard, proxy-ului cu validare DNS, politicilor de sesiune și verificarea opțiunilor de raportare externă. Analiza documentației nu reprezintă un audit complet sau un test de acces la furnizori.
