"""Avvio di find-everywhere senza console e senza .exe compilato.

Doppio clic su questo file (estensione .pyw = eseguito da pythonw.exe) per
avviare l'app usando il Python gia' installato. Utile dove l'antivirus elimina
gli eseguibili creati con PyInstaller.

Gli argomenti vengono passati ad app.py, es.
  FindEverywhere.pyw --startup
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

if not os.path.exists(APP):
    import tkinter.messagebox as mb

    mb.showerror("find-everywhere", f"app.py non trovato in:\n{HERE}")
    raise SystemExit(1)

os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

sys.argv = [APP, *sys.argv[1:]]
runpy.run_path(APP, run_name="__main__")
