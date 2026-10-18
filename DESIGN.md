# Interfața spațiului de lucru

Mod: operare. Prioritatea este completarea ofertelor și citirea dovezilor, inclusiv
de către utilizatori cu mai puțină experiență digitală. Landingul și fundalul local
existent sunt păstrate. Referința utilizatorului stabilește chatul violet închis,
lumina diagonală, titlul centrat și compozitorul rotunjit.

## Materiale și relief

`frontend/src/depth.css` definește relieful: panouri alb–gri (`#ffffff`, `#f8fafc`,
`#eaf0f7`), muchie interioară luminoasă și umbre cu offset. Titlurile folosesc
`#203651`, tracking `-.025em` și umbră discretă. Textul de corp, etichetele,
valorile tehnice și tabelele rămân fără relief tipografic.

Chatul folosește suprafețele `#100c1d`, `#191426`, `#282035`; text principal
`#f9f7ff`, secundar `#cec4df`. Accentul compozitorului este `#ded5f5`, cu text
`#241835`. Lumina diagonală este CSS local, decorativă și fără evenimente pointer.
Nu sunt necesare imagini externe, CDN-uri sau WebGL pentru acest efect.

## Tipografie, spațiere și comportament

Geist este găzduit local. Titlul chatului variază între 32 și 58 px, cu interlinie
1.14 și tracking `-.035em`. La conversație activă devine compact (24 px).
Spațiul interior al scenei este 36 px desktop / 16 px mobil; compozitorul are
raza 25 px / 20 px. Bulele de sugestii nu trimit automat o întrebare.

Butoanele au feedback de apăsare și tranziție de 180 ms cu
`cubic-bezier(.22,1,.36,1)`. `prefers-reduced-motion` dezactivează aceste deplasări.
Focusul vizibil folosește contur de 3 px `#649fdd`, offset 3 px.
Istoricul, citările și controalele reale rămân funcționale.

Revizuirea vizuală a acoperit chatul inițial/activ, mobil, documente și oferte.
Centrarea titlului desktop a fost corectată și verificată. Documentația a fost
finalizată manual; utilitarul Impeccable nu a rulat și sidecar-ul nu a fost validat
împotriva unei scheme externe.


## Chat în stil notebook

`notebook.css` adaugă un panou Surse alimentat din `/sources`, conversația centrală
și un panou Surse și pasaje legat de răspunsuri. Peste 1650 px sunt trei coloane;
sub acest prag pasajele trec dedesubt, iar sub 1050 px toate zonele sunt stivuite.
Panoul de surse este informativ: nu filtrează căutarea pe un subset bifat.
Citările deschid pasajele răspunsului din care provin, inclusiv pentru mesaje vechi.

Inspirație de organizare: [Open Notebook](https://github.com/lfnovo/open-notebook),
proiect sub licență MIT, cu surse și conversații contextualizate. Nu a fost copiat
cod și nu a fost adăugat un al doilea stack de baze de date/LLM. Backend-ul RAG,
verificarea citărilor și Egress Guard rămân cele ale proiectului. Căutarea Live este
opțională, oprită inițial; numai întrebarea curentă merge spre gateway, nu folderele.
