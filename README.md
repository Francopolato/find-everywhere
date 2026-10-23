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
| **Windows Search** (SYSTEMINDEX) | file **e cartelle** indicizzati da Windows; 4 strategie in cascata: nome, nome file, percorso contenitore, contenuto dei documenti | ~0,2–0,4 s (thread separato) |
| **Scansione viva** | `os.scandir` ricorsivo sulle cartelle configurate (es. share di rete) | in streaming, con la rotellina |

Quindi: la finestra mostra subito quello che sa, poi si riempie man mano che
arrivano gli altri risultati. La scansione viva **non** è `Path.rglob` (lento):
usa `os.scandir`, salta le cartelle in `excludes`, non segue junction/symlink,
e **scrive nell'indice** tutto quello che incontra → la seconda volta è
istantanea.

L'indice viene anche ricostruito all'avvio (dopo un walk completo le voci di
file cancellati vengono rimosse).

## Risultati

* **file e cartelle**: le cartelle hanno icona 📁 e nome in evidenza;
* **estensione sempre visibile**: se il nome non la contiene viene aggiunta dal
  percorso (`.pdf`, `.xlsx`, …);
* **nomi lunghi**: troncati con `…` **prima dell'estensione**
  (`contratto quadro molto lungo … 2….pdf`), così il tipo di file resta leggibile;
* **filtro**: in alto a destra il pulsante `Tutti` / `Solo file` / `Solo cartelle`
  (anche `Ctrl+T`); la scelta viene salvata nel config;
* icone di origine: 🖥 indice di Windows, 📄 indice locale, 🌐 cartella
  scansionata a mano, 📃 corrispondenza trovata nel testo del documento,
  📁 cartella.

I percorsi dei risultati di Windows Search vengono ricavati da `System.ItemUrl`:
`System.ItemPathDisplay` restituisce il percorso **localizzato**
(`C:\Utenti\Polat\Documenti\…`) che su disco non esiste, e faceva aprire a
Explorer una cartella sbagliata.

## Ricerca intelligente (jolly `*`)

`*` significa **uno o più caratteri qualsiasi**:

```text
scafallatur*metall*ord*23440
```

trova i nomi che contengono `scafallatur`, poi `metall`, poi `ord`, poi `23440`.
Un `*` in testa o in coda vale "qualsiasi cosa" (`*2024`, `contratto*`).
Senza `*` la ricerca resta quella di sempre.

Come viene applicato:

* **indice locale (SQLite)** e **scansione cartelle**: conversione in `LIKE`
  (`*` → `_%`, cioè almeno un carattere) oppure in regex, quindi sottostringa
  vera;
* **Windows Search**: ogni termine diventa un **prefisso di parola**
  (`CONTAINS(System.FileName, '"scafallatur*" AND "metall*" …')`), tutti i
  termini devono comparire ma **in qualunque ordine**. È il motivo per cui la
  ricerca è veloce (0,1 s): `LIKE '%term%'` costava 12+ secondi perché non usa
  l'indice. Conseguenza: una ricerca a metà parola (es. `tratt` dentro
  `contratto`) non trova nulla in Windows Search, mentre la trova la scansione
  delle cartelle configurate.

## Tasti

| tasto | azione |
|---|---|
| `Invio` / click | apre l'elemento selezionato: file con l'app associata, **cartella** in Esplora file |
| `Ctrl+Shift+E` (solo a finestra aperta) | apre la **cartella che contiene** l'elemento, con l'elemento selezionato |
| `Ctrl+Invio` | come sopra (alias) |
| `↑` / `↓`, rotellina | naviga i risultati |
| `Ctrl+T` (o click su `Tutti`) | filtro: Tutti → Solo file → Solo cartelle |
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
pianificazione con "All'accesso" + ritardo di 30 s, se vuoi che parta pi\u00f9 tardi.

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
