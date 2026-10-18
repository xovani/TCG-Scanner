"""Cruza nome, numeração e coleção sem escolher por ordem alfabética."""
import re
from concurrent.futures import ThreadPoolExecutor

from scanner.catalog import CatalogError
from scanner.recognition import normalize


def set_code(metadata):
    return metadata.get("tcgOnline") or (metadata.get("abbreviation") or {}).get("official") or ""


def liga_fields(english, expansion):
    """Promos não têm denominador impresso, mesmo quando o catálogo informa um total."""
    names = " ".join(str(value) for value in (expansion.get("name", ""), english.get("set", {}).get("name", "")))
    promo = bool(re.search(r"\b(?:promos?|promotional|promocional|promocionais)\b", normalize(names)))
    raw_number = str(english["localId"])
    return {"liga_name": english["name"], "liga_number": raw_number, "liga_promo": promo,
            "set_total": english.get("set", {}).get("cardCount", {}).get("official")
            or expansion.get("cardCount", {}).get("official")}


def identify(matches, lines, catalog, language, explicit_set=""):
    candidates = [card for card in matches if card["number_match"] and card["similarity"] >= 96]
    if not candidates or len(candidates) > 20:
        return None, "Não foi possível confirmar nome, número e coleção. Escolha um candidato."
    # A substring "Pikachu" não deve empatar com "Pikachu ex" lido por inteiro.
    longest_name = max(len(normalize(card["name"]).split()) for card in candidates)
    candidates = [card for card in candidates if len(normalize(card["name"]).split()) == longest_name]
    footer = " ".join(line["text"] for line in lines if line["y"] >= .65)
    normalized_footer = " " + normalize(footer) + " "
    denominators = {int(value) for value in re.findall(r"/\s*(\d{1,3})\b", footer)}
    set_ids = {card["set_id"] for card in candidates}

    def fetch(set_id):
        try:
            return set_id, catalog.set_detail(language, set_id)
        except CatalogError:
            return set_id, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        sets = dict(pool.map(fetch, sorted(set_ids)))
    if any(value is None for value in sets.values()):
        return None, "Não consegui conferir todas as coleções. Escolha o card ou tente novamente."
    by_code, by_total = [], []
    code_seen = False
    for card in candidates:
        metadata = sets[card["set_id"]]
        code = set_code(metadata)
        card["set_code"] = code
        card["set_name"] = metadata.get("name", card["set_id"])
        official = metadata.get("cardCount", {}).get("official")
        total_match = bool(denominators and official in denominators)
        aliases = {normalize(value) for value in (code, (metadata.get("abbreviation") or {}).get("official", ""), card["set_id"])} - {""}
        code_match = normalize(explicit_set) in aliases if explicit_set else any(
            f" {alias} " in normalized_footer for alias in aliases)
        code_seen = code_seen or code_match
        if code_match and (not denominators or total_match):
            by_code.append(card)
        if total_match:
            by_total.append(card)
    eligible = by_code if code_seen or explicit_set else by_total
    if len(eligible) == 1:
        return eligible[0], "Nome, número e código da coleção conferidos." if by_code else "Nome e numeração completa apontam para uma única coleção."
    return None, "Mais de uma edição possível ou coleção não confirmada. Escolha o card para adicionar."


def card_metadata(catalog, language, card_id):
    localized = catalog.detail(language, card_id)
    english = localized if language == "en" else catalog.detail("en", card_id)
    expansion = catalog.set_detail("en", english["set"]["id"])
    number = str(english["localId"])
    if number.isdigit():
        number = str(int(number))
    export_name = english["name"]
    energy = re.fullmatch(r"(?:Basic )?(Grass|Fire|Water|Lightning|Psychic|Fighting|Darkness|Metal|Fairy) Energy", export_name)
    if english.get("category") == "Energy" and energy:
        symbol = {"Grass": "G", "Fire": "R", "Water": "W", "Lightning": "L", "Psychic": "P",
                  "Fighting": "F", "Darkness": "D", "Metal": "M", "Fairy": "Y"}[energy[1]]
        export_name = f"Basic {{{symbol}}} Energy"
    return {"card_id": card_id, "name": localized["name"], "export_name": export_name,
            **liga_fields(english, expansion),
            "category": english.get("category", ""), "set_id": expansion["id"],
            "set_name": localized["set"]["name"], "set_code": set_code(expansion),
            "number": number, "image": localized.get("image"), "language": language}
