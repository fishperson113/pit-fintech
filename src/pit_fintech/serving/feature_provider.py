"""T7 -- the versioned feature-retrieval boundary (guide s9, artifact S2-A14).

Gate: **G7 Serving** -- "API tra prediction + lineage/freshness metadata" (guide s13).

Guide s9: "Feature retrieval duoc tach qua ``FeatureProvider`` interface. Local Redis, Feast SDK va
hosted Upstash la adapters; scoring layer chi nhan versioned feature vector."

AGENTS.md s11 raises the stakes on this interface: it is one of the four things a Feast fallback
would still have to supply (a versioned ``FeatureSpec``, a ``FeatureProvider``, a Redis key/schema
contract, a materialization manifest and parity gates). So it is a project-level contract, not a
serving convenience -- which is why it is an ABC with a declared return type rather than a callable
passed around.

**The interface returns the nine history fields, not twelve.** ``current_amount``, ``event_step``
and ``transaction_type_transfer`` are request-time fields: they are derived from the request being
scored, not looked up (guide s9.3 step 2 -- "derive entity ID/request features bang shared
contract"). Assembling the twelve-field model vector is
:func:`~pit_fintech.serving.scoring.build_model_vector`'s job, and keeping the split explicit is
what stops a provider from inventing a request-time value when the entity is cold.

**A seam T1 left open, flagged rather than silently resolved.** ``feature_repo/definitions.py``
declares all twelve fields as ordinary batch fields on the ``FeatureView``, and its docstring
records that splitting the three request-time fields into an ``OnDemandFeatureView`` is T7 scope.
So :class:`FeastFeatureProvider` will retrieve twelve where the interface wants nine. Whoever
implements it decides -- project down to nine, or add the on-demand view -- and records the
decision; it must not be settled by whichever call site is written first.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pit_fintech.materialization.records import FeatureStatus, OnlineReadResult

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from pit_fintech.materialization.materializer import OnlineStoreConfig


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureVectorResponse:
    """A versioned feature vector plus everything G7 requires the API to report.

    Guide s13 G7 is "prediction + lineage/freshness metadata", and guide s9.2 names the fields the
    response carries: ``feature_service_version``, ``feature_timestamp``,
    ``materialization_watermark`` and ``feature_status``. They originate here, because the scoring
    layer must not be able to report freshness the provider did not actually observe.

    :attr:`values` holds the nine history fields under their contract names. When
    :attr:`status` is :attr:`~pit_fintech.materialization.records.FeatureStatus.MISSING` they are
    the contract defaults (``FeatureSpec.default``) and :attr:`is_cold_start` is ``True`` --
    guide s9.4: "defined cold-start defaults hoac reject, khong random fill."
    """

    entity_id: str
    entity: str
    values: dict[str, int | float]
    status: FeatureStatus
    is_cold_start: bool
    feature_service_version: str
    feature_definition_version: str
    feature_contract_checksum: str
    feature_step: int | None
    feature_timestamp: datetime | None
    materialization_watermark_step: int | None
    materialization_watermark: datetime | None
    staleness_steps: int | None
    provider_name: str
    retrieval_latency_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderHealth:
    """What a readiness probe needs from a provider (guide s10.2).

    Readiness is only true when the model, the online store **and** the feature version all load
    correctly, so ``/health/ready`` reads :attr:`feature_service_version_matches` rather than
    merely whether a socket opened.
    """

    provider_name: str
    reachable: bool
    feature_service_version: str
    feature_service_version_matches: bool
    watermark_step: int | None
    entities_known: int | None
    detail: str


class FeatureProvider(ABC):
    """The versioned retrieval boundary every scoring path goes through.

    **ADR-009 fixes the rule.** The online store is a precomputed aggregate for fast reads; the
    provider reads it (materialized from offline Gold and advanced by the serving write path).
    Feature computation is the write path's job, not the read path's: read-time recomputation is an
    anti-pattern (ADR-009), and offline/online parity is verified at the write path
    (:mod:`pit_fintech.serving.online_state`), observed through telemetry -- not by comparing a
    read-only copy. :class:`RedisFeatureProvider` is therefore the default and only wired adapter.
    """

    #: Stable identifier reported in :attr:`FeatureVectorResponse.provider_name` and logged with
    #: every scoring request, so a lineage trail says which adapter answered.
    name: str = "abstract"

    @abstractmethod
    def get_online_features(
        self,
        *,
        entity_id: str,
        request_step: int,
    ) -> FeatureVectorResponse:
        """Retrieve one entity's history vector as of ``request_step``.

        Never raises for a missing entity: that is a
        :attr:`~pit_fintech.materialization.records.FeatureStatus.MISSING` response with contract
        defaults, and the caller decides the policy (guide s9.4). Reserve exceptions for the store
        being unreachable, which guide s9.4 maps to a bounded retry then ``503``.
        """

    @abstractmethod
    def get_online_features_batch(
        self,
        *,
        entity_ids: tuple[str, ...],
        request_step: int,
    ) -> tuple[FeatureVectorResponse, ...]:
        """Retrieve several entities in request order, one response each, no reordering."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Report reachability and version agreement for the readiness probe."""

    @abstractmethod
    def close(self) -> None:
        """Release connections. Idempotent."""


class RedisFeatureProvider(FeatureProvider):
    """Local Redis adapter -- the MVP default (AGENTS.md s7, guide s7.3).

    Reads keys built by ``materialization/records.py: online_record_key``, so the service-version
    namespace is shared with the materializer by construction rather than by agreement.
    """

    name = "redis"

    def __init__(self, *, store: OnlineStoreConfig, expected_feature_service_version: str) -> None:
        self._store = store
        self._expected_feature_service_version = expected_feature_service_version

    def get_online_features(self, *, entity_id: str, request_step: int) -> FeatureVectorResponse:
        from pit_fintech.materialization.materializer import read_online_features

        result = read_online_features(
            store=self._store, entity_id=entity_id, request_step=request_step
        )
        return self._to_response(result)

    def get_online_features_batch(
        self, *, entity_ids: tuple[str, ...], request_step: int
    ) -> tuple[FeatureVectorResponse, ...]:
        return tuple(
            self.get_online_features(entity_id=entity_id, request_step=request_step)
            for entity_id in entity_ids
        )

    def health(self) -> ProviderHealth:
        from pit_fintech.materialization.materializer import read_watermark

        try:
            watermark = read_watermark(store=self._store)
        except Exception as exc:
            return ProviderHealth(
                provider_name=self.name,
                reachable=False,
                feature_service_version=self._expected_feature_service_version,
                feature_service_version_matches=False,
                watermark_step=None,
                entities_known=None,
                detail=f"read_watermark failed: {exc}",
            )
        return ProviderHealth(
            provider_name=self.name,
            reachable=True,
            feature_service_version=self._store.feature_service_version,
            feature_service_version_matches=(
                self._store.feature_service_version == self._expected_feature_service_version
            ),
            watermark_step=watermark[0] if watermark is not None else None,
            entities_known=None,
            detail="ok" if watermark is not None else "reachable, but no watermark set yet",
        )

    def close(self) -> None:
        """No-op: this adapter holds no connection of its own.

        Every call defers to ``materialization.materializer``, which owns the store handle --
        keeping the one-place-knows-the-layout rule from the module docstring.
        """

    def _to_response(self, result: OnlineReadResult) -> FeatureVectorResponse:
        from pit_fintech.features.paysim_specs import (
            PAYSIM_FEATURE_DEFINITION_VERSION,
            paysim_feature_contract_checksum,
        )

        record = result.record
        if record is not None:
            entity = record.entity
            feature_service_version = record.feature_service_version
            feature_definition_version = record.feature_definition_version
            feature_contract_checksum = record.feature_contract_checksum
            feature_step: int | None = record.feature_step
            feature_timestamp = record.feature_timestamp
            materialization_watermark_step: int | None = record.materialization_watermark_step
            materialization_watermark = record.materialization_watermark
        else:
            # MISSING: nothing was ever written for this entity, so there is no *observed*
            # version/timestamp to report. Report the frozen application contract's own identity
            # instead of leaving these required fields empty -- honest framing of "this is what
            # was looked up under, and nothing was there" rather than inventing an observed value.
            entity = self._store.entity
            feature_service_version = self._store.feature_service_version
            feature_definition_version = PAYSIM_FEATURE_DEFINITION_VERSION
            feature_contract_checksum = paysim_feature_contract_checksum()
            feature_step = None
            feature_timestamp = None
            materialization_watermark_step = None
            materialization_watermark = None

        return FeatureVectorResponse(
            entity_id=result.entity_id,
            entity=entity,
            values=result.feature_values,
            status=result.status,
            is_cold_start=result.status == FeatureStatus.MISSING,
            feature_service_version=feature_service_version,
            feature_definition_version=feature_definition_version,
            feature_contract_checksum=feature_contract_checksum,
            feature_step=feature_step,
            feature_timestamp=feature_timestamp,
            materialization_watermark_step=materialization_watermark_step,
            materialization_watermark=materialization_watermark,
            staleness_steps=result.staleness_steps,
            provider_name=self.name,
            retrieval_latency_ms=result.read_latency_ms,
        )


class SqliteFeatureProvider(FeatureProvider):
    """SQLite adapter -- the deterministic mode of guide s7.3.

    Exists so integration tests and the E2E lane run without a container. Guide s7.3: parity must
    pass on both stores if both are supported paths, so this is a first-class adapter, not a stub.
    """

    name = "sqlite"

    def __init__(self, *, store: OnlineStoreConfig, expected_feature_service_version: str) -> None:
        raise NotImplementedError("T7 round-0 skeleton")

    def get_online_features(self, *, entity_id: str, request_step: int) -> FeatureVectorResponse:
        raise NotImplementedError("T7 round-0 skeleton")

    def get_online_features_batch(
        self, *, entity_ids: tuple[str, ...], request_step: int
    ) -> tuple[FeatureVectorResponse, ...]:
        raise NotImplementedError("T7 round-0 skeleton")

    def health(self) -> ProviderHealth:
        raise NotImplementedError("T7 round-0 skeleton")

    def close(self) -> None:
        raise NotImplementedError("T7 round-0 skeleton")


class FeastFeatureProvider(FeatureProvider):
    """Feast SDK adapter -- retrieval through the registered ``paysim-fraud-scoring-v2`` service.

    Resolves features by feature-service name so the served field set is whatever the registry says
    it is, rather than a list re-typed here. Feast is an optional dependency group; import it
    inside the methods.

    Carries the twelve-vs-nine seam described in the module docstring: T1's ``FeatureView`` serves
    all twelve fields from the batch source, while this interface is defined on nine.
    """

    name = "feast"

    def __init__(
        self,
        *,
        repo_path: Path,
        feature_service_name: str,
        expected_feature_service_version: str,
    ) -> None:
        raise NotImplementedError("T7 round-0 skeleton")

    def get_online_features(self, *, entity_id: str, request_step: int) -> FeatureVectorResponse:
        raise NotImplementedError("T7 round-0 skeleton")

    def get_online_features_batch(
        self, *, entity_ids: tuple[str, ...], request_step: int
    ) -> tuple[FeatureVectorResponse, ...]:
        raise NotImplementedError("T7 round-0 skeleton")

    def health(self) -> ProviderHealth:
        raise NotImplementedError("T7 round-0 skeleton")

    def close(self) -> None:
        raise NotImplementedError("T7 round-0 skeleton")


class UpstashFeatureProvider(FeatureProvider):
    """Hosted Upstash Redis adapter -- **Sprint 3 only**, declared here so the seam exists.

    AGENTS.md s7 lists Upstash as the hosted online-store option and s8 puts cloud smoke deployment
    in Sprint 3's should-have list; CLAUDE.md's scope guards keep cloud out of the MVP until
    Python replay parity and the Sprint 2 gates pass. Naming the adapter now costs nothing and
    stops a hosted path from being bolted onto the scoring layer instead of onto this interface.
    """

    name = "upstash"

    def __init__(self, *, rest_url: str, expected_feature_service_version: str) -> None:
        raise NotImplementedError("T7 round-0 skeleton; Upstash is Sprint 3 scope")

    def get_online_features(self, *, entity_id: str, request_step: int) -> FeatureVectorResponse:
        raise NotImplementedError("T7 round-0 skeleton; Upstash is Sprint 3 scope")

    def get_online_features_batch(
        self, *, entity_ids: tuple[str, ...], request_step: int
    ) -> tuple[FeatureVectorResponse, ...]:
        raise NotImplementedError("T7 round-0 skeleton; Upstash is Sprint 3 scope")

    def health(self) -> ProviderHealth:
        raise NotImplementedError("T7 round-0 skeleton; Upstash is Sprint 3 scope")

    def close(self) -> None:
        raise NotImplementedError("T7 round-0 skeleton; Upstash is Sprint 3 scope")


def build_feature_provider(
    *,
    kind: Literal["redis", "sqlite", "feast", "upstash"],
    store: OnlineStoreConfig | None = None,
    repo_path: Path | None = None,
    feature_service_name: str | None = None,
    expected_feature_service_version: str,
) -> FeatureProvider:
    """Construct the configured adapter.

    ``expected_feature_service_version`` is required for every adapter, not optional: guide s9.4
    makes a version mismatch fail-closed, and a provider that does not know what it expects cannot
    detect one.

    Only ``kind="redis"`` is wired up in this pass -- ADR-009 fixes the read path to the
    materialized aggregate (`RedisFeatureProvider`), which T5 materialization populates and the
    serving write path advances. The other kinds raise a clear, typed error rather than silently
    falling back to Redis. There is deliberately no recompute-at-read adapter: read-time window
    recomputation is an anti-pattern (ADR-009).
    """

    if kind == "redis":
        if store is None:
            raise ValueError("build_feature_provider(kind='redis') requires `store`")
        return RedisFeatureProvider(
            store=store, expected_feature_service_version=expected_feature_service_version
        )
    if kind == "sqlite":
        raise NotImplementedError(
            "SqliteFeatureProvider is not implemented in this pass; only kind='redis' is wired up"
        )
    if kind == "feast":
        raise NotImplementedError(
            "FeastFeatureProvider is not implemented in this pass; only kind='redis' is wired up"
        )
    if kind == "upstash":
        raise NotImplementedError(
            "UpstashFeatureProvider is Sprint 3 scope; only kind='redis' is wired up in this pass"
        )
    raise ValueError(f"unknown feature provider kind: {kind!r}")
