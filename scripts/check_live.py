"""Teste de integração real: catálogo, imagem de referência e OCR, sem câmera."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import tempfile
from app import catalog, create_app
from scanner.recognition import Reader, decode_image, rank_cards


def main():
    for language in ("pt", "en"):
        cards, stale = catalog.cards(language)
        print(f"Catálogo {language}: {len(cards)} cards, cache antigo: {stale}", flush=True)
    detail = catalog.detail("en", "base1-58")
    response = requests.get(detail["image"] + "/high.webp", timeout=30)
    response.raise_for_status()
    image = decode_image(response.content)
    lines = Reader().read(image)
    print("Texto reconhecido:", [line["text"] for line in lines], flush=True)
    cards, _ = catalog.cards("en")
    matches = rank_cards(cards, lines=lines)
    print("Primeiros candidatos:", [card["id"] for card in matches[:5]], flush=True)
    assert any(card["id"] == "base1-58" for card in matches), "Card de referência não identificado"
    import io
    with create_app().test_client() as client:
        result = client.post("/api/scan", data={"language": "en", "image": (io.BytesIO(response.content), "pikachu.webp")})
        assert result.status_code == 200, result.json
        assert any(card["id"] == "base1-58" for card in result.json["matches"]), result.json
    print("Integração de catálogo + OCR + upload HTTP aprovada.", flush=True)
    # Exerce a inclusão automática e a exportação com uma edição moderna.
    detail = catalog.detail("en", "sv03-125")
    response = requests.get(detail["image"] + "/high.webp", timeout=30)
    response.raise_for_status()
    with tempfile.TemporaryDirectory() as folder:
        with create_app(database_path=Path(folder) / "lists.sqlite3").test_client() as client:
            deck = client.post("/api/lists", json={"name": "Teste de integração"}).json
            result = client.post("/api/scan", data={"language": "en", "list_id": deck["id"],
                "token": "modern-reference", "quantity": "2", "image": (io.BytesIO(response.content), "charizard.webp")})
            print("Identificação moderna:", result.json.get("message"), flush=True)
            assert result.status_code == 200 and result.json.get("added"), result.json
            assert result.json["selected"]["id"] == "sv03-125", result.json
            exported = client.get(f"/api/lists/{deck['id']}/export?format=tcglive")
            assert exported.status_code == 200, exported.get_data(as_text=True)
            assert "2 Charizard ex OBF 125" in exported.get_data(as_text=True)
            print(exported.get_data(as_text=True), flush=True)
    print("Inclusão automática por foto + lista + exportação real aprovadas.", flush=True)


if __name__ == "__main__":
    main()
