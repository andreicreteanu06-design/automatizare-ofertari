# Indexare locală și verificarea RAG

Aplicația are RAG hibrid: căutare exactă în facturi (Postgres), căutare densă și
sparse în Qdrant cu BGE-M3, apoi selecția pasajelor de către modelul local. Valorile
din răspuns sunt copiate din pasaje, nu din notele utilizatorului. Indexarea unui
PDF nu certifică exactitatea OCR sau relevanța selecției.

## Instalare existentă pe Windows / Ubuntu

În Ubuntu, cu Docker Desktop pornit, în directorul proiectului:

```bash
docker compose --profile ui up -d --build backend source-watch frontend
docker compose exec -T source-watch python -m app.ingest.diagnostics --retry
```

Prima comandă reconstruiește imaginea cu Tesseract, datele română/engleză și
bibliotecile native pentru OCR. Docling folosește explicit OCR local pe CPU și
TableFormer ACCURATE, fără descărcarea automată a unui alt motor OCR din worker.

A doua verifică importurile Docling/FlagEmbedding/Qdrant, OCR-ul, fișierele de
modele și conectivitatea la Qdrant, fără valori secrete. Dacă toate verificările
trec, repune numai documentele cu erori în așteptare. Documentele eliminate și
cele aflate deja în procesare nu sunt reactivate. Prezența unor fișiere de modele
nu garantează compatibilitatea lor: conversia reală este testul final. Așteaptă
„Disponibil în chat”; „Încărcat” nu este suficient.

În Documentele mele există și „Reîncearcă indexarea”, după remedierea cauzei
afișate pentru fiecare fișier. Nu este necesară încărcarea unui duplicat.

```bash
docker compose logs --tail=60 source-watch
docker compose ps
```

Workerul raportează coduri precum `missing_model`, `missing_dependency`,
`ocr_runtime`, `memory`, `timeout` sau `conversion`. Mesajele afișează acțiunea
necesară, fără textul documentelor sau traceback-ul brut. `memory` poate însemna
și oprire forțată; verifică OOM înainte de concluzii. Controlul nu certifică OCR.

## Modele locale lipsă

Serviciile de procesare au `HF_HUB_OFFLINE=1`. Descărcarea se face separat prin
`model-fetch`, care nu primește documentele clientului:

```bash
docker compose --profile setup run --rm model-fetch python -c "from huggingface_hub import snapshot_download; import subprocess; snapshot_download('BAAI/bge-m3', ignore_patterns=['onnx/*']); subprocess.run(['docling-tools', 'models', 'download', '-o', '/models/docling'], check=True)"
docker compose exec -T source-watch python -m app.ingest.diagnostics --retry
```

Pot fi descărcați mai mulți GB. Dacă apare o eroare DNS, repară rețeaua Docker,
apoi reia descărcarea, fără ștergerea cache-ului. O descărcare oprită înainte de
final nu dovedește că modelele sunt pregătite.

BGE-M3 se verifică și se încarcă din fișierele locale necesare inferenței, inclusiv
capetele ColBERT și sparse ale modelului. Exporturile ONNX omise la descărcare nu sunt
necesare. Versiunile noi `huggingface_hub` pot raporta `IncompleteSnapshotError`
la o verificare a întregului repo, chiar dacă numai acele exporturi lipsesc.
De aceea verificarea și încărcarea folosesc același director local validat.

## Eliminare din index

DELETE pentru fișier/folder înscrie imediat excluderea din căutări. Workerul șterge
toți vectorii acelui `doc_id` din Qdrant cu `wait=True`, apoi copia de upload.
Dacă Qdrant nu răspunde, păstrează sarcina pentru reîncercare. UI arată când
curățarea este în curs. Originalele locale/Drive se păstrează; excluderile persistente
împiedică reindexarea accidentală. Pasajele sunt reverificate înainte de răspuns,
inclusiv când documentul a fost eliminat în timpul generării.

Testele folosesc Qdrant local real și verifică numărul de puncte înainte și după
ștergere, cu păstrarea documentelor vecine; embedderul din teste este determinist.
Istoricul conversațiilor și backup-urile nu reprezintă indexul activ și nu sunt
șterse de eliminarea documentului din bibliotecă.

## Corecțiile chatului

Folosește „Corectează răspunsul”, descrie greșeala și bifează pasajele greșite.
Corecția se păstrează în Postgres pentru același proprietar/spațiu de browser și
proiect, inclusiv în conversații noi. Nu este partajată automat altor conturi sau
calculatoare care folosesc alt cookie și nu reantrenează modelul.

La întrebări identice sau despre același cod/proprietate, pasajele marcate greșite
sunt excluse determinist; observația este oferită separat pentru reverificare.
Reîncărcarea aceluiași pasaj sub alt ID nu ocolește excluderea. Alte proprietăți
și proiecte nu sunt blocate. Dacă lipsesc dovezi alternative, chatul raportează
dovezi insuficiente; nu tratează valoarea propusă ca fapt verificat. Formulările
foarte diferite și produsele fără cod pot necesita o nouă corecție explicită.

Test: salvează o corecție, apoi repetă întrebarea într-o conversație nouă din
același proiect. Pasajul respins nu trebuie să reapară drept răspuns. Notele
„Reține / adaugă notă de revizuire” rămân referințe separate, fără excluderi.

Referințe: [Docling offline](https://docling-project.github.io/docling/usage/advanced_options/),
[opțiuni OCR](https://docling-project.github.io/docling/reference/pipeline_options/).
