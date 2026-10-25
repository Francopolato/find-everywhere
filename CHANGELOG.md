# Changelog

Modifiche rilevanti a **find-everywhere**, dalla più recente. Le versioni
corrispondono ai tag git (`vX.Y`); le note complete di ogni release sono nella
pagina [Releases](https://github.com/Francopolato/find-everywhere/releases).

## v1.29 — limite risultati e tipo dei collegamenti

- in Impostazioni: **«Risultati massimi nella ricerca»**, `0` = **illimitati**
  (default 120);
- i collegamenti `.lnk` che puntano a una **cartella** ora sono trattati come
  cartelle (compaiono in `Solo cartelle` e `Tutti`), quelli che puntano a un file
  come file (`Solo file` e `Tutti`).

## v1.28 — aggiornamento periodico opzionale dell'indice

- nuovo campo in Impostazioni (Cartelle personalizzate): **«Aggiorna l'indice in
  background ogni N minuti»**, `0` = mai (default), **minimo 5** minuti;
- parte solo se l'app è inattiva da almeno 20 s e non c'è una ricerca/scansione in
  corso; fa un giro completo (con pulizia dei file spostati/cancellati) e lo
  registra nel log.

## v1.27 — spostamenti e cancellazioni aggiornati a ogni ricerca

- alla fine di una **scansione completa** durante una ricerca, l'indice viene
  ripulito: i file spostati o cancellati spariscono, i nuovi entrano (prima la
  pulizia avveniva solo all'avvio o con *Ricostruisci indice*);
- la pulizia viene **saltata** se la scansione è stata interrotta o se qualche
  cartella è risultata illeggibile (evita cancellazioni per errori temporanei di
  rete), e viene registrata nel log.

## v1.26 — «Apri in Explorer»

- voce del menu contestuale e legenda rinominate: **«Apri in Explorer»** invece di
  «Apri cartella contenitrice» (stessa funzione: apre la cartella con l'elemento
  selezionato).

## v1.25 — Impostazioni sullo schermo dello Spotlight

- la finestra delle impostazioni si apre **sullo stesso monitor** in cui si trova
  lo Spotlight (centrata nell'area di lavoro), non più sullo schermo primario.

## v1.24 — «resta in secondo piano» per singolo script

- l'opzione non è più globale: **ogni script** ha la sua casella *«Lanciando
  questo script la finestra resta aperta in secondo piano»*;
- nell'elenco gli script con l'opzione attiva sono marcati con **`· dietro`**;
- l'impostazione globale `script_keep_open` (durata una sola versione) è stata
  rimossa: vale solo il flag `keep_open` del singolo script.

## v1.23 — script in secondo piano e selezione ricordata

- nuovo toggle **«Lanciando uno script la finestra resta aperta in secondo
  piano»**: con l'opzione attiva la finestra non si nasconde, va dietro alle
  altre finestre (e il "nascondi alla perdita di focus" non la chiude);
- riaprendo lo Spotlight, oltre all'ultima ricerca torna selezionato **l'ultimo
  elemento** scelto prima della chiusura;
- la selezione non viene più azzerata quando il filtro corrente non ha risultati.

## v1.22 — default: solo ricerca per nome

- `win_content_search` e `win_path_search` **disattivati di default**: una
  installazione nuova cerca solo il **nome** di file e cartelle.

## v1.21 — recall e multi-monitor

- ricerca a metà parola: all'indice si chiedono 5× le righe (minimo 300) invece
  del solo limite → `*menti` ora trova la cartella `investimenti` (prima veniva
  tagliata a 40 risultati);
- la finestra si apre sullo **schermo attivo** (quello del cursore) e ricorda una
  **posizione distinta per ogni monitor** (`window_pos_by_monitor`), ricentrando
  se il layout cambia; usa l'area di lavoro (niente taskbar).

## v1.20 — testo solo con il toggle attivo

- con la ricerca nel testo spenta non compare **nessuna** corrispondenza nel
  contenuto, nemmeno per risultati in coda o già mostrati.

## v1.19 — ricerca nel percorso opzionale

- nuovo toggle `win_path_search`: **spento** si guarda solo l'ultimo elemento del
  percorso (nome del file o della cartella), niente ricerca nelle cartelle
  contenitrici;
- le opzioni (`content_search`, `path_search`) vivono sull'istanza
  `WindowsSearch`, impostate all'avvio e dopo *Salva*.

## v1.18 — filtro «Solo testo»

- toggle della ricerca nel testo in Impostazioni (prima solo nel config);
- `Ctrl+T`: `Tutti → Solo file → Solo cartelle → Solo testo`, dove «Solo testo»
  esiste **solo** con il toggle attivo; «Solo file» mostra solo i nomi ed esclude
  i match trovati nel testo;
- spegnendo il toggle, il filtro torna su `Tutti`.

## v1.17 — colori definitivi

- eliminato il verde «indice locale generico»: le voci rimaste nell'indice di una
  cartella poi rimossa sono **grigie**;
- legenda aggiornata nelle impostazioni.

## v1.16 — cartelle personalizzate con controllo dell'indice

- sezione rinominata **Cartelle personalizzate** (non più «cartelle di rete»);
- aggiungendo una cartella, con l'indice di Windows attivo:
  * **già coperta dall'indice** → errore: va prima disattivata la ricerca
    nell'indice (eviterebbe risultati duplicati);
  * **esclusa / non indicizzata** → avviso con conferma (colore viola);
  * **di rete** → aggiunta diretta (colore ambra);
- il controllo usa le regole reali di indicizzazione (`CrawlScopeManager` nel
  registro), non query su SYSTEMINDEX che userebbero percorsi localizzati;
- legenda dei colori nelle impostazioni.

## v1.15 — icone, collegamenti, aggiornamenti

- **icona = tipo** (📁 cartella, 📄 file), **colore = provenienza**; collegamenti
  `.lnk` con icona doppia `📁↗` / `📄↗` e destinazione `→ C:\...`, più toggle
  *Mostra anche i collegamenti* (attivo di default);
- corretti il taglio e il collasso dell'icona doppia (contenitore in pixel,
  allineato a sinistra, altezza esplicita);
- Impostazioni → **Aggiornamenti**: `Controlla` confronta con l'ultima release
  GitHub; `Aggiorna` esegue `git pull` se sei da sorgente oppure scarica e
  sostituisce l'exe (con `*.old` e rollback); `Riavvia` rilancia l'app.

## Versioni precedenti (già pubblicate)

- **v1.14** — script nel menu contestuale (nome + hotkey, sottomenu se > 3)
- **v1.13** — esclusioni gestibili dalla GUI (aggiungi / modifica / rimuovi)
- **v1.12** — esempi corretti (`scaffalatur`), stati di ricerca (niente lista vecchia)
- **v1.10** — jolly `*`, Windows Search su `CONTAINS` (~0,1 s invece di 12 s)
- **v1.9** — cartelle nei risultati, estensioni sempre visibili, filtro file/cartelle
- **v1.7** — prima release: indice locale SQLite + Windows Search + cartelle di rete
