import re
import os
import random
import time
import logging
from datetime import datetime

from flask import Flask, json, jsonify, request, make_response, send_from_directory
import dotenv

from .db import (
    decrement_inventory,
    get_products,
    get_products_join,
    get_inventory,
    get_promo_code,
)
from .utils import get_iterator

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

pests = ["aphids", "thrips", "spider mites", "lead miners", "scale", "whiteflies", "earwigs", "cutworms", "mealybugs",
         "fungus gnats"]

RELEASE = None
DSN = None
ENVIRONMENT = None
RUN_SLOW_PROFILE = None

NORMAL_SLOW_PROFILE = 2  # seconds
EXTREMELY_SLOW_PROFILE = 24


def before_send(event, hint):
    # 'se' tag may have been set in app.before_request. Kept so a single SE's test
    # runs group into their own issue, exactly like the upstream Empower Plant.
    se = None
    if 'tags' in event.keys() and 'se' in event['tags']:
        se = event['tags']['se']

    if se not in [None, "undefined"]:
        se_tda_prefix_regex = r"[^-]+-tda-[^-]+-"
        se_fingerprint = se
        prefix = re.findall(se_tda_prefix_regex, se)
        if prefix:
            se_fingerprint = prefix[0]

        if se.startswith('prod-tda-'):
            event['fingerprint'] = ['{{ default }}', se_fingerprint, RELEASE]
        else:
            event['fingerprint'] = ['{{ default }}', se_fingerprint]

    return event


def traces_sampler(sampling_context):
    sentry_sdk.set_context("sampling_context", sampling_context)
    wsgi_environ = sampling_context.get('wsgi_environ') or {}
    if wsgi_environ.get('REQUEST_METHOD') == 'OPTIONS':
        return 0.0
    return 1.0


class MyFlask(Flask):
    def __init__(self, import_name, *args, **kwargs):
        global RELEASE, DSN, ENVIRONMENT, RUN_SLOW_PROFILE
        dotenv.load_dotenv()

        RELEASE = os.environ.get("FLASK_RELEASE", "empower-local-flask@1.0.0")
        DSN = os.environ.get("FLASK_DSN", "")
        ENVIRONMENT = os.environ.get("FLASK_ENVIRONMENT", "local")

        RUN_SLOW_PROFILE = os.environ.get("RUN_SLOW_PROFILE", "true").lower() == "true"

        # dsn=None (not "") so the SDK's no-DSN Spotlight path is used cleanly when
        # running in Spotlight mode. Spotlight itself is auto-enabled via the
        # SENTRY_SPOTLIGHT env var (set in docker-compose.spotlight.yaml).
        sentry_sdk.init(
            dsn=DSN or None,
            release=RELEASE,
            environment=ENVIRONMENT,
            enable_logs=True,
            integrations=[
                FlaskIntegration(),
                LoggingIntegration(event_level=None),  # don't send ERROR logs as separate events
            ],
            traces_sample_rate=1.0,
            before_send=before_send,
            traces_sampler=traces_sampler,
            _experiments={
                "profiles_sample_rate": 1.0,
            },
        )

        super(MyFlask, self).__init__(import_name, *args, **kwargs)


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.info("Flask application initialized")
logger.info("DSN: %s", DSN)
logger.info("RELEASE: %s", RELEASE)
logger.info("ENVIRONMENT: %s", ENVIRONMENT)


# Ensures CORS headers are applied to ALL responses, including 500 errors.
# React runs on a different origin (localhost:3000) than Flask (localhost:8080),
# so these headers are also what let the `sentry-trace` / `baggage` request
# headers through preflight -- i.e. this is load-bearing for distributed tracing.
class CORSWSGIWrapper:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        def custom_start_response(status, headers, exc_info=None):
            headers.append(('Access-Control-Allow-Origin', '*'))
            headers.append(('Access-Control-Allow-Headers', '*'))
            headers.append(('Access-Control-Allow-Methods', '*'))
            return start_response(status, headers, exc_info)

        try:
            return self.app(environ, custom_start_response)
        except Exception:
            status = '500 Internal Server Error'
            headers = [
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Headers', '*'),
            ]
            response_body = json.dumps({"error": "Internal Server Error"}).encode('utf-8')
            start_response(status, headers)
            return [response_body]

    def __getattr__(self, name):
        return getattr(self.app, name)


app = MyFlask(__name__)
app = CORSWSGIWrapper(app)


@app.route('/enqueue', methods=['POST'])
def enqueue():
    logger.info('Received /enqueue endpoint request')

    body = json.loads(request.data)
    email = body['email']

    # MOCK: the upstream app hands this to a Celery worker backed by Redis. Here we
    # just emit a span for the work that would have been enqueued and return success.
    with sentry_sdk.start_span(op="function", description="sendEmail") as span:
        span.set_data("email", email)

    logger.info('Completed /enqueue request - email task mocked')
    return jsonify({"status": "success"}), 200


@app.route('/checkout', methods=['POST'])
def checkout():
    logger.info('Received /checkout endpoint request')

    order = json.loads(request.data)
    cart = order["cart"]
    validate_inventory = True if "validate_inventory" not in order else order["validate_inventory"] == "true"

    logger.info('Processing /checkout - validating order details')

    inventory = []
    try:
        inventory = get_inventory(cart)
    except Exception as err:
        logger.error('Failed to get inventory')
        raise (err)

    fulfilled_count = 0
    out_of_stock = []
    try:
        if validate_inventory:
            with sentry_sdk.start_span(op="code.block", name="checkout.process_order"):
                quantities = {int(k): v for k, v in cart['quantities'].items()}
                if len(quantities) == 0:
                    raise Exception("Invalid checkout request: cart is empty")

                inventory_dict = {x.productid: x for x in inventory}
                for product_id in quantities:
                    inventory_count = inventory_dict[product_id].count if product_id in inventory_dict else 0
                    if inventory_count >= quantities[product_id]:
                        decrement_inventory(inventory_dict[product_id].id, quantities[product_id])
                        fulfilled_count += 1
                    else:
                        title = list(filter(lambda x: x['id'] == product_id, cart['items']))[0]['title']
                        out_of_stock.append(title)
    except Exception as err:
        logger.error('Failed to validate inventory with cart: %s', cart)
        raise Exception("Error validating enough inventory for product") from err

    if len(out_of_stock) == 0:
        sentry_sdk.metrics.distribution("checkout.captured.revenue", cart["total"], unit="none")
        result = {'status': 'success'}
        logging.info("Checkout successful")
    else:
        if fulfilled_count == 0:
            result = {'status': 'failed'}  # All items are out of stock
        else:
            result = {'status': 'partial', 'out_of_stock': out_of_stock}

    return make_response(json.dumps(result))


@app.route('/success', methods=['GET'])
def success():
    logger.info('Received /success endpoint request')
    return "success from flask"


@app.route('/products', methods=['GET'])
def products():
    logger.info('Received /products endpoint request')

    fetch_promotions = request.args.get('fetch_promotions')
    in_stock_only = request.args.get('in_stock_only')
    timeout_seconds = (EXTREMELY_SLOW_PROFILE if fetch_promotions else NORMAL_SLOW_PROFILE)

    logger.info('Processing /products')

    try:
        with sentry_sdk.start_span(op="code.block", name="products.get_and_process_products"):
            rows = get_products()

            if RUN_SLOW_PROFILE:
                start_time = time.time()
                productsJSON = json.loads(rows)
                descriptions = [product["description"] for product in productsJSON]
                # this is improper convention (op and name switched up)
                # keeping it to match the upstream demo's profiling frames
                with sentry_sdk.start_span(op="/get_iterator", name="code.block"):
                    loop = get_iterator(len(descriptions) * 6 + (2 if fetch_promotions else -1))

                    for i in range(loop * 10):
                        time_delta = time.time() - start_time
                        if time_delta > timeout_seconds:
                            break

                        for j, description in enumerate(descriptions):
                            for pest in pests:
                                if in_stock_only:
                                    continue
                                if pest in description:
                                    try:
                                        del productsJSON[j:j + 1]
                                    except Exception:
                                        productsJSON = json.loads(rows)
    except Exception as err:
        logger.error('Processing /products - error occurred')
        sentry_sdk.capture_exception(err)
        raise (err)

    logger.info('Completed /products request')
    return rows


@app.route('/products-join', methods=['GET'])
def products_join():
    logger.info('Received /products-join endpoint request')

    try:
        rows = get_products_join()
        logger.info('Processing /products-join - data retrieved')
    except Exception as err:
        logger.error('Processing /products-join - error getting data')
        sentry_sdk.capture_exception(err)
        raise (err)

    return rows


@app.route('/handled', methods=['GET'])
def handled_exception():
    logger.info('Received /handled endpoint request')

    try:
        '2' + 2
    except Exception as err:
        logger.error('Processing /handled - intentional exception occurred')
        sentry_sdk.capture_exception(err)
    return 'failed'


@app.route('/unhandled', methods=['GET'])
def unhandled_exception():
    logger.info('Received /unhandled endpoint request')

    obj = {}
    obj['keyDoesnt  Exist']


@app.route('/api', methods=['GET'])
def api():
    logger.info('Received /api endpoint request')
    return "flask /api"


@app.route('/organization', methods=['GET'])
def organization():
    logger.info('Received /organization endpoint request')
    return "flask /organization"


@app.route('/connect', methods=['GET'])
def connect():
    logger.info('Received /connect endpoint request')
    return "flask /connect"


@app.route('/apply-promo-code', methods=['POST'])
def apply_promo_code():
    logger.info('[/apply-promo-code] request received')

    try:
        body = json.loads(request.data)
        promo_code = body.get('value', '').strip()

        if not promo_code:
            logger.warning('[/apply-promo-code] bad request - missing value parameter')
            return '', 400

        promo_code_data = get_promo_code(promo_code)

        if not promo_code_data:
            logger.warning('[/apply-promo-code] code not found: %s', promo_code)
            return jsonify({
                "error": {"code": "not_found", "message": "Promo code not found."}
            }), 404

        promo_dict = dict(promo_code_data)
        logger.info('[/apply-promo-code] code found: %s', promo_dict)

        if promo_dict.get('expires_at') and promo_dict['expires_at'] <= datetime.now():
            logger.warning('[/apply-promo-code] code has expired: %s', promo_code)
            return jsonify({
                "error": {"code": "expired", "message": "Provided coupon code has expired."}
            }), 410  # Look what a clever HTTP response code! Good luck FE dev :D

        logger.info('[/apply-promo-code] valid code found: %s', promo_dict)

        return jsonify({
            "success": True,
            "promo_code": {
                "code": promo_dict['code'],
                "percent_discount": promo_dict['percent_discount'],
                "max_dollar_savings": promo_dict['max_dollar_savings'],
            }
        }), 200

    except Exception as err:
        sentry_sdk.capture_exception(err)
        return '', 500


@app.route('/product/0/info', methods=['GET'])
def product_info():
    logger.info('Received /product/0/info endpoint request')
    time.sleep(.55)
    logger.info('Completed /product/0/info request')
    return "flask /product/0/info"


# uncompressed assets
@app.route('/uncompressed_assets/<path:path>')
def send_report(path):
    logger.info('Received /uncompressed_assets request')
    time.sleep(.55)
    response = send_from_directory('../uncompressed_assets', path)
    response.headers['Timing-Allow-Origin'] = '*'
    response.headers['Content-Type'] = 'application/octet-stream'
    logger.info('Completed /uncompressed_assets request')
    return response


# compressed assets
@app.route('/compressed_assets/<path:path>')
def send_report_configured_properly(path):
    logger.info('Received /compressed_assets request')
    response = send_from_directory('../compressed_assets', path)
    response.headers['Timing-Allow-Origin'] = '*'
    logger.info('Completed /compressed_assets request')
    return response


@app.before_request
def sentry_event_context():
    # Extract the demo's context headers the React app attaches to every request,
    # and mirror them onto the Sentry scope so they show up as tags/user on the
    # backend side of the distributed trace.
    se = request.headers.get('se')
    customerType = request.headers.get('customerType')
    email = request.headers.get('email')
    cexp = request.headers.get('cexp')

    if se not in [None, "undefined"]:
        sentry_sdk.set_tag("se", se)
    else:
        se = request.args.get('se')
        if se not in [None, "undefined"]:
            sentry_sdk.set_tag("se", se)

    if customerType not in [None, "undefined"]:
        sentry_sdk.set_tag("customerType", customerType)

    if email not in [None, "undefined"]:
        sentry_sdk.set_user({"email": email})

    if cexp not in [None, "undefined"]:
        sentry_sdk.set_tag("cexp", cexp)
