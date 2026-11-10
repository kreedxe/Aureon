from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ProductAvailability = Literal["available", "out_of_stock", "discontinued"]
ProductSort = Literal["name", "price", "stock"]

ProductName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ProductDescription = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=5000),
]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class ProductInput(BaseModel):
    name: ProductName
    description: ProductDescription = None
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: CurrencyCode = "USD"
    stock_quantity: int = Field(ge=0, le=2_147_483_647)
    category: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]
    brand: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=100),
    ] = None
    specifications: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    availability: Literal["available", "discontinued"] = "available"

    model_config = ConfigDict(extra="forbid")


class ProductResponse(ProductInput):
    id: str
    availability: ProductAvailability
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class ProductListResponse(BaseModel):
    products: list[ProductResponse]
    categories: list[str]
    total: int

    model_config = ConfigDict(extra="forbid")


class ProductDescriptionRequest(BaseModel):
    name: ProductName
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: CurrencyCode = "USD"
    category: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]
    brand: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=100),
    ] = None
    specifications: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ProductDescriptionDraft(BaseModel):
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    requires_review: Literal[True] = True

    model_config = ConfigDict(extra="forbid")
