# find-everywhere (SpotlightPy)

Launcher stile *Spotlight / PowerToys Run* per Windows, in Python (solo stdlib,
più pywin32 per l'indice di Windows). Nasce per cercare file che stanno in
**cartelle di rete non indicizzabili** da Windows Search.

```text
Ctrl+Alt+Spazio  ->  apre la finestra (chiudi con Esc). Configurabile o disabilitabile:
                    impostazioni -> hotkey principale -> "Nessuna" (campo vuoto).
```

## Come funziona la ricerca

Ogni ricerca unisce tre fonti, in ordine di velocità:

| fonte | cosa fa | quando arriva |
|---|---|---|
| **Indice locale (SQLite)** | risultati già scansionati in precedenza | immediato (istantaneo) |
| **Windows Search** (SYSTEMINDEX) | file **e cartelle** indicizzati da Windows: con un termine ricerca a metà parola, con più termini prefissi di parola, più il percorso contenitore e il contenuto dei documenti | ~0,1–0,4 s (thread separato) |
| **Scansione viva** | `os.scandir` ricorsivo sulle cartelle configurate (es. share di rete) | in streaming, con la rotellina |

Quindi: la finestra mostra subito quello che sa, poi si riempie man mano che
arrivano gli altri risultati. La scansione viva **non** è `Path.rglob` (lento):
usa `os.scandir`, salta le cartelle in `excludes`, non segue junction/symlink,
e **scrive nell'indice** tutto quello che incontra → la seconda volta è
istantanea.

L'indice viene anche ricostruito all'avvio (dopo un walk completo le voci di
file cancellati vengono rimosse). Lo stesso "riordino" avviene **alla fine di una
scansione completa durante una ricerca**: i file spostati o cancellati spariscono
dall'indice, i nuovi entrano. Se la scansione viene interrotta (nuova ricerca
mentre girava) o se qualche cartella risulta illeggibile, la pulizia viene
saltata per quel percorso, così non si cancellano voci valide per un errore
temporaneo di rete.

Dalle impostazioni si può attivare anche un **aggiornamento periodico opzionale**
dell'indice (*Aggiorna l'indice in background ogni N minuti*: `0` = mai, minimo 5),
che parte solo con l'app inattiva da 20 secondi.

## Risultati

**L'icona dice il tipo, il colore dice da dove arriva** (niente pallini generici):

| icona | significato |
|---|---|
| 📁 | cartella |
| 📄 | file |
| 📁↗ / 📄↗ | **collegamento** (`.lnk`) che punta a una cartella / a un file; a destra si vede la destinazione (`→ C:\...`) |

| colore dell'icona | fonte |
| --- | --- |
| blu | indice di Windows Search |
| ambra | cartella **personale di rete** (scansione dello share) |
| viola | cartella **esclusa dall'indice di Windows**, aggiunta a mano e confermata |
| grigio | voce rimasta nell'indice di una cartella poi rimossa (raro) |

La stessa legenda è ripetuta nelle **impostazioni**, sezione *Cartelle personalizzate*.

Aggiungendo una cartella personale, se «Cerca anche nell'indice di Windows» è attivo:

* se la cartella è **già coperta dall'indice di Windows** → messaggio di **errore**
  (darebbe risultati duplicati): per aggiungerla va prima disattivata la ricerca
  nell'indice di Windows;
* se la cartella è **esclusa dall'indice** (o fuori dagli scope) → **avviso con
  conferma**: viene cercata solo dalla scansione dell'app e colorata in viola;
* se è di **rete** → aggiunta senza domande, colore ambra.

La distinzione non si basa su una query all'indice (che usa nomi *localizzati*,
es. `C:\Utenti\...Documenti`), ma sulle regole reali di indicizzazione
(`CrawlScopeManager` nel registro): vince la regola più specifica, come fa Windows.

Sulla destra di ogni riga, dove serve: `rete · percorso` per i risultati della
scansione cartelle, `testo · percorso` quando la corrispondenza è nel **contenuto**
del documento.

Altro:

* **estensione sempre visibile**: se il nome non la contiene viene aggiunta dal
  percorso (`.pdf`, `.xlsx`, …);
* **nomi lunghi**: troncati con `…` **prima dell'estensione**
  (`contratto quadro molto lungo … 2….pdf`), così il tipo di file resta leggibile;
* **filtro**: in alto a destra il pulsante `Tutti` / `Solo file` / `Solo cartelle`
  (anche `Ctrl+T`); la scelta è **persistente**, anche dopo il riavvio. Significato:
  * `Tutti` — file e cartelle, per nome; in più le corrispondenze nel **testo**
    se la ricerca nel contenuto è attiva;
  * `Solo file` — **solo il nome dei file** (esclude cartelle e match nel testo),
    indipendentemente dal toggle;
  * `Solo cartelle` — solo cartelle (mai ricerca nel testo);
  * `Solo testo` — solo corrispondenze dentro il contenuto dei documenti;
    compare solo se è attivo *Impostazioni → Cerca anche dentro il testo dei documenti*.

La ricerca nel contenuto (indice di Windows) si accende e si spegne nelle
impostazioni, sezione *Indice di Windows Search* (**disattivata di default**), insieme a
**«Cerca anche nel percorso»**: con il percorso attivo si trovano anche le
cartelle che *contengono* il file cercato; **spento** la ricerca guarda solo
l'ultimo elemento del percorso, cioè il nome del file o della cartella.
* **collegamenti**: inclusi nei risultati per default (`.lnk`),
  disattivabili da Impostazioni → *Mostra anche i collegamenti*.

I percorsi dei risultati di Windows Search vengono ricavati da `System.ItemUrl`:
`System.ItemPathDisplay` restituisce il percorso **localizzato**
(`C:\Utenti\Polat\Documenti\…`) che su disco non esiste, e faceva aprire a
Explorer una cartella sbagliata.

## Ricerca intelligente (jolly `*`)

`*` significa **uno o più caratteri qualsiasi**:

```text
scaffalatur*metall*ord*23440
```

trova i nomi che contengono `scaffalatur`, poi `metall`, poi `ord`, poi `23440`.
Un `*` in testa o in coda vale "qualsiasi cosa" (`*2024`, `contratto*`).
Senza `*` la ricerca resta quella di sempre.

Come viene applicato:

* **indice locale (SQLite)** e **scansione cartelle**: conversione in `LIKE`
  (`*` → `_%`, cioè almeno un carattere) oppure in regex, quindi sottostringa
  vera;
* **Windows Search**, in base a quanti termini ci sono:
  * **un solo termine** → `System.ItemNameDisplay LIKE '%term%'`: vera
    sottostringa, quindi `*tratt` e `tratt` trovano `contratto` (~0,3 s). Per
    non perdere risultati si chiedono più righe all'indice (5× il limite,
    minimo 300): con frammenti corti (es. `*menti`) i match sono tanti e il
    taglio a 40 nascondeva cartelle come `investimenti`;
  * **due o più termini** → `CONTAINS(System.FileName, '"steril*" AND "2022*"')`:
    prefissi di parola, tutti obbligatori ma **in qualunque ordine** (~0,1 s).
    Il motivo: `LIKE '%steril%2022%'` costa **12 s** perché non usa l'indice,
    mentre `CONTAINS` sì. Quindi con più termini la ricerca a metà parola non è
    possibile lì (ma lo è nell'indice locale e nella scansione delle cartelle).

## Tasti

| tasto | azione |
|---|---|
| `Invio` / click | apre l'elemento selezionato: file con l'app associata, **cartella** in Esplora file |
| `Ctrl+Shift+E` (solo a finestra aperta) | apre l'elemento **in Explorer** (la cartella che lo contiene, con l'elemento selezionato) |
| `Ctrl+Invio` | come sopra (alias) |
| `↑` / `↓`, rotellina | naviga i risultati |
| `Ctrl+T` (o click su `Tutti`) | filtro: Tutti → Solo file → Solo cartelle → **Solo testo** (quest'ultimo solo se la ricerca nel contenuto è attiva) |
| `Ctrl+,` o ⚙ | impostazioni |
| `Esc` | chiude la finestra |
| `Ctrl+Shift+Q` | **esce dal processo** (deregistra le hotkey) |
| hotkey custom | lancia lo script configurato sul percorso selezionato |

**Spostare la finestra**: trascina con il mouse da una zona "vuota" (barra del
titolo implicita, riga di stato, footer, area sotto i risultati). La posizione
viene salvata nel config e ripristinata al riavvio.

**Più schermi**: la finestra si apre sullo **schermo attivo** (quello dove sta il
cursore) e ricorda **una posizione distinta per ogni monitor**
(`window_pos_by_monitor`); se la posizione salvata non è più valida (layout
cambiato) viene ricentrata. L'area usata è quella di lavoro, quindi non finisce
sotto la barra delle applicazioni. Anche la finestra **Impostazioni** si apre
sullo stesso schermo dello Spotlight, centrata.

Note sull'hotkey principale: si sceglie liberamente nelle impostazioni
(clicca il campo e premi la combinazione) oppure si disabilita con "Nessuna":
con il campo vuoto **non viene registrata nessuna hotkey globale** e la finestra
si apre solo dal bat/exe (doppio clic). `Ctrl+Shift+E` è riservato all'azione
"apri in Explorer" e non è accettato come hotkey globale.

I risultati includono **sia file sia cartelle** (icona 📁 per le cartelle).

Click destro su un risultato: Apri / Apri in Explorer / Copia percorso / script.

## Script personalizzati

Nelle impostazioni puoi aggiungere **più script**, ognuno con la propria
combinazione di tasti (es. `ctrl+shift+1`). Il percorso dell'elemento
selezionato viene passato come argomento:

* se nel comando scrivi `{path}` (o `{file}`, o `%path%`) viene sostituito dal
  percorso tra virgolette;
* se non lo scrivi, il percorso viene aggiunto in coda al comando;
* le variabili d'ambiente (`%LOCALAPPDATA%`, `%USERPROFILE%`, `%ProgramFiles%`, …)
  vengono espanse dall'app, non serve passare da `cmd`.

Esempi:

```
python C:\scripts\carica.py {path}
"C:\Program Files\7-Zip\7zFM.exe" {path}
notepad {path}
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\scripts\carica.ps1" {path}
"%LOCALAPPDATA%\PowerToys\WinUI3Apps\PowerToys.Peek.UI.exe" {path}
```

L'esempio con **PowerToys Peek** è il modello d'uso più interessante: invece di
*aprire* il file, lo **mostra in anteprima** (PDF, Office, immagini, markdown,
archivi, testo) senza avviare l'applicazione associata. Cercare l'ordine o il
contratto, selezionarlo e premerne la hotkey diventa un modo rapido di
controllare il risultato giusto prima di aprirlo — e funziona anche sulle
cartelle. L'eseguibile di Peek accetta uno o più percorsi:

* per-utente: `%LOCALAPPDATA%\PowerToys\WinUI3Apps\PowerToys.Peek.UI.exe`
* machine-wide: `C:\Program Files\PowerToys\WinUI3Apps\PowerToys.Peek.UI.exe`

La stessa ricetta vale per qualunque strumento con interfaccia a riga di comando
che accetta un percorso (7-Zip, VS Code, ffmpeg, uno script PowerShell/Python
che carica il file su un gestionale, ecc.).

Per PowerShell: metti il percorso dello `.ps1` tra virgolette se contiene spazi,
`-ExecutionPolicy Bypass` evita l'errore "esecuzione di script disabilitata"
senza toccare le impostazioni di sistema, e **non** aggiungere virgolette a
`{path}` (le mette già l'app). Nello script usa `param([string]$Path)` oppure
`$args[0]`. Tutto ciò che segue `-File` viene passato allo script, quindi le
opzioni di PowerShell (`-NoProfile`, `-ExecutionPolicy`, …) vanno **prima**
di `-File`.

Argomenti aggiuntivi: puoi mettere altri argomenti **dopo** `{path}`, vengono
passati in coda allo script (es. `... -File "C:\s\carica.ps1" {path} --verbose`).
Con un parametro con nome (lo script deve dichiarare `param([string]$Path)`):

```
powershell -NoProfile -File "C:\scripts\carica.ps1" -Path {path}
```

Avvio del comando: viene eseguito **così com'è scritto** (CreateProcess, nessun
re-quoting). Solo se il primo token non è un eseguibile — script `.bat`/`.cmd`
o comandi interni di `cmd` — si passa a `cmd.exe /c`. Nel log trovi sempre la
command line esatta usata (`script 'Nome': …`).

Nelle impostazioni: **Nuovo** aggiunge una riga `+ nuovo (da compilare)`
nell'elenco, poi compili Nome / Comando / Hotkey e premi **Salva script**
(infine **Salva** per scrivere il config).

Ogni script ha la sua opzione **«Lanciando questo script la finestra resta aperta
in secondo piano»** (casella nel form dello script): attiva, la finestra non si
nasconde quando parte lo script, va dietro alle altre finestre e resta a portata
di mano; spenta, si chiude come sempre. Nell'elenco gli script con l'opzione
attiva sono marcati con **`· dietro`**.

Riaprendo lo Spotlight tornano sia l'ultima ricerca sia **l'ultimo elemento
selezionato**.

Gli script configurati compaiono anche nel **menu del tasto destro** su un
risultato, con il nome scelto e la hotkey accanto (`Apri con Peek  [CTRL+ALT+1]`);
se sono più di tre finiscono nel sottomenu `Script (N)`. Senza script il menu
mostra solo Apri / Apri cartella / Copia percorso (più una voce disabilitata che
lo segnala).

## Impostazioni / file

* config: `%APPDATA%\SpotlightPy\config.json`
* indice: `%APPDATA%\SpotlightPy\index.db`

Chiavi principali del config:

```json
{
  "hotkey": "ctrl+alt+space",
  "window_pos": null,
  "window_pos_by_monitor": {"\\\\.\\DISPLAY1": [120, 80]},
  "paths": ["\\\\server\\share\\cartella"],
  "scripts": [{"name": "Carica", "command": "python C:\\s\\carica.py {path}", "hotkey": "ctrl+shift+1", "keep_open": false}],
  "excludes": ["$RECYCLE.BIN", "System Volume Information", ".git", "node_modules", "__pycache__", ".venv", "venv"],
  "win_search": true,
  "win_search_limit": 40,
  "win_content_search": false,
  "win_path_search": false,
  "index_on_startup": true,
  "live_scan": true,
  "max_results": 120,
  "hide_on_focus_loss": true,
  "refresh_minutes": 0
}
```

Note:

* Se una hotkey non si registra (codice errore in basso), è già usata da un
  altro programma → cambiala nelle impostazioni.
* L'app è a istanza singola: se lanci di nuovo `run.bat` mentre è già attiva,
  **non apre un doppione**, chiede all'istanza esistente di mostrarsi.
* Se la finestra "sparisce": premi `Ctrl+Alt+Spazio` (o rilancia `run.bat`). Per
  chiudere davvero il processo: `Ctrl+Shift+Q` oppure Impostazioni → *Esci da
  SpotlightPy*.
* Diagnostica: `%APPDATA%\SpotlightPy\spotlightpy.log` (avvii, hotkey
  registrate, errori non gestiti). Se qualcosa non va, quel file dice perché.
* `node_modules`, `__pycache__`, `.git`, `.venv` sono esclusi di default per
  velocità: l'elenco si gestisce dalla GUI (Impostazioni → **Esclusioni**:
  Aggiungi / Modifica / Rimuovi, doppio clic per modificare una voce). Sono
  **nomi di cartella**, non percorsi, confrontati senza distinzione di
  maiuscole; dopo il salvataggio parte l'indicizzazione, così le nuove
esclusioni valgono anche per l'indice già esistente.
* L'indice cresce: per un indice pulito usa **Ricostruisci indice** nelle
  impostazioni.

## Avvio automatico (un solo bat, universale)

```bat
install-autostart.bat                :: auto: usa l'exe se c'e', altrimenti Python
install-autostart.bat exe            :: forza l'eseguibile
install-autostart.bat source         :: forza il sorgente (pythonw + app.py)
install-autostart.bat --dry-run      :: mostra cosa farebbe, senza scrivere nulla
install-autostart-source.bat         :: scorciatoia = "install-autostart.bat source"
uninstall-autostart.bat              :: rimuove il collegamento
```

Con `--startup` la finestra **non si apre mai** da sola all'accensione: si apre
con la hotkey globale oppure rilanciando l'app (doppio clic sul collegamento o
sul `.exe`/`.pyw`), che chiede all'istanza già attiva di mostrarsi.

Come sceglie:

* cerca l'exe in `FindEverywhere.exe` accanto al bat, `dist\FindEverywhere.exe`,
  `dist\SpotlightPy.exe`, `%LOCALAPPDATA%\find-everywhere\FindEverywhere.exe`;
  un file < 10 MB viene ignorato (quarantena/stub);
* se non trova un exe valido (o se forzi `source`) usa `pythonw.exe` +
  `app.py --startup`, saltando lo stub `WindowsApps\pythonw.exe`;
* in modalità exe, l'eseguibile viene **copiato** in
  `%LOCALAPPDATA%\find-everywhere\`, così ricompilare (`dist\` viene svuotata)
  non rompe l'avvio automatico;
* il collegamento (`find-everywhere.lnk` in `Esecuzione automatica`) ha
  l'argomento `--startup`: la finestra resta nascosta e si apre solo con la hotkey.

In ogni caso: solo utente corrente, nessun admin, nessuna modifica al registro,
registro intatto, tutto reversibile con `uninstall-autostart.bat`.

**Requisito**: la hotkey globale deve essere **attiva** (Impostazioni → Hotkey
principale → clicca il campo e premi la combinazione → Salva). Senza hotkey,
all'avvio la finestra viene mostrata (per non lasciarti senza modo di aprirla).

In alternativa al collegamento si può usare il registro
(`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valore
`find-everywhere` = `"...\FindEverywhere.exe" --startup`) o Utilità di
pianificazione con "All'accesso" + ritardo di 30 s, se vuoi che parta più tardi.

## Aggiornamenti

Impostazioni → sezione **Aggiornamenti**:

* **Controlla aggiornamenti** confronta la versione installata con l'ultima
  release GitHub (`releases/latest`);
* **Aggiorna** applica l'aggiornamento, in due modi:
  * installazione **da sorgente**: esegue `git pull --ff-only` nella cartella del
    progetto (serve `git` nel PATH);
  * installazione **da eseguibile**: scarica lo zip della release, estrae il
    nuovo `.exe`, rinomina quello in uso in `*.old` e mette il nuovo al suo posto
    (il `*.old` viene rimosso al riavvio successivo);
* **Riavvia** chiude e rilancia l'app con la nuova versione.

Nessun servizio esterno: solo `urllib` verso l'API GitHub, e vengono aperte
soltanto URL http/https.

## Se l'antivirus blocca l'exe

Gli eseguibili creati con PyInstaller (`--onefile`) sono non firmati e in ambito
aziendale vengono spesso eliminati dal sistema di sicurezza. In quel caso **non
serve l'exe**: l'app gira con il Python già installato.

```text
FindEverywhere.pyw              doppio clic: avvia l'app senza console
run.bat                         idem, da riga di comando
install-autostart-source.bat    avvio automatico al login SENZA exe
```

`install-autostart-source.bat` crea il collegamento in Esecuzione automatica
puntando a `pythonw.exe "...\app.py" --startup` (nessun binario nuovo, nessuna
modifica al registro; si annulla con `uninstall-autostart.bat`).

L'exe/zip resta utile per le macchine dove è consentito, o se IT aggiunge
un'eccezione (o se un giorno lo firmi con un certificato di code signing).

## Compilare

Richiede PyInstaller (`pip install pyinstaller`) — qui è già presente.

Doppio click su `build.bat` → `dist\SpotlightPy.exe`.
Per cambiare il nome dell'eseguibile basta passarlo come parametro:

```bat
build.bat                  :: dist\SpotlightPy.exe
build.bat FindEverywhere    :: dist\FindEverywhere.exe
```

Equivalente a mano:

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name FindEverywhere ^
  --hidden-import win32com.client --hidden-import pythoncom ^
  --hidden-import pywintypes --hidden-import win32timezone ^
  --collect-submodules win32com ^
  app.py
```

Risultato: un singolo `.exe` (~30 MB, nessuna console). `build/`, `dist/` e
`*.spec` sono in `.gitignore`, quindi non finiscono nel repo.

## Eseguire dal sorgente

```bat
python app.py                    (con console, per debug)
run.bat                          (senza console)
python app.py --smoke            (self-test: apre la UI per 1,2 s ed esce)
python app.py --selftest-wsearch (verifica la ricerca nell'indice di Windows,
                                  utile anche sull'exe compilato)
```
