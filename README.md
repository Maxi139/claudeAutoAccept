# claudeAutoAccept

Kleines macOS-Automationsprojekt, das Claude-Accept-Buttons per Bildsuche findet und automatisch klickt.

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

Der Hauptmodus fuer Claude Auto Accept ist:

```bash
zsh /Users/maximilian/PycharmProjects/claudeAutoAccept/run_claude_auto_accept.sh
```

Optional mit eigener Schwelle:

```bash
zsh /Users/maximilian/PycharmProjects/claudeAutoAccept/run_claude_auto_accept.sh --threshold 0.8
```

Der Claude-Auto-Accept-Modus:

- scannt den Hauptmonitor in einem Intervall
- sucht nach dem gespeicherten Claude-Accept-Template
- klickt automatisch auf Treffer
- kann mit `Ctrl+C` beendet werden

## Xcode Zusatzmodus

Fuer den separaten Xcode-Build-Button gibt es weiterhin diesen Starter:

```bash
zsh /Users/maximilian/PycharmProjects/claudeAutoAccept/run_xcode_build_click.sh
```

Der Xcode-Modus:

- zeigt vor dem Klick eine Warnphase mit pulsierendem Bildschirmrand und Sound
- bricht ab, wenn in dieser Zeit die Maus bewegt wird
- holt Xcode in den Vordergrund
- sucht auf dem Hauptmonitor nach dem hellen oder dunklen Build-Button
- bewegt die Maus auf den Treffer und klickt
- stellt danach die vorher aktive App wieder her

## Direkter Python-Aufruf

```bash
/Users/maximilian/PycharmProjects/claudeAutoAccept/.venv/bin/python /Users/maximilian/PycharmProjects/claudeAutoAccept/auto_accept.py
```

Direkter Xcode-Aufruf:

```bash
/Users/maximilian/PycharmProjects/claudeAutoAccept/.venv/bin/python /Users/maximilian/PycharmProjects/claudeAutoAccept/xcode_build_click.py
```

## Wichtige Dateien

- `run_claude_auto_accept.sh`: empfohlener Starter fuer Claude Auto Accept
- `auto_accept.py`: Hauptmodus fuer wiederholtes Claude Auto Accept
- `run_xcode_build_click.sh`: empfohlener Starter
- `xcode_build_click.py`: Xcode-spezifische Einmal-Suche mit Warnphase
