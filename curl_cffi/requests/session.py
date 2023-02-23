import re
from enum import Enum
from functools import partialmethod
from io import BytesIO
from json import dumps
from typing import Dict, List, Optional, Tuple, Union, cast
from urllib.parse import ParseResult, parse_qsl, unquote, urlencode, urlparse

from .. import Curl, CurlError, CurlInfo, CurlOpt
from .cookies import Cookies, CookieTypes, Request, Response
from .errors import RequestsError
from .headers import Headers, HeaderTypes


class BrowserType(str, Enum):
    edge99 = "edge99"
    edge101 = "edge101"
    chrome99 = "chrome99"
    chrome100 = "chrome100"
    chrome101 = "chrome101"
    chrome104 = "chrome104"
    chrome99_android = "chrome99_android"
    safari15_3 = "safari15_3"
    safari15_5 = "safari15_5"

    @classmethod
    def has(cls, item):
        return item in cls.__members__


def _update_url_params(url: str, params: Dict) -> str:
    """Add GET params to provided URL being aware of existing.

    :param url: string of target URL
    :param params: dict containing requested params to be added
    :return: string with updated URL

    >> url = 'http://stackoverflow.com/test?answers=true'
    >> new_params = {'answers': False, 'data': ['some','values']}
    >> _update_url_params(url, new_params)
    'http://stackoverflow.com/test?data=some&data=values&answers=false'
    """
    # Unquoting URL first so we don't loose existing args
    url = unquote(url)
    # Extracting url info
    parsed_url = urlparse(url)
    # Extracting URL arguments from parsed URL
    get_args = parsed_url.query
    # Converting URL arguments to dict
    parsed_get_args = dict(parse_qsl(get_args))
    # Merging URL arguments dict with new params
    parsed_get_args.update(params)

    # Bool and Dict values should be converted to json-friendly values
    # you may throw this part away if you don't like it :)
    parsed_get_args.update(
        {k: dumps(v) for k, v in parsed_get_args.items() if isinstance(v, (bool, dict))}
    )

    # Converting URL argument to proper query string
    encoded_get_args = urlencode(parsed_get_args, doseq=True)
    # Creating new parsed result object based on provided with new
    # URL arguments. Same thing happens inside of urlparse.
    new_url = ParseResult(
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        encoded_get_args,
        parsed_url.fragment,
    ).geturl()

    return new_url


def _update_header_line(header_lines: List[str], key: str, value: str):
    for idx, line in enumerate(header_lines):
        if line.lower().startswith(key + ":"):
            header_lines[idx] = f"{key}: {value}"
            break
    else:  # if not break
        header_lines.append(f"{key}: {value}")


class Session:
    __attrs__ = [
        "headers",
        "cookies",
        "auth",
        "proxies",
        "params",
        "verify",
        "cert",
        "stream",  # TODO
        "trust_env",  # TODO
        "max_redirects",
        "impersonate",
        "timeout"
    ]

    def __init__(
        self,
        *,
        curl: Optional[Curl] = None,
        headers: Optional[HeaderTypes] = None,
        cookies: Optional[CookieTypes] = None,
        auth: Optional[Tuple[str, str]] = None,
        proxies: Optional[dict] = None,
        params: Optional[dict] = None,
        verify: bool = True,
        timeout: Union[float, Tuple[float, float]] = 30,
        trust_env: bool = True,
        max_redirects: int = -1,
        impersonate: Optional[Union[str, BrowserType]] = None,
    ):
        self.curl = curl if curl is not None else Curl()
        self.headers = Headers(headers)
        self.cookies = Cookies(cookies)
        self.auth = auth
        self.proxies = proxies
        self.params = params
        self.verify = verify
        self.timeout = timeout
        self.trust_env = trust_env
        self.max_redirects = max_redirects
        self.impersonate = impersonate

    def __enter__(self):
        return self

    def __exit__(self):
        self.close()

    def close(self):
        self.curl.close()

    def request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        data: Optional[Union[Dict[str, str], BytesIO, bytes]] = None,
        json: Optional[dict] = None,
        headers: Optional[HeaderTypes] = None,
        cookies: Optional[CookieTypes] = None,
        files: Optional[Dict] = None,
        auth: Optional[Tuple[str, str]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        allow_redirects: bool = True,
        max_redirects: Optional[int] = None,
        proxies: Optional[dict] = None,
        verify: Optional[bool] = None,
        referer: Optional[str] = None,
        accept_encoding: Optional[str] = "gzip, deflate, br",
        impersonate: Optional[Union[str, BrowserType]] = None,
    ) -> Response:
        c = self.curl

        # method
        c.setopt(CurlOpt.CUSTOMREQUEST, method.encode())

        # url
        if self.params:
            url = _update_url_params(url, self.params)
        if params:
            url = _update_url_params(url, params)
        c.setopt(CurlOpt.URL, url.encode())

        # data/body/json
        if isinstance(data, dict):
            body = urlencode(data).encode()
        elif isinstance(data, BytesIO):
            body = data.read()
        elif isinstance(data, bytes):
            body = data
        elif data is None:
            body = b""
        else:
            raise TypeError("data must be dict, BytesIO or bytes")
        if json:
            body = dumps(json).encode()
        if body:
            c.setopt(CurlOpt.POSTFIELDS, body)
            # necessary if body contains '\0'
            c.setopt(CurlOpt.POSTFIELDSIZE, len(body))

        # headers
        h = Headers(self.headers)
        h.update(headers)

        # cookies
        co = Cookies(self.cookies)
        co.update(cookies)
        req = Request(url=url, headers=h, method=method)
        co.set_cookie_header(req)

        # An alternative way to implement cookiejar is to use curl's builtin cookiejar,
        # However, it would be diffcult to interploate with Headers and get cookies as
        # dicta
        # c.setopt(CurlOpt.COOKIE, cookies_str.encode())

        header_lines = []
        for k, v in h.multi_items():
            header_lines.append(f"{k}: {v}")
        if json:
            _update_header_line(header_lines, "Content-Type", "application/json")
        if isinstance(data, dict):
            _update_header_line(
                header_lines, "Content-Type", "application/x-www-form-urlencoded"
            )
        c.setopt(CurlOpt.HTTPHEADER, [h.encode() for h in header_lines])

        # files
        if files:
            raise NotImplementedError("Files has not been implemented.")

        # auth
        if self.auth or auth:
            if self.auth:
                username, password = self.auth
            if auth:
                username, password = auth
            c.setopt(CurlOpt.USERNAME, username.encode())  # type: ignore
            c.setopt(CurlOpt.PASSWORD, password.encode())  # type: ignore

        # timeout
        timeout = timeout or self.timeout
        if isinstance(timeout, tuple):
            connect_timeout, read_timeout = timeout
            all_timeout = connect_timeout + read_timeout
            c.setopt(CurlOpt.CONNECTTIMEOUT_MS, int(connect_timeout * 1000))
            c.setopt(CurlOpt.TIMEOUT_MS, int(all_timeout * 1000))
        else:
            c.setopt(CurlOpt.TIMEOUT_MS, int(timeout * 1000))

        # allow_redirects
        c.setopt(CurlOpt.FOLLOWLOCATION, int(allow_redirects))

        # max_redirects
        c.setopt(CurlOpt.MAXREDIRS, max_redirects or self.max_redirects)

        # proxies
        if self.proxies:
            proxies = {**self.proxies, **(proxies or {})}
        if proxies:
            if url.startswith("http://"):
                c.setopt(CurlOpt.PROXY, proxies["http"])
            elif url.startswith("https://"):
                if proxies["https"].startswith("https://"):
                    raise RequestsError(
                        "You are using http proxy WRONG, the prefix should be 'http://' not 'https://', see: https://github.com/yifeikong/curl_cffi/issues/6"
                    )
                c.setopt(CurlOpt.PROXY, proxies["https"])
                # for http proxy, need to tell curl to enable tunneling
                if not proxies["https"].startswith("socks"):
                    c.setopt(CurlOpt.HTTPPROXYTUNNEL, 1)

        # verify
        if verify is False or not self.verify and verify is None:
            c.setopt(CurlOpt.SSL_VERIFYPEER, 0)
            c.setopt(CurlOpt.SSL_VERIFYHOST, 0)

        # referer
        if referer:
            c.setopt(CurlOpt.REFERER, referer.encode())

        # accept_encoding
        if accept_encoding is not None:
            c.setopt(CurlOpt.ACCEPT_ENCODING, accept_encoding.encode())

        # impersonate
        impersonate = impersonate or self.impersonate
        if impersonate:
            if not BrowserType.has(impersonate):
                raise RequestsError(f"impersonate {impersonate} is not supported")
            c.impersonate(impersonate)

        buffer = BytesIO()
        c.setopt(CurlOpt.WRITEFUNCTION, buffer.write)
        header_buffer = BytesIO()
        c.setopt(CurlOpt.HEADERFUNCTION, header_buffer.write)

        try:
            c.perform()
        except CurlError as e:
            raise RequestsError(e)

        rsp = Response(c, req)
        rsp.url = cast(bytes, c.getinfo(CurlInfo.EFFECTIVE_URL)).decode()
        rsp.content = buffer.getvalue()
        rsp.status_code = cast(int, c.getinfo(CurlInfo.RESPONSE_CODE))
        rsp.ok = 200 <= rsp.status_code < 400
        header_lines = header_buffer.getvalue().splitlines()

        # TODO history urls
        header_list = []
        for header_line in header_lines:
            if not header_line.strip():
                continue
            if header_line.startswith(b"HTTP/"):
                # read header from last response
                rsp.reason = c.get_reason_phrase(header_line).decode()
                header_list = []  # empty header list for new redirected response
                continue
            header_list.append(header_line)
        rsp.headers = Headers(header_list)
        self.cookies.extract_cookies(rsp)

        content_type = rsp.headers.get("Content-Type", default="")
        m = re.search(r"charset=([\w-]+)", content_type)
        charset = m.group(1) if m else "utf-8"

        rsp.charset = charset
        rsp.encoding = charset

        rsp.elapsed = cast(float, c.getinfo(CurlInfo.TOTAL_TIME))
        rsp.redirect_count = cast(int, c.getinfo(CurlInfo.REDIRECT_COUNT))
        rsp.redirect_url = cast(bytes, c.getinfo(CurlInfo.REDIRECT_URL)).decode()

        return rsp

    head = partialmethod(request, "HEAD")
    get = partialmethod(request, "GET")
    post = partialmethod(request, "POST")
    put = partialmethod(request, "PUT")
    patch = partialmethod(request, "PATCH")
    delete = partialmethod(request, "DELETE")
