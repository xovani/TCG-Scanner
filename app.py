import io
import logging
import os
import socket
from pathlib import Path

import qrcode
from flask import Flask, Response, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from scanner.catalog import Catalog, CatalogError, LANGUAGES
from scanner.recognition import ImageError, Reader, decode_image, rank_cards
from scanner.identification import card_metadata, identify, liga_fields
from scanner.lists import ListStore, export_text, quantity

ROOT = Path(__file__).resolve().parent
catalog = Catalog(ROOT / "data")
reader = Reader()


def local_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def create_app(network_access=False, port=None, database_path=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
    port = int(port if port is not None else os.environ.get("PORT", "5000"))
    lists = ListStore(database_path or ROOT / "data" / "lists.sqlite3")

    def json_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("Envie os dados da operação em JSON.")
        return body

    def access_url():
        host = local_address() if network_access else "127.0.0.1"
        return f"http://{host}:{port}"

    @app.get("/")
    def home():
        return render_template("index.html", network_access=network_access)

    @app.get("/api/access")
    def access():
        return jsonify(url=access_url(), mode="network" if network_access else "local")

    @app.get("/qr.png")
    def qr():
        if not network_access:
            abort(404)
        output = io.BytesIO()
        qrcode.make(access_url()).save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png")

    def language():
        value = request.values.get("language", "pt")
        if value not in LANGUAGES:
            raise ValueError("Escolha português ou inglês.")
        return value

    @app.post("/api/scan")
    def scan():
        lang = language()
        list_id = request.form.get("list_id", "")
        if list_id:
            lists.get(list_id)
        try:
            amount = int(request.form.get("quantity", "1"))
        except ValueError as exc:
            raise ValueError("Quantidade inválida.") from exc
        quantity(amount)
        upload = request.files.get("image")
        if not upload:
            raise ImageError("Escolha uma foto do card.")
        image = decode_image(upload.read())
        lines = reader.read(image)
        if not lines:
            return jsonify(text="", matches=[], stale=False,
                           message="Não consegui ler o texto. Melhore a iluminação ou use a busca manual.")
        # Mantém o texto reconhecido mesmo se o catálogo estiver fora do ar.
        text = "\n".join(line["text"] for line in lines)
        try:
            cards, stale = catalog.cards(lang)
        except CatalogError as exc:
            return jsonify(text=text, matches=[], stale=False, message=str(exc))
        matches = rank_cards(cards, lines=lines, limit=len(cards))
        selected, reason = identify(matches, lines, catalog, lang)
        if selected:
            matches = [selected] + [card for card in matches if card["id"] != selected["id"]]
        result = dict(text=text, matches=matches[:12], stale=stale, selected=selected, message=reason,
                      added=False, list=None)
        if selected and list_id:
            try:
                metadata = card_metadata(catalog, lang, selected["id"])
                result["added"] = lists.add(list_id, metadata, amount, request.form.get("token"))
                result["list"] = lists.get(list_id)
                result["message"] = (f"{amount} × {metadata['name']} adicionado(s) à lista. " if result["added"] else
                                     "Esta foto já foi adicionada a essa lista. ") + reason
            except (CatalogError, ValueError) as exc:
                result["message"] = f"Card identificado, mas não foi adicionado: {exc}"
        return jsonify(result)

    @app.get("/api/search")
    def search():
        lang = language()
        name = request.args.get("name", "").strip()
        number = request.args.get("number", "").strip()
        expansion = request.args.get("set", "").strip()
        if not 3 <= len(name) <= 100 or len(number) > 20:
            raise ValueError("Digite um nome com 3 a 100 caracteres e um número de até 20 caracteres.")
        cards, stale = catalog.cards(lang)
        matches = rank_cards(cards, name=name, number=number, limit=len(cards))
        if expansion:
            if len(expansion) > 40:
                raise ValueError("Código de coleção inválido.")
            if not number:
                raise ValueError("Informe também o número do card para buscar por coleção.")
            matches = [card for card in matches if card["similarity"] >= 90]
            if len({card["set_id"] for card in matches}) > 20:
                raise ValueError("Muitas coleções possíveis. Confira o nome completo e o número do card.")
            from scanner.recognition import normalize
            from scanner.identification import set_code
            sets = {}
            filtered = []
            for card in matches:
                set_id = card["set_id"]
                if set_id not in sets:
                    sets[set_id] = catalog.set_detail(lang, set_id)
                data = sets[set_id]
                if normalize(expansion) in {normalize(set_id), normalize(set_code(data)),
                                           normalize((data.get("abbreviation") or {}).get("official", ""))}:
                    card.update(set_code=set_code(data), set_name=data["name"])
                    filtered.append(card)
            matches = filtered
        return jsonify(matches=matches[:12], stale=stale,
                       message="Confira a coleção e a imagem. A busca mostra até 12 candidatos.")

    @app.get("/api/lists")
    def get_lists():
        return jsonify(lists=lists.all())

    @app.post("/api/lists")
    def new_list():
        return jsonify(lists.create(json_body().get("name"))), 201

    @app.get("/api/lists/<list_id>")
    def get_list(list_id):
        return jsonify(lists.get(list_id))

    @app.patch("/api/lists/<list_id>")
    def rename_list(list_id):
        return jsonify(lists.rename(list_id, json_body().get("name")))

    @app.delete("/api/lists/<list_id>")
    def delete_list(list_id):
        return jsonify(deleted_id=list_id, list=lists.delete(list_id))

    @app.post("/api/lists/<list_id>/items")
    def add_item(list_id):
        body = json_body()
        lists.get(list_id)
        lang = body.get("language", "pt")
        if lang not in LANGUAGES or not isinstance(body.get("card_id"), str):
            raise ValueError("Card ou idioma inválido.")
        amount = quantity(body.get("quantity", 1))
        metadata = card_metadata(catalog, lang, body["card_id"])
        added = lists.add(list_id, metadata, amount, body.get("token"))
        return jsonify(added=added, list=lists.get(list_id))

    @app.patch("/api/lists/<list_id>/items/<card_id>")
    def update_item(list_id, card_id):
        return jsonify(lists.update_quantity(list_id, card_id, json_body().get("quantity")))

    @app.get("/api/lists/<list_id>/export")
    def export_list(list_id):
        deck = lists.get(list_id)
        format_name = request.args.get("format", "tcglive")
        if format_name == "liga":
            for item in deck["items"]:
                if (item.get("liga_name") and item.get("liga_number") and "liga_promo" in item
                        and (item["liga_promo"] or item.get("set_total"))):
                    continue
                english = catalog.detail("en", item["card_id"])
                expansion = catalog.set_detail("en", item["set_id"])
                lists.update_metadata(list_id, item["card_id"], liga_fields(english, expansion))
            deck = lists.get(list_id)
        content = export_text(deck, format_name)
        return Response(content, content_type="text/plain; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="lista-{list_id[:8]}-{format_name}.txt"'
        })

    @app.get("/api/cards/<card_id>")
    def detail(card_id):
        return jsonify(catalog.detail(language(), card_id))

    @app.errorhandler(ImageError)
    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(CatalogError)
    def unavailable(exc):
        return jsonify(error=str(exc)), 503

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(exc):
        return jsonify(error="A foto excedeu 12 MB. Escolha uma imagem menor."), 413

    @app.errorhandler(500)
    def internal(exc):
        return jsonify(error="Não foi possível concluir a leitura. Tente outra foto ou a busca manual. Consulte o terminal para detalhes."), 500

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app


if __name__ == "__main__":
    import argparse
    from waitress import serve
    parser = argparse.ArgumentParser(description="Leitor de cards Pokémon com OCR local.")
    parser.add_argument("--rede", action="store_true", help="Habilita acesso pela rede local; requer uma rede que permita essa conexão.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "5000"))
    print(f"\nCard Scanner TCG\nComputador: http://127.0.0.1:{port}", flush=True)
    if args.rede:
        print(f"Celular na mesma rede Wi-Fi: http://{local_address()}:{port}", flush=True)
    else:
        print("Modo somente neste computador. Use Arquivo de foto ou Usar webcam no navegador.", flush=True)
    print("Ctrl+C para encerrar.\n", flush=True)
    serve(create_app(network_access=args.rede, port=port), host="0.0.0.0" if args.rede else "127.0.0.1", port=port, threads=4)
