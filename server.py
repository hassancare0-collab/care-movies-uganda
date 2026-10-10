# ============================================================
# CARE MOVIES SERVER
# Movie uploads + movie database + MTN MoMo payments
# ============================================================

import os
import json
import uuid
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default


# ============================================================
# BASIC SETTINGS
# ============================================================

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8090))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
IMAGES_DIR = os.path.join(BASE_DIR, "images")

MOVIES_FILE = os.path.join(BASE_DIR, "movies.json")
PAYMENTS_FILE = os.path.join(BASE_DIR, "payments.json")
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "subscriptions.json")


# Create folders if they don't exist
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)


# Create JSON files if they don't exist
def create_json_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)


create_json_file(MOVIES_FILE, [])
create_json_file(PAYMENTS_FILE, [])
create_json_file(SUBSCRIPTIONS_FILE, [])


# ============================================================
# MTN MOBILE MONEY SETTINGS
# ============================================================

MTN_BASE_URL = "https://sandbox.momodeveloper.mtn.com"

MTN_TARGET_ENVIRONMENT = "sandbox"

# ------------------------------------------------------------
# PUT YOUR MTN CREDENTIALS HERE
# ------------------------------------------------------------

MTN_SUBSCRIPTION_KEY = "PUT_YOUR_COLLECTION_PRIMARY_KEY_HERE"

MTN_API_USER = "PUT_YOUR_API_USER_HERE"

MTN_API_KEY = "PUT_YOUR_API_KEY_HERE"

# ------------------------------------------------------------
# IMPORTANT:
# DO NOT PUT THESE KEYS IN caremovies.html
# DO NOT SHARE THESE KEYS WITH ANYONE
# ------------------------------------------------------------


# MTN Sandbox uses EUR according to MTN's current sandbox docs.
# For production Uganda, this should be changed to UGX.
MTN_CURRENCY = "EUR"


# ============================================================
# CARE MOVIES PLANS
# ============================================================

PLANS = {
    "daily": {
        "name": "Daily",
        "amount": 1000,
        "days": 1
    },

    "weekly": {
        "name": "Weekly",
        "amount": 1500,
        "days": 7
    },

    "monthly": {
        "name": "Monthly",
        "amount": 5000,
        "days": 30
    }
}


# ============================================================
# JSON HELPERS
# ============================================================

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else []


def write_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    os.replace(temp_path, path)


# ============================================================
# HTTP RESPONSE HELPERS
# ============================================================

def send_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    handler.send_response(status)

    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, Authorization"
    )

    handler.end_headers()

    handler.wfile.write(body)


def send_error_json(handler, message, status=400):
    send_json(
        handler,
        {
            "success": False,
            "error": message
        },
        status
    )


# ============================================================
# PHONE NUMBER
# ============================================================

def normalize_phone(phone):
    phone = str(phone or "").strip()

    phone = phone.replace(" ", "")
    phone = phone.replace("-", "")

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("0"):
        phone = "256" + phone[1:]

    return phone


# ============================================================
# MTN ACCESS TOKEN
# ============================================================

def get_mtn_access_token():

    if not MTN_SUBSCRIPTION_KEY or MTN_SUBSCRIPTION_KEY.startswith("PUT_"):
        raise Exception("MTN Subscription Key has not been added to server.py")

    if not MTN_API_USER or MTN_API_USER.startswith("PUT_"):
        raise Exception("MTN API User has not been added to server.py")

    if not MTN_API_KEY or MTN_API_KEY.startswith("PUT_"):
        raise Exception("MTN API Key has not been added to server.py")

    credentials = f"{MTN_API_USER}:{MTN_API_KEY}"

    encoded_credentials = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("utf-8")

    url = MTN_BASE_URL + "/collection/token/"

    request = urllib.request.Request(
        url,
        method="POST"
    )

    request.add_header(
        "Authorization",
        "Basic " + encoded_credentials
    )

    request.add_header(
        "Ocp-Apim-Subscription-Key",
        MTN_SUBSCRIPTION_KEY
    )

    request.add_header(
        "X-Target-Environment",
        MTN_TARGET_ENVIRONMENT
    )

    request.add_header(
        "Content-Type",
        "application/x-www-form-urlencoded"
    )

    request.data = b""

    try:

        with urllib.request.urlopen(request, timeout=30) as response:

            response_data = response.read().decode("utf-8")

            data = json.loads(response_data)

            token = data.get("access_token")

            if not token:
                raise Exception(
                    "MTN did not return an access token"
                )

            return token

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise Exception(
            f"MTN token error {e.code}: {error_body}"
        )


# ============================================================
# MTN REQUEST TO PAY
# ============================================================

def request_mtn_payment(amount, phone, plan):

    access_token = get_mtn_access_token()

    reference_id = str(uuid.uuid4())

    external_id = str(uuid.uuid4())

    url = (
        MTN_BASE_URL
        + "/collection/v1_0/requesttopay"
    )

    payload = {
        "amount": str(amount),

        "currency": MTN_CURRENCY,

        "externalId": external_id,

        "payer": {
            "partyIdType": "MSISDN",
            "partyId": phone
        },

        "payerMessage": f"Care Movies {plan} subscription",

        "payeeNote": f"Care Movies {plan} subscription"
    }

    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method="POST"
    )

    request.add_header(
        "Authorization",
        "Bearer " + access_token
    )

    request.add_header(
        "Ocp-Apim-Subscription-Key",
        MTN_SUBSCRIPTION_KEY
    )

    request.add_header(
        "X-Target-Environment",
        MTN_TARGET_ENVIRONMENT
    )

    request.add_header(
        "X-Reference-Id",
        reference_id
    )

    request.add_header(
        "Content-Type",
        "application/json"
    )

    try:

        with urllib.request.urlopen(request, timeout=30) as response:

            status_code = response.getcode()

            return {
                "referenceId": reference_id,
                "statusCode": status_code
            }

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise Exception(
            f"MTN payment error {e.code}: {error_body}"
        )


# ============================================================
# CHECK MTN PAYMENT STATUS
# ============================================================

def get_mtn_payment_status(reference_id):

    access_token = get_mtn_access_token()

    url = (
        MTN_BASE_URL
        + "/collection/v1_0/requesttopay/"
        + reference_id
    )

    request = urllib.request.Request(
        url,
        method="GET"
    )

    request.add_header(
        "Authorization",
        "Bearer " + access_token
    )

    request.add_header(
        "Ocp-Apim-Subscription-Key",
        MTN_SUBSCRIPTION_KEY
    )

    request.add_header(
        "X-Target-Environment",
        MTN_TARGET_ENVIRONMENT
    )

    request.add_header(
        "Content-Type",
        "application/json"
    )

    try:

        with urllib.request.urlopen(request, timeout=30) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            return data

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise Exception(
            f"MTN status error {e.code}: {error_body}"
        )


# ============================================================
# ACTIVATE SUBSCRIPTION
# ============================================================

def activate_subscription(payment):

    subscriptions = read_json(
        SUBSCRIPTIONS_FILE,
        []
    )

    plan_key = payment.get("plan")

    if plan_key not in PLANS:
        return None

    plan = PLANS[plan_key]

    now = datetime.now()

    expires = now + timedelta(
        days=plan["days"]
    )

    subscription = {
        "id": str(uuid.uuid4()),

        "phone": payment.get("phone"),

        "plan": plan_key,

        "planName": plan["name"],

        "amount": plan["amount"],

        "startedAt": now.isoformat(),

        "expiresAt": expires.isoformat(),

        "maxDevices": 3,

        "paymentReference": payment.get(
            "referenceId"
        ),

        "status": "active"
    }

    subscriptions.append(subscription)

    write_json(
        SUBSCRIPTIONS_FILE,
        subscriptions
    )

    return subscription


# ============================================================
# PARSE MULTIPART UPLOAD
# ============================================================

def parse_multipart(handler):

    content_type = handler.headers.get(
        "Content-Type",
        ""
    )

    content_length = int(
        handler.headers.get(
            "Content-Length",
            "0"
        )
    )

    body = handler.rfile.read(content_length)

    header_bytes = (
        b"Content-Type: "
        + content_type.encode("utf-8")
        + b"\r\n\r\n"
    )

    message = BytesParser(
        policy=default
    ).parsebytes(
        header_bytes + body
    )

    fields = {}
    files = {}

    for part in message.iter_parts():

        name = part.get_param(
            "name",
            header="Content-Disposition"
        )

        filename = part.get_filename()

        data = part.get_payload(
            decode=True
        )

        if data is None:
            data = b""

        if filename:

            files[name] = {
                "filename": filename,
                "data": data
            }

        else:

            try:
                fields[name] = data.decode(
                    "utf-8"
                )
            except Exception:
                fields[name] = ""

    return fields, files


# ============================================================
# SAVE UPLOADED FILE
# ============================================================

def safe_extension(filename, default):

    extension = os.path.splitext(
        filename
    )[1].lower()

    allowed = {
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    }

    if extension not in allowed:
        return default

    return extension


# ============================================================
# SERVER
# ============================================================

class CareMoviesHandler(SimpleHTTPRequestHandler):

    def end_headers(self):

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, DELETE, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization"
        )

        super().end_headers()


    # ========================================================
    # OPTIONS
    # ========================================================

    def do_OPTIONS(self):

        self.send_response(204)

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, DELETE, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization"
        )

        self.end_headers()


    # ========================================================
    # GET
    # ========================================================

    def do_GET(self):

        # -----------------------------------------------
        # MOVIES API
        # -----------------------------------------------

        if self.path == "/api/movies":

            movies = read_json(
                MOVIES_FILE,
                []
            )

            result = []

            for movie in movies:

                item = dict(movie)

                video_name = item.get(
                    "videoName",
                    ""
                )

                poster_name = item.get(
                    "posterName",
                    ""
                )

                if video_name:

                    item["video"] = (
                        f"/videos/{video_name}"
                    )

                else:

                    item["video"] = ""

                if poster_name:

                    item["poster"] = (
                        f"/images/{poster_name}"
                    )

                else:

                    item["poster"] = ""

                result.append(item)

            send_json(
                self,
                {
                    "success": True,
                    "movies": result
                }
            )

            return


        # -----------------------------------------------
        # PAYMENT STATUS
        # -----------------------------------------------

        if self.path.startswith(
            "/api/payment-status/"
        ):

            reference_id = self.path[
                len("/api/payment-status/"):
            ]

            if not reference_id:

                send_error_json(
                    self,
                    "Missing payment reference",
                    400
                )

                return

            try:

                status_data = (
                    get_mtn_payment_status(
                        reference_id
                    )
                )

                status = str(
                    status_data.get(
                        "status",
                        ""
                    )
                ).upper()

                payments = read_json(
                    PAYMENTS_FILE,
                    []
                )

                payment = None

                for p in payments:

                    if p.get(
                        "referenceId"
                    ) == reference_id:

                        payment = p

                        break

                # ---------------------------------------
                # SUCCESSFUL PAYMENT
                # ---------------------------------------

                if status == "SUCCESSFUL":

                    if payment:

                        already_activated = payment.get(
                            "subscriptionActivated",
                            False
                        )

                        if not already_activated:

                            subscription = (
                                activate_subscription(
                                    payment
                                )
                            )

                            payment[
                                "subscriptionActivated"
                            ] = True

                            payment[
                                "subscriptionId"
                            ] = (
                                subscription["id"]
                                if subscription
                                else None
                            )

                            payment[
                                "status"
                            ] = "SUCCESSFUL"

                            write_json(
                                PAYMENTS_FILE,
                                payments
                            )

                    send_json(
                        self,
                        {
                            "success": True,
                            "status": "SUCCESSFUL",
                            "payment": status_data
                        }
                    )

                    return


                # ---------------------------------------
                # FAILED PAYMENT
                # ---------------------------------------

                if status in (
                    "FAILED",
                    "REJECTED"
                ):

                    if payment:

                        payment[
                            "status"
                        ] = status

                        write_json(
                            PAYMENTS_FILE,
                            payments
                        )

                    send_json(
                        self,
                        {
                            "success": True,
                            "status": status,
                            "payment": status_data
                        }
                    )

                    return


                # ---------------------------------------
                # STILL WAITING
                # ---------------------------------------

                send_json(
                    self,
                    {
                        "success": True,
                        "status": status or "PENDING",
                        "payment": status_data
                    }
                )

                return

            except Exception as e:

                send_error_json(
                    self,
                    str(e),
                    500
                )

                return


        # -----------------------------------------------
        # NORMAL WEBSITE FILES
        # -----------------------------------------------

        return super().do_GET()


    # ========================================================
    # POST
    # ========================================================

    def do_POST(self):

        # -----------------------------------------------
        # PAYMENT
        # -----------------------------------------------

        if self.path == "/api/pay":

            try:

                content_length = int(
                    self.headers.get(
                        "Content-Length",
                        "0"
                    )
                )

                raw_body = self.rfile.read(
                    content_length
                )

                data = json.loads(
                    raw_body.decode("utf-8")
                )

                plan_key = str(
                    data.get(
                        "plan",
                        ""
                    )
                ).lower()

                phone = normalize_phone(
                    data.get(
                        "phone",
                        ""
                    )
                )

                if plan_key not in PLANS:

                    send_error_json(
                        self,
                        "Invalid subscription plan",
                        400
                    )

                    return

                if not phone:

                    send_error_json(
                        self,
                        "Phone number is required",
                        400
                    )

                    return

                plan = PLANS[plan_key]

                payment_result = request_mtn_payment(
                    plan["amount"],
                    phone,
                    plan["name"]
                )

                reference_id = (
                    payment_result[
                        "referenceId"
                    ]
                )

                payments = read_json(
                    PAYMENTS_FILE,
                    []
                )

                payment = {

                    "id": str(uuid.uuid4()),

                    "referenceId": reference_id,

                    "phone": phone,

                    "plan": plan_key,

                    "planName": plan["name"],

                    "amount": plan["amount"],

                    "currency": MTN_CURRENCY,

                    "status": "PENDING",

                    "subscriptionActivated": False,

                    "createdAt": datetime.now().isoformat()
                }

                payments.append(payment)

                write_json(
                    PAYMENTS_FILE,
                    payments
                )

                send_json(
                    self,
                    {
                        "success": True,

                        "message": (
                            "Payment request sent. "
                            "Approve it on the MTN Mobile Money phone."
                        ),

                        "referenceId": reference_id,

                        "status": "PENDING",

                        "plan": plan["name"],

                        "amount": plan["amount"],

                        "currency": MTN_CURRENCY
                    },
                    202
                )

                return

            except Exception as e:

                send_error_json(
                    self,
                    str(e),
                    500
                )

                return


        # -----------------------------------------------
        # MOVIE UPLOAD
        # -----------------------------------------------

        if self.path == "/upload":

            try:

                fields, files = parse_multipart(
                    self
                )

                title = fields.get(
                    "title",
                    ""
                ).strip()

                description = fields.get(
                    "description",
                    ""
                ).strip()

                category = fields.get(
                    "category",
                    "Action"
                ).strip()

                video_file = (
                    files.get("video")
                    or files.get("videoFile")
                    or files.get("file")
                )

                poster_file = (
                    files.get("poster")
                    or files.get("posterFile")
                    or files.get("image")
                )

                if not title:

                    send_error_json(
                        self,
                        "Movie title is required",
                        400
                    )

                    return

                if not video_file:

                    send_error_json(
                        self,
                        "Video file is required",
                        400
                    )

                    return

                # ---------------------------------------
                # SAVE VIDEO
                # ---------------------------------------

                video_extension = safe_extension(
                    video_file["filename"],
                    ".mp4"
                )

                video_name = (
                    str(uuid.uuid4())
                    + video_extension
                )

                video_path = os.path.join(
                    VIDEOS_DIR,
                    video_name
                )

                with open(
                    video_path,
                    "wb"
                ) as f:

                    f.write(
                        video_file["data"]
                    )


                # ---------------------------------------
                # SAVE POSTER
                # ---------------------------------------

                poster_name = ""

                if poster_file:

                    poster_extension = safe_extension(
                        poster_file["filename"],
                        ".jpg"
                    )

                    poster_name = (
                        str(uuid.uuid4())
                        + poster_extension
                    )

                    poster_path = os.path.join(
                        IMAGES_DIR,
                        poster_name
                    )

                    with open(
                        poster_path,
                        "wb"
                    ) as f:

                        f.write(
                            poster_file["data"]
                        )


                # ---------------------------------------
                # SAVE MOVIE DATABASE ENTRY
                # ---------------------------------------

                movies = read_json(
                    MOVIES_FILE,
                    []
                )

                movie = {

                    "id": str(uuid.uuid4()),

                    "title": title,

                    "description": description,

                    "category": category,

                    "videoName": video_name,

                    "posterName": poster_name,

                    "createdAt": datetime.now().isoformat()
                }

                movies.append(movie)

                write_json(
                    MOVIES_FILE,
                    movies
                )

                send_json(
                    self,
                    {
                        "success": True,

                        "message": "Movie uploaded successfully",

                        "movie": {
                            **movie,

                            "video": (
                                f"/videos/{video_name}"
                            ),

                            "poster": (
                                f"/images/{poster_name}"
                                if poster_name
                                else ""
                            )
                        }
                    }
                )

                return

            except Exception as e:

                send_error_json(
                    self,
                    f"Upload failed: {e}",
                    500
                )

                return


        # -----------------------------------------------
        # UNKNOWN POST
        # -----------------------------------------------

        send_error_json(
            self,
            "Unknown API endpoint",
            404
        )


    # ========================================================
    # DELETE MOVIE
    # ========================================================

    def do_DELETE(self):

        if self.path.startswith(
            "/delete/"
        ):

            movie_id = self.path[
                len("/delete/"):
            ]

            movies = read_json(
                MOVIES_FILE,
                []
            )

            movie_to_delete = None

            for movie in movies:

                if movie.get("id") == movie_id:

                    movie_to_delete = movie

                    break

            if not movie_to_delete:

                send_error_json(
                    self,
                    "Movie not found",
                    404
                )

                return

            # ---------------------------------------
            # DELETE VIDEO
            # ---------------------------------------

            video_name = movie_to_delete.get(
                "videoName",
                ""
            )

            if video_name:

                video_path = os.path.join(
                    VIDEOS_DIR,
                    video_name
                )

                if os.path.exists(video_path):

                    try:
                        os.remove(video_path)
                    except Exception:
                        pass


            # ---------------------------------------
            # DELETE POSTER
            # ---------------------------------------

            poster_name = movie_to_delete.get(
                "posterName",
                ""
            )

            if poster_name:

                poster_path = os.path.join(
                    IMAGES_DIR,
                    poster_name
                )

                if os.path.exists(poster_path):

                    try:
                        os.remove(poster_path)
                    except Exception:
                        pass


            # ---------------------------------------
            # UPDATE DATABASE
            # ---------------------------------------

            movies = [
                movie
                for movie in movies
                if movie.get("id") != movie_id
            ]

            write_json(
                MOVIES_FILE,
                movies
            )

            send_json(
                self,
                {
                    "success": True,
                    "message": "Movie deleted successfully"
                }
            )

            return

        send_error_json(
            self,
            "Unknown delete endpoint",
            404
        )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print()
    print("==============================================")
    print("           CARE MOVIES SERVER")
    print("==============================================")
    print()
    print(f"Server running at:")
    print(f"http://{HOST}:{PORT}")
    print()
    print("Movie API:")
    print(f"http://{HOST}:{PORT}/api/movies")
    print()
    print("Payment API:")
    print(f"http://{HOST}:{PORT}/api/pay")
    print()
    print("Videos folder:")
    print(VIDEOS_DIR)
    print()
    print("Images folder:")
    print(IMAGES_DIR)
    print()
    print("==============================================")
    print()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        CareMoviesHandler
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print()
        print("Care Movies server stopped.")

    finally:

        server.server_close()