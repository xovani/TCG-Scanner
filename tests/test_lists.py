import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from app import create_app
from scanner.identification import card_metadata, identify
from scanner.lists import ListError, ListStore, export_text
from scanner.recognition import rank_cards

CARD = {"id": "sv03-125", "localId": "125", "name": "Charizard ex", "image": "https://assets.tcgdex.net/en/sv/sv03/125"}
OTHER = {"id": "sv04-125", "localId": "125", "name": "Charizard ex"}
EXPANSION = {"id": "sv03", "name": "Obsidian Flames", "abbreviation": {"official": "OBF"}, "cardCount": {"official": 197}}
DETAIL = {**CARD, "category": "Pokemon", "set": {"id": "sv03", "name": "Obsidian Flames"}}
METADATA = {"card_id": CARD["id"], "name": "Charizard ex", "export_name": "Charizard ex", "category": "Pokemon",
            "set_id": "sv03", "set_name": "Obsidian Flames", "set_code": "OBF", "number": "125", "language": "en"}
LINES = [{"text": "Charizard ex", "y": .06}, {"text": "OBF EN 125/197", "y": .93}]


def fake_catalog():
    catalog = Mock()
    catalog.cards.return_value = ([CARD, OTHER], False)
    catalog.detail.return_value = DETAIL
    catalog.set_detail.side_effect = lambda lang, set_id: EXPANSION if set_id == "sv03" else {
        "id": set_id, "name": "Other Set", "tcgOnline": "OTH", "cardCount": {"official": 182}}
    return catalog


def promo_catalog():
    catalog = fake_catalog()
    catalog.detail.return_value = {"id": "mep-087", "name": "Binacle", "localId": "087", "category": "Pokemon",
                                   "set": {"id": "mep", "name": "Mega Evolution Promos", "cardCount": {"official": 0}}}
    catalog.set_detail.side_effect = None
    # Mesmo um total cadastrado para uma coleção aberta não é denominador impresso.
    catalog.set_detail.return_value = {"id": "mep", "name": "Mega Evolution Promos", "abbreviation": {"official": "MEP"},
                                       "cardCount": {"official": 150, "total": 150}}
    return catalog


class IdentificationTests(unittest.TestCase):
    def test_set_code_resolves_same_name_and_number(self):
        matches = rank_cards([CARD, OTHER], lines=LINES)
        selected, _ = identify(matches, LINES, fake_catalog(), "en")
        self.assertEqual(selected["id"], CARD["id"])

    def test_denominator_can_resolve_without_code(self):
        lines = [{"text": "Charizard ex", "y": .06}, {"text": "125/197", "y": .93}]
        selected, _ = identify(rank_cards([CARD, OTHER], lines=lines), lines, fake_catalog(), "en")
        self.assertEqual(selected["id"], CARD["id"])

    def test_ambiguous_editions_are_never_auto_selected(self):
        catalog = fake_catalog()
        catalog.set_detail.side_effect = lambda lang, set_id: {**EXPANSION, "id": set_id}
        lines = [{"text": "Charizard ex", "y": .06}, {"text": "125/197", "y": .93}]
        selected, _ = identify(rank_cards([CARD, OTHER], lines=lines), lines, catalog, "en")
        self.assertIsNone(selected)

    def test_code_and_denominator_conflict_never_adds(self):
        lines = [{"text": "Charizard ex", "y": .06}, {"text": "OBF EN 125/100", "y": .93}]
        selected, _ = identify(rank_cards([CARD], lines=lines), lines, fake_catalog(), "en")
        self.assertIsNone(selected)

    def test_missing_number_does_not_auto_select(self):
        lines = [{"text": "Charizard ex", "y": .06}]
        selected, _ = identify(rank_cards([CARD], lines=lines), lines, fake_catalog(), "en")
        self.assertIsNone(selected)

    def test_conflicting_code_does_not_fall_back_to_another_set(self):
        lines = [{"text": "Charizard ex", "y": .06}, {"text": "OBF EN 125/182", "y": .93}]
        selected, _ = identify(rank_cards([CARD, OTHER], lines=lines), lines, fake_catalog(), "en")
        self.assertIsNone(selected)

    def test_promo_number_with_code_without_fraction(self):
        card = {"id": "svp-001", "name": "Pikachu", "localId": "001"}
        lines = [{"text": "Pikachu", "y": .05}, {"text": "SVP PT 001", "y": .9}]
        catalog = Mock()
        catalog.set_detail.return_value = {"id": "svp", "name": "Promos", "abbreviation": {"official": "SVP"}}
        selected, _ = identify(rank_cards([card], lines=lines), lines, catalog, "pt")
        self.assertEqual(selected["id"], "svp-001")

    def test_metadata_uses_english_and_removes_numeric_padding(self):
        catalog = fake_catalog()
        english = {**DETAIL, "localId": "025", "name": "Professor's Research", "category": "Trainer"}
        localized = {**english, "name": "Pesquisa de Professores"}
        catalog.detail.side_effect = lambda lang, card_id: english if lang == "en" else localized
        result = card_metadata(catalog, "pt", CARD["id"])
        self.assertEqual(result["export_name"], "Professor's Research")
        self.assertEqual(result["name"], "Pesquisa de Professores")
        self.assertEqual(result["set_code"], "OBF")
        self.assertEqual(result["number"], "25")
        self.assertEqual(result["set_total"], 197)
        self.assertEqual(result["liga_name"], "Professor's Research")

    def test_basic_energy_is_exported_with_live_symbol(self):
        catalog = fake_catalog()
        catalog.detail.return_value = {**DETAIL, "name": "Lightning Energy", "category": "Energy"}
        self.assertEqual(card_metadata(catalog, "en", CARD["id"])["export_name"], "Basic {L} Energy")

    def test_promo_preserves_printed_number_for_liga_only(self):
        result = card_metadata(promo_catalog(), "en", "mep-087")
        self.assertTrue(result["liga_promo"])
        self.assertEqual(result["liga_number"], "087")
        self.assertEqual(result["number"], "87")
        self.assertEqual(export_text({"items": [{**result, "quantity": 4}]}, "liga"), "4 Binacle (087/∞)\n")
        self.assertIn("4 Binacle MEP 87", export_text({"items": [{**result, "quantity": 4}]}, "tcglive"))

    def test_regular_collection_is_not_promotional(self):
        result = card_metadata(fake_catalog(), "en", CARD["id"])
        self.assertFalse(result["liga_promo"])
        self.assertEqual(export_text({"items": [{**result, "quantity": 2}]}, "liga"), "2 Charizard ex (125/197)\n")


class ListTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "lists.sqlite3"
        self.store = ListStore(self.path)

    def test_multiple_lists_persistence_and_quantity(self):
        first = self.store.create("Deck 1")
        second = self.store.create("Deck 2")
        self.store.add(first["id"], METADATA, 2, "scan-first")
        self.store.add(first["id"], METADATA, 1, "scan-next")
        self.store.add(second["id"], METADATA, 4, "scan-first")
        reloaded = ListStore(self.path)
        self.assertEqual(reloaded.get(first["id"])["total"], 3)
        self.assertEqual(reloaded.get(second["id"])["total"], 4)
        self.assertEqual(reloaded.rename(first["id"], "Novo nome")["name"], "Novo nome")
        self.assertEqual(reloaded.update_quantity(first["id"], CARD["id"], 0)["total"], 0)

    def test_retried_scan_is_idempotent_across_restart(self):
        deck = self.store.create("Deck")
        self.assertTrue(self.store.add(deck["id"], METADATA, 1, "same-photo"))
        self.assertFalse(ListStore(self.path).add(deck["id"], METADATA, 1, "same-photo"))
        self.assertEqual(self.store.get(deck["id"])["total"], 1)

    def test_delete_removes_only_target_list_and_related_rows(self):
        first = self.store.create("Apagar")
        second = self.store.create("Manter")
        self.store.add(first["id"], METADATA, 2, "first-token")
        self.store.add(second["id"], METADATA, 5, "second-token")
        selected = self.store.delete(first["id"])
        self.assertEqual(selected["id"], second["id"])
        self.assertEqual(selected["total"], 5)
        self.assertEqual(len(self.store.all()), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items WHERE list_id = ?", (first["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM additions WHERE list_id = ?", (first["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM additions WHERE list_id = ?", (second["id"],)).fetchone()[0], 1)

    def test_delete_last_list_creates_new_empty_list(self):
        original = self.store.create("Última")
        self.store.add(original["id"], METADATA, 3, "last-token")
        replacement = self.store.delete(original["id"])
        self.assertNotEqual(replacement["id"], original["id"])
        self.assertEqual(replacement["total"], 0)
        self.assertEqual(replacement["items"], [])
        self.assertEqual(len(self.store.all()), 1)

    def test_delete_unknown_list_does_not_change_existing_lists(self):
        original = self.store.create("Manter")
        with self.assertRaises(ListError):
            self.store.delete("missing-list")
        self.assertEqual([row["id"] for row in self.store.all()], [original["id"]])

    def test_concurrent_retries_add_once(self):
        from concurrent.futures import ThreadPoolExecutor
        deck = self.store.create("Deck")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.add(deck["id"], METADATA, 1, "same-photo"), range(4)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.get(deck["id"])["total"], 1)

    def test_invalid_quantities_do_not_corrupt_list(self):
        deck = self.store.create("Deck")
        self.store.add(deck["id"], METADATA, 999, "first-read")
        with self.assertRaises(ListError):
            self.store.add(deck["id"], METADATA, 1, "overflow-read")
        for value in (-1, 1.5, True, "4"):
            with self.assertRaises(ListError):
                self.store.update_quantity(deck["id"], CARD["id"], value)
        self.assertEqual(self.store.get(deck["id"])["total"], 999)

    def test_exports_preserve_categories_counts_and_codes(self):
        items = [{**METADATA, "quantity": 4},
                 {**METADATA, "export_name": "Arven", "category": "Trainer", "number": "166", "quantity": 3},
                 {**METADATA, "export_name": "Basic {R} Energy", "category": "Energy", "set_code": "SVE", "number": "2", "quantity": 8}]
        deck = {"items": items}
        live = export_text(deck, "tcglive")
        self.assertIn("Pokémon: 1\n4 Charizard ex OBF 125", live)
        self.assertIn("Trainer: 1\n3 Arven OBF 166", live)
        self.assertIn("Total Cards: 15", live)
        limitless = export_text(deck, "limitless")
        self.assertEqual(live, limitless)

    def test_liga_uses_official_total_without_headers_or_set_code(self):
        item = {**METADATA, "liga_name": "Dragapult ex", "number": "130", "set_total": 167,
                "quantity": 4, "set_code": "", "category": ""}
        self.assertEqual(export_text({"items": [item]}, "liga"), "4 Dragapult ex (130/167)\n")
        item.update(liga_name="Charizard ex", number="223", set_total=197)
        self.assertEqual(export_text({"items": [item]}, "liga"), "4 Charizard ex (223/197)\n")

    def test_liga_preserves_prefix_and_raw_energy_name(self):
        items = [{**METADATA, "liga_name": "Pikachu", "number": "TG05", "set_total": 30, "quantity": 1},
                 {**METADATA, "liga_name": "Lightning Energy", "export_name": "Basic {L} Energy", "number": "4", "set_total": 8, "quantity": 9}]
        self.assertEqual(export_text({"items": items}, "liga"), "1 Pikachu (TG05/030)\n9 Lightning Energy (004/008)\n")

    def test_liga_pads_card_and_set_numbers_for_existing_items(self):
        items = [{**METADATA, "liga_name": "Mienfoo", "liga_number": "52", "number": "52", "set_total": 86, "quantity": 1},
                 {**METADATA, "liga_name": "Jett", "number": "79", "set_total": 84, "quantity": 1},
                 {**METADATA, "liga_name": "Binacle", "liga_number": "87", "liga_promo": True, "quantity": 1}]
        self.assertEqual(export_text({"items": items}, "liga"),
                         "1 Mienfoo (052/086)\n1 Jett (079/084)\n1 Binacle (087/∞)\n")
        # A correção é de apresentação: não altera os números usados no Live ou quantidades salvas.
        self.assertEqual(items[0]["number"], "52")
        self.assertEqual(items[0]["quantity"], 1)

    def test_liga_preserves_existing_padding_and_long_numbers(self):
        item = {**METADATA, "liga_name": "Pikachu", "liga_number": "0052", "set_total": 1000, "quantity": 1}
        self.assertEqual(export_text({"items": [item]}, "liga"), "1 Pikachu (0052/1000)\n")

    def test_liga_does_not_invent_missing_or_zero_denominator(self):
        for total in (None, 0, -1):
            with self.assertRaises(ListError):
                export_text({"items": [{**METADATA, "liga_name": "Pikachu", "quantity": 1, "set_total": total}]}, "liga")

    def test_export_does_not_invent_missing_codes(self):
        with self.assertRaises(ListError):
            export_text({"items": [{**METADATA, "quantity": 1, "set_code": ""}]}, "tcglive")


class ListApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.client = create_app(database_path=Path(self.folder.name) / "lists.sqlite3").test_client()
        self.deck = self.client.post("/api/lists", json={"name": "Meu deck"}).json

    def photo(self, token="unique-photo"):
        image = io.BytesIO()
        Image.new("RGB", (500, 700), "white").save(image, "JPEG")
        image.seek(0)
        return self.client.post("/api/scan", data={"language": "en", "list_id": self.deck["id"],
                    "quantity": "2", "token": token, "image": (image, "card.jpg")})

    def test_delete_endpoint_returns_replacement_and_rejects_deleted_id(self):
        result = self.client.delete(f"/api/lists/{self.deck['id']}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["deleted_id"], self.deck["id"])
        self.assertNotEqual(result.json["list"]["id"], self.deck["id"])
        self.assertEqual(result.json["list"]["items"], [])
        self.assertEqual(self.client.get(f"/api/lists/{self.deck['id']}").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/lists/{self.deck['id']}").status_code, 400)
        self.assertEqual(len(self.client.get("/api/lists").json["lists"]), 1)

    def test_scan_to_list_and_export_roundtrip(self):
        with patch("app.catalog", fake_catalog()), patch("app.reader.read", return_value=LINES):
            result = self.photo()
            self.assertEqual(result.status_code, 200, result.json)
            self.assertTrue(result.json["added"])
            self.assertEqual(result.json["list"]["total"], 2)
            self.assertFalse(self.photo().json["added"])
        response = self.client.get(f"/api/lists/{self.deck['id']}/export?format=tcglive")
        self.assertEqual(response.status_code, 200)
        self.assertIn("2 Charizard ex OBF 125", response.get_data(as_text=True))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(self.client.get(f"/api/lists/{self.deck['id']}").json["total"], 2)

    def test_manual_add_and_remove(self):
        with patch("app.catalog", fake_catalog()):
            result = self.client.post(f"/api/lists/{self.deck['id']}/items", json={
                "card_id": CARD["id"], "language": "en", "quantity": 3, "token": "manual-entry"})
        self.assertEqual(result.json["list"]["total"], 3)
        result = self.client.patch(f"/api/lists/{self.deck['id']}/items/{CARD['id']}", json={"quantity": 0})
        self.assertEqual(result.json["total"], 0)

    def test_liga_export_enriches_old_lists_without_changing_quantities(self):
        # Simula um banco criado antes da adição dos metadados de Liga Pokémon.
        store = ListStore(Path(self.folder.name) / "lists.sqlite3")
        store.add(self.deck["id"], METADATA, 4, "old-list-entry")
        with patch("app.catalog", fake_catalog()) as catalog:
            result = self.client.get(f"/api/lists/{self.deck['id']}/export?format=liga")
        self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
        self.assertEqual(result.get_data(as_text=True), "4 Charizard ex (125/197)\n")
        self.assertEqual(store.get(self.deck["id"])["total"], 4)
        self.assertEqual(store.get(self.deck["id"])["items"][0]["set_total"], 197)
        with patch("app.catalog.detail", side_effect=AssertionError("Já deve estar salvo")):
            self.assertEqual(self.client.get(f"/api/lists/{self.deck['id']}/export?format=liga").status_code, 200)

    def test_liga_enrichment_failure_preserves_old_list(self):
        from scanner.catalog import CatalogError
        store = ListStore(Path(self.folder.name) / "lists.sqlite3")
        store.add(self.deck["id"], METADATA, 2, "old-list-entry")
        with patch("app.catalog.detail", side_effect=CatalogError("Offline")):
            result = self.client.get(f"/api/lists/{self.deck['id']}/export?format=liga")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(store.get(self.deck["id"])["total"], 2)

    def test_liga_backfills_old_promos_and_exports_infinity(self):
        store = ListStore(Path(self.folder.name) / "lists.sqlite3")
        old_promo = {**METADATA, "card_id": "mep-087", "name": "Binacle", "export_name": "Binacle",
                     "liga_name": "Binacle", "set_id": "mep", "set_name": "Mega Evolution Promos",
                     "set_code": "MEP", "number": "87", "set_total": 150}
        store.add(self.deck["id"], old_promo, 4, "old-promo-entry")
        with patch("app.catalog", promo_catalog()):
            response = self.client.get(f"/api/lists/{self.deck['id']}/export?format=liga")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "4 Binacle (087/∞)\n")
        self.assertIn("charset=utf-8", response.content_type)
        self.assertEqual(store.get(self.deck["id"])["total"], 4)
        with patch("app.catalog.detail", side_effect=AssertionError("Promo deve estar salva")):
            self.assertEqual(self.client.get(f"/api/lists/{self.deck['id']}/export?format=liga").status_code, 200)

    def test_manual_search_filters_collection(self):
        with patch("app.catalog", fake_catalog()):
            result = self.client.get("/api/search?language=en&name=Charizard%20ex&number=125&set=OBF")
        self.assertEqual([card["id"] for card in result.json["matches"]], [CARD["id"]])

    def test_ambiguous_scan_does_not_modify_list(self):
        catalog = fake_catalog()
        catalog.set_detail.side_effect = lambda lang, set_id: {**EXPANSION, "id": set_id}
        with patch("app.catalog", catalog), patch("app.reader.read", return_value=LINES):
            result = self.photo()
        self.assertFalse(result.json["added"])
        self.assertIsNone(result.json["selected"])
        self.assertEqual(self.client.get(f"/api/lists/{self.deck['id']}").json["total"], 0)


if __name__ == "__main__":
    unittest.main()
