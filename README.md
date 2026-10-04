# Rangeur

**Ton dossier Téléchargements se range tout seul, et rien n'est jamais supprimé.** Pour macOS.

> *English: a hands-off Downloads organizer for macOS. Files wait 24 h, then get filed by simple
> name-based rules; anything unclear goes to a "to sort" folder, duplicates and installers to a
> quarantine folder. Nothing is ever deleted, every move is logged and can be undone.*

## Ce que ça fait

- **Un délai avant de ranger** (24 h par défaut) : le fichier que tu viens de télécharger reste sous la main.
- **Des règles simples** dans un fichier JSON : « si le nom contient *bulletin de paie*, va dans *Administratif/Paie* ».
- **L'ambigu ne se perd pas** : ce que les règles ne reconnaissent pas part dans un dossier « À trier ».
- **Zéro suppression** : doublons exacts (même empreinte SHA-256) et installeurs (`.dmg`, `.pkg`…) vont en
  quarantaine, avec un `INDEX.md` qui dit d'où vient chaque fichier. Aucun fichier n'est jamais écrasé.
- **Un journal lisible**, toujours dans Téléchargements : `_OÙ SONT MES FICHIERS.md`.
- **Annulable** : `rangeur --annuler 2026-10-05` remet en place tout ce qui a été rangé ce jour-là.
- **Compatible iCloud Drive / OneDrive** : plusieurs dossiers sources possibles (par exemple les téléchargements
  de l'iPhone qui arrivent dans iCloud Drive), et les fichiers « en ligne uniquement » sont gérés.
- **Calibre en option** : les livres (`.epub`, `.azw3`…) sont ajoutés à ta bibliothèque Calibre.
- **Aucune dépendance** : un seul fichier Python, le Python fourni par macOS suffit. Pas d'abonnement, pas d'internet.

Exemple de journal :

```markdown
## 2026-10-05
- 14:02 · `bulletin-de-paie-septembre-2026.pdf` → `~/Documents/Administratif/Paie`
- 14:02 · `IMG_5719.HEIC` → `~/Pictures/À importer`
- 14:02 · `Outil-2.3.dmg` → `~/Documents/Quarantaine/2026-10` (installeur, se retélécharge)
- 14:02 · `A700000006636809.pdf` → `~/Documents/À trier` (ambigu)
```

## Installation

```bash
git clone https://github.com/ynsnait-lab/rangeur.git
cd rangeur
./installer.sh
```

L'installeur crée ta config (`~/.rangeur/config.json`), la commande `rangeur`, une petite app
`Rangeur.app` et un agent qui la lance toutes les heures.

**Dernière étape, à la main** : Réglages Système › Confidentialité et sécurité › **Accès complet au disque** ›
« + » › `Rangeur.app`. macOS interdit sinon à un programme d'arrière-plan de lire Téléchargements et iCloud.
L'app ne sert qu'à ça : c'est elle seule qui reçoit l'accès, et le script qu'elle lance en hérite.

Désinstaller : `./installer.sh --desinstaller` (ta config et tes journaux sont gardés).

## Configuration

Tout est dans `~/.rangeur/config.json`. Ce que tu n'y mets pas reprend la valeur par défaut
(voir [`config.exemple.json`](config.exemple.json)).

```json
{
  "delai_heures": 24,
  "sources": [{"dossier": "~/Downloads"}],
  "ambigus": "~/Documents/À trier",
  "quarantaine": "~/Documents/Quarantaine/{annee}-{mois}",
  "destinations": {
    "paie": "~/Documents/Administratif/Paie",
    "projet-x": "~/Projets/Projet X"
  },
  "regles_en_plus": [
    ["projet-x", "projet[ -]?x|px-\\d+"]
  ]
}
```

- **`regles`** : liste de `[destination, expression régulière]`, testées dans l'ordre sur le nom du fichier
  (en minuscules, sans accents). La première qui correspond gagne. Remplace la liste par défaut.
- **`regles_en_plus`** : tes règles à toi, testées **avant** celles par défaut. Le plus simple pour commencer.
- **`destinations`** : clé → dossier. `{annee}` et `{mois}` sont remplacés par la date du jour.
  Valeurs spéciales : `QUARANTAINE`, `AMBIGUS`, `CALIBRE`.
- **`sources`** : les dossiers surveillés ; chacun peut avoir sa propre `quarantaine` et ses `ambigus`.
- **`journal`** : chemin du journal lisible (`""` pour aucun).
- **`calibre`** : chemins de `calibredb` et de ta bibliothèque, ou `null`.

## Commandes

```bash
rangeur --plan                      # ce qui serait fait, sans rien bouger
rangeur                             # ranger maintenant (en respectant le délai)
rangeur --min-age 0                 # tout ranger tout de suite
rangeur --annuler 2026-10-05        # remettre en place une journée
rangeur --noter SRC DEST "raison"   # ajouter une ligne au journal depuis un autre script
```

Le journal technique (pour annuler) est `~/.rangeur/journal.tsv`, le log de l'agent `~/.rangeur/rangeur.log`.

## Garanties

- Les déplacements se font sans jamais remplacer un fichier existant : en cas de nom identique et de contenu
  différent, le nouveau devient « nom (2).ext ».
- Un fichier n'est considéré comme doublon que si son contenu est **identique** (SHA-256), même sous un autre nom.
- Rien n'est supprimé : vider la quarantaine reste ta décision.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Licence

MIT — voir [LICENSE](LICENSE).
