"""Parsertests op echte TED-aankondigingen (fixtures uit de officiële dagpakketten)."""

import unittest
from pathlib import Path

from tenders import config
from tenders.ted import Candidate, parse_notice

FIX = Path(__file__).parent / "fixtures"


def parse(name, pn, date="2024-01-01", notice_type="can-standard"):
    return parse_notice((FIX / f"ted_{name}.xml").read_bytes(), pn, notice_type, date)


class EformsTest(unittest.TestCase):
    def test_single_winner_out_of_seven_tenders(self):
        # 7 inschrijvers, enkel de combinatie Bemat-Moury wint
        [a] = parse("741513-2023", "741513-2023")
        self.assertEqual(a.winnaar, "SM BEMAT MOURY")
        self.assertEqual(a.bedrag_excl_btw, 5308002.61)
        self.assertEqual(a.datum_gunning, "2023-11-21")
        self.assertEqual(a.ondernemingsnummer, "0402.375.301")
        self.assertFalse(a.is_combinatie)  # combinatie van twee groepsbedrijven = 100 % groep
        self.assertEqual(a.looptijd_maanden, 10.1)  # 220 werkdagen
        self.assertEqual(a.bron_id, "741513-2023/TEN-0006")
        self.assertEqual(a.publicatiedatum, "2024-01-01")  # doorgegeven publicatiedatum

    def test_multi_lot_only_group_lot_counted(self):
        # 5 percelen met verschillende winnaars; totaal 6,8 mln, Moury enkel perceel 1
        [a] = parse("219449-2025", "219449-2025")
        self.assertEqual(a.winnaar, "Entreprises Gilles Moury")
        self.assertEqual(a.bedrag_excl_btw, 5192853.13)
        self.assertFalse(a.is_combinatie)


class LegacyTest(unittest.TestCase):
    def test_legacy_f03(self):
        [a] = parse("58196-2018", "58196-2018", "2018-02-08")
        self.assertEqual(a.opdrachtgever, "CHC ASBL")
        self.assertEqual(a.bedrag_excl_btw, 6473500.76)
        self.assertEqual(a.datum_gunning, "2017-07-10")
        self.assertTrue(a.is_combinatie)  # "A.M." = association momentanée


class ConfigTest(unittest.TestCase):
    def test_names(self):
        for n in ["BEMAT S.A.", "Les Entreprises Gilles MOURY SA", "D-FI s.a.", "SSM BEMAT SA - LIXON SA"]:
            self.assertTrue(config.is_group_member(n), n)
        for n in ["MOURY CPC", "Franki", "Moury Promotion"]:
            self.assertFalse(config.is_group_member(n), n)
        self.assertTrue(config.is_group_member("X", "BE 0403.907.307"))

    def test_external_partner(self):
        h = config.has_external_partner
        for names in (["SM BEMAT MOURY"], ["SA Bemat", "SA Moury"], ["Les Entreprises Gilles Moury SA"],
                      ["Bétons et Matériaux, en abrégé BEMAT S.A."], ["D-FI s.a."]):
            self.assertFalse(h(names), names)
        for names in (["SSM MOURY - FRANKI"], ["BEMAT S.A.", "DUCHENE S.A."], ["Association Duchêne Moury"],
                      ["A.M. Galère CFE Cit Blaton Moury Maquet"], ["SM BERNARD / MOURY"]):
            self.assertTrue(h(names), names)

    def test_supabase_url(self):
        from tenders.store import normalize_base_url as n
        for raw in ("https://abc.supabase.co", "https://abc.supabase.co/", "https://abc.supabase.co/rest/v1",
                    " https://abc.supabase.co/rest/v1/ \n"):
            self.assertEqual(n(raw), "https://abc.supabase.co", raw)
        with self.assertRaises(ValueError):
            n("https://abc.supabase.co/project/settings")

    def test_key_role(self):
        import base64, json
        from tenders.store import Supabase, key_role

        def jwt(role):
            enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
            return f"{enc({'alg': 'HS256'})}.{enc({'role': role})}.sig"

        self.assertEqual(key_role(jwt("service_role")), "service_role")
        self.assertEqual(key_role(jwt("anon")), "anon")
        self.assertEqual(key_role("sb_secret_abc"), "secret")
        self.assertEqual(key_role("sb_publishable_abc"), "publishable")
        with self.assertRaises(ValueError):
            Supabase("https://abc.supabase.co", jwt("anon"))
        with self.assertRaises(ValueError):
            Supabase("https://abc.supabase.co", "sb_publishable_abc")
        Supabase("https://abc.supabase.co", jwt("service_role"))

    def test_package_id(self):
        self.assertEqual(Candidate("58196-2018", "2018-02-08", "can-standard", "27/2018").package_id, "201800027")


if __name__ == "__main__":
    unittest.main()
