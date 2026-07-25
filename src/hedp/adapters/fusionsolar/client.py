import base64
import secrets
import time
from functools import wraps
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from hedp.adapters.external_errors import (
    AUTHENTICATION_FAILED,
    AUTHENTICATION_REQUIRED,
    INVALID_RESPONSE,
    ExternalErrorReport,
    ExternalServiceError,
)


def _within_operation_budget(method):
    """Share one wall-clock budget across a public client operation."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        outermost = self._operation_deadline is None
        if outermost:
            self._operation_deadline = (
                time.monotonic() + self.operation_timeout_seconds
            )
        try:
            return method(self, *args, **kwargs)
        finally:
            if outermost:
                self._operation_deadline = None

    return wrapped


class FusionSolarClient:
    _REDIRECT_STATUSES = {301, 302, 303, 307, 308}
    _AUTH_FAILURE_STATUSES = _REDIRECT_STATUSES | {401, 403}

    def __init__(
        self,
        base_url: str,
        station_dn: str,
        username: str,
        password: str,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
        operation_timeout_seconds: float = 120.0,
    ) -> None:
        if not 0 < connect_timeout_seconds <= 60:
            raise ValueError(
                "connect_timeout_seconds must be greater than 0 and at most 60"
            )
        if not 0 < read_timeout_seconds <= 120:
            raise ValueError(
                "read_timeout_seconds must be greater than 0 and at most 120"
            )
        if not 0 < operation_timeout_seconds <= 300:
            raise ValueError(
                "operation_timeout_seconds must be greater than 0 and at most 300"
            )
        self.base_url = base_url.rstrip("/")
        self.station_dn = station_dn
        self.username = username
        self.password = password
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.operation_timeout_seconds = operation_timeout_seconds
        self._operation_deadline: Optional[float] = None
        self.session = requests.Session()
        self.csrf_token: Optional[str] = None

    @_within_operation_budget
    def login(self) -> None:
        app_url = (
            f"{self.base_url}/pvmswebsite/assets/build/index.html"
            f"#/view/station/{self.station_dn}/overview"
        )
        auth_service = f"/unisess/v1/auth?service={quote(app_url, safe='')}"
        login_url = self._url("/unisso/login.action")
        login_referer = f"{login_url}?service={quote(auth_service, safe='')}"
        common_headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": login_referer,
            "X-Requested-With": "XMLHttpRequest",
        }

        login_response = self.session.get(
            login_url,
            params={"service": auth_service},
            allow_redirects=False,
            timeout=self._request_timeout(),
        )
        self._raise_for_status(login_response)
        self._raise_for_auth_challenge(login_response)

        public_key_response = self.session.get(
            self._url("/unisso/pubkey"),
            headers=common_headers,
            timeout=self._request_timeout(),
        )
        self._raise_for_status(public_key_response)
        public_key_data = self._nested_data(self._json_object(public_key_response))

        enable_encrypt = bool(public_key_data.get("enableEncrypt"))
        password = self.password
        version = "v2"
        validation_params = {"service": auth_service, "decision": "1"}
        if enable_encrypt:
            public_key = public_key_data.get("pubKey")
            public_key_version = public_key_data.get("version")
            if not isinstance(public_key, str):
                raise ExternalServiceError(INVALID_RESPONSE)
            if not isinstance(public_key_version, (str, int)):
                raise ExternalServiceError(INVALID_RESPONSE)
            password = self._encrypt_password(
                public_key, str(public_key_version)
            )
            version = "v3"
            validation_params.update(
                {
                    "timeStamp": str(int(time.time() * 1000)),
                    "nonce": secrets.token_hex(16),
                }
            )

        validation_headers = {
            **common_headers,
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": self._origin(),
        }
        validation_response = self.session.post(
            self._url(f"/unisso/{version}/validateUser.action"),
            params=validation_params,
            json={
                "organizationName": "",
                "username": self.username,
                "password": password,
                "verifycode": "",
                "multiRegionName": "",
            },
            headers=validation_headers,
            timeout=self._request_timeout(),
        )
        self._raise_for_status(validation_response)
        validation_data = self._json_object(validation_response)
        self._raise_for_auth_challenge(validation_response, validation_data)

        transition_url = self._transition_url(validation_data)
        if transition_url is None:
            raise ExternalServiceError(AUTHENTICATION_FAILED)
        self._follow_redirects(urljoin(self.base_url, transition_url))

        session_data = self._get_session_data()
        csrf_token = session_data.get("csrfToken")
        if not isinstance(csrf_token, str) or len(csrf_token) < 16:
            raise ExternalServiceError(AUTHENTICATION_FAILED)
        self.csrf_token = csrf_token

    @_within_operation_budget
    def is_session_active(self) -> bool:
        try:
            data = self._get_session_data()
        except (requests.RequestException, RuntimeError, TypeError, ValueError):
            return False
        csrf_token = data.get("csrfToken")
        if not isinstance(csrf_token, str) or len(csrf_token) < 16:
            return False
        self.csrf_token = csrf_token
        return True

    @_within_operation_budget
    def get_json(
        self, url: str, headers: Optional[dict[str, str]] = None
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/pvmswebsite/assets/build/index.html",
            "X-Requested-With": "XMLHttpRequest",
            "X-Timezone-Offset": "540",
            "X-Non-Renewal-Session": "true",
            "roarand": self.csrf_token or "",
        }
        if headers:
            request_headers.update(headers)

        response = self._get_api_response(url, request_headers)
        if self._is_auth_failure(response):
            self.login()
            request_headers["roarand"] = self.csrf_token or ""
            if headers:
                request_headers.update(headers)
            response = self._get_api_response(url, request_headers)
        if self._is_auth_failure(response):
            raise ExternalServiceError(AUTHENTICATION_FAILED)
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as error:
            raise ExternalServiceError(INVALID_RESPONSE) from error

    @_within_operation_budget
    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/pvmswebsite/assets/build/index.html",
            "X-Requested-With": "XMLHttpRequest",
            "X-Timezone-Offset": "540",
            "X-Non-Renewal-Session": "true",
            "roarand": self.csrf_token or "",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": self.base_url,
        }
        if headers:
            request_headers.update(headers)

        request_url = urljoin(f"{self.base_url}/", url)
        response = self.session.post(
            request_url,
            json=payload,
            headers=request_headers,
            allow_redirects=False,
            timeout=self._request_timeout(),
        )
        if self._is_auth_failure(response):
            self.login()
            request_headers["roarand"] = self.csrf_token or ""
            if headers:
                request_headers.update(headers)
            response = self.session.post(
                request_url,
                json=payload,
                headers=request_headers,
                allow_redirects=False,
                timeout=self._request_timeout(),
            )
        if self._is_auth_failure(response):
            raise ExternalServiceError(AUTHENTICATION_FAILED)
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as error:
            raise ExternalServiceError(INVALID_RESPONSE) from error

    def _get_api_response(
        self, url: str, headers: dict[str, str]
    ) -> requests.Response:
        return self.session.get(
            urljoin(f"{self.base_url}/", url),
            headers=headers,
            allow_redirects=False,
            timeout=self._request_timeout(),
        )

    def _get_session_data(self) -> dict[str, Any]:
        response = self.session.get(
            self._url("/unisess/v1/auth/session"),
            params={"_": int(time.time() * 1000)},
            allow_redirects=False,
            timeout=self._request_timeout(),
        )
        if self._is_auth_failure(response):
            raise ExternalServiceError(AUTHENTICATION_FAILED)
        self._raise_for_status(response)
        return self._nested_data(self._json_object(response))

    def _follow_redirects(self, url: str) -> None:
        current_url = url
        for redirect_count in range(13):
            response = self.session.get(
                current_url,
                allow_redirects=False,
                timeout=self._request_timeout(),
            )
            if response.status_code not in self._REDIRECT_STATUSES:
                self._raise_for_status(response)
                self._raise_for_auth_challenge(response)
                return
            if redirect_count == 12:
                raise ExternalServiceError(AUTHENTICATION_FAILED)
            location = response.headers.get("Location")
            if not location:
                raise ExternalServiceError(AUTHENTICATION_FAILED)
            current_url = urljoin(current_url, location)

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path)

    def _origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    def _request_timeout(self) -> tuple[float, float]:
        """Return bounded connect/read timeouts without exceeding the operation budget."""

        if self._operation_deadline is None:
            raise RuntimeError("FusionSolar request attempted outside an operation")
        remaining_seconds = self._operation_deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise requests.Timeout("FusionSolar operation exceeded its time budget")
        connect_timeout = min(
            self.connect_timeout_seconds, remaining_seconds / 2
        )
        read_timeout = min(
            self.read_timeout_seconds, remaining_seconds - connect_timeout
        )
        return (
            connect_timeout,
            read_timeout,
        )

    @staticmethod
    def _nested_data(data: dict[str, Any]) -> dict[str, Any]:
        nested = data.get("data")
        return nested if isinstance(nested, dict) else data

    @staticmethod
    def _json_object(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as error:
            raise ExternalServiceError(INVALID_RESPONSE) from error
        if not isinstance(data, dict):
            raise ExternalServiceError(INVALID_RESPONSE)
        return data

    @classmethod
    def _is_auth_failure(cls, response: requests.Response) -> bool:
        if response.status_code in cls._AUTH_FAILURE_STATUSES:
            return True
        content_type = response.headers.get("Content-Type", "").lower()
        text = response.text.lstrip().lower()
        return (
            "text/html" in content_type
            or text.startswith("<!doctype html")
            or text.startswith("<html")
        )

    @staticmethod
    def _raise_for_auth_challenge(
        response: requests.Response, data: Optional[dict[str, Any]] = None
    ) -> None:
        auth_messages = []
        if data is not None:
            for source in (data, FusionSolarClient._nested_data(data)):
                for key in (
                    "captcha",
                    "needCaptcha",
                    "needVerifyCode",
                    "verifyCodeRequired",
                    "verificationCodeRequired",
                ):
                    if source.get(key) is True:
                        raise ExternalServiceError(AUTHENTICATION_REQUIRED)
                for key in ("errorMsg", "message"):
                    value = source.get(key)
                    if isinstance(value, str) and value:
                        auth_messages.append(value)
        message = " ".join(auth_messages).strip()
        challenge_markers = (
            "captcha",
            "verification code",
            "verifycode",
            "認証コード",
            "確認コード",
        )
        if any(marker in message.lower() for marker in challenge_markers):
            raise ExternalServiceError(AUTHENTICATION_REQUIRED)
        successful_messages = {
            "success",
            "ok",
            "succeeded",
            "operation successful",
        }
        for auth_message in auth_messages:
            if auth_message.strip().lower() not in successful_messages:
                raise ExternalServiceError(AUTHENTICATION_FAILED)

    @staticmethod
    def _transition_url(data: dict[str, Any]) -> Optional[str]:
        for source in (data, FusionSolarClient._nested_data(data)):
            regions = source.get("respMultiRegionName")
            if (
                isinstance(regions, list)
                and len(regions) > 1
                and isinstance(regions[1], str)
            ):
                return regions[1]

        def find(value: Any) -> Optional[str]:
            if isinstance(value, str):
                if "/unisess/v1/auth" in value and "ticket=" in value:
                    return value
                return None
            if isinstance(value, dict):
                for nested in value.values():
                    result = find(nested)
                    if result is not None:
                        return result
            if isinstance(value, list):
                for nested in value:
                    result = find(nested)
                    if result is not None:
                        return result
            return None

        return find(data)

    def _encrypt_password(
        self, public_key_text: str, version: str
    ) -> str:
        try:
            public_key = serialization.load_pem_public_key(
                public_key_text.encode("utf-8")
            )
            encoded_password = quote(self.password, safe="")
            encrypted_blocks = []
            for start in range(0, len(encoded_password), 270):
                block = encoded_password[start : start + 270]
                encrypted = public_key.encrypt(
                    block.encode("utf-8"),
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA384()),
                        algorithm=hashes.SHA384(),
                        label=None,
                    ),
                )
                encrypted_blocks.append(
                    base64.b64encode(encrypted).decode("ascii")
                )
        except (TypeError, ValueError) as error:
            raise ExternalServiceError(INVALID_RESPONSE) from error
        return "00000001".join(encrypted_blocks) + version

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            status_code = getattr(response, "status_code", 0)
            if status_code in {401, 403}:
                raise ExternalServiceError(AUTHENTICATION_FAILED) from error
            retryable = status_code >= 500 or status_code == 429
            code = "service_unavailable" if retryable else "request_rejected"
            raise ExternalServiceError(
                ExternalErrorReport(
                    "service_unavailable" if retryable else "request_rejected",
                    "service",
                    code,
                    retryable,
                )
            ) from error
