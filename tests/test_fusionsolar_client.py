from unittest.mock import Mock, patch
from urllib.parse import quote

import pytest

from hedp.fusionsolar_client import FusionSolarClient


def make_response(
    *,
    status_code: int = 200,
    json_data=None,
    text: str = "",
    headers=None,
    content_type: str = "application/json",
) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.headers = {"Content-Type": content_type, **(headers or {})}
    response.text = text
    response.json.return_value = json_data
    return response


@pytest.fixture
def client_and_session():
    with patch("hedp.fusionsolar_client.requests.Session") as session_class:
        session = session_class.return_value
        client = FusionSolarClient(
            "https://example.test", "station-dn", "user", "password"
        )
        yield client, session


def test_login_uses_verified_requests_and_follows_redirects(
    client_and_session,
) -> None:
    client, session = client_and_session
    session.get.side_effect = [
        make_response(text="login"),
        make_response(
            json_data={"enableEncrypt": True, "pubKey": "pem", "version": "7"}
        ),
        make_response(status_code=302, headers={"Location": "/redirect/two"}),
        make_response(status_code=303, headers={"Location": "final"}),
        make_response(text="authenticated", content_type="text/plain"),
        make_response(json_data={"csrfToken": "1234567890abcdef"}),
    ]
    session.post.return_value = make_response(
        json_data={
            "respMultiRegionName": [
                "region",
                "/unisess/v1/auth?service=app&ticket=ticket-value",
            ]
        }
    )
    client._encrypt_password = Mock(return_value="encrypted7")

    client.login()

    app_url = (
        "https://example.test/pvmswebsite/assets/build/index.html"
        "#/view/station/station-dn/overview"
    )
    auth_service = f"/unisess/v1/auth?service={quote(app_url, safe='')}"
    login_call = session.get.call_args_list[0]
    assert login_call.args == ("https://example.test/unisso/login.action",)
    assert login_call.kwargs == {
        "params": {"service": auth_service},
        "allow_redirects": False,
    }

    public_key_call = session.get.call_args_list[1]
    assert public_key_call.args == ("https://example.test/unisso/pubkey",)
    assert public_key_call.kwargs["headers"] == {
        "Accept": "application/json, text/plain, */*",
        "Referer": (
            "https://example.test/unisso/login.action?service="
            f"{quote(auth_service, safe='')}"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }

    validate_call = session.post.call_args
    assert validate_call.args == (
        "https://example.test/unisso/v3/validateUser.action",
    )
    assert validate_call.kwargs["params"]["service"] == auth_service
    assert validate_call.kwargs["params"]["decision"] == "1"
    assert validate_call.kwargs["params"]["timeStamp"].isdigit()
    assert len(validate_call.kwargs["params"]["nonce"]) == 32
    assert validate_call.kwargs["json"] == {
        "organizationName": "",
        "username": "user",
        "password": "encrypted7",
        "verifycode": "",
        "multiRegionName": "",
    }
    assert validate_call.kwargs["headers"] == {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://example.test",
        "Referer": (
            "https://example.test/unisso/login.action?service="
            f"{quote(auth_service, safe='')}"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }
    assert session.get.call_args_list[2].args[0].endswith("ticket=ticket-value")
    assert session.get.call_args_list[3].args[0] == (
        "https://example.test/redirect/two"
    )
    assert session.get.call_args_list[4].args[0] == (
        "https://example.test/redirect/final"
    )
    assert session.get.call_args_list[5].kwargs["params"]["_"] > 0
    assert client.csrf_token == "1234567890abcdef"


def test_encrypt_password_url_encodes_chunks_and_appends_version(
    client_and_session,
) -> None:
    client, _ = client_and_session
    client.password = "a b" * 100
    public_key = Mock()
    public_key.encrypt.side_effect = [b"first", b"second"]

    with patch(
        "hedp.fusionsolar_client.serialization.load_pem_public_key",
        return_value=public_key,
    ):
        encrypted = client._encrypt_password("pem", "version-7")

    assert encrypted == "Zmlyc3Q=00000001c2Vjb25kversion-7"
    encrypted_input = b"".join(call.args[0] for call in public_key.encrypt.call_args_list)
    assert encrypted_input == quote(client.password, safe="").encode()
    assert all(
        len(call.args[0]) <= 270 for call in public_key.encrypt.call_args_list
    )


def test_session_active_requires_long_csrf_token(client_and_session) -> None:
    client, session = client_and_session
    session.get.return_value = make_response(
        json_data={"csrfToken": "1234567890abcdef"}
    )

    assert client.is_session_active() is True
    assert client.csrf_token == "1234567890abcdef"
    assert session.get.call_args.kwargs["params"]["_"] > 0


def test_session_inactive_with_short_csrf_token(client_and_session) -> None:
    client, session = client_and_session
    session.get.return_value = make_response(json_data={"csrfToken": "short"})

    assert client.is_session_active() is False


def test_get_json_uses_default_and_overridden_headers(client_and_session) -> None:
    client, session = client_and_session
    client.csrf_token = "1234567890abcdef"
    session.get.return_value = make_response(json_data={"value": 42})

    assert client.get_json("/data", headers={"X-Timezone-Offset": "0"}) == {
        "value": 42
    }
    assert session.get.call_args.kwargs["headers"] == {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://example.test/pvmswebsite/assets/build/index.html",
        "X-Requested-With": "XMLHttpRequest",
        "X-Timezone-Offset": "0",
        "X-Non-Renewal-Session": "true",
        "roarand": "1234567890abcdef",
    }


def test_get_json_logs_in_and_retries_once(client_and_session) -> None:
    client, session = client_and_session
    session.get.side_effect = [
        make_response(status_code=401),
        make_response(json_data={"value": 42}),
    ]

    def login() -> None:
        client.csrf_token = "new-token-123456"

    client.login = Mock(side_effect=login)

    assert client.get_json("/data") == {"value": 42}
    client.login.assert_called_once_with()
    assert session.get.call_count == 2
    assert session.get.call_args_list[1].kwargs["headers"]["roarand"] == (
        "new-token-123456"
    )


def test_get_json_fails_after_single_retry(client_and_session) -> None:
    client, session = client_and_session
    session.get.side_effect = [
        make_response(status_code=401),
        make_response(status_code=403),
    ]
    client.login = Mock()

    with pytest.raises(RuntimeError, match="authentication failed after retry"):
        client.get_json("/data")

    client.login.assert_called_once_with()
    assert session.get.call_count == 2


def test_get_json_rejects_non_json_response(client_and_session) -> None:
    client, session = client_and_session
    response = make_response(text="plain text", content_type="text/plain")
    response.json.side_effect = ValueError
    session.get.return_value = response

    with pytest.raises(RuntimeError, match="not valid JSON"):
        client.get_json("/data")


def test_login_rejects_captcha_message(client_and_session) -> None:
    client, session = client_and_session
    session.get.side_effect = [
        make_response(text="login"),
        make_response(json_data={"enableEncrypt": False}),
    ]
    session.post.return_value = make_response(
        json_data={"errorMsg": "verifycode is required"}
    )

    with pytest.raises(RuntimeError, match="CAPTCHA or a verification code"):
        client.login()


@pytest.mark.parametrize(
    "message",
    ["", "success", "OK", "Succeeded", "Operation Successful"],
)
def test_auth_challenge_accepts_empty_and_success_messages(message) -> None:
    response = make_response(json_data={"message": message})

    FusionSolarClient._raise_for_auth_challenge(
        response, {"message": message}
    )


def test_auth_challenge_rejects_other_non_empty_message() -> None:
    response = make_response(json_data={"errorMsg": "Invalid credentials"})

    with pytest.raises(RuntimeError, match="authentication failed"):
        FusionSolarClient._raise_for_auth_challenge(
            response, {"errorMsg": "Invalid credentials"}
        )


def test_transition_url_is_found_recursively() -> None:
    data = {
        "nested": {
            "items": [
                "ignored",
                "https://example.test/unisess/v1/auth?ticket=value",
            ]
        }
    }

    assert FusionSolarClient._transition_url(data) == (
        "https://example.test/unisess/v1/auth?ticket=value"
    )
