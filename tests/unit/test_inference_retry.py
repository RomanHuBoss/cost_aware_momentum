from app.workers.runner import should_retry_incomplete_inference


def test_partial_hourly_inference_is_retryable() -> None:
    assert should_retry_incomplete_inference(
        {
            "symbols_total": 141,
            "published": 1,
            "existing_current_hour": 0,
            "inference_retry_count": 0,
        },
        max_retries=5,
    )


def test_complete_hourly_inference_is_not_retryable() -> None:
    assert not should_retry_incomplete_inference(
        {
            "symbols_total": 141,
            "published": 20,
            "existing_current_hour": 121,
            "inference_retry_count": 2,
        },
        max_retries=5,
    )


def test_hourly_inference_stops_after_retry_limit() -> None:
    assert not should_retry_incomplete_inference(
        {
            "symbols_total": 141,
            "published": 0,
            "existing_current_hour": 0,
            "inference_retry_count": 5,
        },
        max_retries=5,
    )
