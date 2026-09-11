import io

import pytest
from fastapi.testclient import TestClient

from agentictriage.api import app
from agentictriage.ingest import SheetFormatError, parse_tickets
from agentictriage.jobs import JobPayload, JobSubmission

HEADER = "id,subject,body,region,regulated\n"


def sheet(*rows: str) -> bytes:
    return (HEADER + "".join(rows)).encode("utf-8")


def test_csv_rows_become_tickets_scoped_to_the_caller_tenant() -> None:
    data = sheet("t-1,Card declined,Customer card was declined,eu,true\n")
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert parsed.errors == []
    assert len(parsed.tickets) == 1
    ticket = parsed.tickets[0]
    assert ticket.id == "t-1"
    assert ticket.tenant_id == "tenant-a"
    assert ticket.region == "eu"
    assert ticket.regulated is True


def test_tenant_column_in_the_file_cannot_override_the_caller() -> None:
    data = b"id,tenant_id,subject,body\nt-1,tenant-evil,Sub,Body text\n"
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert parsed.tickets[0].tenant_id == "tenant-a"


def test_optional_columns_fall_back_to_model_defaults() -> None:
    data = b"id,subject,body\nt-1,Sub,Body text\n"
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert parsed.tickets[0].region == "unspecified"
    assert parsed.tickets[0].regulated is False


def test_excel_utf8_bom_is_stripped_from_the_first_header() -> None:
    data = b"\xef\xbb\xbf" + sheet("t-1,Sub,Body text,eu,no\n")
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert [ticket.id for ticket in parsed.tickets] == ["t-1"]


def test_bad_row_is_reported_without_losing_the_good_rows() -> None:
    data = sheet(
        "t-1,Sub,Body text,eu,false\n",
        ",Sub,Body text,eu,false\n",  # blank id
        "t-3,Sub,Body text,eu,false\n",
    )
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert [ticket.id for ticket in parsed.tickets] == ["t-1", "t-3"]
    assert [error.row for error in parsed.errors] == [3]


def test_unrecognised_regulated_value_is_an_error_not_a_silent_false() -> None:
    data = sheet("t-1,Sub,Body text,eu,maybe\n")
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert parsed.tickets == []
    assert "regulated" in parsed.errors[0].error


def test_blank_trailing_rows_are_skipped() -> None:
    data = sheet("t-1,Sub,Body text,eu,false\n", ",,,,\n", ",,,,\n")
    parsed = parse_tickets(data, "tickets.csv", tenant_id="tenant-a")

    assert len(parsed.tickets) == 1
    assert parsed.errors == []


def test_missing_required_column_rejects_the_whole_file() -> None:
    with pytest.raises(SheetFormatError, match="body"):
        parse_tickets(b"id,subject\nt-1,Sub\n", "tickets.csv", tenant_id="tenant-a")


def test_empty_file_is_rejected() -> None:
    with pytest.raises(SheetFormatError, match="empty"):
        parse_tickets(b"", "tickets.csv", tenant_id="tenant-a")


def workbook_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.append(["id", "subject", "body", "region", "regulated"])
    worksheet.append(["t-1", "Card declined", "Customer card was declined", "eu", True])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_is_parsed_and_native_booleans_survive() -> None:
    parsed = parse_tickets(workbook_bytes(), "tickets.xlsx", tenant_id="tenant-a")

    assert parsed.errors == []
    assert parsed.tickets[0].id == "t-1"
    assert parsed.tickets[0].regulated is True


def test_xlsx_detected_by_magic_bytes_despite_a_csv_filename() -> None:
    parsed = parse_tickets(workbook_bytes(), "mislabelled.csv", tenant_id="tenant-a")

    assert [ticket.id for ticket in parsed.tickets] == ["t-1"]


class StubQueue:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def enqueue(
        self, tenant_id: str, idempotency_key: str, payload: JobPayload
    ) -> JobSubmission:
        self.keys.append(idempotency_key)
        return JobSubmission(id=f"job-{len(self.keys)}", status="queued")


def upload(client: TestClient, data: bytes, name: str = "tickets.csv") -> object:
    return client.post(
        "/v1/triage/batch",
        headers={
            "X-Tenant-ID": "tenant-a",
            "X-Roles": "triage:write",
            "Idempotency-Key": "idem-batch-1",
            "X-Correlation-ID": "corr-batch-1",
        },
        files={"file": (name, data, "text/csv")},
    )


def test_batch_upload_enqueues_one_job_per_row() -> None:
    queue = StubQueue()
    with TestClient(app) as client:
        client.app.state.jobs = queue
        response = upload(client, sheet("t-1,Sub,Body text,eu,false\n", "t-2,Sub,Body,eu,false\n"))

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 2
    assert body["rejected"] == []
    # Keys are scoped per ticket so re-uploading the same sheet is a no-op.
    assert queue.keys == ["idem-batch-1:t-1", "idem-batch-1:t-2"]


def test_batch_upload_reports_rejected_rows_alongside_accepted_ones() -> None:
    with TestClient(app) as client:
        client.app.state.jobs = StubQueue()
        response = upload(client, sheet("t-1,Sub,Body text,eu,false\n", ",Sub,Body,eu,false\n"))

    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected"][0]["row"] == 3


def test_batch_upload_rejects_a_sheet_with_missing_columns() -> None:
    with TestClient(app) as client:
        client.app.state.jobs = StubQueue()
        response = upload(client, b"id,subject\nt-1,Sub\n")

    assert response.status_code == 400
    assert "body" in response.json()["detail"]


def test_batch_upload_requires_the_write_role() -> None:
    with TestClient(app) as client:
        client.app.state.jobs = StubQueue()
        response = client.post(
            "/v1/triage/batch",
            headers={
                "X-Tenant-ID": "tenant-a",
                "X-Roles": "triage:read",
                "Idempotency-Key": "idem-batch-2",
                "X-Correlation-ID": "corr-batch-2",
            },
            files={"file": ("tickets.csv", sheet("t-1,Sub,Body,eu,false\n"), "text/csv")},
        )

    assert response.status_code == 403
