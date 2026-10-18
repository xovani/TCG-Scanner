import io
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app import create_app
from scanner.catalog import Catalog, CatalogError
from scanner.recognition import ImageError, collector_numbers, decode_image, rank_cards

CARDS = [
    {"id": "base1-58", "name": "Pikachu", "localId": "58"},
    {"id": "sv2-25", "name": "Pikachu", "localId": "25"},
    {"id": "sv8-238", "name": "Pikachu ex", "localId": "238"},
    {"id": "base1-4", "name": "Charizard", "localId": "4"},
]


class RecognitionTests(unittest.TestCase):
    def test_number_from_footer_disambiguates_editions(self):
        lines = [{"text": "BÁSICO Pikachu HP 60", "y": .06}, {"text": "025/165", "y": .94}]
        results = rank_cards(CARDS, lines=lines)
        self.assertEqual(results[0]["id"], "sv2-25")
        self.assertTrue(results[0]["number_match"])

    def test_ex_suffix_is_preserved(self):
        results = rank_cards(CARDS, lines=[{"text": "Pikachu ex", "y": .08}])
        self.assertEqual(results[0]["id"], "sv8-238")

    def test_manual_number_filters_candidates(self):
        results = rank_cards(CARDS, name="Pikachu", number="058/102")
        self.assertEqual([card["id"] for card in results], ["base1-58"])

    def test_attack_text_cannot_supply_card_name(self):
        self.assertEqual(rank_cards(CARDS, lines=[{"text": "Pikachu", "y": .60}]), [])

    def test_blank_image_and_promo_number(self):
        self.assertEqual(rank_cards(CARDS, lines=[]), [])
        self.assertEqual(collector_numbers("TG01/TG30"), {"tg01"})

    def test_decode_rejects_non_image(self):
        with self.assertRaises(ImageError):
            decode_image(b"not a photo")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_home_qr_and_upload_errors(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/qr.png").status_code, 404)
        self.assertEqual(self.client.post("/api/scan").status_code, 400)
        response = self.client.post("/api/scan", data={"image": (io.BytesIO(b"bad"), "card.jpg")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json)

    def test_default_access_stays_on_this_computer(self):
        with patch("app.local_address", side_effect=AssertionError("Não deve consultar a rede")):
            client = create_app(port=5050).test_client()
            self.assertEqual(client.get("/api/access").json,
                             {"url": "http://127.0.0.1:5050", "mode": "local"})
            page = client.get("/").get_data(as_text=True)
        self.assertNotIn('src="/qr.png"', page)
        self.assertIn("Uso somente neste computador", page)

    def test_network_mode_remains_available_explicitly(self):
        with patch("app.local_address", return_value="192.168.2.10"):
            client = create_app(network_access=True, port=5000).test_client()
            self.assertEqual(client.get("/api/access").json,
                             {"url": "http://192.168.2.10:5000", "mode": "network"})
            self.assertEqual(client.get("/qr.png").mimetype, "image/png")

    def test_search_and_language_validation(self):
        with patch("app.catalog.cards", return_value=(CARDS, False)):
            response = self.client.get("/api/search?name=Pikachu&number=25&language=pt")
            self.assertEqual(response.json["matches"][0]["id"], "sv2-25")
        self.assertEqual(self.client.get("/api/search?name=Pikachu&language=xx").status_code, 400)

    def test_ocr_text_survives_catalog_outage(self):
        image = io.BytesIO()
        Image.new("RGB", (500, 700), "white").save(image, "JPEG")
        image.seek(0)
        with patch("app.reader.read", return_value=[{"text": "Pikachu", "y": .1}]), \
             patch("app.catalog.cards", side_effect=CatalogError("Offline")):
            response = self.client.post("/api/scan", data={"image": (image, "photo.jpg")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["text"], "Pikachu")
        self.assertEqual(response.json["matches"], [])

    def test_oversized_upload(self):
        response = self.client.post("/api/scan", data=b"x" * (12 * 1024 * 1024 + 1),
                                    content_type="application/octet-stream")
        self.assertEqual(response.status_code, 413)

    def test_catalog_uses_stale_cache_on_outage(self):
        import json
        import os
        import requests
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(folder)
            cache = catalog.cache_dir / "catalog-pt.json"
            cache.write_text(json.dumps(CARDS), encoding="utf-8")
            os.utime(cache, (1, 1))
            with patch("scanner.catalog.requests.get", side_effect=requests.ConnectionError):
                cards, stale = catalog.cards("pt")
            self.assertEqual(cards, CARDS)
            self.assertTrue(stale)


if __name__ == "__main__":
    unittest.main()
