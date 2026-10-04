#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rangeur — range ton dossier Téléchargements tout seul, sans jamais rien supprimer.

- Un fichier reste un certain temps (24 h par défaut) dans Téléchargements, puis il est rangé.
- Les règles (nom de fichier -> dossier) sont dans un simple fichier JSON.
- Ce qui est ambigu part dans un dossier « À trier ».
- Les doublons exacts (même empreinte SHA-256) et les installeurs partent en quarantaine.
- Chaque déplacement est noté dans un journal lisible (Markdown) et dans un journal technique
  qui permet d'annuler une journée entière.

Commandes
  rangeur                          rangement normal (toutes les sources de la config)
  rangeur --plan                   montre ce qui serait fait, sans rien bouger
  rangeur --annuler 2026-10-05     remet en place ce qui a été rangé ce jour-là
  rangeur --init-config            crée ~/.rangeur/config.json à partir de l'exemple
  rangeur --noter SRC DEST RAISON  ajoute une ligne au journal (pour d'autres scripts)

Config : ~/.rangeur/config.json (ou variable RANGEUR_CONFIG, ou --config).
Aucune dépendance : Python 3.9+ de macOS suffit.
"""
import argparse, copy, datetime, errno, fcntl, hashlib, json, os, re, shutil, subprocess, sys, time, unicodedata, zipfile

__version__ = "1.0.0"
HOME = os.path.expanduser("~")
STATE = os.environ.get("RANGEUR_ETAT", os.path.join(HOME, ".rangeur"))
JOURNAL_TSV = os.path.join(STATE, "journal.tsv")
SF_DATALESS = 0x40000000          # fichier iCloud/OneDrive présent seulement dans le cloud
PARTIELS = (".crdownload", ".download", ".part", ".partial", ".tmp")
SPECIAUX = ("QUARANTAINE", "CALIBRE", "AMBIGUS")

CONFIG_INTEGREE = {
    "delai_heures": 24,
    "sources": [{"dossier": "~/Downloads"}],
    "journal": "~/Downloads/_OÙ SONT MES FICHIERS.md",
    "ambigus": "~/Documents/À trier",
    "quarantaine": "~/Documents/Quarantaine/{annee}-{mois}",
    "calibre": {"calibredb": "/Applications/calibre.app/Contents/MacOS/calibredb",
                "bibliotheque": "~/Calibre Library"},
    "destinations": {
        "installeur": "QUARANTAINE",
        "ebook": "CALIBRE",
        "livres": "~/Documents/Livres",
        "paie": "~/Documents/Administratif/Paie",
        "impots": "~/Documents/Administratif/Impôts",
        "banque": "~/Documents/Administratif/Banque",
        "factures": "~/Documents/Administratif/Factures",
        "sante": "~/Documents/Administratif/Santé",
        "logement": "~/Documents/Administratif/Logement",
        "vehicule": "~/Documents/Administratif/Véhicule",
        "identite": "~/Documents/Administratif/Identité",
        "attestation": "~/Documents/Administratif/Attestations",
        "etudes": "~/Documents/Études",
        "travail": "~/Documents/Travail",
        "electronique": "~/Documents/Datasheets",
        "cao3d": "~/Documents/Modèles 3D",
        "capture": "~/Pictures/Captures/{annee}-{mois}",
        "media": "~/Pictures/À importer",
    },
    # Première règle qui correspond = destination. Noms comparés sans accents, en minuscules.
    "regles": [
        ["installeur", r"\.(dmg|pkg|ipa|msi|exe|apk)$|installer"],
        ["ebook", r"\.(epub|azw3|mobi)$"],
        ["paie", r"bulletin.{0,4}de.{0,3}(paie|salaire)|fiche de paie|payslip"],
        ["impots", r"impot|avis d.imposition|dgfip|taxe fonciere|taxe d.habitation"],
        ["sante", r"assurance.?maladie|ameli|cpam|ordonnance|mutuelle|radio|analyses? (de )?sang|compte.rendu medical"],
        ["logement", r"quittance|loyer|\bbail\b|echeance|assurance habitation|etat des lieux"],
        ["vehicule", r"carte grise|certificat d.immatriculation|pneu|controle technique|assurance auto"],
        ["identite", r"passeport|carte.?d.?identit|\bcni\b|titre de sejour|permis de conduire"],
        ["etudes", r"certificat.de.scolarit|releve.{0,3}de.notes|diplome|bulletin scolaire"],
        ["attestation", r"attestation|responsabilite civile|cvec"],
        ["banque", r"\brib\b|\biban\b|releve de compte|mandat.?sepa"],
        ["travail", r"^cv\b|^cv[ _-]|lettre de motivation|contrat de travail|convention de stage|candidature"],
        ["electronique", r"datasheet|schematic|\bbom\b"],
        ["cao3d", r"\.(step|stp|stl|igs|iges|sldprt|sldasm|f3d|3mf)$"],
        ["factures", r"factur|invoice|receipt|\brecu\b|\border\b|commande|devis"],
        ["capture", r"capture d.?ecran|screenshot"],
        ["media", r"^(img_|dji_|pxl_|dsc|mvimg|\d{8}_\d{6}).*\.(heic|jpe?g|png|gif|webp|dng|mov|mp4|m4v|mpg|avi)$|\.(heic|mov|mp4|m4v|mpg|avi)$"],
    ],
}


# ------------------------------------------------------------------ configuration
def charger_config(chemin_cfg=None):
    """Config intégrée, complétée par le fichier JSON de l'utilisateur s'il existe."""
    cfg = copy.deepcopy(CONFIG_INTEGREE)
    chemin_cfg = chemin_cfg or os.environ.get("RANGEUR_CONFIG") or os.path.join(STATE, "config.json")
    if os.path.exists(chemin_cfg):
        with open(chemin_cfg, encoding="utf-8") as f:
            perso = json.load(f)
        dest = perso.pop("destinations", None)
        en_plus = perso.pop("regles_en_plus", [])
        cfg.update(perso)
        if dest:
            cfg["destinations"].update(dest)
        cfg["regles"] = list(en_plus) + list(cfg["regles"])
    return cfg


def chemin(p, quand=None):
    """Développe ~ et les variables {annee} {mois}."""
    if p in SPECIAUX:
        return p
    d = quand or datetime.date.today()
    p = p.replace("{annee}", "%04d" % d.year).replace("{mois}", "%02d" % d.month)
    return os.path.abspath(os.path.expanduser(p))


def norm(s):
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def compiler(regles):
    return [(cle, re.compile(rx)) for cle, rx in regles]


def classer(nom, regles):
    n = norm(nom)
    for cle, rx in regles:
        if rx.search(n):
            return cle
    return None


# ------------------------------------------------------------------ fichiers
def espace(p):
    rp = os.path.realpath(p)
    if rp.startswith(os.path.join(HOME, "Library", "Mobile Documents") + os.sep):
        return "icloud"
    if rp.startswith(os.path.join(HOME, "Library", "CloudStorage") + os.sep):
        return "cloud"
    for nom in ("Documents", "Desktop"):   # synchronisés si « Bureau et Documents » est actif dans iCloud
        pre = os.path.join(HOME, nom)
        if rp == pre or rp.startswith(pre + os.sep):
            return "icloud?"
    return "local"


def dataless(p):
    try:
        return bool(os.lstat(p).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


def _lire(p):
    with open(p, "rb") as f:
        while f.read(8 << 20):
            pass


def materialiser(p):
    """Télécharge depuis le cloud les fichiers qui n'y sont qu'en ligne (avant de les sortir du cloud)."""
    if os.path.isdir(p) and not os.path.islink(p):
        for r, ds, fs in os.walk(p):
            for f in fs:
                q = os.path.join(r, f)
                if not os.path.islink(q) and dataless(q):
                    _lire(q)
    elif not os.path.islink(p) and dataless(p):
        _lire(p)


def sha_fichier(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloc in iter(lambda: f.read(8 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def empreinte(p):
    if os.path.islink(p):
        return "lien:" + os.readlink(p)
    if os.path.isdir(p):
        h = hashlib.sha256()
        for r, ds, fs in os.walk(p):
            ds.sort()
            for f in sorted(fs):
                if f == ".DS_Store":
                    continue
                q = os.path.join(r, f)
                h.update(os.path.relpath(q, p).encode("utf-8", "surrogateescape"))
                h.update(empreinte(q).encode())
        return h.hexdigest()
    return sha_fichier(p)


def taille(p):
    if os.path.isdir(p) and not os.path.islink(p):
        t = 0
        for r, ds, fs in os.walk(p):
            for f in fs:
                if f != ".DS_Store":
                    try:
                        t += os.lstat(os.path.join(r, f)).st_size
                    except OSError:
                        pass
        return t
    return os.lstat(p).st_size


def identiques(a, b):
    try:
        if os.path.isdir(a) != os.path.isdir(b) or taille(a) != taille(b):
            return False
        return empreinte(a) == empreinte(b)
    except OSError:
        return False


DUP = re.compile(r"^(?P<base>.+?)(?: \d{1,2}| \(\d{1,2}\)|-\d)(?P<ext>\.[A-Za-z0-9]{1,5})?$")


def original_probable(dossier, nom):
    """« doc 2.pdf », « doc (1).pdf », « doc-1.pdf » -> « doc.pdf » s'il existe."""
    m = DUP.match(nom)
    if not m:
        return None
    cand = m.group("base") + (m.group("ext") or "")
    if cand == nom:
        return None
    p = os.path.join(dossier, cand)
    return p if os.path.lexists(p) else None


def zip_deja_decompresse(dossier, nom):
    if not nom.lower().endswith(".zip"):
        return None
    d = os.path.join(dossier, nom[:-4])
    if not os.path.isdir(d):
        return None
    try:
        with zipfile.ZipFile(os.path.join(dossier, nom)) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename
                     and not i.filename.endswith(".DS_Store")]
            n_zip, t_zip = len(infos), sum(i.file_size for i in infos)
    except Exception:
        return None
    n_dir = t_dir = 0
    for r, ds, fs in os.walk(d):
        for f in fs:
            if f != ".DS_Store":
                n_dir += 1
                t_dir += os.lstat(os.path.join(r, f)).st_size
    return d if (n_zip, t_zip) == (n_dir, t_dir) and n_zip > 0 else None


def chemin_libre(p):
    if not os.path.lexists(p):
        return p
    base, ext = (p, "") if os.path.isdir(p) else os.path.splitext(p)
    i = 2
    while os.path.lexists("%s (%d)%s" % (base, i, ext)):
        i += 1
    return "%s (%d)%s" % (base, i, ext)


def doublon_dans(dossier, src):
    """Un fichier identique (même sous un autre nom) est-il déjà dans dossier ?"""
    if os.path.isdir(src) or not os.path.isdir(dossier):
        return None
    t = os.lstat(src).st_size
    for nom in os.listdir(dossier):
        q = os.path.join(dossier, nom)
        try:
            if os.path.isfile(q) and not os.path.islink(q) and os.lstat(q).st_size == t and identiques(src, q):
                return q
        except OSError:
            pass
    return None


def deplacer(src, dossier_dest, eviter_doublon=True):
    """Déplace src dans dossier_dest. Ne remplace jamais rien. Renvoie (statut, destination)."""
    dst = os.path.join(dossier_dest, os.path.basename(src))
    if os.path.lexists(dst):
        if eviter_doublon and identiques(src, dst):
            return "deja_la", dst
        dst = chemin_libre(dst)
    os.makedirs(dossier_dest, exist_ok=True)
    if espace(src) != espace(dossier_dest):
        materialiser(src)
    try:
        os.rename(src, dst)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        if os.path.isdir(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        if not identiques(src, dst):
            raise RuntimeError("copie non conforme, original conservé : " + src)
        shutil.rmtree(src) if os.path.isdir(src) else os.remove(src)
    if not os.path.lexists(dst) or os.path.lexists(src):
        raise RuntimeError("déplacement incomplet : " + src)
    return "deplace", dst


def calibre_ajouter(p, cfg):
    c = cfg.get("calibre") or {}
    exe, lib = c.get("calibredb"), chemin(c.get("bibliotheque", "")) if c.get("bibliotheque") else None
    if not exe or not lib or not os.path.exists(exe) or not os.path.isdir(lib):
        return False, "Calibre absent"
    try:
        r = subprocess.run([exe, "add", "--library-path", lib, p], capture_output=True, text=True, timeout=600)
    except Exception as e:
        return False, str(e)
    out = (r.stdout or "") + (r.stderr or "")
    bas = out.lower()
    if r.returncode == 0 and "error" not in bas and "erreur" not in bas and "traceback" not in bas:
        return True, out.strip()
    return False, out.strip()


# ------------------------------------------------------------------ journaux
def affiche(p):
    return "~" + p[len(HOME):] if p.startswith(HOME) else p


def journaliser(src, dst, raison, log_extra=None):
    os.makedirs(STATE, exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(JOURNAL_TSV, "a", encoding="utf-8", errors="surrogateescape") as f:
        f.write("%s\t%s\t%s\t%s\n" % (stamp, src, dst, raison))
    if log_extra:
        with open(log_extra, "a", encoding="utf-8", errors="surrogateescape") as f:
            f.write("%s\t%s\n" % (src, dst))


def noter_quarantaine(dossier_q, nom, origine, raison):
    os.makedirs(dossier_q, exist_ok=True)
    idx = os.path.join(dossier_q, "INDEX.md")
    neuf = not os.path.exists(idx)
    with open(idx, "a", encoding="utf-8", errors="surrogateescape") as f:
        if neuf:
            f.write("# Quarantaine — %s\n\nRien ici n'a été supprimé. Chaque ligne : élément, d'où il vient, "
                    "pourquoi il est là.\n\n" % os.path.basename(dossier_q))
        f.write("- `%s` ← `%s` — %s\n" % (nom, affiche(origine), raison))


def ecrire_journal_md(md, entrees, cfg=None):
    """Journal lisible, jour le plus récent en haut."""
    if not entrees or not md:
        return
    amb = affiche(chemin((cfg or CONFIG_INTEGREE)["ambigus"]))
    entete = ("# Où sont mes fichiers ?\n\n"
              "Tenu à jour par le rangeur. Un fichier reste quelque temps dans Téléchargements, puis il est rangé. "
              "Rien n'est jamais supprimé : doublons et installeurs vont en quarantaine, ce qui est ambigu va dans "
              "`%s`.\n\nAnnuler une journée : `rangeur --annuler AAAA-MM-JJ`\n" % amb)
    ancien = ""
    if os.path.exists(md):
        with open(md, encoding="utf-8") as f:
            ancien = f.read()
    corps = ("## " + ancien.split("\n## ", 1)[1]) if "\n## " in ancien else ""
    titre = "## " + datetime.date.today().isoformat()
    lignes = "\n".join("- %s · `%s` → `%s`%s" % (h, nom, dest, (" (%s)" % r) if r else "") for h, nom, dest, r in entrees)
    if corps.startswith(titre + "\n"):
        corps = titre + "\n" + lignes + "\n" + corps[len(titre) + 1:]
    else:
        corps = titre + "\n" + lignes + "\n\n" + corps
    os.makedirs(os.path.dirname(md), exist_ok=True)
    tmp = md + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(entete + "\n" + corps.rstrip() + "\n")
    os.replace(tmp, md)


# ------------------------------------------------------------------ rangement
def planifier(source, min_age, regles, dest, reste, quarantaine, ponctuel, exclus=()):
    maintenant = time.time()
    plan = []
    for nom in sorted(os.listdir(source)):
        if nom in exclus or nom in (".DS_Store", ".localized") or nom.startswith(".") or nom.lower().endswith(PARTIELS):
            continue
        p = os.path.join(source, nom)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if (maintenant - st.st_ctime) / 3600.0 < min_age:      # ctime = arrivée dans le dossier
            continue
        if nom in ponctuel:
            cible, raison = ponctuel[nom]
            plan.append((p, quarantaine if cible == "QUARANTAINE" else chemin(cible), "ponctuel", raison))
            continue
        orig = original_probable(source, nom)
        if orig and identiques(p, orig):
            plan.append((p, quarantaine, "doublon", "doublon exact de « %s »" % os.path.basename(orig)))
            continue
        if zip_deja_decompresse(source, nom):
            plan.append((p, quarantaine, "doublon", "zip déjà décompressé à côté"))
            continue
        cle = classer(nom, regles)
        if cle is None:
            plan.append((p, reste, "ambigu", "ambigu"))
            continue
        cible = dest.get(cle)
        if cible is None:
            plan.append((p, reste, cle, "pas de destination pour « %s »" % cle))
        elif cible == "QUARANTAINE":
            plan.append((p, quarantaine, cle, "installeur, se retélécharge"))
        elif cible == "AMBIGUS":
            plan.append((p, reste, cle, ""))
        elif cible == "CALIBRE":
            plan.append((p, "CALIBRE", cle, "livre"))
        else:
            plan.append((p, chemin(cible), cle, ""))
    return plan


def executer(plan, cfg, quarantaine, reste, log_extra=None):
    entrees, erreurs = [], 0
    livres = chemin(cfg["destinations"]["livres"]) if cfg["destinations"].get("livres") else os.path.join(reste, "Livres")
    for p, cible, cle, raison in plan:
        nom = os.path.basename(p)
        if not os.path.lexists(p):
            continue
        try:
            if cible == "CALIBRE":
                ok, msg = calibre_ajouter(p, cfg)
                if ok:
                    statut, dst = deplacer(p, quarantaine, eviter_doublon=False)
                    raison = "importé dans Calibre, original en quarantaine"
                else:
                    statut, dst = deplacer(p, livres)
                    raison = "livre (Calibre indisponible)"
            else:
                jumeau = doublon_dans(cible, p) if cible != quarantaine else None
                if jumeau:
                    statut, dst = deplacer(p, quarantaine, eviter_doublon=False)
                    raison = "identique à « %s », déjà rangé" % affiche(jumeau)
                else:
                    statut, dst = deplacer(p, cible, eviter_doublon=(cible != quarantaine))
                    if statut == "deja_la":
                        statut, dst = deplacer(p, quarantaine, eviter_doublon=False)
                        raison = "déjà présent, identique, dans %s" % affiche(cible)
            if dst.startswith(quarantaine + os.sep):
                noter_quarantaine(quarantaine, os.path.basename(dst), p, raison or cle)
            journaliser(p, dst, raison or cle, log_extra)
            entrees.append((time.strftime("%H:%M"), nom, affiche(os.path.dirname(dst)), raison))
        except Exception as e:
            erreurs += 1
            print("! %s : %s" % (nom, e), file=sys.stderr)
    return entrees, erreurs


def ranger(cfg, source=None, min_age=None, plan_seul=False, reste=None, quarantaine=None,
           ponctuel=None, log_extra=None, journal=None):
    """Range une source (ou toutes celles de la config). Renvoie (entrées, erreurs)."""
    regles = compiler(cfg["regles"])
    md = chemin(cfg["journal"]) if journal is None and cfg.get("journal") else (chemin(journal) if journal else None)
    sources = [{"dossier": source}] if source else cfg["sources"]
    toutes, err = [], 0
    for s in sources:
        dossier = chemin(s["dossier"])
        if not os.path.isdir(dossier):
            continue
        q = chemin(quarantaine or s.get("quarantaine") or cfg["quarantaine"])
        r = chemin(reste or s.get("ambigus") or cfg["ambigus"])
        age = cfg.get("delai_heures", 24) if min_age is None else min_age
        exclus = (os.path.basename(md),) if md and os.path.dirname(md) == dossier else ()
        try:
            plan = planifier(dossier, age, regles, cfg["destinations"], r, q, ponctuel or {}, exclus)
        except PermissionError:
            print("Accès refusé à %s : donne l'accès complet au disque à Rangeur.app "
                  "(Réglages Système > Confidentialité et sécurité > Accès complet au disque)." % affiche(dossier))
            continue
        if plan_seul:
            for p, cible, cle, raison in plan:
                print("%-13s %s  →  %s%s" % (cle, os.path.basename(p), "Calibre" if cible == "CALIBRE" else affiche(cible),
                                              ("  (%s)" % raison) if raison else ""))
            continue
        e, n = executer(plan, cfg, q, r, log_extra)
        toutes += e
        err += n
    if not plan_seul:
        ecrire_journal_md(md, toutes, cfg)
    return toutes, err


def annuler(jour):
    if not os.path.exists(JOURNAL_TSV):
        print("Aucun journal.")
        return 0
    with open(JOURNAL_TSV, encoding="utf-8", errors="surrogateescape") as f:
        lignes = [l.rstrip("\n").split("\t") for l in f if l.startswith(jour)]
    n = 0
    for stamp, src, dst, raison in reversed(lignes):
        if src != dst and os.path.lexists(dst) and not os.path.lexists(src):
            os.makedirs(os.path.dirname(src), exist_ok=True)
            os.rename(dst, src)
            n += 1
            print("remis en place :", affiche(src))
    print("%d élément(s) remis en place." % n)
    return n


def main():
    ap = argparse.ArgumentParser(description="Range Téléchargements après un délai, sans rien supprimer.")
    ap.add_argument("--version", action="version", version="rangeur " + __version__)
    ap.add_argument("--config", help="fichier de configuration (défaut : ~/.rangeur/config.json)")
    ap.add_argument("--init-config", action="store_true", help="crée la config à partir de l'exemple intégré")
    ap.add_argument("--plan", action="store_true", help="montre ce qui serait fait, ne bouge rien")
    ap.add_argument("--annuler", metavar="AAAA-MM-JJ")
    ap.add_argument("--noter", nargs="+", metavar="ARG", help="SOURCE DESTINATION [RAISON] : ajoute une ligne au journal")
    ap.add_argument("--source", help="ne ranger que ce dossier")
    ap.add_argument("--min-age", type=float, help="délai en heures (remplace la config)")
    ap.add_argument("--reste", help="dossier des ambigus (remplace la config)")
    ap.add_argument("--quarantaine", help="dossier de quarantaine (remplace la config)")
    ap.add_argument("--ponctuel", help="JSON {nom: [dossier ou QUARANTAINE, raison]} pour un rangement ponctuel")
    ap.add_argument("--dest", action="append", default=[], help="remplace une destination : cle=chemin")
    ap.add_argument("--log", help="journal supplémentaire source<TAB>destination")
    ap.add_argument("--journal", help="fichier du journal lisible ('' = aucun)")
    a = ap.parse_args()
    cfg = charger_config(a.config)
    if a.init_config:
        cible = a.config or os.path.join(STATE, "config.json")
        if os.path.exists(cible):
            print("Existe déjà : " + affiche(cible))
            return
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        with open(cible, "w", encoding="utf-8") as f:
            json.dump(CONFIG_INTEGREE, f, ensure_ascii=False, indent=2)
        print("Config créée : " + affiche(cible))
        return
    if a.annuler:
        annuler(a.annuler)
        return
    if a.noter:
        src, dst = a.noter[0], a.noter[1]
        raison = " ".join(a.noter[2:])
        journaliser(os.path.abspath(src), os.path.abspath(dst), raison)
        ecrire_journal_md(chemin(cfg["journal"]), [(time.strftime("%H:%M"), os.path.basename(src),
                                                     affiche(os.path.dirname(os.path.abspath(dst))), raison)], cfg)
        return
    for kv in a.dest:
        k, v = kv.split("=", 1)
        cfg["destinations"][k] = v
    os.makedirs(STATE, exist_ok=True)
    verrou = open(os.path.join(STATE, "verrou"), "w")
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Un rangement est déjà en cours.")
        return
    ponctuel = {}
    if a.ponctuel:
        with open(a.ponctuel, encoding="utf-8") as f:
            ponctuel = json.load(f)
    entrees, err = ranger(cfg, source=a.source, min_age=a.min_age, plan_seul=a.plan, reste=a.reste,
                          quarantaine=a.quarantaine, ponctuel=ponctuel, log_extra=a.log, journal=a.journal)
    if not a.plan:
        print("%d rangé(s), %d erreur(s)" % (len(entrees), err))


if __name__ == "__main__":
    main()
