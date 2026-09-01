"""Tests import d'une liste de leads depuis un fichier Excel/CSV (source 'import')."""
from __future__ import annotations

import io
import unittest
import zipfile
from unittest.mock import patch

from src import lead_import
from src.lead_import import LeadImportError, parse_leads_file
from src.lead_search import canonical_profile_url


def _csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def _xlsx_inline(rows: list[list[str]]) -> bytes:
    """Construit un .xlsx minimal (chaînes inline) en mémoire."""
    cells_xml = []
    for r, row in enumerate(rows, start=1):
        cols = []
        for c, value in enumerate(row):
            ref = chr(ord("A") + c) + str(r)
            cols.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cols)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells_xml)}</sheetData></worksheet>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


class CsvParsingTest(unittest.TestCase):
    def test_french_excel_export_semicolons_accents_and_bom(self):
        # Export Excel FR typique : BOM, séparateur `;`, en-têtes accentués.
        data = _csv(
            "﻿Prénom;Nom;Poste;Entreprise;URL LinkedIn\n"
            "Camille;Roy;CMO;Acme;https://www.linkedin.com/in/camille-roy\n"
            "Jean;Dupont;CTO;Globex;https://fr.linkedin.com/in/jean-dupont/\n"
        )
        out = parse_leads_file("leads.csv", data)
        self.assertEqual(out["ignored"], 0)
        self.assertEqual(out["rows"], 2)
        self.assertEqual(len(out["leads"]), 2)
        lead = out["leads"][0]
        # Prénom + Nom recombinés ; poste et entreprise fusionnés en headline.
        self.assertEqual(lead["name"], "Camille Roy")
        self.assertEqual(lead["headline"], "CMO · Acme")
        # URL CANONIQUE (dédup avec les autres chemins d'arrivée d'un lead).
        self.assertEqual(lead["profile_url"], "https://www.linkedin.com/in/camille-roy")
        self.assertEqual(
            out["leads"][1]["profile_url"], "https://www.linkedin.com/in/jean-dupont"
        )
        # Un lead importé n'a PAS commenté : aucun signal inventé.
        self.assertIsNone(lead["comment_text"])
        self.assertIsNone(lead["commented_at"])
        self.assertEqual(lead["reaction_count"], 0)

    def test_cp1252_export_is_readable(self):
        # Excel FR sans UTF-8 : accents en cp1252. Un décodage naïf en UTF-8
        # planterait — le client verrait « fichier illisible » sur un export normal.
        data = _csv(
            "Nom;LinkedIn\nJérôme Bélanger;linkedin.com/in/jerome\n", encoding="cp1252"
        )
        out = parse_leads_file("export.csv", data)
        self.assertEqual(out["leads"][0]["name"], "Jérôme Bélanger")

    def test_english_comma_headers(self):
        data = _csv(
            "First Name,Last Name,Title,Company,Profile URL\n"
            "Ada,Lovelace,Engineer,Analytical,https://www.linkedin.com/in/ada\n"
        )
        out = parse_leads_file("leads.csv", data)
        self.assertEqual(out["leads"][0]["name"], "Ada Lovelace")
        self.assertEqual(out["leads"][0]["headline"], "Engineer · Analytical")

    def test_nom_alone_is_a_full_name(self):
        # « Nom » sans « Prénom » à côté = nom complet (usage FR), pas un nom de famille.
        data = _csv("Nom,URL\nMarie Curie,https://www.linkedin.com/in/marie\n")
        out = parse_leads_file("l.csv", data)
        self.assertEqual(out["leads"][0]["name"], "Marie Curie")

    def test_headerless_file_still_imports(self):
        # Fichier sans en-tête : la première ligne porte déjà une URL — toutes
        # les lignes sont des données, l'URL est détectée par son contenu.
        data = _csv(
            "https://www.linkedin.com/in/aaa\n"
            "https://www.linkedin.com/in/bbb\n"
        )
        out = parse_leads_file("urls.csv", data)
        self.assertEqual(len(out["leads"]), 2)
        self.assertEqual(out["rows"], 2)

    def test_rows_without_profile_url_are_counted_never_swallowed(self):
        # Les lignes sans URL valide sont IGNORÉES ET COMPTÉES (« 13 lignes
        # ignorées ») — les avaler ferait passer un fichier à moitié lu pour un
        # import complet. Les lignes vides, elles, ne comptent pas.
        data = _csv(
            "name,url\n"
            "Ok,https://www.linkedin.com/in/ok\n"
            "Sans URL,\n"
            ",,\n"
            "\n"
            "URL entreprise,https://www.linkedin.com/company/acme\n"
        )
        out = parse_leads_file("l.csv", data)
        self.assertEqual(len(out["leads"]), 1)
        self.assertEqual(out["ignored"], 2)  # « Sans URL » + URL d'entreprise
        self.assertEqual(out["rows"], 3)     # les lignes vides n'existent pas

    def test_same_person_under_two_url_shapes_is_one_lead(self):
        # fr.linkedin.com + slash final + tracking : même personne → UN lead.
        # Deux lignes créeraient deux invitations à la même personne.
        data = _csv(
            "url\n"
            "https://fr.linkedin.com/in/jean-dupont/\n"
            "https://www.linkedin.com/in/jean-dupont?trk=public_profile\n"
        )
        out = parse_leads_file("l.csv", data)
        self.assertEqual(len(out["leads"]), 1)

    def test_url_found_in_any_column_row_by_row(self):
        # Fichier hétérogène : l'URL ne vit pas toujours dans la même colonne.
        data = _csv(
            "a,b\n"
            "https://www.linkedin.com/in/left,x\n"
            "y,https://www.linkedin.com/in/right\n"
        )
        out = parse_leads_file("l.csv", data)
        self.assertEqual(len(out["leads"]), 2)
        self.assertEqual(out["ignored"], 0)

    def test_no_profile_url_at_all_is_a_clear_422(self):
        data = _csv("name,email\nAda,ada@example.com\n")
        with self.assertRaises(LeadImportError) as ctx:
            parse_leads_file("l.csv", data)
        self.assertIn("linkedin.com/in/", str(ctx.exception))

    def test_header_only_and_empty_files_fail_clearly(self):
        with self.assertRaises(LeadImportError):
            parse_leads_file("l.csv", _csv("name,url\n"))
        with self.assertRaises(LeadImportError):
            parse_leads_file("l.csv", b"")

    def test_file_over_size_cap_is_refused(self):
        with patch.object(lead_import, "MAX_FILE_BYTES", 100):
            with self.assertRaises(LeadImportError) as ctx:
                parse_leads_file("l.csv", b"a" * 101)
        self.assertIn("volumineux", str(ctx.exception))

    def test_import_is_truncated_at_the_lead_cap(self):
        rows = "url\n" + "".join(
            f"https://www.linkedin.com/in/p{i}\n" for i in range(5)
        )
        with patch.object(lead_import, "MAX_LEADS", 3):
            out = parse_leads_file("l.csv", _csv(rows))
        self.assertEqual(len(out["leads"]), 3)
        self.assertTrue(out["truncated"])

    def test_unreadable_csv_is_a_clean_422_not_a_500(self):
        # `csv` lève une `csv.Error` brute sur une cellule > 128 Ko ou un octet
        # NUL (binaire renommé .csv, export corrompu). Sans garde, l'exception
        # remonte jusqu'à l'endpoint et le client lit « erreur serveur » là où
        # son fichier est simplement illisible.
        for label, data in (
            ("cellule démesurée", b'url\n"' + b"x" * 200_000 + b'"\n'),
            ("octet NUL", b"url\nhttps://www.linkedin.com/in/a\x00b\n"),
        ):
            with self.subTest(label):
                with self.assertRaises(LeadImportError) as ctx:
                    parse_leads_file("l.csv", data)
                self.assertIn("illisible", str(ctx.exception))

    def test_old_xls_binary_is_refused_with_guidance(self):
        with self.assertRaises(LeadImportError) as ctx:
            parse_leads_file("vieux.xls", b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
        self.assertIn(".xlsx", str(ctx.exception))


class ProfileUrlPrefilterTest(unittest.TestCase):
    """Le pré-filtre `/in/`|`/pub/` doit être un SUR-ENSEMBLE strict du parseur.

    Il existe pour la vitesse (la détection de colonne canonicalise chaque
    cellule : 350 000 `urlparse` sur un export de 5 Mo, mesurés à 2,9 s de CPU
    dans la requête d'upload). Mais s'il rejetait ne serait-ce qu'une forme
    d'URL que `canonical_profile_url` accepte, des prospects disparaîtraient de
    l'import SANS AUCUNE ERREUR — exactement la panne muette qu'on veut éviter.
    D'où ce test de parité plutôt qu'un test de vitesse.
    """

    CELLS = [
        "https://www.linkedin.com/in/ada",
        "https://fr.linkedin.com/in/jean-dupont/",
        "http://linkedin.com/in/bob?trk=x",
        "www.linkedin.com/in/carol",
        "linkedin.com/in/dave",
        "https://WWW.LINKEDIN.COM/IN/ERIN",          # casse inversée
        "https://www.linkedin.com/pub/frank/1/2/3",  # ancien format /pub/
        "https://www.linkedin.com/in/clément-géynet-☀️",
        "https://www.linkedin.com/company/acme",     # entreprise : PAS un profil
        "https://www.linkedin.com/posts/activity-123",
        "Ada Lovelace",
        "ada@example.com",
        "Directeur/interim/RH",                      # « /in » sans « /in/ »
        "",
        None,
        "42",
    ]

    def test_prefilter_never_loses_a_profile_the_parser_would_accept(self):
        for cell in self.CELLS:
            with self.subTest(cell=cell):
                self.assertEqual(
                    lead_import._profile_url(cell), canonical_profile_url(cell)
                )


class XlsxParsingTest(unittest.TestCase):
    def test_minimal_xlsx_with_inline_strings(self):
        data = _xlsx_inline(
            [
                ["Nom", "Poste", "LinkedIn"],
                ["Camille Roy", "CMO", "https://www.linkedin.com/in/camille-roy"],
                ["Sans URL", "CEO", ""],
            ]
        )
        out = parse_leads_file("leads.xlsx", data)
        self.assertEqual(len(out["leads"]), 1)
        self.assertEqual(out["leads"][0]["name"], "Camille Roy")
        self.assertEqual(out["leads"][0]["headline"], "CMO")
        self.assertEqual(out["ignored"], 1)

    def test_shared_strings_and_numeric_cells(self):
        # Le vrai Excel range les textes dans sharedStrings (t="s") et laisse
        # les nombres en <v> nu — les deux doivent se lire.
        shared = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">'
            "<si><t>URL</t></si>"
            "<si><t>https://www.linkedin.com/in/ada</t></si>"
            "<si><r><t>Ada </t></r><r><t>Lovelace</t></r></si>"
            "</sst>"
        )
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>'
            "</sheetData></worksheet>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/sharedStrings.xml", shared)
            zf.writestr("xl/worksheets/sheet1.xml", sheet)
        out = parse_leads_file("leads.xlsx", buf.getvalue())
        self.assertEqual(out["leads"][0]["profile_url"], "https://www.linkedin.com/in/ada")

    def test_corrupted_zip_gets_a_clear_message(self):
        with self.assertRaises(LeadImportError) as ctx:
            parse_leads_file("leads.xlsx", b"PK\x03\x04" + b"\x00" * 32)
        self.assertIn("CSV", str(ctx.exception))

    def test_zip_without_worksheet_gets_a_clear_message(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("hello.txt", "pas un classeur")
        with self.assertRaises(LeadImportError):
            parse_leads_file("leads.xlsx", buf.getvalue())


class ImportSourceKeyTest(unittest.TestCase):
    def test_same_bytes_same_key(self):
        # Clé = hash du contenu : re-téléverser LE MÊME fichier retombe sur la
        # même source (dédup (user_id, post_url)) au lieu d'en créer une seconde.
        a = lead_import.import_source_key(b"abc")
        b = lead_import.import_source_key(b"abc")
        c = lead_import.import_source_key(b"abcd")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("import://"))
        self.assertTrue(lead_import.is_import_source_key(a))
        self.assertFalse(lead_import.is_import_source_key("https://www.linkedin.com/in/x"))


class PersistImportTest(unittest.TestCase):
    def test_persists_scores_and_never_debits_credits(self):
        leads = [
            {
                "name": "Ada",
                "headline": "Engineer",
                "profile_url": "https://www.linkedin.com/in/ada",
                "provider_id": None,
                "comment_text": None,
                "commented_at": None,
                "reaction_count": 0,
            }
        ]
        source = {"id": "s1", "post_url": "import://abc"}
        with patch(
            "src.db.save_leads",
            return_value={"inserted": 1, "updated": 0, "skipped": 0, "ids_by_url": {"u": "l1"}},
        ) as save, \
             patch("src.lead_finder._score_leads_for_source") as score, \
             patch("src.db.update_lead_source") as upd, \
             patch("src.db.debit_credits") as debit:
            result = lead_import.persist_import("tok", source, leads, ignored=3, rows=4)

        # Import gratuit : lire un fichier ne coûte rien — comme la recherche.
        debit.assert_not_called()
        score.assert_called_once()
        save.assert_called_once()
        self.assertEqual(result["comments_count"], 1)
        self.assertEqual(result["profiles_count"], 1)
        self.assertEqual(result["ignored_rows"], 3)
        self.assertEqual(result["total_rows"], 4)
        self.assertIsNone(result["credits"])
        # `ids_by_url` reste interne au scoring, jamais renvoyé dans le job.
        self.assertNotIn("ids_by_url", result["leads"])
        # La source garde la trace de la collecte (compteur + date).
        self.assertEqual(upd.call_args[0][2]["comments_count"], 1)
        self.assertIn("collected_at", upd.call_args[0][2])


class ImportJobRoutingTest(unittest.TestCase):
    """Un job/une source `import` ne doit JAMAIS partir sur Apify ni Unipile.

    Le fichier n'existe plus côté serveur : la « recollecte » d'une source import
    par le chemin générique doit échouer NET avec un message actionnable, pas
    scraper les « commentaires » d'une URL `import://…` (la panne silencieuse
    de #407, en pire).
    """

    def _run(self, job, source):
        from src import jobs

        with patch("src.db.get_lead_collection_job", return_value=job), \
             patch("src.db.get_lead_collection_job_status", return_value="running"), \
             patch("src.db.update_lead_collection_job") as upd, \
             patch("src.db.get_lead_source", return_value=source), \
             patch("src.lead_search.collect_and_persist_search") as search, \
             patch("src.jobs._collect_and_persist_guarded") as comments:
            jobs.process_lead_collection_job("tok", "j1")
        return upd, search, comments

    def test_import_job_kind_is_refused_cleanly(self):
        upd, search, comments = self._run(
            {"id": "j1", "source_id": "s1", "kind": "import", "max_comments": 10},
            {"id": "s1", "post_url": "import://abc", "kind": "import"},
        )
        search.assert_not_called()
        comments.assert_not_called()
        last = upd.call_args
        self.assertEqual(last.kwargs.get("status"), "error")
        self.assertIn("re-téléverse", last.kwargs.get("error", ""))

    def test_source_kind_saves_the_day_when_the_job_kind_is_missing(self):
        # Le piège de projection (cf. `_LEAD_JOB_COLS`) : job relu SANS `kind`.
        # La nature de la source doit suffire à refuser.
        upd, search, comments = self._run(
            {"id": "j1", "source_id": "s1", "max_comments": 10},
            {"id": "s1", "post_url": "import://abc", "kind": "import"},
        )
        search.assert_not_called()
        comments.assert_not_called()
        self.assertEqual(upd.call_args.kwargs.get("status"), "error")


class ProcessLeadImportJobTest(unittest.TestCase):
    def _leads(self):
        return [{"profile_url": "https://www.linkedin.com/in/a"}]

    def test_success_writes_done_with_result(self):
        from src import jobs

        with patch("src.db.get_lead_collection_job_status", return_value="running"), \
             patch("src.db.update_lead_collection_job") as upd, \
             patch("src.lead_import.persist_import", return_value={"comments_count": 1}) as persist:
            jobs.process_lead_import_job("tok", "j1", {"id": "s1"}, self._leads(), 0, 1)
        persist.assert_called_once()
        self.assertEqual(upd.call_args.kwargs.get("status"), "done")
        self.assertEqual(upd.call_args.kwargs.get("result"), {"comments_count": 1})

    def test_cancelled_job_is_never_overwritten(self):
        from src import jobs

        with patch("src.db.get_lead_collection_job_status", return_value="cancelled"), \
             patch("src.db.update_lead_collection_job") as upd, \
             patch("src.lead_import.persist_import") as persist:
            jobs.process_lead_import_job("tok", "j1", {"id": "s1"}, self._leads(), 0, 1)
        persist.assert_not_called()
        upd.assert_not_called()

    def test_failure_is_isolated_into_the_job_error(self):
        from src import jobs

        with patch("src.db.get_lead_collection_job_status", return_value="running"), \
             patch("src.db.update_lead_collection_job") as upd, \
             patch("src.lead_import.persist_import", side_effect=RuntimeError("boom")):
            jobs.process_lead_import_job("tok", "j1", {"id": "s1"}, self._leads(), 0, 1)
        self.assertEqual(upd.call_args.kwargs.get("status"), "error")
        self.assertIn("boom", upd.call_args.kwargs.get("error", ""))


if __name__ == "__main__":
    unittest.main()
