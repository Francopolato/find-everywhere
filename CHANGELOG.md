# Changelog

Modifiche rilevanti a **find-everywhere**, dalla più recente. Le versioni
corrispondono ai tag git (`vX.Y`); le note complete di ogni release sono nella
pagina [Releases](https://github.com/Francopolato/find-everywhere/releases).

## v1.44 — frecce invertite di default

- `path_scroll_invert` ora è **`true` di default**: `→` riporta verso l'inizio del
  percorso e `←` avanza verso la fine (era l'impostazione che funzionava come
  voluto); deselezionando la casella in Impostazioni → *Aspetto* si torna al verso
  "classico".

## v1.43 — inversione opzionale delle frecce per il percorso

- nuova casella in Impostazioni → *Aspetto*: **«Inverti le frecce per scorrere il
  percorso «←/→»»** (`path_scroll_invert`, default `false`);
- serve se il verso di scorrimento non è quello atteso: con l'opzione attiva `→`
  torna verso l'inizio e `←` avanza verso la fine (prima: `→` = verso la fine,
  `←` = verso l'inizio, verificato con pressioni di tasto reali);
- la preferenza è salvata in `config.json` e non richiede riavvio.

## v1.42 — colonna percorso allineata a sinistra (direzione di scorrimento chiara)

- la colonna del percorso non è più allineata a **destra**: ora parte da sinistra e
  occupa lo spazio residuo della riga. Prima l'ancora era il bordo destro, quindi lo
  scorrimento sembrava avvenire nella **direzione sbagliata** (il testo “si
  spostava” invece di scorrere);
- con l'allineamento a sinistra il movimento è quello naturale: `→` fa avanzare il
  percorso (i caratteri escono a sinistra ed entrano a destra, `←` torna indietro);
- larghezza della colonna calcolata per riga in pixel, con margine di sicurezza,
  così il testo non viene mai tagliato da Tk.

## v1.41 — larghezza del percorso calcolata per riga

- la colonna del percorso ora viene dimensionata **in base alla lunghezza del nome**
  di quella riga (misurata in pixel, non con una costante): il nome può occupare
  fino a 52 caratteri, quindi lo spazio residuo cambia molto da riga a riga;
- prima il testo scorrevole poteva essere più lungo dello spazio reale e Tk lo
  tagliava dal lato sbagliato: lo scorrimento sembrava bloccato e non arrivava mai
  agli estremi. Ora il testo sta sempre nella colonna, e a fine corsa si vede
  l'ultima cartella, a inizio corsa la prima lettera del percorso.

## v1.40 — scorrimento del percorso: estremi raggiungibili

- la finestra di testo è ora **esatta**: a inizio corsa si vede il **primo**
  carattere del percorso, a fine corsa si arriva all'**ultimo** (prima i `…`
  mangiavano 1-2 caratteri, quindi gli estremi non si raggiungevano mai);
- nei tre casi (inizio / mezzo / fine) il testo occupa sempre la stessa larghezza,
  quindi la colonna non “salta” mentre scorri.

## v1.39 — scorrimento del percorso: limite corretto

- il fondo corsa ora coincide con la **larghezza visibile** della colonna
  (`len - larghezza`) e non con `len - 10`: premendo `→` a fine corsa non si
  accumulano più offset "oltre la fine", quindi **la prima `←` fa subito tornare
  indietro** il testo (prima bisognava smaltire le pressioni in eccesso);
- se il percorso sta tutto nella colonna, `←`/`→` non fanno nulla e non
  accumulano posizione.

## v1.38 — scorrimento del percorso per riga, senza interferenze

- la posizione dello scorrimento (`←`/`→`) è ora memorizzata **per riga**: tornando
  su un elemento ritrovi il percorso dov'era invece di ripartire sempre da zero;
- **l'hover del mouse non ruba più la selezione**: il passaggio del puntatore è
  gestito con `<Motion>` (movimento reale) e non con `<Enter>`, che Tk invia anche
  ai widget appena ricreati sotto il cursore. Era questo a cambiare riga durante lo
  scorrimento, facendolo sembrare “fermo prima” o “tutto a destra all'improvviso”.

## v1.37 — scorrere il percorso con ← e →

- dopo aver navigato i risultati con `↑`/`↓`, le frecce **`←`/`→`** fanno scorrere
  orizzontalmente il percorso della riga selezionata (passo di 8 caratteri, con
  `…` ai bordi): si legge tutto il path senza mouse;
- appena si scrive nel campo di ricerca, le frecce tornano a spostare il cursore di
  testo (nessun conflitto con la modifica della query);
- cambiando riga o ricerca lo scorrimento riparte dall'inizio del percorso.

## v1.36 — i file cancellati spariscono subito dai risultati

- **alla ricerca successiva** i risultati dell'indice locale che non esistono più
  su un'unità locale vengono scartati subito (prima restavano finché non passava
  una pulizia dell'indice);
- quando una scansione completa **ripulisce un percorso**, la lista a schermo viene
  aggiornata in quel momento: le voci sparite vengono tolte e lo stato dice
  «N voci rimosse (file spostati o cancellati)»;
- la verifica di esistenza viene fatta solo su unità locali (fissa/rimovibile),
  quindi nessun rallentamento sugli share di rete, dove vale la pulizia a fine
  scansione.

## v1.35 — tema chiaro opzionale

- nuovo blocco in Impostazioni → **Aspetto**: **Scuro** (default) oppure **Chiaro**
  in stile PowerToys Run (sfondo `#F3F3F3`, campi bianchi, testo scuro, accento
  `#0067C0` — non bianco puro);
- la scelta si applica **subito** (la finestra viene ridisegnata) e viene salvata
  in `config.json` (`theme`), quindi resta anche dopo il riavvio;
- anche i quattro colori dei risultati hanno una variante chiara, cosí restano
  leggibili (blu `#0067C0`, grigio `#6E6E6E`, ambra `#9A6700`, viola `#6B3FA0`).

## v1.34 — tooltip con il percorso completo

- tenendo il mouse fermo sul nome o sul percorso di un risultato (≈600 ms) compare
  un **tooltip** con il percorso intero (e per i `.lnk` anche la destinazione
  `→ ...`): nomi e percorsi restano troncati nella lista ma sono leggibili per
  intero al volo;
- il tooltip si chiude spostando il mouse, chiudendo la finestra o ridisegnando la
  lista (nessun tooltip “orfano”); resta dentro l'area di lavoro del monitor.

## v1.33 — controllo aggiornamenti consapevole dei tag

- il controllo legge anche l'elenco dei **tag**: se esiste un tag più recente
  dell'ultima release (tag creato ma release non pubblicata) lo scrive nel
  messaggio — es. «Ultima release: v1.30 · esiste il tag v1.32 (non pubblicato):
  «Aggiorna» fa git pull». Prima sembrava un controllo rotto perché veniva
  mostrata solo la release;
- da **eseguibile**, in quel caso il pulsante `Aggiorna` resta disattivato e il
  messaggio spiega che non c'è ancora uno zip da scaricare.

## v1.32 — classificazione dei collegamenti: il filesystem ha la precedenza

- un solo `stat` sul target: se **esiste** è il filesystem a dire se è cartella o
  file (quindi un file **senza estensione** non viene più scambiato per cartella);
- l'euristica "niente estensione = cartella" si applica **solo** quando il target
  è irraggiungibile (share offline, unità scollegata, percorso inesistente);
- corretta l'asimmetria precedente, che su `OSError` tornava "file" senza
  provare l'euristica.

## v1.31 — percorso spento ovunque e collegamenti a cartelle più affidabili

- con **«Cerca anche nel percorso» spento** anche l'**indice locale** non fa più
  il fallback sul nome della cartella contenitrice: si vedevano sottocartelle
  della cartella cercata, comportamento da ricerca per percorso;
- un `.lnk` verso una cartella **non raggiungibile** (share di rete offline) ora
  viene riconosciuto come cartella: se il target non esiste e l'ultimo elemento
  del percorso non ha estensione, viene trattato come cartella. Prima finiva
  sempre in `Solo file`.

## v1.30 — esclusioni applicate anche ai risultati di Windows Search

- le esclusioni ora filtrano i risultati di **tutte le fonti**, compreso l'indice
  di Windows: una cartella esclusa sparisce dai risultati dell'app senza toccare
  l'indice di Windows;
- una voce può essere un **nome di cartella** (`Temp`, vale per ogni cartella con
  quel nome) oppure un **percorso** (`C:\Temp\lavoro`, `\\server\share\x`: la
  cartella e le sottocartelle); virgolette attorno alla voce sono ammesse.

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
  - **già coperta dall'indice** → errore: va prima disattivata la ricerca
    nell'indice (eviterebbe risultati duplicati);
  - **esclusa / non indicizzata** → avviso con conferma (colore viola);
  - **di rete** → aggiunta diretta (colore ambra);
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
