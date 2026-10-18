# Editor PDF local

Secțiunea Editor PDF integrează pachetul web oficial PDFCraft **0.8.0**, nemodificat,
din https://github.com/storytold/pdfcraft/releases/tag/v0.8.0.
SHA-256 arhivă: `1f9ea51f3c1f71cc719c12814e10f236912fa41ef54a7782c7dd4a619d9eee9a`.
Fișierele JS/WASM sunt incluse local în frontend/public/pdfcraft, împreună cu
licențele MIT/Apache și NOTICE. Nu există descărcări externe la pornirea editorului.

## Utilizare

1. Editor PDF → Deschide editorul PDF → Open.
2. Selectează documentul local. All tools oferă organizarea paginilor, combinare,
   note și formulare. Instrumentele disponibile sunt cele din versiunea PDFCraft.
3. Save / Export descarcă rezultatul. Originalul de pe disc nu este suprascris automat.
4. Pentru indexarea în chat, pune copia salvată în folderul monitorizat.

Modificarea textului existent este încă în dezvoltare upstream și poate fi
indisponibilă sau inexactă pentru anumite PDF-uri/fonturi/limbi. Textul scanat nu
devine automat text editabil. Integrarea nu promite OCR sau editare echivalentă Word.
Verificarea cu documentele tehnice ale clientului rămâne necesară.

## Izolare și comportament

Iframe-ul permite scripturi și descărcări, dar nu same-origin, popup-uri sau
navigarea paginii principale. Are origine opacă, fără acces la DOM-ul aplicației,
cookie-urile sau stocarea sa. Preferințele PDFCraft nu sunt persistate în această
configurație. Schimbarea tabului intern păstrează iframe-ul; reîncărcarea paginii
pierde sesiunea. Aplicația avertizează la închidere cât timp editorul este deschis,
chiar dacă documentul a fost deja salvat, deoarece nu inspectează starea internă.

Nginx și Vite aplică separat CSP pentru /pdfcraft/: WebAssembly și scriptul de
inițializare cu hash fix sunt permise doar acolo. CORS anonim este permis numai
pentru aceste resurse publice, necesar originii opace; nu pentru /api. Accesul extern
este blocat de CSP. Linkurile externe din aplicația upstream nu deschid ferestre.
Modul CPU evită dependența de WebGPU, dar poate fi lent la documente mari. Butonul
Ecran complet este recomandat pe ecrane mici. Documentele nu sunt trimise backend-ului.

Test automat: pornește WASM cu CSP/sandbox, deschide un PDF sintetic și verifică
descărcarea PDF prin Save. Acesta nu validează fidelitatea tuturor operațiilor
upstream. Containerele necesită reconstruire pentru publicarea noilor fișiere.

La actualizare: verificați checksum-ul release-ului, licențele, hash-ul scriptului
inline în Vite/Nginx și reluați testele. Nu înlocuiți fișierele cu o versiune latest
nefixată. Nu eliminați avertismentul privind editarea textului fără validare.
