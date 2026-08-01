import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Event, ExternalAttempt, Mission, utcnow
from .schemas import BudgetMeaning, Environment, Phase, ProviderResult, Quote, ShoppingIntent


class WorkflowError(Exception):
    status_code = 400


class NotFound(WorkflowError):
    status_code = 404


class Conflict(WorkflowError):
    status_code = 409


TERMINAL_PHASES = {
    Phase.PAYMENT_DECLINED,
    Phase.COMPLETED,
    Phase.CANCELLED,
}


def _mission(session: Session, mission_id: str) -> Mission:
    mission = session.get(Mission, mission_id)
    if not mission:
        raise NotFound("mission not found")
    return mission


def _request_hash(scope: str, payload: dict) -> str:
    encoded = json.dumps({"scope": scope, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _existing_command(
    session: Session,
    command_id: str,
    scope: str,
    payload: dict,
    mission_id: str | None = None,
) -> Mission | None:
    event = session.scalar(select(Event).where(Event.command_id == command_id))
    if not event:
        return None
    if event.command_scope != scope or event.request_hash != _request_hash(scope, payload):
        raise Conflict("idempotency key was already used for a different command")
    if mission_id is not None and event.mission_id != mission_id:
        raise Conflict("idempotency key belongs to another mission")
    return session.get(Mission, event.mission_id, populate_existing=True)


def _replay_or_conflict(
    session: Session,
    command_id: str,
    scope: str,
    payload: dict,
    mission_id: str | None,
    message: str,
) -> Mission:
    if existing := _existing_command(session, command_id, scope, payload, mission_id):
        return existing
    raise Conflict(message)


def _next_sequence(session: Session, mission_id: str) -> int:
    return (session.scalar(select(func.max(Event.sequence)).where(Event.mission_id == mission_id)) or 0) + 1


def _event_metadata(
    event_type: str,
    mission_environment: str,
    command_scope: str,
    agent_mode: str,
) -> tuple[str, str | None, bool, str]:
    human = command_scope in {"reply", "requote"} or event_type in {
        "OWNER_APPROVED_EXACT_QUOTE",
        "MISSION_CANCELLED",
        "PACKAGE_READY",
    }
    if event_type == "AGENT_INTERPRETATION_FAILED":
        provider = "OPENAI" if agent_mode == "openai" else "SIMULATED_PARSER"
        return "agent", provider, False, mission_environment
    if event_type in {"INTENT_VALIDATED", "CLARIFICATION_REQUIRED"}:
        provider = "OPENAI" if agent_mode == "openai" else "SIMULATED_PARSER"
        return "agent", provider, human, mission_environment
    if event_type in {"SIMULATED_QUOTE_CREATED", "QUOTE_CHANGED_APPROVAL_INVALIDATED", "QUOTE_EXPIRED"}:
        return "commerce", "SIMULATED_SWIGGY", human, mission_environment
    if event_type == "SWIGGY_QUOTE_CREATED":
        return "commerce", "SWIGGY_INSTAMART_MCP", human, Environment.PRODUCTION
    if event_type.startswith("SWIGGY_BROWSER_"):
        return "commerce", "SWIGGY_BROWSER", human, Environment.PRODUCTION
    if event_type == "SIMULATED_CHECKOUT_OUTCOME_UNKNOWN":
        return "commerce", "SIMULATED_SWIGGY", human, Environment.LOCAL
    if event_type == "PACKAGE_READY":
        return "fulfilment", "OPERATOR", True, mission_environment
    if "PRAVA" in event_type:
        if not event_type.startswith("SIMULATED_"):
            return "payment", "PRAVA", human, Environment.SANDBOX
        return "payment", "SIMULATED_PRAVA", human, Environment.LOCAL
    if "MERCHANT" in event_type or event_type == "SIMULATED_ORDER_CONFIRMED":
        environment = Environment.STAGED if event_type == "SIMULATED_ORDER_CONFIRMED" else Environment.LOCAL
        return "commerce", "SIMULATED_SWIGGY", human, environment
    if "ROBOT" in event_type or event_type == "SIMULATED_ITEM_SECURED":
        return "robot", "SIMULATED_ROBOT", human, Environment.LOCAL
    if "NOTIFICATION" in event_type:
        return "notification", "SIMULATED_NOTIFICATION", human, Environment.LOCAL
    return "orchestrator", None, human, mission_environment


def _event_phases(event_type: str, before: str, after: str) -> tuple[str, str]:
    return {
        "SIMULATED_ROBOT_DISPATCHED": (Phase.READY_TO_DISPATCH, Phase.EN_ROUTE_TO_PICKUP),
        "SIMULATED_ROBOT_ARRIVED": (Phase.EN_ROUTE_TO_PICKUP, Phase.AT_PICKUP),
        "SIMULATED_ITEM_SECURED": (Phase.AT_PICKUP, Phase.ITEM_SECURED),
        "SIMULATED_ROBOT_RETURNING": (Phase.ITEM_SECURED, Phase.RETURNING),
        "SIMULATED_ROBOT_COMPLETED": (Phase.RETURNING, Phase.COMPLETED),
        "SIMULATED_NOTIFICATION_DISPATCHED": (Phase.READY_TO_DISPATCH, Phase.READY_TO_DISPATCH),
        "SIMULATED_NOTIFICATION_COMPLETED": (Phase.COMPLETED, Phase.COMPLETED),
    }.get(event_type, (before, after))


def _transition(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    command_scope: str,
    command_payload: dict,
    updates: dict,
    events: list[tuple[str, dict]],
    attempt: ExternalAttempt | None = None,
) -> Mission:
    if existing := _existing_command(session, command_id, command_scope, command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    before = mission.phase
    after = updates.get("phase", before)
    values = {**updates, "version": expected_version + 1, "updated_at": utcnow()}
    if after in TERMINAL_PHASES:
        values["active_slot"] = None
    result = session.execute(
        update(Mission)
        .where(Mission.id == mission_id, Mission.version == expected_version)
        .values(**values)
    )
    if result.rowcount != 1:
        session.rollback()
        if existing := _existing_command(session, command_id, command_scope, command_payload, mission_id):
            return existing
        raise Conflict("mission changed; refresh before retrying")

    sequence = _next_sequence(session, mission_id)
    for index, (event_type, payload) in enumerate(events):
        component, provider, human, event_environment = _event_metadata(
            event_type,
            updates.get("environment", mission.environment),
            command_scope,
            mission.agent_mode,
        )
        event_before, event_after = _event_phases(event_type, before, after)
        session.add(Event(
            mission_id=mission_id,
            sequence=sequence + index,
            command_id=command_id if index == 0 else None,
            command_scope=command_scope,
            request_hash=_request_hash(command_scope, command_payload),
            event_type=event_type,
            component=component,
            provider=provider,
            human_intervened=human,
            environment=event_environment,
            phase_before=event_before,
            phase_after=event_after,
            payload=payload,
        ))
    if attempt:
        session.add(attempt)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if existing := _existing_command(session, command_id, command_scope, command_payload, mission_id):
            return existing
        raise Conflict("command conflicts with an existing workflow record")
    session.expire_all()
    return _mission(session, mission_id)


def create_mission(session: Session, request_text: str, command_id: str, agent_mode: str) -> Mission:
    command_payload = {"request_text": request_text, "agent_mode": agent_mode}
    if existing := _existing_command(session, command_id, "create_mission", command_payload):
        return existing
    if session.scalar(select(Mission.id).where(Mission.active_slot == "active")):
        raise Conflict("another mission is active")
    now = utcnow()
    mission = Mission(
        id=str(uuid4()),
        active_slot="active",
        version=1,
        phase=Phase.DRAFT,
        environment=Environment.LOCAL,
        agent_mode=agent_mode,
        request_text=request_text,
        commerce_status="NOT_STARTED",
        payment_status="NOT_STARTED",
        checkout_status="NOT_STARTED",
        fulfilment_status="NOT_STARTED",
        notification_status="NOT_STARTED",
        created_at=now,
        updated_at=now,
    )
    event = Event(
        mission_id=mission.id,
        sequence=1,
        command_id=command_id,
        command_scope="create_mission",
        request_hash=_request_hash("create_mission", command_payload),
        event_type="REQUEST_RECEIVED",
        component="orchestrator",
        provider=None,
        human_intervened=True,
        environment=Environment.LOCAL,
        phase_before=Phase.DRAFT,
        phase_after=Phase.DRAFT,
        payload={"agent_mode": agent_mode},
    )
    try:
        session.add(mission)
        session.flush()
        session.add(event)
        session.commit()
        return mission
    except IntegrityError:
        session.rollback()
        if existing := _existing_command(session, command_id, "create_mission", command_payload):
            return existing
        if session.scalar(select(Mission.id).where(Mission.active_slot == "active")):
            raise Conflict("another mission is active")
        raise Conflict("command conflicts with an existing workflow record")


def missing_fields(intent: ShoppingIntent) -> list[str]:
    missing = []
    if not intent.item:
        missing.append("item")
    if not intent.quantity:
        missing.append("quantity")
    if not intent.budget_meaning:
        missing.append("budget meaning")
    if intent.budget_meaning in {BudgetMeaning.EXACT, BudgetMeaning.MINIMUM, BudgetMeaning.RANGE} and intent.budget_min_minor is None:
        missing.append("budget minimum")
    if intent.budget_meaning in {BudgetMeaning.EXACT, BudgetMeaning.MAXIMUM, BudgetMeaning.RANGE} and intent.budget_max_minor is None:
        missing.append("budget maximum")
    if not intent.destination:
        missing.append("destination")
    return missing


def clarification_for(fields: list[str]) -> str:
    return f"Please provide {fields[0]}." if len(fields) == 1 else f"Please provide {', '.join(fields[:-1])}, and {fields[-1]}."


def _quote_amount(intent: ShoppingIntent) -> int:
    if intent.budget_meaning == BudgetMeaning.EXACT:
        return intent.budget_max_minor or 0
    if intent.budget_meaning == BudgetMeaning.MAXIMUM:
        return min(19_900, intent.budget_max_minor or 0)
    if intent.budget_meaning == BudgetMeaning.MINIMUM:
        return max(19_900, intent.budget_min_minor or 0)
    return min(intent.budget_max_minor or 0, max(19_900, intent.budget_min_minor or 0))


def quote_hash(quote: Quote) -> str:
    payload = json.dumps(quote.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def preflight_command(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    command_scope: str,
    command_payload: dict,
    allowed_phases: set[Phase],
) -> Mission | None:
    if existing := _existing_command(session, command_id, command_scope, command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.version != expected_version:
        return _replay_or_conflict(
            session, command_id, command_scope, command_payload, mission_id,
            "mission changed; refresh before retrying",
        )
    if mission.phase not in allowed_phases:
        return _replay_or_conflict(
            session, command_id, command_scope, command_payload, mission_id,
            "command is not valid in the current phase",
        )
    return None


def command_failed(session: Session, command_id: str) -> bool:
    return bool(session.scalar(select(Event.id).where(
        Event.command_id == command_id,
        Event.event_type == "AGENT_INTERPRETATION_FAILED",
    )))


def record_agent_failure(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    command_scope: str,
    command_payload: dict,
    error_class: str,
) -> Mission:
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        command_scope,
        command_payload,
        {},
        [("AGENT_INTERPRETATION_FAILED", {"error_class": error_class})],
    )


def apply_intent(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    intent: ShoppingIntent,
    request_text: str | None = None,
    command_scope: str = "apply_intent",
    command_payload: dict | None = None,
    resolved_quote: Quote | None = None,
) -> Mission:
    command_payload = command_payload or {
        "intent": intent.model_dump(mode="json"),
        "request_text": request_text,
        "expected_version": expected_version,
    }
    if existing := _existing_command(session, command_id, command_scope, command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase not in {Phase.DRAFT, Phase.NEEDS_CLARIFICATION}:
        return _replay_or_conflict(
            session, command_id, command_scope, command_payload, mission_id,
            "intent can only be applied before a quote",
        )
    missing = missing_fields(intent)
    base_updates = {"intent": intent.model_dump(mode="json")}
    if request_text is not None:
        base_updates["request_text"] = request_text
    if missing:
        question = clarification_for(missing)
        return _transition(
            session, mission_id, expected_version, command_id,
            command_scope, command_payload,
            {**base_updates, "phase": Phase.NEEDS_CLARIFICATION, "clarification_question": question},
            [("CLARIFICATION_REQUIRED", {"missing_fields": missing, "question": question})],
        )

    quote = resolved_quote or Quote(
            revision=(mission.quote or {}).get("revision", 0) + 1,
            merchant="SIMULATED_SWIGGY_INSTAMART",
            product_name=intent.item or "",
            variant_id=f"sim-{hashlib.sha256((intent.item or '').encode()).hexdigest()[:10]}",
            quantity=intent.quantity or 1,
            amount_minor=_quote_amount(intent),
            currency=intent.currency,
            destination=intent.destination or "",
            environment=Environment.LOCAL,
            expires_at=utcnow() + timedelta(minutes=15),
        )
    hashed = quote_hash(quote)
    live = resolved_quote is not None
    return _transition(
        session, mission_id, expected_version, command_id,
        command_scope, command_payload,
        {
            **base_updates,
            "phase": Phase.AWAITING_OWNER_APPROVAL,
            "clarification_question": None,
            "quote": quote.model_dump(mode="json"),
            "quote_hash": hashed,
            "approval_quote_hash": None,
            "commerce_status": "LIVE_QUOTED" if live else "SIMULATED_QUOTED",
        },
        [
            ("INTENT_VALIDATED", {"budget_meaning": intent.budget_meaning, "currency": intent.currency}),
            (
                "SWIGGY_QUOTE_CREATED" if live else "SIMULATED_QUOTE_CREATED",
                {"quote_hash": hashed, "amount_minor": quote.amount_minor, "currency": quote.currency},
            ),
        ],
    )


def _quote_expired(mission: Mission) -> bool:
    return not mission.quote or Quote.model_validate(mission.quote).expires_at <= utcnow()


def _record_quote_expired(session: Session, mission: Mission, expected_version: int, source_command_id: str) -> None:
    command_id = hashlib.sha256(f"{source_command_id}:quote-expired".encode()).hexdigest()[:48]
    payload = {"mission_id": mission.id, "quote_hash": mission.quote_hash}
    _transition(
        session,
        mission.id,
        expected_version,
        command_id,
        "expire_quote",
        payload,
        {
            "phase": Phase.AWAITING_OWNER_APPROVAL,
            "approval_quote_hash": None,
            "commerce_status": "QUOTE_EXPIRED",
            "payment_status": "NOT_STARTED",
        },
        [("QUOTE_EXPIRED", {"quote_hash": mission.quote_hash})],
    )


def approve_quote(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    approved_hash: str,
    checkout_outcome: str | None = None,
    payment_mode: str = "simulated",
) -> Mission:
    command_payload = {
        "mission_id": mission_id,
        "expected_version": expected_version,
        "quote_hash": approved_hash,
        "checkout_outcome": checkout_outcome,
        "payment_mode": payment_mode,
    }
    if existing := _existing_command(session, command_id, "approve_quote", command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase != Phase.AWAITING_OWNER_APPROVAL:
        return _replay_or_conflict(
            session, command_id, "approve_quote", command_payload, mission_id,
            "mission is not awaiting approval",
        )
    if not mission.quote_hash or approved_hash != mission.quote_hash:
        raise Conflict("approval does not match the current immutable quote")
    if _quote_expired(mission):
        _record_quote_expired(session, mission, expected_version, command_id)
        raise Conflict("quote expired; request a fresh quote")
    live = payment_mode == "prava"
    return _transition(
        session, mission_id, expected_version, command_id,
        "approve_quote", command_payload,
        {
            "phase": Phase.PAYMENT_APPROVAL_REQUIRED if live else Phase.PAYMENT_PERMISSION_READY,
            "approval_quote_hash": approved_hash,
            "payment_status": "PRAVA_SESSION_REQUIRED" if live else "SIMULATED_PERMISSION_READY",
        },
        [("OWNER_APPROVED_EXACT_QUOTE", {"quote_hash": approved_hash})] + ([] if live else [
            ("SIMULATED_PRAVA_PERMISSION_READY", {"quote_hash": approved_hash, "environment": Environment.LOCAL}),
        ]),
    )


def record_prava_session(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    action: dict,
) -> Mission:
    payload = {"mission_id": mission_id, **action}
    if existing := _existing_command(session, command_id, "record_prava_session", payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase not in {Phase.AWAITING_OWNER_APPROVAL, Phase.PAYMENT_APPROVAL_REQUIRED}:
        raise Conflict("Prava session requires a current quote")
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "record_prava_session",
        payload,
        {
            "phase": Phase.PAYMENT_APPROVAL_REQUIRED,
            "payment_status": "AWAITING_PRAVA_VERIFICATION",
        },
        [("PRAVA_SANDBOX_SESSION_CREATED", action)],
    )


def record_prava_payment_state(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    state: str,
    txn_ref_id: str | None,
    credential_fields_present: bool,
) -> Mission:
    payload = {
        "mission_id": mission_id,
        "state": state,
        "txn_ref_id": txn_ref_id,
        "credential_fields_present": credential_fields_present,
    }
    if existing := _existing_command(session, command_id, "refresh_prava", payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase != Phase.PAYMENT_APPROVAL_REQUIRED:
        raise Conflict("mission is not awaiting Prava verification")
    if state == "awaiting_result":
        if not txn_ref_id or not credential_fields_present:
            raise Conflict("Prava reported ready without the required credential fields")
        updates = {
            "phase": Phase.PAYMENT_PERMISSION_READY,
            "approval_quote_hash": mission.quote_hash,
            "payment_status": "PRAVA_PERMISSION_READY",
        }
        events = []
        if mission.approval_quote_hash != mission.quote_hash:
            events.append(("OWNER_APPROVED_EXACT_QUOTE", {"quote_hash": mission.quote_hash, "via": "PRAVA"}))
        events.append(("PRAVA_PERMISSION_READY", payload))
    elif state == "pending":
        updates = {"payment_status": "AWAITING_PRAVA_VERIFICATION"}
        events = [("PRAVA_VERIFICATION_PENDING", payload)]
    elif state == "failed":
        updates = {"phase": Phase.PAYMENT_DECLINED, "payment_status": "PRAVA_FAILED"}
        events = [("PRAVA_VERIFICATION_FAILED", payload)]
    else:
        raise Conflict("Prava state is not valid before merchant checkout")
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "refresh_prava",
        payload,
        updates,
        events,
    )


def start_checkout_attempt(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    provider: str = "SIMULATED_SWIGGY",
    environment: Environment = Environment.LOCAL,
) -> ExternalAttempt:
    command_payload = {
        "mission_id": mission_id,
        "expected_version": expected_version,
        "operation": "merchant_checkout",
        "provider": provider,
        "environment": environment,
    }
    existing_mission = _existing_command(session, command_id, "start_checkout", command_payload, mission_id)
    existing_attempt = session.scalar(select(ExternalAttempt).where(ExternalAttempt.command_id == command_id))
    if existing_mission and existing_attempt:
        return existing_attempt
    mission = _mission(session, mission_id)
    if mission.phase != Phase.PAYMENT_PERMISSION_READY or mission.approval_quote_hash != mission.quote_hash:
        existing_mission = _existing_command(session, command_id, "start_checkout", command_payload, mission_id)
        existing_attempt = session.scalar(select(ExternalAttempt).where(ExternalAttempt.command_id == command_id))
        if existing_mission and existing_attempt:
            return existing_attempt
        raise Conflict("checkout requires approval for the current quote")
    if _quote_expired(mission):
        _record_quote_expired(session, mission, expected_version, command_id)
        raise Conflict("quote expired before checkout; request a fresh quote")
    attempt = ExternalAttempt(
        id=str(uuid4()),
        mission_id=mission_id,
        command_id=command_id,
        provider=provider,
        operation="merchant_checkout",
        environment=environment,
        status="IN_PROGRESS",
        terminal=None,
        retry_eligible=False,
    )
    _transition(
        session, mission_id, expected_version, command_id,
        "start_checkout", command_payload,
        {
            "phase": Phase.MERCHANT_CHECKOUT_IN_PROGRESS,
            "checkout_status": "LIVE_IN_PROGRESS" if provider == "SWIGGY_BROWSER" else "SIMULATED_IN_PROGRESS",
        },
        [(
            "SWIGGY_BROWSER_CHECKOUT_STARTED" if provider == "SWIGGY_BROWSER" else "SIMULATED_MERCHANT_CHECKOUT_STARTED",
            {"attempt_id": attempt.id},
        )],
        attempt=attempt,
    )
    persisted = session.scalar(select(ExternalAttempt).where(ExternalAttempt.command_id == command_id))
    if not persisted:
        raise Conflict("checkout attempt record is missing")
    return persisted


def simulate_checkout(outcome: str, attempt_id: str) -> ProviderResult:
    if outcome == "decline":
        return ProviderResult(
            provider="SIMULATED_SWIGGY",
            operation="merchant_checkout",
            environment=Environment.LOCAL,
            status="DECLINED",
            terminal=True,
            redacted_reference=f"sim…{attempt_id[-4:]}",
        )
    return ProviderResult(
        provider="SIMULATED_SWIGGY",
        operation="merchant_checkout",
        environment=Environment.LOCAL,
        status="TIMED_OUT" if outcome == "timeout" else "UNKNOWN",
        terminal=False,
        redacted_reference=f"sim…{attempt_id[-4:]}",
        error_class="provider_timeout" if outcome == "timeout" else "outcome_unknown",
        retry_eligible=False,
    )


def finalize_checkout(session: Session, mission_id: str, expected_version: int, command_id: str, attempt_id: str, result: ProviderResult) -> Mission:
    command_payload = {
        "mission_id": mission_id,
        "expected_version": expected_version,
        "attempt_id": attempt_id,
        "result": result.model_dump(mode="json"),
    }
    if existing := _existing_command(session, command_id, "finalize_checkout", command_payload, mission_id):
        return existing
    attempt = session.get(ExternalAttempt, attempt_id)
    if not attempt or attempt.mission_id != mission_id:
        raise NotFound("checkout attempt not found")
    if (result.provider, result.operation, result.environment) != (
        attempt.provider,
        attempt.operation,
        Environment(attempt.environment),
    ):
        raise Conflict("provider result does not match the checkout attempt")
    if (result.status in {"APPROVED", "DECLINED"}) != result.terminal:
        raise Conflict("provider result terminal flag is inconsistent with its status")
    if attempt.status != "IN_PROGRESS":
        return _replay_or_conflict(
            session, command_id, "finalize_checkout", command_payload, mission_id,
            "checkout attempt is already resolved",
        )
    now = utcnow()
    attempt.status = result.status
    attempt.terminal = result.terminal
    attempt.redacted_reference = result.redacted_reference
    attempt.error_class = result.error_class
    attempt.retry_eligible = result.retry_eligible
    attempt.finished_at = now

    live = attempt.provider == "SWIGGY_BROWSER"
    if live and result.status in {"APPROVED", "DECLINED"}:
        updates = {
            "phase": Phase.PAYMENT_RESULT_REPORT_REQUIRED,
            "checkout_status": result.status,
            "payment_status": "PRAVA_RESULT_REPORT_REQUIRED",
        }
        events = [(f"SWIGGY_BROWSER_{result.status}", result.model_dump(mode="json"))]
    elif not live and result.status == "DECLINED":
        updates = {"phase": Phase.PAYMENT_DECLINED, "checkout_status": "DECLINED", "payment_status": "FAILED"}
        events = [
            ("SIMULATED_MERCHANT_DECLINED", result.model_dump(mode="json")),
            ("SIMULATED_PRAVA_RESULT_REPORTED_DECLINED", {"attempt_id": attempt_id}),
            ("SIMULATED_PRAVA_FINAL_FAILED", {"attempt_id": attempt_id}),
        ]
    else:
        updates = {"phase": Phase.CHECKOUT_OUTCOME_UNKNOWN, "checkout_status": "UNKNOWN", "payment_status": "OUTCOME_UNKNOWN"}
        events = [(
            "SWIGGY_BROWSER_OUTCOME_UNKNOWN" if live else "SIMULATED_CHECKOUT_OUTCOME_UNKNOWN",
            result.model_dump(mode="json"),
        )]

    mission = _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "finalize_checkout",
        command_payload,
        updates,
        events,
    )
    return mission


def abort_checkout_attempt(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    attempt_id: str,
) -> Mission:
    payload = {"mission_id": mission_id, "expected_version": expected_version, "attempt_id": attempt_id}
    if existing := _existing_command(session, command_id, "abort_checkout", payload, mission_id):
        return existing
    attempt = session.get(ExternalAttempt, attempt_id)
    if not attempt or attempt.mission_id != mission_id or attempt.provider != "SWIGGY_BROWSER":
        raise NotFound("live checkout attempt not found")
    if attempt.status != "IN_PROGRESS":
        return _replay_or_conflict(
            session, command_id, "abort_checkout", payload, mission_id, "checkout attempt is already resolved"
        )
    attempt.status = "NOT_SUBMITTED"
    attempt.terminal = True
    attempt.error_class = "browser_not_ready"
    attempt.retry_eligible = True
    attempt.finished_at = utcnow()
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "abort_checkout",
        payload,
        {"phase": Phase.PAYMENT_PERMISSION_READY, "checkout_status": "NOT_SUBMITTED"},
        [("SWIGGY_BROWSER_NOT_SUBMITTED", {"attempt_id": attempt_id})],
    )


def record_prava_final_state(
    session: Session,
    mission_id: str,
    expected_version: int,
    command_id: str,
    attempt_id: str,
    state: str,
) -> Mission:
    payload = {
        "mission_id": mission_id,
        "expected_version": expected_version,
        "attempt_id": attempt_id,
        "state": state,
    }
    if existing := _existing_command(session, command_id, "record_prava_result", payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    attempt = session.get(ExternalAttempt, attempt_id)
    if mission.phase != Phase.PAYMENT_RESULT_REPORT_REQUIRED or not attempt or attempt.mission_id != mission_id:
        raise Conflict("mission has no confirmed merchant result awaiting a Prava report")
    expected = "completed" if attempt.status == "APPROVED" else "failed" if attempt.status == "DECLINED" else None
    if state != expected:
        raise Conflict("Prava final state does not match the merchant result")
    declined = state == "failed"
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "record_prava_result",
        payload,
        {
            "phase": Phase.PAYMENT_DECLINED if declined else Phase.ORDER_CONFIRMED,
            "payment_status": "PRAVA_FAILED" if declined else "PRAVA_COMPLETED",
            "checkout_status": "DECLINED" if declined else "ORDER_CONFIRMED",
        },
        [
            (f"PRAVA_RESULT_REPORTED_{attempt.status}", {"attempt_id": attempt_id}),
            ("PRAVA_FINAL_FAILED" if declined else "PRAVA_FINAL_COMPLETED", {"attempt_id": attempt_id}),
        ],
    )


def recover_in_progress_attempts(session: Session) -> int:
    attempts = session.scalars(select(ExternalAttempt).where(ExternalAttempt.status == "IN_PROGRESS")).all()
    recovered = 0
    for attempt in attempts:
        mission = _mission(session, attempt.mission_id)
        result = ProviderResult(
            provider=attempt.provider,
            operation=attempt.operation,
            environment=Environment(attempt.environment),
            status="UNKNOWN",
            terminal=False,
            redacted_reference=attempt.redacted_reference,
            error_class="process_interrupted",
            retry_eligible=False,
        )
        finalize_checkout(session, mission.id, mission.version, f"recover-{attempt.id}", attempt.id, result)
        recovered += 1
    return recovered


def requote(session: Session, mission_id: str, expected_version: int, command_id: str, amount_minor: int) -> Mission:
    command_payload = {"mission_id": mission_id, "expected_version": expected_version, "amount_minor": amount_minor}
    if existing := _existing_command(session, command_id, "requote", command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase not in {Phase.AWAITING_OWNER_APPROVAL, Phase.PAYMENT_PERMISSION_READY} or not mission.quote:
        return _replay_or_conflict(
            session, command_id, "requote", command_payload, mission_id,
            "only a pending quote can be revised",
        )
    if Quote.model_validate(mission.quote).environment == Environment.PRODUCTION:
        return _replay_or_conflict(
            session, command_id, "requote", command_payload, mission_id,
            "live quote must be recreated from the merchant",
        )
    quote = Quote.model_validate({**mission.quote, "revision": mission.quote["revision"] + 1, "amount_minor": amount_minor, "expires_at": utcnow() + timedelta(minutes=15)})
    hashed = quote_hash(quote)
    return _transition(
        session, mission_id, expected_version, command_id,
        "requote", command_payload,
        {
            "phase": Phase.AWAITING_OWNER_APPROVAL,
            "quote": quote.model_dump(mode="json"),
            "quote_hash": hashed,
            "approval_quote_hash": None,
            "commerce_status": "SIMULATED_QUOTED",
            "payment_status": "NOT_STARTED",
        },
        [("QUOTE_CHANGED_APPROVAL_INVALIDATED", {"quote_hash": hashed, "amount_minor": amount_minor})],
    )


def cancel(session: Session, mission_id: str, expected_version: int, command_id: str) -> Mission:
    command_payload = {"mission_id": mission_id, "expected_version": expected_version}
    if existing := _existing_command(session, command_id, "cancel", command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.phase not in {
        Phase.DRAFT,
        Phase.NEEDS_CLARIFICATION,
        Phase.AWAITING_OWNER_APPROVAL,
        Phase.PAYMENT_APPROVAL_REQUIRED,
        Phase.PAYMENT_PERMISSION_READY,
        Phase.ORDER_CONFIRMED,
        Phase.READY_TO_DISPATCH,
    }:
        return _replay_or_conflict(
            session, command_id, "cancel", command_payload, mission_id,
            "mission cannot be cancelled from its current state",
        )
    updates = {"phase": Phase.CANCELLED}
    if mission.environment == Environment.STAGED:
        updates["fulfilment_status"] = "CANCELLED"
    return _transition(
        session,
        mission_id,
        expected_version,
        command_id,
        "cancel",
        command_payload,
        updates,
        [("MISSION_CANCELLED", {})],
    )


def start_staged_fulfilment(session: Session, parent_id: str, expected_version: int, command_id: str) -> Mission:
    command_payload = {"parent_id": parent_id, "expected_version": expected_version}
    if existing := _existing_command(session, command_id, "start_staged", command_payload):
        return existing
    parent = _mission(session, parent_id)
    if parent.version != expected_version:
        return _replay_or_conflict(
            session, command_id, "start_staged", command_payload, None,
            "mission changed; refresh before retrying",
        )
    if parent.phase != Phase.PAYMENT_DECLINED:
        return _replay_or_conflict(
            session, command_id, "start_staged", command_payload, None,
            "staged fulfilment requires the recorded decline",
        )
    if session.scalar(select(Mission).where(Mission.parent_mission_id == parent_id)):
        raise Conflict("staged fulfilment already exists for this mission")
    if session.scalar(select(Mission.id).where(Mission.active_slot == "active")):
        raise Conflict("another mission is active")
    child = Mission(
        id=str(uuid4()),
        parent_mission_id=parent.id,
        active_slot="active",
        version=1,
        phase=Phase.ORDER_CONFIRMED,
        environment=Environment.STAGED,
        agent_mode=parent.agent_mode,
        request_text=parent.request_text,
        intent=parent.intent,
        quote=parent.quote,
        quote_hash=parent.quote_hash,
        approval_quote_hash=None,
        commerce_status="SIMULATED_ORDER_CONFIRMED",
        payment_status="NOT_APPLICABLE_STAGED",
        checkout_status="NOT_APPLICABLE_STAGED",
        fulfilment_status="AWAITING_PACKAGE_READY",
        notification_status="NOT_STARTED",
    )
    try:
        session.add(child)
        session.flush()
        session.add(Event(
            mission_id=child.id,
            sequence=1,
            command_id=command_id,
            command_scope="start_staged",
            request_hash=_request_hash("start_staged", command_payload),
            event_type="SIMULATED_ORDER_CONFIRMED",
            component="commerce",
            provider="SIMULATED_SWIGGY",
            human_intervened=True,
            environment=Environment.STAGED,
            phase_before=Phase.DRAFT,
            phase_after=Phase.ORDER_CONFIRMED,
            payload={"source_mission_id": parent.id, "source_payment_result": parent.phase},
        ))
        session.commit()
        return child
    except IntegrityError:
        session.rollback()
        if existing := _existing_command(session, command_id, "start_staged", command_payload):
            return existing
        if session.scalar(select(Mission).where(Mission.parent_mission_id == parent_id)):
            raise Conflict("staged fulfilment already exists for this mission")
        if session.scalar(select(Mission.id).where(Mission.active_slot == "active")):
            raise Conflict("another mission is active")
        raise Conflict("staged fulfilment already exists for this mission")


def package_ready(session: Session, mission_id: str, expected_version: int, command_id: str) -> Mission:
    command_payload = {"mission_id": mission_id, "expected_version": expected_version}
    if existing := _existing_command(session, command_id, "package_ready", command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.environment != Environment.STAGED or mission.phase != Phase.ORDER_CONFIRMED:
        return _replay_or_conflict(
            session, command_id, "package_ready", command_payload, mission_id,
            "PACKAGE_READY applies only to a staged mission awaiting its package",
        )
    return _transition(
        session, mission_id, expected_version, command_id,
        "package_ready", command_payload,
        {"phase": Phase.READY_TO_DISPATCH, "fulfilment_status": "PACKAGE_READY"},
        [("PACKAGE_READY", {"source": "operator", "environment": Environment.STAGED})],
    )


def run_robot_simulation(session: Session, mission_id: str, expected_version: int, command_id: str) -> Mission:
    command_payload = {"mission_id": mission_id, "expected_version": expected_version}
    if existing := _existing_command(session, command_id, "run_robot", command_payload, mission_id):
        return existing
    mission = _mission(session, mission_id)
    if mission.environment != Environment.STAGED or mission.phase != Phase.READY_TO_DISPATCH or mission.fulfilment_status != "PACKAGE_READY":
        return _replay_or_conflict(
            session, command_id, "run_robot", command_payload, mission_id,
            "robot dispatch is blocked until staged PACKAGE_READY",
        )
    return _transition(
        session, mission_id, expected_version, command_id,
        "run_robot", command_payload,
        {
            "phase": Phase.COMPLETED,
            "fulfilment_status": "SIMULATED_COMPLETED",
            "notification_status": "SIMULATED_DELIVERED",
        },
        [
            ("SIMULATED_NOTIFICATION_DISPATCHED", {}),
            ("SIMULATED_ROBOT_DISPATCHED", {}),
            ("SIMULATED_ROBOT_ARRIVED", {}),
            ("SIMULATED_ITEM_SECURED", {}),
            ("SIMULATED_ROBOT_RETURNING", {}),
            ("SIMULATED_ROBOT_COMPLETED", {}),
            ("SIMULATED_NOTIFICATION_COMPLETED", {}),
        ],
    )


def retry_allowed(operation: str, status: str) -> bool:
    return operation in {"catalog_search", "status_read"} and status in {"ERROR", "TIMED_OUT"}
