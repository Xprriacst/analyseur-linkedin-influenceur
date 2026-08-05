"""Photo d'annonce dans la génération (fix « l'image ne se télécharge plus »).

Deux protections verrouillées ici :

1. `_first_img_src` (repli quand `og:image` manque) ne doit jamais retenir un
   placeholder de lazy-loading (`data:image/svg+xml…`) : c'est lui qui faisait
   échouer toute la lecture sur « Lien non supporté » alors que la page avait
   de vraies photos.

2. `cached_listing_preview` : le parcours guidé lit la même annonce jusqu'à
   trois fois (rôle → structures → lancement). Le mémo doit éviter de
   retélécharger la page — mais ne JAMAIS mémoriser un échec (un blocage
   passager ne doit pas coller pendant 10 minutes).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import listing
from src.listing import ListingError, _first_img_src, build_listing_topic, cached_listing_preview


class FirstImgSrcTest(unittest.TestCase):
    def test_ignore_les_placeholders_data_uri(self):
        html = (
            '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" alt="flou" />'
            '<img src="https://cdn.example.com/photo.jpg" alt="bien" />'
        )
        self.assertEqual(_first_img_src(html), "https://cdn.example.com/photo.jpg")

    def test_aucune_vraie_image_rend_none(self):
        html = '<img src="data:image/gif;base64,R0lGOD=" />'
        self.assertIsNone(_first_img_src(html))

    def test_image_relative_acceptee(self):
        """Une URL relative est légitime : elle sera absolutisée par urljoin en aval."""
        self.assertEqual(_first_img_src('<img src="/img/photo.jpg" />'), "/img/photo.jpg")


class CachedListingPreviewTest(unittest.TestCase):
    def setUp(self):
        listing._preview_cache.clear()

    def tearDown(self):
        listing._preview_cache.clear()

    def test_memoise_la_lecture_pendant_le_parcours(self):
        """Rôle → structures → lancement : une seule lecture de l'annonce."""
        preview = {"source_url": "https://ex.com/a", "image_url": "https://ex.com/p.jpg", "title": "Loft"}
        with patch.object(listing, "fetch_listing_preview", return_value=preview) as fetch:
            first = cached_listing_preview("https://ex.com/a")
            second = cached_listing_preview("https://ex.com/a ")  # espace = même annonce
        fetch.assert_called_once()
        self.assertEqual(first, preview)
        self.assertEqual(second, preview)

    def test_un_echec_n_est_pas_memorise(self):
        """Blocage passager du site : le prochain essai doit vraiment réessayer."""
        preview = {"source_url": "https://ex.com/a", "image_url": "https://ex.com/p.jpg"}
        with patch.object(
            listing, "fetch_listing_preview",
            side_effect=[ListingError("bloqué"), preview],
        ) as fetch:
            with self.assertRaises(ListingError):
                cached_listing_preview("https://ex.com/a")
            self.assertEqual(cached_listing_preview("https://ex.com/a"), preview)
        self.assertEqual(fetch.call_count, 2)

    def test_deux_annonces_distinctes_ne_partagent_pas_le_memo(self):
        with patch.object(
            listing, "fetch_listing_preview",
            side_effect=lambda url, **kw: {"source_url": url},
        ):
            a = cached_listing_preview("https://ex.com/a")
            b = cached_listing_preview("https://ex.com/b")
        self.assertNotEqual(a["source_url"], b["source_url"])


class BuildListingTopicTest(unittest.TestCase):
    def test_le_sujet_porte_les_faits_du_bien(self):
        topic = build_listing_topic({
            "title": "Loft 3 pièces — Bordeaux",
            "price": "450000 EUR",
            "surface": "92 m²",
            "rooms": "3",
            "location": "Bordeaux, 33000",
            "description": "Loft lumineux proche des quais.",
        })
        for fragment in ("Loft 3 pièces", "450000 EUR", "92 m²", "3 pièces", "Bordeaux, 33000", "quais"):
            self.assertIn(fragment, topic)


if __name__ == "__main__":
    unittest.main()
