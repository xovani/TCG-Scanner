import json
import logging
import re
import time
from pathlib import Path
from threading import Lock

import requests

LOGGER = logging.getLogger(__name__)
LANGUAGES = {"pt", "en"}


class CatalogError(Exception):
    pass


class Catalog:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.lock = Lock()
        self.memory = {}
        self.resources = {}

    def cards(self, language):
        if language not in LANGUAGES:
            raise ValueError("Idioma inválido.")
        with self.lock:
            if language in self.memory:
                cards, timestamp = self.memory[language]
                if time.time() - timestamp < 86400:
                    return cards, False
            path = self.cache_dir / f"catalog-{language}.json"
            cached = None
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(cached, list) or not cached:
                    cached = None
                elif time.time() - path.stat().st_mtime < 7 * 86400:
                    self.memory[language] = (cached, time.time())
                    return cached, False
            except (OSError, ValueError):
                pass
            try:
                response = requests.get(f"https://api.tcgdex.net/v2/{language}/cards", timeout=(8, 45))
                response.raise_for_status()
                cards = response.json()
                if not isinstance(cards, list) or not cards or not all(
                    isinstance(card, dict) and all(key in card for key in ("id", "name", "localId"))
                    for card in cards
                ):
                    raise ValueError("Catálogo inválido.")
            except (requests.RequestException, ValueError) as exc:
                if cached:
                    return cached, True
                raise CatalogError("Não foi possível baixar o catálogo. Verifique a internet e tente novamente.") from exc
            self.memory[language] = (cards, time.time())
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                LOGGER.warning("Não foi possível salvar o cache do catálogo.")
            return cards, False

    def detail(self, language, card_id):
        return self._resource(language, "cards", card_id)

    def set_detail(self, language, set_id):
        return self._resource(language, "sets", set_id)

    def _resource(self, language, kind, resource_id):
        if language not in LANGUAGES or not re.fullmatch(r"[A-Za-z0-9.-]{1,90}", resource_id):
            raise ValueError("Identificador inválido.")
        key = f"{language}-{kind}-{resource_id}"
        with self.lock:
            if key in self.resources:
                return self.resources[key]
        path = self.cache_dir / "metadata" / f"{key}.json"
        cached = None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cached, dict) or cached.get("id") != resource_id:
                cached = None
            elif time.time() - path.stat().st_mtime < 7 * 86400:
                with self.lock:
                    self.resources[key] = cached
                return cached
        except (OSError, ValueError):
            pass
        try:
            response = requests.get(
                f"https://api.tcgdex.net/v2/{language}/{kind}/{resource_id}", timeout=(8, 20)
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("id") != resource_id:
                raise ValueError("Metadados inválidos.")
        except (requests.RequestException, ValueError) as exc:
            if cached:
                return cached
            raise CatalogError("Não foi possível consultar os detalhes do card ou da coleção.") from exc
        with self.lock:
            self.resources[key] = data
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                LOGGER.warning("Não foi possível salvar os metadados do catálogo.")
        return data
