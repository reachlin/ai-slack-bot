import httpx2
import openai
import pytest

from bot.llm import describe_error

REQ = httpx2.Request("POST", "https://llm.example")


def _status(cls, code):
    return cls("err", response=httpx2.Response(code, request=REQ), body=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_status(openai.RateLimitError, 429), "rate-limited"),
        (_status(openai.AuthenticationError, 401), "API key was rejected"),
        (_status(openai.APIStatusError, 402), "out of credit"),
        (openai.APITimeoutError(REQ), "took too long"),
        (openai.APIConnectionError(request=REQ), "Couldn't reach"),
        (_status(openai.APIStatusError, 503), "having problems (503)"),
        (_status(openai.APIStatusError, 400), "rejected the request (400)"),
        (RuntimeError("boom"), "Something went wrong"),
    ],
)
def test_describe_error(exc, expected):
    assert expected in describe_error(exc)
