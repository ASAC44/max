import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import parse_request
from .config import admin_token, agent_mode, commerce_mode, payment_mode, web_origin
from .db import SessionLocal, get_session
from .integrations import BrowserCheckoutError, IntegrationError, PravaClient, SwiggyBrowserCheckout, SwiggyClient
from .models import Event, ExternalAttempt, Mission
from .schemas import (
    ApprovalView,
    ApproveCommand,
    AttemptView,
    CheckoutView,
    CommandBase,
    MissionCreate,
    MissionReply,
    MissionView,
    PaymentActionView,
    Quote,
    RequoteCommand,
)
from .workflow import (
    WorkflowError,
    abort_checkout_attempt,
    apply_intent,
    approve_quote,
    cancel,
    command_failed,
    create_mission,
    finalize_checkout,
    missing_fields,
    package_ready,
    preflight_command,
    record_agent_failure,
    record_prava_payment_state,
    record_prava_final_state,
    record_prava_session,
    recover_in_progress_attempts,
    requote,
    run_robot_simulation,
    simulate_checkout,
    start_checkout_attempt,
    start_staged_fulfilment,
)

bearer = HTTPBearer(auto_error=False)
# ponytail: one demo operator; replace with per-account distributed locks only if this becomes multi-instance.
checkout_lock = asyncio.Lock()


def interpretation_error(mission_id: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"message": "request interpretation failed", "mission_id": mission_id},
    )


async def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    expected = admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="MAX_ADMIN_TOKEN is not configured")
    if not credentials or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="invalid operator credential")


def mission_view(session: Session, mission: Mission) -> MissionView:
    events = session.scalars(select(Event).where(Event.mission_id == mission.id).order_by(Event.sequence)).all()
    attempts = session.scalars(select(ExternalAttempt).where(ExternalAttempt.mission_id == mission.id).order_by(ExternalAttempt.started_at)).all()
    attempt_views = [AttemptView.model_validate(attempt) for attempt in attempts]
    payment_action = None
    for event in reversed(events):
        if event.event_type == "PRAVA_SANDBOX_SESSION_CREATED":
            payment_action = PaymentActionView(
                provider="PRAVA",
                environment="sandbox",
                **event.payload,
            )
            break
    return MissionView(
        id=mission.id,
        parent_mission_id=mission.parent_mission_id,
        version=mission.version,
        phase=mission.phase,
        environment=mission.environment,
        agent_mode=mission.agent_mode,
        request_text=mission.request_text,
        intent=mission.intent,
        clarification_question=mission.clarification_question,
        quote=mission.quote,
        quote_hash=mission.quote_hash,
        commerce_status=mission.commerce_status,
        payment_status=mission.payment_status,
        checkout_status=mission.checkout_status,
        fulfilment_status=mission.fulfilment_status,
        notification_status=mission.notification_status,
        created_at=mission.created_at,
        updated_at=mission.updated_at,
        events=events,
        attempts=attempt_views,
        approval=ApprovalView(status=mission.payment_status, quote_hash=mission.approval_quote_hash),
        checkout=CheckoutView(status=mission.checkout_status, latest_attempt=attempt_views[-1] if attempt_views else None),
        payment_action=payment_action,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as session:
        recover_in_progress_attempts(session)
    yield


app = FastAPI(title="Max API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[web_origin()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


@app.exception_handler(WorkflowError)
async def workflow_error_handler(_request, exc: WorkflowError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "agent_mode": agent_mode(),
        "commerce_mode": commerce_mode(),
        "payment_mode": payment_mode(),
        "environment": "local",
    }


@app.get("/api/payments/prava/complete", response_class=HTMLResponse)
async def prava_complete() -> str:
    return "<h1>Prava verification complete</h1><p>You can close this page. Max will continue automatically.</p>"


async def start_live_prava_approval(session: Session, mission: Mission, command_id: str) -> Mission:
    if payment_mode() != "prava" or mission.phase != "AWAITING_OWNER_APPROVAL":
        return mission
    quote = Quote.model_validate(mission.quote)
    try:
        prava_session = await PravaClient().create_session(quote)
    except IntegrationError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": str(exc), "mission_id": mission.id},
        ) from exc
    return record_prava_session(
        session,
        mission.id,
        mission.version,
        f"{command_id}-prava",
        {
            "session_id": prava_session.session_id,
            "order_id": prava_session.order_id,
            "approval_url": prava_session.approval_url,
            "expires_at": prava_session.expires_at,
        },
    )


@app.post("/api/missions", response_model=MissionView, dependencies=[Depends(require_admin)])
async def create(
    body: MissionCreate,
    idempotency_key: str = Header(min_length=8, max_length=48, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    mode = agent_mode()
    try:
        mission = create_mission(session, body.text, idempotency_key, mode)
    except WorkflowError as exc:
        active = session.scalar(select(Mission).where(Mission.active_slot == "active"))
        if str(exc) == "another mission is active" and active:
            raise HTTPException(
                status_code=409,
                detail={"message": str(exc), "mission_id": active.id},
            ) from exc
        raise
    if mission.phase != "DRAFT":
        return mission_view(session, mission)
    parse_command = f"{idempotency_key}-parse"
    parse_payload = {"text": body.text}
    if replay := preflight_command(
        session, mission.id, mission.version, parse_command, "initial_parse", parse_payload, {"DRAFT"}
    ):
        if command_failed(session, parse_command):
            raise interpretation_error(replay.id)
        return mission_view(session, replay)
    try:
        intent = await parse_request(body.text)
    except Exception as exc:
        failed = record_agent_failure(
            session,
            mission.id,
            mission.version,
            parse_command,
            "initial_parse",
            parse_payload,
            type(exc).__name__,
        )
        raise interpretation_error(failed.id) from exc
    resolved_quote = None
    if commerce_mode() == "swiggy" and not missing_fields(intent):
        try:
            resolved_quote = await SwiggyClient().quote(intent)
        except IntegrationError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": str(exc), "mission_id": mission.id},
            ) from exc
    mission = apply_intent(
        session,
        mission.id,
        mission.version,
        parse_command,
        intent,
        command_scope="initial_parse",
        command_payload=parse_payload,
        resolved_quote=resolved_quote,
    )
    if resolved_quote is not None:
        mission = await start_live_prava_approval(session, mission, parse_command)
    return mission_view(session, mission)


@app.get("/api/missions/{mission_id}", response_model=MissionView, dependencies=[Depends(require_admin)])
async def get_mission(mission_id: str, session: Session = Depends(get_session)):
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/reply", response_model=MissionView, dependencies=[Depends(require_admin)])
async def reply(mission_id: str, body: MissionReply, session: Session = Depends(get_session)):
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    command_payload = {"text": body.text, "expected_version": body.expected_version}
    if replay := preflight_command(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        "reply",
        command_payload,
        {"DRAFT", "NEEDS_CLARIFICATION"},
    ):
        if command_failed(session, body.command_id):
            raise interpretation_error(replay.id)
        return mission_view(session, replay)
    combined = f"{mission.request_text}\nOwner clarification: {body.text}"
    try:
        intent = await parse_request(combined)
    except Exception as exc:
        failed = record_agent_failure(
            session,
            mission_id,
            body.expected_version,
            body.command_id,
            "reply",
            command_payload,
            type(exc).__name__,
        )
        raise interpretation_error(failed.id) from exc
    resolved_quote = None
    if commerce_mode() == "swiggy" and not missing_fields(intent):
        try:
            resolved_quote = await SwiggyClient().quote(intent)
        except IntegrationError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": str(exc), "mission_id": mission.id},
            ) from exc
    mission = apply_intent(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        intent,
        combined,
        command_scope="reply",
        command_payload=command_payload,
        resolved_quote=resolved_quote,
    )
    if resolved_quote is not None:
        mission = await start_live_prava_approval(session, mission, body.command_id)
    return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/approve", response_model=MissionView, dependencies=[Depends(require_admin)])
async def approve(mission_id: str, body: ApproveCommand, session: Session = Depends(get_session)):
    mode = payment_mode()
    current = session.get(Mission, mission_id)
    if not current:
        raise HTTPException(status_code=404, detail="mission not found")
    current_quote = Quote.model_validate(current.quote) if current.quote else None
    if mode == "prava" and (
        not current_quote
        or current_quote.merchant != "SWIGGY_INSTAMART"
        or current_quote.environment != "production"
    ):
        raise HTTPException(status_code=409, detail="live Prava requires a live Swiggy quote")
    mission = approve_quote(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        body.quote_hash,
        body.simulated_outcome,
        payment_mode=mode,
    )
    if mode == "prava":
        existing = session.scalar(select(Event).where(
            Event.mission_id == mission_id,
            Event.event_type == "PRAVA_SANDBOX_SESSION_CREATED",
        ))
        if not existing:
            try:
                prava_session = await PravaClient().create_session(current_quote)
            except IntegrationError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            mission = record_prava_session(
                session,
                mission_id,
                mission.version,
                f"{body.command_id}-prava",
                {
                    "session_id": prava_session.session_id,
                    "order_id": prava_session.order_id,
                    "approval_url": prava_session.approval_url,
                    "expires_at": prava_session.expires_at,
                },
            )
        return mission_view(session, mission)
    if mission.phase in {"PAYMENT_DECLINED", "CHECKOUT_OUTCOME_UNKNOWN"}:
        return mission_view(session, mission)
    attempt_command = f"{body.command_id}-checkout"
    if mission.phase == "PAYMENT_PERMISSION_READY":
        attempt = start_checkout_attempt(session, mission_id, mission.version, attempt_command)
        mission = session.get(Mission, mission_id)
    elif mission.phase == "MERCHANT_CHECKOUT_IN_PROGRESS":
        attempt = session.scalar(
            select(ExternalAttempt).where(
                ExternalAttempt.mission_id == mission_id,
                ExternalAttempt.command_id == attempt_command,
            )
        )
        if not attempt:
            raise HTTPException(status_code=409, detail="checkout attempt record is missing")
    else:
        raise HTTPException(status_code=409, detail="approval flow cannot continue from the current phase")
    result = simulate_checkout(body.simulated_outcome, attempt.id)
    mission = finalize_checkout(session, mission_id, mission.version, f"{body.command_id}-result", attempt.id, result)
    return mission_view(session, mission)


@app.post(
    "/api/missions/{mission_id}/commands/refresh-payment",
    response_model=MissionView,
    dependencies=[Depends(require_admin)],
)
async def refresh_payment(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    event = session.scalar(select(Event).where(
        Event.mission_id == mission_id,
        Event.event_type == "PRAVA_SANDBOX_SESSION_CREATED",
    ))
    if not event:
        raise HTTPException(status_code=409, detail="mission has no Prava session")
    try:
        state = await PravaClient().payment_state(event.payload["session_id"])
    except IntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if state.status == "pending" and mission.payment_status == "AWAITING_PRAVA_VERIFICATION":
        return mission_view(session, mission)
    mission = record_prava_payment_state(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        state.status,
        state.txn_ref_id,
        state.credential_fields_present,
    )
    return mission_view(session, mission)


@app.post(
    "/api/missions/{mission_id}/commands/execute-checkout",
    response_model=MissionView,
    dependencies=[Depends(require_admin)],
)
async def execute_checkout(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    async with checkout_lock:
        mission = session.get(Mission, mission_id, populate_existing=True)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        attempt_command = f"{body.command_id}-attempt"
        if session.scalar(select(ExternalAttempt).where(ExternalAttempt.command_id == attempt_command)):
            return mission_view(session, mission)
        if payment_mode() != "prava" or commerce_mode() != "swiggy":
            raise HTTPException(status_code=409, detail="live checkout requires Swiggy commerce and Prava payment modes")
        if mission.phase != "PAYMENT_PERMISSION_READY" or mission.version != body.expected_version:
            raise HTTPException(status_code=409, detail="checkout requires the current Prava-ready mission version")
        quote = Quote.model_validate(mission.quote)
        session_event = session.scalar(select(Event).where(
            Event.mission_id == mission_id,
            Event.event_type == "PRAVA_SANDBOX_SESSION_CREATED",
        ))
        ready_event = session.scalar(select(Event).where(
            Event.mission_id == mission_id,
            Event.event_type == "PRAVA_PERMISSION_READY",
        ))
        if not session_event or not ready_event:
            raise HTTPException(status_code=409, detail="mission is missing its Prava checkout evidence")

        try:
            await SwiggyClient().verify_quote(quote)
            prava = PravaClient()
            credential = await prava.credential(session_event.payload["session_id"])
        except IntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if credential.txn_ref_id != ready_event.payload.get("txn_ref_id"):
            del credential
            raise HTTPException(status_code=409, detail="Prava transaction reference changed; stop and inspect")

        try:
            attempt = start_checkout_attempt(
                session,
                mission_id,
                mission.version,
                attempt_command,
                provider="SWIGGY_BROWSER",
                environment="production",
            )
            mission = session.get(Mission, mission_id, populate_existing=True)
            try:
                result = await SwiggyBrowserCheckout().checkout(quote, credential)
            except BrowserCheckoutError as exc:
                abort_checkout_attempt(
                    session,
                    mission_id,
                    mission.version,
                    f"{body.command_id}-not-submitted",
                    attempt.id,
                )
                raise HTTPException(
                    status_code=409,
                    detail={"message": str(exc), "mission_id": mission_id, "submitted": False},
                ) from exc
        finally:
            del credential

        mission = finalize_checkout(
            session,
            mission_id,
            mission.version,
            f"{body.command_id}-merchant-result",
            attempt.id,
            result,
        )
        if result.status not in {"APPROVED", "DECLINED"}:
            return mission_view(session, mission)
        try:
            final_state = await prava.report_result(
                session_event.payload["session_id"],
                ready_event.payload["txn_ref_id"],
                result.status,
            )
        except IntegrationError as exc:
            raise HTTPException(status_code=502, detail={
                "message": str(exc),
                "mission_id": mission_id,
                "merchant_result": result.status,
                "checkout_was_not_retried": True,
            }) from exc
        mission = record_prava_final_state(
            session,
            mission_id,
            mission.version,
            f"{body.command_id}-prava-result",
            attempt.id,
            final_state.status,
        )
        return mission_view(session, mission)


@app.post(
    "/api/missions/{mission_id}/commands/report-payment-result",
    response_model=MissionView,
    dependencies=[Depends(require_admin)],
)
async def report_payment_result(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    async with checkout_lock:
        mission = session.get(Mission, mission_id, populate_existing=True)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        if session.scalar(select(Event).where(Event.mission_id == mission_id, Event.command_id == body.command_id)):
            return mission_view(session, mission)
        attempt = session.scalar(
            select(ExternalAttempt)
            .where(
                ExternalAttempt.mission_id == mission_id,
                ExternalAttempt.provider == "SWIGGY_BROWSER",
                ExternalAttempt.status.in_(("APPROVED", "DECLINED")),
            )
            .order_by(ExternalAttempt.started_at.desc())
        )
        event = session.scalar(select(Event).where(
            Event.mission_id == mission_id,
            Event.event_type == "PRAVA_SANDBOX_SESSION_CREATED",
        ))
        ready = session.scalar(select(Event).where(
            Event.mission_id == mission_id,
            Event.event_type == "PRAVA_PERMISSION_READY",
        ))
        if (
            mission.phase != "PAYMENT_RESULT_REPORT_REQUIRED"
            or mission.version != body.expected_version
            or not attempt
            or not event
            or not ready
        ):
            raise HTTPException(status_code=409, detail="mission has no merchant result awaiting a Prava report")
        try:
            state = await PravaClient().report_result(
                event.payload["session_id"], ready.payload["txn_ref_id"], attempt.status
            )
        except IntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        mission = record_prava_final_state(
            session, mission_id, mission.version, body.command_id, attempt.id, state.status
        )
        return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/requote", response_model=MissionView, dependencies=[Depends(require_admin)])
async def change_quote(mission_id: str, body: RequoteCommand, session: Session = Depends(get_session)):
    return mission_view(session, requote(session, mission_id, body.expected_version, body.command_id, body.amount_minor))


@app.post("/api/missions/{mission_id}/commands/cancel", response_model=MissionView, dependencies=[Depends(require_admin)])
async def cancel_mission(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, cancel(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/start-staged", response_model=MissionView, dependencies=[Depends(require_admin)])
async def start_staged(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, start_staged_fulfilment(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/package-ready", response_model=MissionView, dependencies=[Depends(require_admin)])
async def mark_package_ready(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, package_ready(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/run-robot", response_model=MissionView, dependencies=[Depends(require_admin)])
async def run_robot(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, run_robot_simulation(session, mission_id, body.expected_version, body.command_id))
