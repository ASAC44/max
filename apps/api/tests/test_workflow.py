import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from max_api.agent import parse_simulated
from max_api.db import Base, build_engine
from max_api.models import Event, ExternalAttempt, Mission, utcnow
from max_api.schemas import Phase
from max_api.workflow import (
    Conflict,
    apply_intent,
    arm_delivery_dispatch,
    approve_quote,
    bind_delivery_order,
    cancel,
    close_unresolved,
    create_mission,
    finalize_checkout,
    package_ready,
    recover_in_progress_attempts,
    record_robot_dispatched,
    record_robot_progress,
    record_prava_payment_state,
    record_prava_session,
    record_robot_dispatch_acknowledgement,
    record_robot_lifecycle,
    requote,
    retry_allowed,
    run_robot_simulation,
    simulate_checkout,
    start_checkout_attempt,
    start_staged_fulfilment,
)


def ready_for_approval(session, command="create-0001"):
    mission = create_mission(session, "get 1 milk under ₹300 for work", command, "simulated")
    intent = parse_simulated(mission.request_text)
    return apply_intent(session, mission.id, mission.version, f"{command}-parse", intent)


def complete_decline(session):
    mission = ready_for_approval(session)
    mission = approve_quote(session, mission.id, mission.version, "approve-0001", mission.quote_hash)
    attempt = start_checkout_attempt(session, mission.id, mission.version, "checkout-0001")
    mission = session.get(type(mission), mission.id)
    return finalize_checkout(
        session,
        mission.id,
        mission.version,
        "result-0001",
        attempt.id,
        simulate_checkout("decline", attempt.id),
    )


def test_clarification_stops_before_commerce(session):
    mission = create_mission(session, "get milk", "create-missing", "simulated")
    mission = apply_intent(session, mission.id, mission.version, "parse-missing", parse_simulated(mission.request_text))
    assert mission.phase == Phase.NEEDS_CLARIFICATION
    assert mission.quote is None
    assert mission.commerce_status == "NOT_STARTED"
    event = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "CLARIFICATION_REQUIRED",
    ))
    assert (event.component, event.provider) == ("agent", "SIMULATED_PARSER")


def test_prava_hosted_flow_stops_before_merchant_checkout(session):
    mission = ready_for_approval(session, "prava-create")
    mission = record_prava_session(session, mission.id, mission.version, "prava-session", {
        "session_id": "ses_safe",
        "order_id": "ord_safe",
        "approval_url": "https://sandbox.collect.prava.space?session=ses_safe",
        "expires_at": "2026-08-01T12:15:00Z",
    })
    pending = record_prava_payment_state(
        session, mission.id, mission.version, "prava-pending", "pending", None, False
    )
    assert pending.phase == Phase.PAYMENT_APPROVAL_REQUIRED
    ready = record_prava_payment_state(
        session, pending.id, pending.version, "prava-ready", "awaiting_result", "tli_safe", True
    )
    assert ready.phase == Phase.PAYMENT_PERMISSION_READY
    assert ready.approval_quote_hash == ready.quote_hash
    approval = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "OWNER_APPROVED_EXACT_QUOTE",
    ))
    assert approval.payload["via"] == "PRAVA"
    event = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "PRAVA_PERMISSION_READY",
    ))
    serialized = json.dumps(event.payload)
    assert "token" not in serialized
    assert "dynamic_cvv" not in serialized


def test_prava_hosted_wait_can_be_cancelled(session):
    mission = ready_for_approval(session, "prava-cancel-create")
    waiting = approve_quote(
        session,
        mission.id,
        mission.version,
        "prava-cancel-approve",
        mission.quote_hash,
        payment_mode="prava",
    )
    cancelled = cancel(session, waiting.id, waiting.version, "prava-cancel")
    assert cancelled.phase == Phase.CANCELLED


def test_quote_change_invalidates_approval_and_stale_command_conflicts(session):
    mission = ready_for_approval(session)
    old_hash = mission.quote_hash
    old_version = mission.version
    changed = requote(session, mission.id, mission.version, "requote-0001", 25_000)
    assert changed.quote_hash != old_hash
    assert changed.approval_quote_hash is None
    interpreted = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "INTENT_VALIDATED",
    ))
    assert (interpreted.component, interpreted.provider) == ("agent", "SIMULATED_PARSER")
    changed_event = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "QUOTE_CHANGED_APPROVAL_INVALIDATED",
    ))
    assert (changed_event.component, changed_event.provider, changed_event.human_intervened) == (
        "commerce", "SIMULATED_SWIGGY", True,
    )
    with pytest.raises(Conflict):
        cancel(session, changed.id, old_version, "stale-cancel")


def test_decline_and_staged_branch_preserve_separate_truth(session):
    declined = complete_decline(session)
    parent_version = declined.version
    child = start_staged_fulfilment(session, declined.id, parent_version, "staged-0001")
    assert child.parent_mission_id == declined.id
    assert child.environment == "staged_demo"
    child = package_ready(session, child.id, child.version, "package-0001")
    child = run_robot_simulation(session, child.id, child.version, "robot-0001")
    assert child.phase == Phase.COMPLETED

    session.expire_all()
    parent = session.get(type(declined), declined.id)
    assert parent.phase == Phase.PAYMENT_DECLINED
    assert parent.payment_status == "FAILED"
    child_events = session.scalars(select(Event).where(Event.mission_id == child.id).order_by(Event.sequence)).all()
    assert [event.event_type for event in child_events][-1] == "SIMULATED_NOTIFICATION_COMPLETED"
    robot_phases = [
        (event.phase_before, event.phase_after)
        for event in child_events
        if event.component == "robot"
    ]
    assert robot_phases == [
        (Phase.READY_TO_DISPATCH, Phase.EN_ROUTE_TO_PICKUP),
        (Phase.EN_ROUTE_TO_PICKUP, Phase.AT_PICKUP),
        (Phase.AT_PICKUP, Phase.ITEM_SECURED),
        (Phase.ITEM_SECURED, Phase.RETURNING),
        (Phase.RETURNING, Phase.COMPLETED),
    ]
    assert all(event.environment == "local" for event in child_events if event.component in {"robot", "notification"})


def test_pi_robot_dry_run_acknowledgement_does_not_claim_motion(session):
    declined = complete_decline(session)
    child = start_staged_fulfilment(session, declined.id, declined.version, "pi-stage")
    child = package_ready(session, child.id, child.version, "pi-package")
    acknowledged = record_robot_dispatch_acknowledgement(
        session,
        child.id,
        child.version,
        "pi-dispatch",
        dry_run=True,
        motion_started=False,
    )
    assert acknowledged.phase == Phase.READY_TO_DISPATCH
    assert acknowledged.fulfilment_status == "ROBOT_DRY_RUN_ACKNOWLEDGED"
    event = session.scalar(select(Event).where(
        Event.mission_id == child.id,
        Event.event_type == "PI_ROBOT_DRY_RUN_ACKNOWLEDGED",
    ))
    assert (event.component, event.provider, event.environment) == (
        "robot",
        "PI_ROBOT_BRIDGE",
        "staged_demo",
    )


def test_physical_robot_acknowledgement_and_lifecycle_claim_motion(session):
    declined = complete_decline(session)
    child = start_staged_fulfilment(session, declined.id, declined.version, "physical-stage")
    child = package_ready(session, child.id, child.version, "physical-package")
    child = record_robot_dispatch_acknowledgement(
        session,
        child.id,
        child.version,
        "physical-dispatch",
        dry_run=False,
        motion_started=True,
    )
    assert child.phase == Phase.EN_ROUTE_TO_PICKUP
    for stage, phase in {
        "AT_PICKUP": Phase.AT_PICKUP,
        "ITEM_SECURED": Phase.ITEM_SECURED,
        "RETURNING": Phase.RETURNING,
        "COMPLETED": Phase.COMPLETED,
    }.items():
        child = record_robot_lifecycle(
            session,
            child.id,
            child.version,
            f"physical-{stage.lower()}",
            stage=stage,
            dry_run=False,
            motion_started=True,
        )
        assert child.phase == phase


def test_physical_robot_can_report_cancellation(session):
    declined = complete_decline(session)
    child = start_staged_fulfilment(session, declined.id, declined.version, "cancel-stage")
    child = package_ready(session, child.id, child.version, "cancel-package")
    child = record_robot_dispatch_acknowledgement(
        session,
        child.id,
        child.version,
        "cancel-dispatch",
        dry_run=False,
        motion_started=True,
    )
    child = record_robot_lifecycle(
        session,
        child.id,
        child.version,
        "cancel-report",
        stage="CANCELLED",
        dry_run=False,
        motion_started=True,
    )
    assert child.phase == Phase.CANCELLED
    assert child.fulfilment_status == "ROBOT_CANCELLED"


def test_unknown_checkout_is_not_retryable(session):
    mission = ready_for_approval(session, "unknown-create")
    mission = approve_quote(session, mission.id, mission.version, "unknown-approve", mission.quote_hash)
    attempt = start_checkout_attempt(session, mission.id, mission.version, "unknown-checkout")
    mission = session.get(type(mission), mission.id)
    mission = finalize_checkout(
        session, mission.id, mission.version, "unknown-result", attempt.id, simulate_checkout("timeout", attempt.id)
    )
    assert mission.phase == Phase.CHECKOUT_OUTCOME_UNKNOWN
    assert session.get(ExternalAttempt, attempt.id).retry_eligible is False
    assert retry_allowed("merchant_checkout", "TIMED_OUT") is False
    assert retry_allowed("status_read", "TIMED_OUT") is True
    unknown_event = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "SIMULATED_CHECKOUT_OUTCOME_UNKNOWN",
    ))
    assert (unknown_event.component, unknown_event.provider, unknown_event.environment) == (
        "commerce", "SIMULATED_SWIGGY", "local",
    )
    with pytest.raises(Conflict, match="another mission is active"):
        create_mission(session, "get juice", "unknown-new-root", "simulated")
    closed = close_unresolved(session, mission.id, mission.version, "close-unknown")
    assert closed.phase == Phase.CLOSED_UNRESOLVED
    assert closed.active_slot is None
    assert closed.checkout_status == "UNKNOWN"
    assert closed.payment_status == "OUTCOME_UNKNOWN"
    event = session.scalar(select(Event).where(
        Event.mission_id == mission.id,
        Event.event_type == "MISSION_CLOSED_UNRESOLVED",
    ))
    assert event.human_intervened is True
    assert create_mission(session, "get juice", "after-unknown", "simulated").active_slot == "active"


def test_restart_recovers_in_progress_attempt_as_unknown(session):
    mission = ready_for_approval(session, "restart-create")
    mission = approve_quote(session, mission.id, mission.version, "restart-approve", mission.quote_hash)
    attempt = start_checkout_attempt(session, mission.id, mission.version, "restart-checkout")
    assert recover_in_progress_attempts(session) == 1
    session.expire_all()
    assert session.get(type(mission), mission.id).phase == Phase.CHECKOUT_OUTCOME_UNKNOWN
    assert session.get(ExternalAttempt, attempt.id).status == "UNKNOWN"


def test_command_id_is_idempotent(session):
    first = ready_for_approval(session, "idempotent-create")
    second = apply_intent(
        session,
        first.id,
        1,
        "idempotent-create-parse",
        parse_simulated(first.request_text),
    )
    assert second.id == first.id
    assert second.version == first.version


def test_idempotency_key_rejects_changed_request_and_cross_mission_use(session):
    first = create_mission(session, "get milk", "shared-command", "simulated")
    assert create_mission(session, "get milk", "shared-command", "simulated").id == first.id
    with pytest.raises(Conflict):
        create_mission(session, "get juice", "shared-command", "simulated")

    cancel(session, first.id, first.version, "cancel-first-root")
    second = create_mission(session, "get juice", "second-create", "simulated")
    with pytest.raises(Conflict):
        apply_intent(session, second.id, second.version, "shared-command", parse_simulated("get juice"))


def test_expired_quote_is_recorded_and_cannot_be_approved(session):
    mission = ready_for_approval(session, "expired-create")
    mission.quote = {**mission.quote, "expires_at": (utcnow() - timedelta(seconds=1)).isoformat()}
    session.commit()
    with pytest.raises(Conflict, match="quote expired"):
        approve_quote(session, mission.id, mission.version, "expired-approve", mission.quote_hash)
    session.expire_all()
    expired = session.get(type(mission), mission.id)
    assert expired.commerce_status == "QUOTE_EXPIRED"
    assert expired.approval_quote_hash is None
    assert session.scalar(
        select(Event).where(Event.mission_id == mission.id, Event.event_type == "QUOTE_EXPIRED")
    )
    refreshed = requote(session, expired.id, expired.version, "expired-refresh", expired.quote["amount_minor"])
    assert refreshed.commerce_status == "SIMULATED_QUOTED"
    approved = approve_quote(session, refreshed.id, refreshed.version, "expired-refreshed-approve", refreshed.quote_hash)
    assert approved.phase == Phase.PAYMENT_PERMISSION_READY


def test_live_quote_must_be_recreated_from_merchant(session):
    mission = ready_for_approval(session, "live-expired-create")
    mission.quote = {**mission.quote, "environment": "production"}
    session.commit()
    with pytest.raises(Conflict, match="live quote must be recreated"):
        requote(session, mission.id, mission.version, "live-expired-refresh", mission.quote["amount_minor"])


def test_provider_result_must_match_attempt(session):
    mission = ready_for_approval(session, "mismatch-create")
    mission = approve_quote(session, mission.id, mission.version, "mismatch-approve", mission.quote_hash)
    attempt = start_checkout_attempt(session, mission.id, mission.version, "mismatch-checkout")
    mission = session.get(type(mission), mission.id)
    result = simulate_checkout("decline", attempt.id).model_copy(update={"provider": "OTHER_PROVIDER"})
    with pytest.raises(Conflict, match="does not match"):
        finalize_checkout(session, mission.id, mission.version, "mismatch-result", attempt.id, result)
    assert session.get(ExternalAttempt, attempt.id).status == "IN_PROGRESS"


def test_only_one_staged_child_can_exist(session):
    declined = complete_decline(session)
    child = start_staged_fulfilment(session, declined.id, declined.version, "one-stage")
    assert start_staged_fulfilment(session, declined.id, declined.version, "one-stage").id == child.id
    with pytest.raises(Conflict, match="another mission is active"):
        create_mission(session, "get juice", "root-during-stage", "simulated")
    with pytest.raises(Conflict, match="already exists"):
        start_staged_fulfilment(session, declined.id, declined.version, "second-stage")


def test_pending_mission_can_be_cancelled(session):
    mission = ready_for_approval(session, "cancel-create")
    cancelled = cancel(session, mission.id, mission.version, "cancel-success")
    assert cancelled.phase == Phase.CANCELLED


def test_delivery_must_be_bound_and_armed_before_dispatch(session):
    declined = complete_decline(session)
    mission = start_staged_fulfilment(session, declined.id, declined.version, "tracking-stage")
    mission = bind_delivery_order(
        session, mission.id, mission.version, "bind-order", "order-private-1234", 12.9, 77.5
    )
    assert mission.delivery["order_reference"] == "…1234"
    assert "order-private-1234" not in json.dumps(mission_view := {
        "order_reference": mission.delivery["order_reference"],
        "status": mission.delivery["status"],
    })
    with pytest.raises(Conflict):
        record_robot_dispatched(session, mission, "dispatch-before-arm")
    mission = arm_delivery_dispatch(session, mission.id, mission.version, "arm-order")
    mission = record_robot_dispatched(session, mission, "dispatch-order")
    assert mission.phase == Phase.EN_ROUTE_TO_PICKUP
    assert mission.delivery["robot_status"] == "OUTBOUND"
    mission = record_robot_progress(session, mission, "AT_PICKUP")
    mission = record_robot_progress(session, mission, "RETURNING")
    mission = record_robot_progress(session, mission, "COMPLETE")
    assert mission.phase == Phase.COMPLETED
    assert "order_id" not in mission.delivery


def test_only_one_root_mission_can_be_active(session):
    first = create_mission(session, "get milk", "first-active-root", "simulated")
    with pytest.raises(Conflict, match="another mission is active"):
        create_mission(session, "get juice", "second-active-root", "simulated")
    cancel(session, first.id, first.version, "release-active-root")
    assert create_mission(session, "get juice", "second-active-root", "simulated").active_slot == "active"


@pytest.mark.parametrize("package_is_ready", [False, True])
def test_staged_mission_can_be_cancelled_before_dispatch(session, package_is_ready):
    declined = complete_decline(session)
    staged = start_staged_fulfilment(session, declined.id, declined.version, f"cancel-stage-{package_is_ready}")
    if package_is_ready:
        staged = package_ready(session, staged.id, staged.version, "cancel-stage-ready")
    cancelled = cancel(session, staged.id, staged.version, f"cancel-staged-{package_is_ready}")
    assert cancelled.phase == Phase.CANCELLED
    assert cancelled.fulfilment_status == "CANCELLED"
    assert cancelled.active_slot is None
    assert create_mission(session, "get juice", f"after-stage-{package_is_ready}", "simulated").active_slot == "active"


def test_simultaneous_commands_allow_only_one_transition(tmp_path):
    url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    ConcurrentSession = sessionmaker(bind=engine, expire_on_commit=False)
    with ConcurrentSession() as setup:
        mission = ready_for_approval(setup, "concurrent-create")
        mission_id, version = mission.id, mission.version

    barrier = Barrier(2)

    def attempt(command_id):
        with ConcurrentSession() as worker:
            barrier.wait()
            try:
                cancel(worker, mission_id, version, command_id)
                return "ok"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["concurrent-cancel-a", "concurrent-cancel-b"]))
    assert sorted(outcomes) == ["conflict", "ok"]
    engine.dispose()


def test_simultaneous_identical_command_replays_one_transition(tmp_path):
    url = f"sqlite:///{tmp_path / 'concurrent-replay.db'}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    ConcurrentSession = sessionmaker(bind=engine, expire_on_commit=False)
    with ConcurrentSession() as setup:
        mission = ready_for_approval(setup, "concurrent-replay-create")
        mission_id, version = mission.id, mission.version

    barrier = Barrier(2)

    def attempt(_index):
        with ConcurrentSession() as worker:
            barrier.wait()
            return cancel(worker, mission_id, version, "same-concurrent-cancel").phase

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    with ConcurrentSession() as check:
        event_count = len(check.scalars(select(Event).where(Event.command_id == "same-concurrent-cancel")).all())
    assert outcomes == [Phase.CANCELLED, Phase.CANCELLED]
    assert event_count == 1
    engine.dispose()


def test_simultaneous_root_creation_keeps_one_active_mission(tmp_path):
    url = f"sqlite:///{tmp_path / 'concurrent-root.db'}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    ConcurrentSession = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)

    def attempt(index):
        with ConcurrentSession() as worker:
            barrier.wait()
            try:
                create_mission(worker, f"get item {index}", f"concurrent-root-{index}", "simulated")
                return "ok"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    with ConcurrentSession() as check:
        active_count = len(check.scalars(select(Mission).where(Mission.active_slot == "active")).all())
    assert sorted(outcomes) == ["conflict", "ok"]
    assert active_count == 1
    engine.dispose()


def test_simultaneous_staged_commands_create_one_child(tmp_path):
    url = f"sqlite:///{tmp_path / 'concurrent-stage.db'}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    ConcurrentSession = sessionmaker(bind=engine, expire_on_commit=False)
    with ConcurrentSession() as setup:
        declined = complete_decline(setup)
        parent_id, version = declined.id, declined.version

    barrier = Barrier(2)

    def attempt(command_id):
        with ConcurrentSession() as worker:
            barrier.wait()
            try:
                start_staged_fulfilment(worker, parent_id, version, command_id)
                return "ok"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["concurrent-stage-a", "concurrent-stage-b"]))
    with ConcurrentSession() as check:
        child_count = len(check.scalars(select(Mission).where(Mission.parent_mission_id == parent_id)).all())
    assert sorted(outcomes) == ["conflict", "ok"]
    assert child_count == 1
    engine.dispose()


def test_dispatch_without_package_ready_is_blocked(session):
    declined = complete_decline(session)
    child = start_staged_fulfilment(session, declined.id, declined.version, "blocked-stage")
    with pytest.raises(Conflict):
        run_robot_simulation(session, child.id, child.version, "blocked-robot")


def test_persisted_timeline_survives_database_reopen(tmp_path):
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    first_engine = build_engine(url)
    Base.metadata.create_all(first_engine)
    FirstSession = sessionmaker(bind=first_engine, expire_on_commit=False)
    with FirstSession() as first:
        declined = complete_decline(first)
        mission_id = declined.id
        version = declined.version
    first_engine.dispose()

    second_engine = build_engine(url)
    SecondSession = sessionmaker(bind=second_engine, expire_on_commit=False)
    with SecondSession() as second:
        mission = second.get(type(declined), mission_id)
        events = second.scalars(select(Event).where(Event.mission_id == mission_id).order_by(Event.sequence)).all()
        assert mission.version == version
        assert mission.phase == Phase.PAYMENT_DECLINED
        assert events[-1].event_type == "SIMULATED_PRAVA_FINAL_FAILED"
    second_engine.dispose()


def test_scoped_credential_sentinel_never_enters_persistence(session, monkeypatch):
    sentinel = "SENSITIVE_TEST_SENTINEL"
    monkeypatch.setenv("PRAVA_SCOPED_CREDENTIAL", sentinel)
    declined = complete_decline(session)
    events = session.scalars(select(Event).where(Event.mission_id == declined.id)).all()
    attempts = session.scalars(select(ExternalAttempt).where(ExternalAttempt.mission_id == declined.id)).all()
    persisted = json.dumps({
        "mission": {column.name: getattr(declined, column.name) for column in declined.__table__.columns},
        "events": [event.payload for event in events],
        "attempts": [
            {column.name: getattr(attempt, column.name) for column in attempt.__table__.columns}
            for attempt in attempts
        ],
    }, default=str)
    assert sentinel not in persisted
