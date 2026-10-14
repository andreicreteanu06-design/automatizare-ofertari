# Integrări locale pentru documentație tehnică

Sunt folosite bibliotecile publice prin API-urile lor; nu sunt copiate proiecte întregi în repository și nu sunt adăugate servicii cloud.

## Pint: conversii și comparații fizice

[Pint](https://github.com/hgrecco/pint) normalizează valorile scalare recunoscute folosind `Decimal`. Exemple: `0,5 MPa = 5 bar`, `12000 g = 12 kg`, `20 °C = 293.15 K`. Se verifică dimensiunea fizică și se păstrează simbolurile SI cu distincția dintre majuscule/minuscule. Textul citat nu se schimbă; `technical_claims[].normalized_quantity` prezintă separat valoarea normalizată și unitatea.

Comparatorul de contradicții nu mai semnalează ca diferite aceste reprezentări echivalente. Sunt acceptate doar unitățile enumerate în `backend/app/rag/quantities.py`. Intervalele, toleranțele, separatoarele de mii și unitățile necunoscute nu sunt deduse. Nu se convertesc valute prin Pint. Conversia corectă nu confirmă produsul, condițiile sau actualitatea sursei.

## FlagEmbedding: reranking opțional

[FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) era deja folosit pentru BGE-M3. Integrarea nouă folosește `FlagReranker` cu `BAAI/bge-reranker-v2-m3`: căutarea hibridă recuperează până la 30 de fragmente, reranker-ul le reordonează față de întrebare, apoi păstrează primele `k`. Rândurile exacte din facturi nu sunt reordonate sau modificate. Reranking-ul nu este verificare de adevăr.

Modelul rulează pe CPU, cu batch 1, maximum 512 tokeni per pereche și acces serializat. Pentru scor se folosește cel mult începutul de 6.000 caractere al fragmentului; fragmentul original rămâne intact. Informația relevantă aflată mai târziu într-un tabel poate fi ratată la scorare; acest compromis trebuie evaluat pe documentele clientului.

Activarea este explicită pentru a nu încărca un al doilea model în limita implicită de 3 GB a backend-ului:

```bash
docker compose --profile setup run --rm --build reranker-fetch
```

După descărcare, setează local `RERANK_ENABLED=true` în `.env`. Ajustează `BACKEND_MEMORY_LIMIT` numai după verificarea RAM-ului disponibil pentru întregul stack; de exemplu `6g` este o valoare de pornire pentru testare, nu o cerință măsurată sau o garanție că sistemul încape în 16 GB.

```bash
docker compose --profile ui --profile mail up -d --build
```

Modelul este montat read-only din `data/reranker`, exclus din Git. Calea trebuie să fie absolută în container. Backend-ul rămâne pe rețeaua internă, cu `HF_HUB_OFFLINE=1`; nu descarcă modele la cereri. Lipsa modelului, scorurile invalide sau o eroare recuperabilă păstrează ordinea RRF și setează `rerank_status=fallback`, afișat în UI. Un proces omorât de limita RAM nu poate executa acest fallback.

`rerank_status` poate fi `disabled`, `empty`, `applied`, `fallback`; descrie ultima recuperare a răspunsului. Scorurile sunt numai semnale de relevanță, nu probabilități că valoarea este adevărată.

## Docling: proveniență structurală

[Docling](https://github.com/docling-project/docling) furnizează acum și metadatele păstrate în Qdrant: referința elementului, pagina, dreptunghiul original cu originea coordonatelor și celulele tabelului cu pozițiile rândurilor/coloanelor. La unirea tabelelor peste pagini, proveniența fiecărui element se păstrează separat.

Dovezile returnate includ `provenance`, cu pozițiile elementelor și celulele asociate rândului în care apare codul. Nu se inventează coordonate pentru celule care nu au fost localizate de extractor. UI permite inspectarea coordonatelor; nu include încă un viewer PDF cu evidențiere grafică. Poziția elementului nu reprezintă întotdeauna dreptunghiul exact al citatului.

Documentele indexate anterior trebuie reingerate pentru aceste metadate. Modelul de date rămâne compatibil cu documentele vechi, care nu au `provenance`. OCR-ul, antetele complexe, notele și desenele tehnice necesită în continuare evaluare; această modificare nu introduce un model vizual.

## Validare și limite

Testele rulează Pint real, DoclingDocument real construit din fixture-uri și Qdrant local. Scorurile reranker-ului sunt simulate în teste: modelul complet și consumul său de RAM nu au fost validate în Docker. Nu s-au introdus LangGraph, Qwen3-VL sau Ragas; selecția de față acoperă conversiile, reordonarea și trasabilitatea, fără migrarea orchestrării existente.

Sursele API consultate: [FlagReranker](https://github.com/FlagOpen/FlagEmbedding/tree/master/examples/inference/reranker), [temperaturi Pint](https://pint.readthedocs.io/en/stable/user/nonmult.html), [modelul documentelor Docling](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/document.py).
