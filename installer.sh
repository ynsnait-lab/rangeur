#!/bin/zsh
# Installe le rangeur : config, commande « rangeur », Rangeur.app et agent qui tourne toutes les heures.
# Désinstaller : ./installer.sh --desinstaller
set -e
ICI="${0:A:h}"
LABEL=fr.rangeur.agent
PL="$HOME/Library/LaunchAgents/$LABEL.plist"
APPDIR=/Applications; [[ -w $APPDIR ]] || APPDIR="$HOME/Applications"
APP="$APPDIR/Rangeur.app"

if [[ ${1:-} == --desinstaller ]]; then
  launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
  rm -f "$PL" "$HOME/.local/bin/rangeur"
  print "Agent et commande retirés. Rangeur.app ($APP), ta config et tes journaux (~/.rangeur) sont conservés."
  exit 0
fi

command -v clang >/dev/null || { print "Il faut les outils en ligne de commande : xcode-select --install"; exit 1; }
mkdir -p "$HOME/.rangeur" "$HOME/.local/bin"
[[ -f "$HOME/.rangeur/config.json" ]] || /usr/bin/python3 "$ICI/rangeur.py" --init-config
chmod +x "$ICI/rangeur.py"
ln -sf "$ICI/rangeur.py" "$HOME/.local/bin/rangeur"

mkdir -p "$APP/Contents/MacOS"
cp "$ICI/app/Info.plist" "$APP/Contents/Info.plist"
clang -O2 -DRANGEUR_PY="\"$ICI/rangeur.py\"" -o "$APP/Contents/MacOS/Rangeur" "$ICI/app/lanceur.c"
codesign --force --sign - --identifier fr.rangeur.app "$APP"

sed -e "s|@APP@|$APP/Contents/MacOS/Rangeur|g" -e "s|@ETAT@|$HOME/.rangeur|g" "$ICI/app/$LABEL.plist" > "$PL"
launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PL"

cat <<EOF

Rangeur installé.
  Config     : ~/.rangeur/config.json   (destinations et règles, à adapter)
  Commande   : rangeur --plan           (voir ce qui serait fait)
  Journal    : ~/Downloads/_OÙ SONT MES FICHIERS.md

Dernière étape, à faire à la main (réglage de sécurité) :
  Réglages Système > Confidentialité et sécurité > Accès complet au disque > « + » > $APP
EOF
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
