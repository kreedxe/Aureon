from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from platformdirs import user_data_dir

from app.schemas.products import ProductAvailability, ProductInput, ProductResponse, ProductSort


class ProductRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or (
            Path(user_data_dir("Aureon", "Aureon")) / "aureon.sqlite3"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    price TEXT NOT NULL,
                    currency TEXT NOT NULL CHECK(length(currency) = 3),
                    stock_quantity INTEGER NOT NULL CHECK(stock_quantity >= 0),
                    category TEXT NOT NULL,
                    brand TEXT,
                    specifications TEXT NOT NULL,
                    availability TEXT NOT NULL CHECK(availability IN ('available', 'discontinued')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS products_name_index ON products(name COLLATE NOCASE)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS products_category_index "
                "ON products(category COLLATE NOCASE)"
            )

    def list_products(
        self,
        *,
        query: str = "",
        category: str | None = None,
        availability: ProductAvailability | None = None,
        sort: ProductSort = "name",
        descending: bool = False,
    ) -> tuple[list[ProductResponse], list[str]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if query:
            clauses.append(
                "(name LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE "
                "OR brand LIKE ? COLLATE NOCASE OR category LIKE ? COLLATE NOCASE)"
            )
            search_term = f"%{query}%"
            parameters.extend([search_term] * 4)
        if category:
            clauses.append("category = ? COLLATE NOCASE")
            parameters.append(category)
        if availability == "out_of_stock":
            clauses.append("stock_quantity = 0 AND availability = 'available'")
        elif availability in {"available", "discontinued"}:
            clauses.append("availability = ?")
            parameters.append(availability)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        column = {
            "name": "name COLLATE NOCASE",
            "price": "CAST(price AS NUMERIC)",
            "stock": "stock_quantity",
        }[sort]
        direction = "DESC" if descending else "ASC"
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM products{where} ORDER BY {column} {direction}, name COLLATE NOCASE",
                parameters,
            ).fetchall()
            categories = [
                row["category"]
                for row in connection.execute(
                    "SELECT DISTINCT category FROM products ORDER BY category COLLATE NOCASE"
                )
            ]
        return [self._to_response(row) for row in rows], categories

    def get_product(self, product_id: str) -> ProductResponse | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        return self._to_response(row) if row is not None else None

    def create_product(self, product: ProductInput) -> ProductResponse:
        product_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO products (
                    id, name, description, price, currency, stock_quantity, category,
                    brand, specifications, availability, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(
                    product_id,
                    product,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        return self._to_response(row)

    def update_product(self, product_id: str, product: ProductInput) -> ProductResponse | None:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE products SET
                    name = ?, description = ?, price = ?, currency = ?, stock_quantity = ?,
                    category = ?, brand = ?, specifications = ?, availability = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    product.name,
                    product.description,
                    str(product.price),
                    product.currency,
                    product.stock_quantity,
                    product.category,
                    product.brand,
                    json.dumps(product.specifications, ensure_ascii=False),
                    product.availability,
                    now,
                    product_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        return self._to_response(row)

    def delete_product(self, product_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _values(
        product_id: str,
        product: ProductInput,
        created_at: str,
        updated_at: str,
    ) -> tuple[object, ...]:
        return (
            product_id,
            product.name,
            product.description,
            str(product.price),
            product.currency,
            product.stock_quantity,
            product.category,
            product.brand,
            json.dumps(product.specifications, ensure_ascii=False),
            product.availability,
            created_at,
            updated_at,
        )

    @staticmethod
    def _to_response(row: sqlite3.Row) -> ProductResponse:
        availability: ProductAvailability = row["availability"]
        if availability == "available" and row["stock_quantity"] == 0:
            availability = "out_of_stock"
        return ProductResponse(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            price=Decimal(row["price"]),
            currency=row["currency"],
            stock_quantity=row["stock_quantity"],
            category=row["category"],
            brand=row["brand"],
            specifications=json.loads(row["specifications"]),
            availability=availability,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
