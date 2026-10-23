# SpotlightPy

Launcher stile *Spotlight / PowerToys Run* per Windows, in Python (solo stdlib
+ pywin32 per l'indice di Windows). Nasce per cercare file che stanno in
**cartelle di rete non indicizzabili** da Windows Search.

```
Ctrl+Alt+Spazio  ->  apre la finestra (chiudi con Esc). Configurabile o disabilitabile:
                    impostazioni -> hotkey principale -> "Nessuna" (campo vuoto).
```

## Come funziona la ricerca

Ogni ricerca unisce tre fonti, in ordine di velocità:

| fonte | cosa fa | quando arriva |
|---|---|---|
| **Indice locale (SQLite)** | risultati già scansionati in precedenza | immediato (istantaneo) |
| **Windows Search** (SYSTEMINDEX) | file indicizzati da Windows su questo PC | ~0,2–0,4 s (thread separato) |
| **Scansione viva** | `os.scandir` ricorsivo sulle cartelle configurate (es. share di rete) | in streaming, con la rotellina |

Quindi: la finestra mostra subito quello che sa, poi si riempie man mano che
arrivano gli altri risultati. La scansione viva **non** è `Path.rglob` (lento):
usa `os.scandir`, salta le cartelle in `excludes`, non segue junction/symlink,
e **scrive nell'indice** tutto quello che incontra → la seconda volta è
istantanea.

L'indice viene anche ricostruito all'avvio (dopo un walk completo le voci di
file cancellati vengono rimosse). Icone nei risultati: 🗂 cartella, 🖥 indice di
Windows, 📄 indice locale, 🌐 cartella scansionata a mano, 📃 corrispondenza
trovata nel testo del documento.

I percorsi dei risultati di Windows Search vengono ricavati da `System.ItemUrl`:
`System.ItemPathDisplay` restituisce il percorso **localizzato**
(`C:\Utenti\Polat\Documenti\…`) che su disco non esiste, e faceva aprire a
Explorer una cartella sbagliata.

## Tasti

| tasto | azione |
|---|---|
| `Invio` / click | apre l'elemento selezionato: file con l'app associata, **cartella** in Esplora file |
| `Ctrl+Shift+E` (solo a finestra aperta) | apre la **cartella che contiene** l'elemento, con l'elemento selezionato |
| `Ctrl+Invio` | come sopra (alias) |
| `↑` / `↓`, rotellina | naviga i risultati |
| `Ctrl+,` o ⚙ | impostazioni |
| `Esc` | chiude la finestra |
| `Ctrl+Shift+Q` | **esce dal processo** (deregistra le hotkey) |
| hotkey custom | lancia lo script configurato sul percorso selezionato |

**Spostare la finestra**: trascina con il mouse da una zona "vuota" (barra del
titolo implicita, riga di stato, footer, area sotto i risultati). La posizione
viene salvata nel config e ripristinata al riavvio.

Note sull'hotkey principale: si sceglie liberamente nelle impostazioni
(clicca il campo e premi la combinazione) oppure si disabilita con "Nessuna":
con il campo vuoto **non viene registrata nessuna hotkey globale** e la finestra
si apre solo dal bat/exe (doppio clic). `Ctrl+Shift+E` è riservato all'azione
"apri la cartella contenitrice" e non è accettato come hotkey globale.

I risultati includono **sia file sia cartelle** (icona 🗂 per le cartelle).

Click destro su un risultato: Apri / Apri cartella / Copia percorso / script.

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

## Impostazioni / file

* config: `%APPDATA%\SpotlightPy\config.json`
* indice: `%APPDATA%\SpotlightPy\index.db`

Chiavi principali del config:

```json
{
  "hotkey": "ctrl+alt+space",
  "paths": ["\\\\server\\share\\cartella"],
  "scripts": [{"name": "Carica", "command": "python C:\\s\\carica.py {path}", "hotkey": "ctrl+shift+1"}],
  "excludes": ["$RECYCLE.BIN", "System Volume Information", ".git", "node_modules", "__pycache__", ".venv", "venv"],
  "win_search": true,
  "win_search_limit": 40,
  "index_on_startup": true,
  "live_scan": true,
  "max_results": 120,
  "hide_on_focus_loss": true
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
  velocità: togli la voce da `excludes` se ti servono.
* L'indice cresce: per un indice pulito usa **Ricostruisci indice** nelle
  impostazioni.

## Avvio automatico

`Win+R` → `shell:startup` → copia lì un collegamento a `SpotlightPy.exe`.

## Avvio automatico

```bat
install-autostart.bat     :: copia l'exe in %LOCALAPPDATA%\find-everywhere e
                          :: crea il collegamento in Esecuzione automatica
uninstall-autostart.bat   :: rimuove il collegamento
```

Come funziona:

* l'exe viene **copiato** in `%LOCALAPPDATA%\find-everywhere\FindEverywhere.exe`,
  così ricompilare (`build.bat`, che svuota `dist\`) non rompe l'avvio automatico;
* il collegamento creato punta a quell'exe con il parametro **`--startup`**;
* con `--startup` l'app resta **nascosta** e si apre solo con la hotkey globale;
  se per\u00f2 la hotkey \u00e8 disabilitata (campo vuoto) la finestra viene mostrata,
  altrimenti non avresti modo di aprirla;
* solo utente corrente, nessun permesso di amministratore, nessuna modifica al
  registro: tutto reversibile con `uninstall-autostart.bat`.

**Requisito**: la hotkey globale deve essere **attiva** (Impostazioni → Hotkey
principale → clicca il campo e premi la combinazione → Salva). Con `Ctrl+Alt+Spazio`
sei a posto: è il default e risulta libero su questo PC.

In alternativa al collegamento si può usare il registro
(`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valore
`find-everywhere` = `"...\FindEverywhere.exe" --startup`) o Utilità di
pianificazione con "All'accesso" + ritardo di 30 s, se vuoi che parta pi\u00f9 tardi.

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
