from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from time import sleep

import pytest

from fixtures import types
from fixtures.auth import USER_ADMIN_EMAIL, USER_ADMIN_PASSWORD
from fixtures.logs import Logs, insert_logs_to_clickhouse
from fixtures.metrics import Metrics
from fixtures.querier import (
    RequestType,
    build_metrics_aggregation,
    build_scalar_query,
    get_scalar_table_data,
    make_query_request,
)
from fixtures.traces import TraceIdGenerator, Traces, TracesKind, TracesStatusCode, insert_traces_to_clickhouse

PREFIX = "semconv-fam"
CURRENT_KEY = "deployment.environment.name"
OLD_KEY = "deployment.environment"

# Tests compare identity sets filtered by PREFIX, so reruns on a reused stack
# with leftover rows stay stable.
OLD = f"{PREFIX}-old"
NEW = f"{PREFIX}-new"
BOTH = f"{PREFIX}-both"  # current "staging" and old "production" - the conflict row
NEITHER = f"{PREFIX}-neither"

_ROWS = [
    (OLD, {OLD_KEY: "production"}, timedelta(seconds=4)),
    (NEW, {CURRENT_KEY: "production"}, timedelta(seconds=3)),
    (BOTH, {CURRENT_KEY: "staging", OLD_KEY: "production"}, timedelta(seconds=2)),
    (NEITHER, {}, timedelta(seconds=1)),
]


@pytest.fixture(name="family_fleet", scope="package")
def family_fleet(clickhouse: types.TestContainerClickhouse) -> Generator[datetime]:
    """Seeds one time per package. The base aligns to the minute, so no row
    offset crosses a 60s time-series bucket boundary."""
    now = datetime.now(tz=UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)

    def insert_traces(traces: list[Traces]) -> None:
        insert_traces_to_clickhouse(clickhouse.conn, traces)

    def insert_logs(logs: list[Logs]) -> None:
        insert_logs_to_clickhouse(clickhouse.conn, logs)

    insert_traces(
        [
            Traces(
                timestamp=now - offset,
                duration=timedelta(milliseconds=10),
                trace_id=TraceIdGenerator.trace_id(),
                span_id=TraceIdGenerator.span_id(),
                name=identity,
                kind=TracesKind.SPAN_KIND_SERVER,
                status_code=TracesStatusCode.STATUS_CODE_OK,
                resources={"service.name": identity, **family},
                attributes=dict(family),
            )
            for identity, family, offset in _ROWS
        ]
    )
    insert_logs(
        [
            Logs(
                timestamp=now - offset,
                body=identity,
                resources={"service.name": identity, **family},
                attributes=dict(family),
            )
            for identity, family, offset in _ROWS
        ]
    )
    yield now


LABEL_METRIC = "semconv.fam.label.metric"
# A signoz_ name, so the resource_ label layout of the span-metrics
# processor applies.
SPAN_METRIC = "signoz_semconv_fam_calls"
OLD_NAME_METRIC = "k8s.pod.cpu.utilization"
CURRENT_NAME_METRIC = "k8s.pod.cpu.usage"


@pytest.fixture(name="metric_family_fleet", scope="function")
def metric_family_fleet(
    signoz: types.SigNoz,
    create_user_admin: None,  # pylint: disable=unused-argument
    get_token: Callable[[str, str], str],
    insert_metrics: Callable[[list[Metrics]], None],
) -> datetime:
    """Every series has a power-of-two value, so a missed member is a unique
    wrong sum."""
    now = datetime.now(tz=UTC)
    # The querier clamps very recent metric samples (flux interval), so the
    # fleet sits in the past.
    seeded = now - timedelta(minutes=10)
    gauge = {"temporality": "Unspecified", "type_": "Gauge", "is_monotonic": False}
    insert_metrics(
        [
            Metrics(metric_name=LABEL_METRIC, labels={"deployment.environment.name": "staging"}, timestamp=seeded, value=1.0, **gauge),
            Metrics(metric_name=LABEL_METRIC, labels={"deployment.environment": "production"}, timestamp=seeded, value=2.0, **gauge),
            Metrics(metric_name=SPAN_METRIC, labels={"resource_deployment.environment.name": "staging", "pod": "span-current"}, timestamp=seeded, value=4.0, **gauge),
            Metrics(metric_name=LABEL_METRIC, labels={"region": "keyless"}, timestamp=seeded, value=8.0, **gauge),
            Metrics(metric_name=OLD_NAME_METRIC, labels={"pod": "a"}, timestamp=seeded, value=16.0, **gauge),
            Metrics(metric_name=CURRENT_NAME_METRIC, labels={"pod": "b"}, timestamp=seeded, value=32.0, **gauge),
            Metrics(metric_name=LABEL_METRIC, labels={"deployment.environment.name": "staging", "deployment.environment": "production"}, timestamp=seeded, value=64.0, **gauge),
            Metrics(metric_name=SPAN_METRIC, labels={"resource_deployment.environment": "production", "pod": "span-old"}, timestamp=seeded, value=128.0, **gauge),
            Metrics(metric_name=SPAN_METRIC, labels={"deployment.environment": "production", "pod": "span-plain"}, timestamp=seeded, value=256.0, **gauge),
            Metrics(metric_name=LABEL_METRIC, labels={"deployment.environment.name": "production"}, timestamp=seeded, value=512.0, **gauge),
        ]
    )

    # Metric metadata lags the insert. Each probe reads a label value only
    # its own series carries, so the family union of the flag-on instance
    # cannot pass before every member is queryable.
    token = get_token(USER_ADMIN_EMAIL, USER_ADMIN_PASSWORD)
    probes = [
        (LABEL_METRIC, "region = 'keyless'"),
        (SPAN_METRIC, "pod = 'span-plain'"),
        (OLD_NAME_METRIC, "pod = 'a'"),
        (CURRENT_NAME_METRIC, "pod = 'b'"),
    ]
    deadline = datetime.now(tz=UTC) + timedelta(seconds=60)
    while datetime.now(tz=UTC) < deadline:
        seen = []
        for metric, expression in probes:
            response = make_query_request(
                signoz,
                token,
                start_ms=int((datetime.now(tz=UTC) - timedelta(minutes=30)).timestamp() * 1000),
                end_ms=int(datetime.now(tz=UTC).timestamp() * 1000),
                request_type=RequestType.SCALAR,
                queries=[
                    build_scalar_query(
                        name="A",
                        signal="metrics",
                        aggregations=[build_metrics_aggregation(metric, "latest", "sum", "unspecified", reduce_to="last")],
                        filter_expression=expression,
                    )
                ],
            )
            seen.append(get_scalar_table_data(response.json()))
        if all(rows for rows in seen):
            return now
        sleep(1)
    raise AssertionError(f"seeded metrics never became queryable: {seen}")
