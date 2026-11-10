import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.schemas.products import (
    ProductAvailability,
    ProductDescriptionDraft,
    ProductDescriptionRequest,
    ProductInput,
    ProductListResponse,
    ProductResponse,
    ProductSort,
)
from app.services.products import ProductRepository

router = APIRouter()


def get_repository(request: Request) -> ProductRepository:
    return request.app.state.product_repository


@router.post("/products/description-draft", response_model=ProductDescriptionDraft)
async def generate_product_description(
    payload: ProductDescriptionRequest,
    request: Request,
) -> ProductDescriptionDraft:
    engine = request.app.state.recording_session.ai_engine
    try:
        return await asyncio.to_thread(
            engine.generate_product_description,
            payload,
            lambda _progress, _message: None,
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Local AI could not draft the description: {error}",
        ) from error


@router.get("/products", response_model=ProductListResponse)
def list_products(
    request: Request,
    query: Annotated[str, Query(max_length=160)] = "",
    category: Annotated[str | None, Query(max_length=100)] = None,
    availability: ProductAvailability | None = None,
    sort: ProductSort = "name",
    descending: bool = False,
) -> ProductListResponse:
    products, categories = get_repository(request).list_products(
        query=query.strip(),
        category=category.strip() if category else None,
        availability=availability,
        sort=sort,
        descending=descending,
    )
    return ProductListResponse(products=products, categories=categories, total=len(products))


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(payload: ProductInput, request: Request) -> ProductResponse:
    return get_repository(request).create_product(payload)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: str, request: Request) -> ProductResponse:
    product = get_repository(request).get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.put("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    payload: ProductInput,
    request: Request,
) -> ProductResponse:
    product = get_repository(request).update_product(product_id, payload)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_product(product_id: str, request: Request) -> Response:
    if not get_repository(request).delete_product(product_id):
        raise HTTPException(status_code=404, detail="Product not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
