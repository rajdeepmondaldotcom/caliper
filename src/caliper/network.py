from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable

from caliper import __version__

DEFAULT_TIMEOUT_SECONDS = 5
CALIPER_USER_AGENT = f"caliper/{__version__}"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def validate_source_url(
    url: str,
    *,
    allowed_schemes: set[str],
    source_kind: str,
) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        raise ValueError(f"unsupported {source_kind} URL: {url}")
    return url


def fetch_text(
    url: str,
    *,
    allowed_schemes: set[str],
    source_kind: str,
    user_agents: Iterable[str] = (CALIPER_USER_AGENT,),
    accept: str = "application/json,text/html,text/plain,*/*",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retry_statuses: set[int] | None = None,
) -> str:
    return fetch_bytes(
        url,
        allowed_schemes=allowed_schemes,
        source_kind=source_kind,
        user_agents=user_agents,
        accept=accept,
        timeout=timeout,
        retry_statuses=retry_statuses,
    ).decode("utf-8", errors="replace")


def fetch_bytes(
    url: str,
    *,
    allowed_schemes: set[str],
    source_kind: str,
    user_agents: Iterable[str] = (CALIPER_USER_AGENT,),
    accept: str = "application/json,text/html,text/plain,*/*",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retry_statuses: set[int] | None = None,
) -> bytes:
    try:
        validate_source_url(url, allowed_schemes=allowed_schemes, source_kind=source_kind)
    except ValueError as exc:
        raise OSError(str(exc)) from exc

    retryable = retry_statuses or set()
    last_error: OSError | None = None
    for user_agent in tuple(user_agents):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": accept},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in retryable:
                raise
        except OSError:
            raise
    if last_error is not None:
        raise last_error
    raise OSError(f"could not fetch {source_kind} URL: {url}")
