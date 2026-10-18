"""Listas persistentes e exportação textual, sem dependências externas."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


class ListError(ValueError):
    pass


def quantity(value, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or not (0 if allow_zero else 1) <= value <= 999:
        raise ListError("A quantidade deve ser um número inteiro de 1 a 999 (ou zero para remover).")
    return value


class ListStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS lists (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS items (
                    list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
                    card_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
                    metadata TEXT NOT NULL, PRIMARY KEY(list_id, card_id)
                );
                CREATE TABLE IF NOT EXISTS additions (
                    list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
                    token TEXT NOT NULL, PRIMARY KEY(list_id, token)
                );
            """)
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def require(db, list_id):
        row = db.execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()
        if row is None:
            raise ListError("Lista não encontrada. Selecione ou crie outra lista.")
        return dict(row)

    def all(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT l.*, COALESCE(SUM(i.quantity), 0) AS total
                FROM lists l LEFT JOIN items i ON i.list_id = l.id
                GROUP BY l.id ORDER BY l.created_at, l.rowid
            """)]

    def create(self, name):
        name = self.validate_name(name)
        list_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("INSERT INTO lists(id, name) VALUES (?, ?)", (list_id, name))
        return self.get(list_id)

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ListError("Dê à lista um nome de 1 a 80 caracteres.")
        return name.strip()

    def rename(self, list_id, name):
        name = self.validate_name(name)
        with self.connection() as db:
            self.require(db, list_id)
            db.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
        return self.get(list_id)

    def delete(self, list_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require(db, list_id)
            # As chaves estrangeiras removem somente os itens e tokens dessa lista.
            db.execute("DELETE FROM lists WHERE id = ?", (list_id,))
            remaining = db.execute("SELECT id FROM lists ORDER BY created_at, rowid LIMIT 1").fetchone()
            if remaining:
                next_id = remaining["id"]
            else:
                next_id = uuid.uuid4().hex
                db.execute("INSERT INTO lists(id, name) VALUES (?, ?)", (next_id, "Minha lista"))
        return self.get(next_id)

    def get(self, list_id):
        with self.connection() as db:
            result = self.require(db, list_id)
            result["items"] = [{**json.loads(row["metadata"]), "quantity": row["quantity"]}
                               for row in db.execute("SELECT * FROM items WHERE list_id = ? ORDER BY rowid", (list_id,))]
            result["total"] = sum(item["quantity"] for item in result["items"])
            return result

    def add(self, list_id, metadata, amount=1, token=None):
        quantity(amount)
        if not isinstance(token, str) or not 8 <= len(token) <= 160:
            raise ListError("Identificador da leitura inválido. Tente uma nova leitura.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require(db, list_id)
            if db.execute("SELECT 1 FROM additions WHERE list_id = ? AND token = ?", (list_id, token)).fetchone():
                return False
            row = db.execute("SELECT quantity FROM items WHERE list_id = ? AND card_id = ?", (list_id, metadata["card_id"])).fetchone()
            new_quantity = quantity((row["quantity"] if row else 0) + amount)
            db.execute("""INSERT INTO items(list_id, card_id, quantity, metadata) VALUES (?, ?, ?, ?)
                          ON CONFLICT(list_id, card_id) DO UPDATE SET quantity=excluded.quantity, metadata=excluded.metadata""",
                       (list_id, metadata["card_id"], new_quantity, json.dumps(metadata, ensure_ascii=False)))
            db.execute("INSERT INTO additions(list_id, token) VALUES (?, ?)", (list_id, token))
        return True

    def update_quantity(self, list_id, card_id, value):
        quantity(value, allow_zero=True)
        with self.connection() as db:
            self.require(db, list_id)
            if value == 0:
                db.execute("DELETE FROM items WHERE list_id = ? AND card_id = ?", (list_id, card_id))
            else:
                cursor = db.execute("UPDATE items SET quantity = ? WHERE list_id = ? AND card_id = ?", (value, list_id, card_id))
                if not cursor.rowcount:
                    raise ListError("Card não encontrado nessa lista.")
        return self.get(list_id)

    def update_metadata(self, list_id, card_id, fields):
        """Completa listas antigas sem substituir quantidades alteradas em outra aba."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require(db, list_id)
            row = db.execute("SELECT metadata FROM items WHERE list_id = ? AND card_id = ?", (list_id, card_id)).fetchone()
            if row:
                metadata = {**json.loads(row["metadata"]), **fields}
                db.execute("UPDATE items SET metadata = ? WHERE list_id = ? AND card_id = ?",
                           (json.dumps(metadata, ensure_ascii=False), list_id, card_id))


def liga_numeral(value):
    text = str(value)
    return text.zfill(3) if text.isdigit() else text


def export_text(deck, format_name):
    if format_name not in {"tcglive", "limitless", "liga"}:
        raise ListError("Escolha o formato TCG Live / Limitless ou Liga Pokémon.")
    items = deck["items"]
    if not items:
        raise ListError("Adicione cards antes de exportar.")
    if format_name == "liga":
        invalid = [item["name"] for item in items if not item.get("liga_name") or not (item.get("liga_number") or item.get("number"))
                   or (not item.get("liga_promo") and (type(item.get("set_total")) is not int or item["set_total"] <= 0))]
        if invalid:
            raise ListError("Não foi possível obter o nome e a numeração completa para Liga Pokémon de: "
                            + ", ".join(invalid) + ". A lista foi preservada.")
        return "\n".join(f"{item['quantity']} {item['liga_name']} ({liga_numeral(item.get('liga_number') or item['number'])}/"
                         f"{'∞' if item.get('liga_promo') else liga_numeral(item['set_total'])})" for item in items) + "\n"
    invalid = [item["name"] for item in items if not item.get("export_name") or not item.get("set_code")
               or not item.get("number") or item.get("category") not in {"Pokemon", "Trainer", "Energy"}]
    if invalid:
        raise ListError("O catálogo não informa os dados de exportação de: " + ", ".join(invalid) + ". A lista foi preservada.")
    groups = []
    for category, title in (("Pokemon", "Pokémon"), ("Trainer", "Trainer"), ("Energy", "Energy")):
        selected = [item for item in items if item["category"] == category]
        if not selected:
            continue
        rows = [f"{item['quantity']} {item['export_name']} {item['set_code']} {item['number']}" for item in selected]
        # O cabeçalho do Live conta entradas distintas, e o total conta cópias.
        rows.insert(0, f"{title}: {len(selected)}")
        groups.append("\n".join(rows))
    groups.append(f"Total Cards: {sum(item['quantity'] for item in items)}")
    return "\n\n".join(groups) + "\n"
