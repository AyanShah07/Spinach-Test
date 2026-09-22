"""Structured exception + validation error shape tests."""
from app.core.exceptions import AppError, NotFoundError, RateLimitError, ErrorBody


def test_app_error_fields():
    err = AppError("boom", code="x", status_code=400, details={"a": 1})
    assert err.message == "boom"
    assert err.code == "x"
    assert err.status_code == 400
    assert err.details == {"a": 1}


def test_not_found():
    err = NotFoundError("missing")
    assert err.status_code == 404
    assert err.code == "not_found"


def test_rate_limit():
    err = RateLimitError()
    assert err.status_code == 429


def test_error_body_schema():
    body = ErrorBody(error="e", code="c", details=None)
    assert body.model_dump()["code"] == "c"
