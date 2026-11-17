import os
import base64
import requests
import traceback
import logging
import logging.config
import yaml

with open("/app/src/logging.yaml") as f:
    logging.config.dictConfig(yaml.safe_load(f))

logging.getLogger("urllib3").setLevel(logging.DEBUG)
logging.getLogger("requests").setLevel(logging.DEBUG)
logging.getLogger("aiohttp").setLevel(logging.DEBUG)


def get_oauth_token(token_url: str, client_id: str, client_secret: str) -> str:
    response = requests.post(
        token_url,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_destination(dest_name: str) -> dict:
    token = get_oauth_token(
        os.environ["DEST_URL"] + "/oauth/token",
        os.environ["DEST_CLIENT_ID"],
        os.environ["DEST_CLIENT_SECRET"],
    )
    url = os.environ["DEST_URI"] + f"/destination-configuration/v1/destinations/{dest_name}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["destinationConfiguration"]


def test_http_odata(dest_config: dict, path: str, conn_token: str, proxies: dict) -> requests.Response:
    """Call an OData endpoint on-premise via the Cloud Connector proxy.

    Credentials (user/password) and the SCC Location ID come from the resolved
    BTP Destination rather than direct environment variables.
    """
    backend_user = dest_config.get("User", "")
    backend_pass = dest_config.get("Password", "")
    basic = base64.b64encode(f"{backend_user}:{backend_pass}".encode()).decode()

    headers = {
        "Accept":                            "application/json",
        "Proxy-Authorization":               f"Bearer {conn_token}",
        "Authorization":                     f"Basic {basic}",
        "SAP-Connectivity-SCC-Location_ID":  dest_config.get("CloudConnectorLocationId", ""),
    }

    sap_client = dest_config.get("URL.queries.sap-client", "")
    if sap_client:
        headers["sap-client"] = sap_client

    target_url = dest_config["URL"].rstrip("/") + path
    return requests.get(target_url, headers=headers, proxies=proxies, timeout=600)


if __name__ == "__main__":

    DESTINATION_NAME = os.environ.get("DESTINATION_NAME", "S4H_ODATA_DEST")
    ODATA_PATH       = "/sap/opu/odata/sap/ZKM_I_CUSTOMER_SRV/I_Customer"

    proxy_host = os.getenv(
        "CONNECTIVITY_PROXY_HOST",
         "connectivity-proxy.connectivity-proxy.svc.cluster.local")
    proxy_port = os.getenv("CONNECTIVITY_PROXY_PORT", "20003")
    proxies = {
         "http":  f"http://{proxy_host}:{proxy_port}",
         "https": f"http://{proxy_host}:{proxy_port}",
     }
     #proxies = {
     #"http": "http://connectivity-proxy.default.svc.cluster.local:20003",
     #https": "http://connectivity-proxy.default.svc.cluster.local:20003",
     #}

    try:
        print(f"Resolving BTP destination: {DESTINATION_NAME}")
        dest_config = get_destination(DESTINATION_NAME)
        print(f"Destination resolved — URL: {dest_config.get('URL')}")
        print(f"CC S4 Location ID: {dest_config.get('CloudConnectorLocationId')}")
        print(f"CC SAP Client ID ID: {dest_config.get('URL.queries.sap-client')}")

        print("Acquiring Connectivity Service token")
        conn_token = get_oauth_token(
            os.environ["CP_TOKEN_SERVICE_URL"],
            os.environ["CP_CLIENT_ID"],
            os.environ["CP_CLIENT_SECRET"],
        )
        print("Connectivity token acquired")

        print("### Testing OData call via Cloud Connector ###")
        response = test_http_odata(dest_config, ODATA_PATH, conn_token, proxies)
        response.raise_for_status()

        data    = response.json()
        results = data.get("d", {}).get("results", [])

        print(f"OData call successful. Records returned: {len(results)}")
        if results:
            print(f"Sample record: {results[0]}")

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error: {http_err}")
        print(f"Response body: {response.text}")
    except Exception:
        print(f"Request failed:\n{traceback.format_exc()}")
