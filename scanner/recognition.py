import io
import re
import unicodedata
from threading import Lock

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from rapidfuzz import fuzz, process

Image.MAX_IMAGE_PIXELS = 25_000_000


class ImageError(Exception):
    pass


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def decode_image(payload):
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                raise ImageError("A foto excede 25 megapixels. Escolha uma imagem menor.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            if min(image.size) < 150:
                raise ImageError("A foto está muito pequena. Fotografe o card mais de perto.")
            image.thumbnail((2000, 2600))
            return image
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageError("Imagem inválida ou grande demais. Use uma foto JPG, PNG ou WebP de até 25 megapixels.") from exc


class Reader:
    def __init__(self):
        self.engine = None
        self.lock = Lock()

    def read(self, image):
        # Inicialização tardia: a busca manual funciona mesmo sem iniciar o OCR.
        with self.lock:
            if self.engine is None:
                from rapidocr import RapidOCR
                self.engine = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                               "EngineConfig.onnxruntime.inter_op_num_threads": 2})
            # RapidOCR recebe arrays OpenCV em BGR.
            result = self.engine(np.asarray(image)[:, :, ::-1].copy())
        lines = []
        if result.txts is None:
            return lines
        for box, text, confidence in zip(result.boxes, result.txts, result.scores):
            if confidence >= 0.45:
                lines.append({"text": text, "confidence": round(float(confidence), 3),
                              "y": float(min(point[1] for point in box)) / image.height})
        return sorted(lines, key=lambda line: line["y"])


def collector_numbers(text):
    return {normalize(match).replace(" ", "").lstrip("0") or "0"
            for match in re.findall(r"\b([A-Za-z]{0,3}\d{1,3})\s*/\s*(?:[A-Za-z]{0,3}\d{1,3})\b", text)}


def rank_cards(cards, lines=None, name="", number="", limit=12):
    lines = lines or []
    # O nome costuma estar no topo. Texto de ataques não deve dominar a busca.
    queries = [normalize(name)] if name.strip() else [
        normalize(re.sub(r"\b(?:HP|PS|PV)\s*\d+|\d+\s*(?:HP|PS|PV)\b", "", line["text"], flags=re.I))
        for line in lines if line["y"] < 0.36
    ]
    queries = [query for query in queries if len(query) >= 3]
    numbers = collector_numbers(" ".join(line["text"] for line in lines))
    footer = " ".join(line["text"] for line in lines if line["y"] >= .65)
    # Promos podem trazer apenas "SVP PT 001", sem denominador.
    numbers.update(normalize(value).replace(" ", "").lstrip("0") or "0" for value in re.findall(
        r"\b[A-Z][A-Z0-9-]{1,7}\s+(?:(?:PT|EN|FR|DE|ES|IT)\s+)?([A-Za-z]{0,4}\d{1,3})\b", footer))
    if number.strip():
        numbers = {normalize(number.split("/")[0]).replace(" ", "").lstrip("0") or "0"}
    if not queries:
        return []
    names = {normalize(card["name"]) for card in cards}
    scores = {}
    for query in queries:
        # Janelas toleram "BÁSICO Pikachu" sem confundir Pikachu com Pikachu ex.
        words = query.split()
        windows = {" ".join(words[start:start + size])
                   for size in range(1, min(len(words), 6) + 1)
                   for start in range(len(words) - size + 1)} if not name.strip() else {query}
        for window in windows:
            for candidate, score, _ in process.extract(window, names, scorer=fuzz.ratio, limit=5, score_cutoff=72):
                # Nomes completos mais longos prevalecem sobre substrings.
                weighted = score + min(len(candidate.split()) - 1, 3) * 0.8
                scores[candidate] = max(scores.get(candidate, 0), weighted)
    results = []
    for card in cards:
        similarity = scores.get(normalize(card["name"]), 0)
        if similarity < 72:
            continue
        card_number = normalize(card["localId"]).replace(" ", "").lstrip("0") or "0"
        number_match = bool(numbers and card_number in numbers)
        if number.strip() and not number_match:
            continue
        results.append({**card, "similarity": min(100, round(similarity)), "number_match": number_match,
                        "set_id": card["id"].rsplit("-", 1)[0],
                        "_rank": similarity + (18 if number_match else 0)})
    results.sort(key=lambda card: (-card["_rank"], card["id"]))
    for card in results:
        card.pop("_rank")
    return results[:limit]
