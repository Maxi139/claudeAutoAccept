# claudeAutoAccept

Kleines macOS-Automationsprojekt, das den Xcode-Build-Button per Bildsuche findet und klickt.

## Voraussetzungen

- macOS
- Python-Venv in `.venv`
- Bildschirmaufnahme-Berechtigung
- Bedienungshilfen-Berechtigung fuer Maussteuerung

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Start

Der einfachste Startbefehl ist:

```bash
zsh /Users/maximilian/PycharmProjects/claudeAutoAccept/run_xcode_build_click.sh
```

Der Ablauf ist:

- zeigt vor dem Klick eine Warnphase mit pulsierendem Bildschirmrand und Sound
- bricht ab, wenn in dieser Zeit die Maus bewegt wird
- holt Xcode in den Vordergrund
- sucht auf dem Hauptmonitor nach dem hellen oder dunklen Build-Button
- bewegt die Maus auf den Treffer und klickt
- stellt danach die vorher aktive App wieder her

## Direkter Python-Aufruf

```bash
/Users/maximilian/PycharmProjects/claudeAutoAccept/.venv/bin/python /Users/maximilian/PycharmProjects/claudeAutoAccept/xcode_build_click.py
```

## Wichtige Dateien

- `run_xcode_build_click.sh`: empfohlener Starter
- `xcode_build_click.py`: Xcode-spezifische Einmal-Suche mit Warnphase
- `auto_accept.py`: urspruengliche Schleifenvariante
