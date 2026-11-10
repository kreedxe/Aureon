from collections.abc import Callable
from pathlib import Path

from pytest import MonkeyPatch
from test_api import AUTH_HEADERS, request

from app.core.config import settings
from app.main import app
from app.schemas.products import ProductDescriptionDraft, ProductDescriptionRequest
from app.services.products import ProductRepository

PRODUCT = {
    "name": "Studio Headphones",
    "description": "Closed-back headphones for monitoring.",
    "price": "129.95",
    "currency": "USD",
    "stock_quantity": 7,
    "category": "Audio",
    "brand": "Aureon",
    "specifications": {"Color": "Black", "Impedance": "32 ohm"},
    "availability": "available",
}


def use_test_database(monkeypatch: MonkeyPatch, tmp_path: Path) -> ProductRepository:
    monkeypatch.setattr(
        settings,
        "session_token",
        type(settings.session_token)("test-session-token"),
    )
    repository = ProductRepository(tmp_path / "products.sqlite3")
    monkeypatch.setattr(app.state, "product_repository", repository, raising=False)
    return repository


def test_product_crud_persists_across_repository_instances(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = use_test_database(monkeypatch, tmp_path)
    created = request("POST", "/api/v1/products", headers=AUTH_HEADERS, json=PRODUCT)
    assert created.status_code == 201
    item = created.json()
    assert item["name"] == PRODUCT["name"]
    assert item["price"] == "129.95"
    assert item["availability"] == "available"
    assert item["specifications"] == PRODUCT["specifications"]

    updated_data = {**PRODUCT, "stock_quantity": 0}
    updated = request(
        "PUT",
        f"/api/v1/products/{item['id']}",
        headers=AUTH_HEADERS,
        json=updated_data,
    )
    assert updated.status_code == 200
    assert updated.json()["availability"] == "out_of_stock"
    assert updated.json()["stock_quantity"] == 0

    reopened = ProductRepository(repository.database_path)
    persisted = reopened.get_product(item["id"])
    assert persisted is not None
    assert persisted.name == PRODUCT["name"]
    assert persisted.stock_quantity == 0

    assert (
        request(
            "DELETE",
            f"/api/v1/products/{item['id']}",
            headers=AUTH_HEADERS,
        ).status_code
        == 204
    )
    assert (
        request(
            "GET",
            f"/api/v1/products/{item['id']}",
            headers=AUTH_HEADERS,
        ).status_code
        == 404
    )


def test_product_search_filters_and_sorting(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_test_database(monkeypatch, tmp_path)
    first = request("POST", "/api/v1/products", headers=AUTH_HEADERS, json=PRODUCT)
    second = request(
        "POST",
        "/api/v1/products",
        headers=AUTH_HEADERS,
        json={
            **PRODUCT,
            "name": "Travel Speaker",
            "price": "59.99",
            "stock_quantity": 0,
            "category": "Portable Audio",
            "brand": None,
        },
    )
    assert first.status_code == second.status_code == 201

    search = request(
        "GET",
        "/api/v1/products",
        headers=AUTH_HEADERS,
        json=None,
    )
    assert search.status_code == 200
    assert search.json()["total"] == 2
    assert search.json()["categories"] == ["Audio", "Portable Audio"]

    filtered = request(
        "GET",
        "/api/v1/products?query=speaker&availability=out_of_stock",
        headers=AUTH_HEADERS,
    )
    assert filtered.status_code == 200
    assert [product["name"] for product in filtered.json()["products"]] == ["Travel Speaker"]

    sorted_products = request(
        "GET",
        "/api/v1/products?sort=price&descending=true",
        headers=AUTH_HEADERS,
    )
    assert [product["name"] for product in sorted_products.json()["products"]] == [
        "Studio Headphones",
        "Travel Speaker",
    ]


def test_product_validation_and_authentication(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_test_database(monkeypatch, tmp_path)
    invalid = request(
        "POST",
        "/api/v1/products",
        headers=AUTH_HEADERS,
        json={**PRODUCT, "stock_quantity": -1},
    )
    assert invalid.status_code == 422

    unauthorized = request("GET", "/api/v1/products")
    assert unauthorized.status_code == 401


def test_ai_description_returns_reviewable_draft_without_saving(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_test_database(monkeypatch, tmp_path)
    session = app.state.recording_session

    def generate_description(
        payload: ProductDescriptionRequest,
        report_progress: Callable[[float, str], None],
    ) -> ProductDescriptionDraft:
        assert payload.name == PRODUCT["name"]
        assert payload.specifications == PRODUCT["specifications"]
        report_progress(80, "Drafting")
        return ProductDescriptionDraft(
            description="A draft based only on the supplied catalog details.",
            requires_review=True,
        )

    monkeypatch.setattr(
        session.ai_engine,
        "generate_product_description",
        generate_description,
    )
    response = request(
        "POST",
        "/api/v1/products/description-draft",
        headers=AUTH_HEADERS,
        json={
            "name": PRODUCT["name"],
            "price": PRODUCT["price"],
            "currency": PRODUCT["currency"],
            "category": PRODUCT["category"],
            "brand": PRODUCT["brand"],
            "specifications": PRODUCT["specifications"],
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "description": "A draft based only on the supplied catalog details.",
        "requires_review": True,
    }
    products, _ = app.state.product_repository.list_products()
    assert products == []
