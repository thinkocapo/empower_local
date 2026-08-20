"""
MOCKED data layer for Empower Local.

There is NO real database here. Every function below returns static, in-memory
dummy data. The original Empower Plant talks to a cloud Postgres; this local
version replaces those queries with fakes so a customer can run the app with
zero backend dependencies.

To keep the Sentry tracing/performance story intact, each mock still opens a
span for the query it *would* have run:

    op          = "function"
    description = the SQL statement the real app issues

So traces and the performance waterfall in Sentry look realistic even though
the data never leaves this file.
"""

import json
import time
import random

import sentry_sdk
from .utils import weighter
import operator


class DatabaseConnectionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Static, fake data (stands in for the products / reviews / inventory tables)
# ---------------------------------------------------------------------------

DUMMY_REVIEWS = {
    3: [
        {"id": 1, "productid": 3, "rating": 5, "customerId": 101,
         "description": "Love the glow — I always know when to water now.", "created": "2024-01-11"},
        {"id": 2, "productid": 3, "rating": 4, "customerId": 102,
         "description": "Looks great on my desk.", "created": "2024-02-02"},
    ],
    4: [
        {"id": 3, "productid": 4, "rating": 5, "customerId": 103,
         "description": "My fern finally talks back. 10/10.", "created": "2024-01-20"},
    ],
    5: [
        {"id": 4, "productid": 5, "rating": 4, "customerId": 104,
         "description": "Watching it walk to the window never gets old.", "created": "2024-03-05"},
        {"id": 5, "productid": 5, "rating": 3, "customerId": 105,
         "description": "Startled the cat. Otherwise excellent.", "created": "2024-03-09"},
    ],
    6: [
        {"id": 6, "productid": 6, "rating": 5, "customerId": 106,
         "description": "Great entry point for monitoring a whole shelf.", "created": "2024-02-18"},
    ],
}

DUMMY_PRODUCTS = [
    {
        "id": 3,
        "title": "Plant Mood",
        "description": "The mood ring for plants.",
        "descriptionfull": "Plant Mood transforms plant care into an intuitive, visual "
        "experience. A soft-glow LED ring shifts color based on real-time soil moisture, "
        "light, and temperature so you always know how your plant is doing.",
        "price": 155,
        "img": "/product-images/mood-planter.jpg",
        "imgcropped": "/product-images/mood-planter-cropped.jpg",
    },
    {
        "id": 4,
        "title": "Botana Voice",
        "description": "Lets plants speak for themselves.",
        "descriptionfull": "Botana Voice translates your plant's bioelectric signals into "
        "speech. Place the glass dome sensor nearby and hear needs like 'I'm thirsty' or "
        "'Too much sun' in a voice personality of your choosing.",
        "price": 175,
        "img": "/product-images/plant-to-text.jpg",
        "imgcropped": "/product-images/plant-to-text-cropped.jpg",
    },
    {
        "id": 5,
        "title": "Plant Stroller",
        "description": "Because plants don't have feet.",
        "descriptionfull": "Plant Stroller is an autonomous platform that physically moves "
        "your potted plant to the best light through the day on eight articulated legs. "
        "Program patrol routes or let it chase the sun on its own.",
        "price": 250,
        "img": "/product-images/plant-spider.jpg",
        "imgcropped": "/product-images/plant-spider-cropped.jpg",
    },
    {
        "id": 6,
        "title": "Plant Nodes",
        "description": "Listen more carefully to your plants.",
        "descriptionfull": "Plant Nodes are wireless soil sensors that measure moisture, pH, "
        "temperature, and light for every pot in your collection, relayed to a single "
        "dashboard through a self-forming mesh network.",
        "price": 25,
        "img": "/product-images/nodes.png",
        "imgcropped": "/product-images/nodes-cropped.jpg",
    },
]

# productid -> available count. ProductCard only lets ids 3-6 be added to cart.
DUMMY_INVENTORY = {3: 40, 4: 25, 5: 8, 6: 100}

# A couple of promo codes so the checkout promo field has something to hit.
DUMMY_PROMO_CODES = {
    "PLANTS10": {
        "code": "PLANTS10",
        "percent_discount": 10,
        "max_dollar_savings": 25,
        "is_active": True,
        "expires_at": None,
    },
    "GROW20": {
        "code": "GROW20",
        "percent_discount": 20,
        "max_dollar_savings": 50,
        "is_active": True,
        "expires_at": None,
    },
}


class InventoryRow:
    """Tiny stand-in for a SQLAlchemy row, so main.py's checkout logic
    (x.productid / x.id / x.count) keeps working against the mock."""

    def __init__(self, productid, count):
        self.id = productid
        self.productid = productid
        self.count = count


def _with_products_and_reviews():
    """Build the products list with nested reviews (what the real N+1 query did)."""
    results = []
    for product in DUMMY_PRODUCTS:
        result = dict(product)
        result["reviews"] = [dict(r) for r in DUMMY_REVIEWS.get(product["id"], [])]
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Mocked "queries". Each opens a span describing the SQL it replaces.
# ---------------------------------------------------------------------------

@sentry_sdk.trace
def get_products():
    """Mock of the N+1 products query (one products query + a reviews query per row)."""
    try:
        with sentry_sdk.start_span(op="function", description="SELECT * FROM products"):
            # keep the demo's variable, weighted latency so the waterfall isn't flat
            time.sleep(weighter(operator.le, 12) * 4)

        for product in DUMMY_PRODUCTS:
            with sentry_sdk.start_span(
                op="function",
                description="SELECT * FROM reviews WHERE productId = %s",
            ) as span:
                span.set_data("productId", product["id"])
                time.sleep(weighter(operator.le, 12))

        with sentry_sdk.start_span(op="serialization", description="get_products.combined_reviews.json"):
            return json.dumps(_with_products_and_reviews(), default=str)
    except Exception as err:
        raise DatabaseConnectionError("get_products") from err


@sentry_sdk.trace
def get_products_join():
    """Mock of the 2-query + in-memory-join variant."""
    try:
        with sentry_sdk.start_span(op="function", description="SELECT * FROM products") as span:
            span.set_data("totalProducts", len(DUMMY_PRODUCTS))
            time.sleep(weighter(operator.le, 12))

        with sentry_sdk.start_span(
            op="function",
            description="SELECT reviews.* FROM reviews INNER JOIN products ON reviews.productId = products.id",
        ):
            time.sleep(weighter(operator.le, 12))

        with sentry_sdk.start_span(op="serialization", description="get_products_join.json"):
            return json.dumps(_with_products_and_reviews(), default=str)
    except Exception as err:
        raise DatabaseConnectionError("get_products_join") from err


@sentry_sdk.trace
def get_inventory(cart):
    """Mock of: SELECT * FROM inventory WHERE productId = ANY(:ids)."""
    quantities = cart.get("quantities", {})
    product_ids = [int(pid) for pid in quantities.keys()]

    try:
        with sentry_sdk.start_span(
            op="function",
            description="SELECT * FROM inventory WHERE productId = ANY(%s)",
        ) as span:
            span.set_data("productIds", product_ids)
            time.sleep(weighter(operator.le, 12))
            return [
                InventoryRow(pid, DUMMY_INVENTORY.get(pid, 0)) for pid in product_ids
            ]
    except Exception as err:
        raise DatabaseConnectionError("get_inventory") from err


def decrement_inventory(id, count):
    """No-op: there is no real inventory table to update."""
    pass


@sentry_sdk.trace
def get_promo_code(code):
    """Mock of: SELECT * FROM promo_codes WHERE code = :code AND is_active = true."""
    try:
        with sentry_sdk.start_span(
            op="function",
            description="SELECT * FROM promo_codes WHERE code = %s AND is_active = true",
        ) as span:
            span.set_data("code", code)
            time.sleep(weighter(operator.le, 12))
            promo = DUMMY_PROMO_CODES.get(code)
            return dict(promo) if promo else None
    except Exception as err:
        raise DatabaseConnectionError("get_promo_code") from err
