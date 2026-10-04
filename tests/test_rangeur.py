"""Tests du rangeur : python3 -m unittest discover -s tests"""
import datetime, os, shutil, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rangeur as R


class TestRangeur(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dl = os.path.join(self.tmp, "Downloads")
        os.makedirs(self.dl)
        R.STATE = os.path.join(self.tmp, "etat")
        R.JOURNAL_TSV = os.path.join(R.STATE, "journal.tsv")
        self.cfg = R.charger_config(os.path.join(self.tmp, "absente.json"))
        self.cfg.update({"sources": [{"dossier": self.dl}], "journal": os.path.join(self.dl, "_journal.md"),
                         "ambigus": os.path.join(self.tmp, "ambigus"), "quarantaine": os.path.join(self.tmp, "quarantaine"),
                         "calibre": None})
        self.cfg["destinations"] = {k: (v if v in R.SPECIAUX else os.path.join(self.tmp, k))
                                    for k, v in self.cfg["destinations"].items()}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ecrire(self, nom, contenu=b"contenu"):
        p = os.path.join(self.dl, nom)
        with open(p, "wb") as f:
            f.write(contenu)
        return p

    def d(self, *parts):
        return os.path.join(self.tmp, *parts)

    def test_delai_respecte(self):
        self.ecrire("bulletin-de-paie-aout-2026.pdf")
        R.ranger(self.cfg, min_age=1)
        self.assertTrue(os.path.exists(os.path.join(self.dl, "bulletin-de-paie-aout-2026.pdf")))

    def test_classement_et_journal(self):
        self.ecrire("bulletin-de-paie-aout-2026.pdf")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("paie", "bulletin-de-paie-aout-2026.pdf")))
        journal = open(os.path.join(self.dl, "_journal.md"), encoding="utf-8").read()
        self.assertIn("bulletin-de-paie-aout-2026.pdf", journal)
        self.assertTrue(os.path.exists(os.path.join(self.dl, "_journal.md")), "le journal reste en place")

    def test_ambigu(self):
        self.ecrire("A700000006636809.pdf")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("ambigus", "A700000006636809.pdf")))

    def test_doublon_exact_en_quarantaine(self):
        self.ecrire("note.txt", b"meme")
        self.ecrire("note 2.txt", b"meme")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("quarantaine", "note 2.txt")))
        self.assertTrue(os.path.exists(self.d("ambigus", "note.txt")))
        self.assertIn("note 2.txt", open(self.d("quarantaine", "INDEX.md"), encoding="utf-8").read())

    def test_jamais_d_ecrasement(self):
        os.makedirs(self.d("paie"))
        with open(self.d("paie", "bulletin-de-paie-mai.pdf"), "wb") as f:
            f.write(b"ancien")
        self.ecrire("bulletin-de-paie-mai.pdf", b"nouveau")
        R.ranger(self.cfg, min_age=0)
        self.assertEqual(open(self.d("paie", "bulletin-de-paie-mai.pdf"), "rb").read(), b"ancien")
        self.assertEqual(open(self.d("paie", "bulletin-de-paie-mai (2).pdf"), "rb").read(), b"nouveau")

    def test_installeur_en_quarantaine(self):
        self.ecrire("Outil-1.0.dmg")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("quarantaine", "Outil-1.0.dmg")))

    def test_zip_deja_decompresse(self):
        os.makedirs(os.path.join(self.dl, "pack"))
        with open(os.path.join(self.dl, "pack", "a.txt"), "w") as f:
            f.write("abc")
        with zipfile.ZipFile(os.path.join(self.dl, "pack.zip"), "w") as z:
            z.writestr("a.txt", "abc")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("quarantaine", "pack.zip")))

    def test_annulation(self):
        self.ecrire("bulletin-de-paie-juin.pdf")
        R.ranger(self.cfg, min_age=0)
        R.annuler(datetime.date.today().isoformat())
        self.assertTrue(os.path.exists(os.path.join(self.dl, "bulletin-de-paie-juin.pdf")))

    def test_variables_de_date(self):
        aujourd = datetime.date.today()
        self.assertTrue(R.chemin("~/X/{annee}-{mois}").endswith("/X/%04d-%02d" % (aujourd.year, aujourd.month)))

    def test_regles_en_plus_prioritaires(self):
        cfg_json = os.path.join(self.tmp, "c.json")
        with open(cfg_json, "w", encoding="utf-8") as f:
            f.write('{"regles_en_plus": [["perso", "projet-x"]], "destinations": {"perso": "~/Perso"}}')
        cfg = R.charger_config(cfg_json)
        self.assertEqual(R.classer("facture projet-x.pdf", R.compiler(cfg["regles"])), "perso")

    def test_commande_externe(self):
        script = os.path.join(self.tmp, "ranger-capture.sh")
        cible = os.path.join(self.tmp, "captures-renommees")
        with open(script, "w") as f:
            f.write('#!/bin/sh\nmkdir -p "%s"\nmv "$1" "%s/renommee.png" && echo "%s/renommee.png"\n' % (cible, cible, cible))
        os.chmod(script, 0o755)
        self.cfg["commandes"] = {"capture": script}
        self.ecrire("Capture d’écran 2026-10-05 à 10.00.00.png")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(os.path.join(cible, "renommee.png")))
        self.assertIn("captures-renommees", open(os.path.join(self.dl, "_journal.md"), encoding="utf-8").read())

    def test_commande_en_echec_range_normalement(self):
        self.cfg["commandes"] = {"capture": "/bin/false"}
        self.ecrire("Capture d’écran 2026-10-05 à 11.00.00.png")
        R.ranger(self.cfg, min_age=0)
        self.assertTrue(os.path.exists(self.d("capture", "Capture d’écran 2026-10-05 à 11.00.00.png")))

if __name__ == "__main__":
    unittest.main()
