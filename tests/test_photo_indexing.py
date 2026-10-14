from unittest.mock import Mock

from pyicloud_ipd.response_types import (
    PhotoLibraryInitSuccess,
    PhotoLibraryNotFinishedIndexing,
    ResponseSuccess,
)
from pyicloud_ipd.services import photos


class JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def indexing_response(state: str, progress: int, job_id: str = "job-1") -> JsonResponse:
    return JsonResponse(
        {
            "records": [
                {
                    "fields": {
                        "state": {"value": state},
                        "progress": {"value": progress},
                        "indexJobId": {"value": job_id},
                    }
                }
            ]
        }
    )


def make_session(responses: list[JsonResponse]) -> Mock:
    session = Mock()
    session.post.side_effect = responses
    session.evaluate_response.side_effect = lambda response: ResponseSuccess(response)
    return session


def test_indexing_poll_retries_until_finished(monkeypatch) -> None:
    session = make_session(
        [indexing_response("RUNNING", 0), indexing_response("FINISHED", 100, "job-2")]
    )
    clock = iter([0.0, 0.0, 1.0, 1.0, 1.0, 2.0])
    monkeypatch.setenv("ICLOUDPD_INDEXING_TIMEOUT", "15")
    monkeypatch.setattr(photos.time, "monotonic", lambda: next(clock))
    sleep = Mock()
    monkeypatch.setattr(photos.time, "sleep", sleep)

    result = photos.PhotoLibrary.check_and_create(
        "https://example.test",
        {},
        session,
        {"zoneName": "PrimarySync"},
        "private",
    )

    assert isinstance(result, PhotoLibraryInitSuccess)
    assert session.post.call_count == 2
    sleep.assert_called_once_with(5.0)


def test_indexing_terminal_state_does_not_wait(monkeypatch) -> None:
    session = make_session([indexing_response("COMPLETED", 100)])
    monkeypatch.setenv("ICLOUDPD_INDEXING_TIMEOUT", "300")
    sleep = Mock()
    monkeypatch.setattr(photos.time, "sleep", sleep)

    result = photos.PhotoLibrary.check_and_create(
        "https://example.test",
        {},
        session,
        {"zoneName": "PrimarySync"},
        "private",
    )

    assert isinstance(result, PhotoLibraryNotFinishedIndexing)
    assert result.reason == (
        "Apple returned an unexpected indexing state. The Photos library could not be initialized."
    )
    sleep.assert_not_called()


def test_invalid_timeout_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("ICLOUDPD_INDEXING_TIMEOUT", "nan")

    assert photos._indexing_timeout_seconds() == photos._DEFAULT_INDEXING_TIMEOUT
