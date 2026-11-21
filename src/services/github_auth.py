import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from threading import Event
from time import monotonic, time

import requests
from pydantic import BaseModel, PositiveInt, SecretStr, ValidationError

from src.utils.project_paths import BUNDLE_ROOT, IS_PACKAGED
from src.utils.runtime_support import RuntimeSetupError

CLIENT_ID_ENV = "ASTRABOT_GITHUB_CLIENT_ID"
DEVICE_PAGE = "https://github.com/login/device"
TOKEN_URL = "https://github.com/login/oauth/access_token"


class DeviceCode(BaseModel):
    device_code: SecretStr
    user_code: str
    expires_in: PositiveInt
    interval: PositiveInt


class TokenResponse(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr
    expires_in: PositiveInt


class Session(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float


class OAuthError(BaseModel):
    error: str


def _github_client_id() -> str:
    value = os.environ.get(CLIENT_ID_ENV, "").strip()
    if not value and IS_PACKAGED:
        try:
            return (BUNDLE_ROOT / "github-client-id.txt").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
    return value


def require_github_sign_in(
    progress: Callable[[str], None],
    show_code: Callable[[str], None],
    cancelled: Event,
) -> None:
    client_id = _github_client_id()
    if not client_id:
        return
    progress("Signing in to GitHub...")
    for refresh in (False, True):
        token = authorize(client_id, show_code, cancelled, refresh=refresh)
        if token is None or cancelled.is_set():
            break
        progress("Verifying GitHub sign-in…")
        if verify_identity(token):
            return
    if not cancelled.is_set():
        raise RuntimeSetupError("GitHub sign-in could not be completed. Try again to reconnect.")


def verify_identity(token: str) -> bool:
    try:
        with requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=(5, 10),
            allow_redirects=False,
        ) as response:
            if response.status_code == 401:
                return False
            if response.status_code == 200:
                return True
    except requests.RequestException:
        pass
    raise RuntimeSetupError("Unable to verify your GitHub sign-in. Check your connection and try again.")


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def read_session(target: str) -> Session | None:
    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    credential = ctypes.POINTER(Credential)()
    if not api.CredReadW(ctypes.c_wchar_p(target), 1, 0, ctypes.byref(credential)):
        error = ctypes.get_last_error()
        if error == 1168:
            return None
        raise ctypes.WinError(error)
    try:
        entry = credential.contents
        return Session.model_validate_json(ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize))
    finally:
        api.CredFree(credential)


def save_session(target: str, session: Session) -> None:
    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    payload = session.model_dump_json().encode()
    buffer = ctypes.create_string_buffer(payload)
    credential = Credential(
        Type=1,
        TargetName=target,
        CredentialBlobSize=len(payload),
        CredentialBlob=ctypes.cast(buffer, ctypes.c_void_p),
        Persist=2,
    )
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def oauth_post(url: str, data: dict[str, str]) -> str:
    with requests.post(
        url, data=data, headers={"Accept": "application/json"}, timeout=(5, 10), allow_redirects=False
    ) as response:
        if response.status_code != 200:
            raise RuntimeSetupError("GitHub authorization is temporarily unavailable.")
        return response.text


def exchange(data: dict[str, str]) -> Session | str:
    payload = oauth_post(TOKEN_URL, data)
    try:
        result = TokenResponse.model_validate_json(payload)
    except ValidationError:
        return OAuthError.model_validate_json(payload).error
    return Session(
        access_token=result.access_token.get_secret_value(),
        refresh_token=result.refresh_token.get_secret_value(),
        expires_at=time() + result.expires_in,
    )


def authorize(
    client_id: str,
    show_code: Callable[[str], None],
    cancelled: Event,
    *,
    refresh: bool = False,
) -> str | None:
    if cancelled.is_set():
        return None
    target = f"AstraBot/GitHub/{client_id}"
    try:
        session = read_session(target)
        if session is not None:
            if not refresh and session.expires_at > time() + 60:
                return session.access_token
            result = exchange(
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": session.refresh_token,
                }
            )
            if isinstance(result, Session):
                save_session(target, result)
                return result.access_token
            if result != "bad_refresh_token":
                raise RuntimeSetupError("GitHub could not renew the authorization.")
        if cancelled.is_set():
            return None
        device = DeviceCode.model_validate_json(
            oauth_post(
                "https://github.com/login/device/code", {"client_id": client_id, "scope": "offline_access"}
            )
        )
        if cancelled.is_set():
            return None
        show_code(device.user_code)
        deadline = monotonic() + device.expires_in
        interval = device.interval
        while not cancelled.wait(min(interval, max(0, deadline - monotonic()))) and monotonic() < deadline:
            result = exchange(
                {
                    "client_id": client_id,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device.device_code.get_secret_value(),
                }
            )
            if isinstance(result, Session):
                if cancelled.is_set():
                    return None
                save_session(target, result)
                return result.access_token
            if result == "slow_down":
                interval += 5
            elif result != "authorization_pending":
                raise RuntimeSetupError("GitHub authorization was declined or expired.")
        return None
    except requests.RequestException, ValidationError, OSError:
        raise RuntimeSetupError("Unable to complete GitHub authorization.") from None
