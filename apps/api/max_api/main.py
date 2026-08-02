import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import parse_request
from .config import (
    admin_token,
    agent_mode,
    commerce_mode,
    payment_mode,
    purchase_enabled,
    robot_dry_run,
    robot_heartbeat_stale_seconds,
    robot_mode,
    robot_token,
    runtime_environment,
    teleop_agent_idle_seconds,
    teleop_controller_idle_seconds,
    teleop_deadman_ms,
    teleop_enabled,
    teleop_max_client_age_ms,
    teleop_state_file,
    telegram_bot_token,
    telegram_owner_user_id,
    telegram_webhook_secret,
    web_origin,
)
from .db import SessionLocal, get_session
from .integrations import (
    BrowserCheckoutError,
    IntegrationError,
    PravaClient,
    RobotClient,
    SwiggyBrowserCheckout,
    SwiggyClient,
    SwiggyConnectionError,
)
from .models import Event, ExternalAttempt, Mission, RobotJob, utcnow
from .order_sync import order_sync_worker_readiness
from .robot_jobs import (
    acknowledge_robot_job,
    current_robot_job,
    latest_robot_node,
    next_robot_job,
    record_robot_heartbeat,
    record_robot_lifecycle_report,
    stage_robot_job,
)
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
    RobotPollAck,
    RobotHeartbeat,
    RobotLifecycleReport,
    RobotJobView,
    ShoppingIntent,
)
from .telegram import (
    TelegramError,
    enqueue_telegram_update,
    parse_telegram_update,
    verify_telegram_owner,
)
from .teleop import (
    TeleopConflict,
    TeleopHub,
    TeleopSafetyStore,
    authenticate_websocket,
)
from .workflow import (
    WorkflowError,
    abort_checkout_attempt,
    apply_intent,
    approve_quote,
    cancel,
    command_failed,
    close_unresolved,
    create_mission,
    finalize_checkout,
    missing_fields,
    package_ready,
    preflight_command,
    record_agent_failure,
    record_prava_payment_state,
    record_prava_final_state,
    record_prava_session,
    record_robot_dispatch_acknowledgement,
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
teleop_hub = TeleopHub(
    store=TeleopSafetyStore(teleop_state_file()),
    feature_enabled=teleop_enabled(),
    deadman_ms=teleop_deadman_ms(),
    max_client_age_ms=teleop_max_client_age_ms(),
    controller_idle_seconds=teleop_controller_idle_seconds(),
    agent_idle_seconds=teleop_agent_idle_seconds(),
)


async def swiggy_quote_with_transport_retry(intent: ShoppingIntent) -> Quote:
    """Retry one pre-checkout MCP transport failure.

    Quote construction may only search and rebuild the cart. It cannot submit
    merchant checkout or payment, so one bounded retry is safe. Provider
    rejections and validation errors are never retried.
    """
    try:
        return await SwiggyClient().quote(intent)
    except SwiggyConnectionError:
        await asyncio.sleep(0.25)
        return await SwiggyClient().quote(intent)


def interpretation_error(mission_id: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"message": "request interpretation failed", "mission_id": mission_id},
    )


def readiness_check_passes(check: dict) -> bool:
    if "connected" in check:
        return bool(check["connected"])
    return bool(check.get("configured", False))


PRAVA_SESSION_EVENT_TYPES = (
    "PRAVA_SESSION_CREATED",
    "PRAVA_SANDBOX_SESSION_CREATED",
)


def prava_session_event(session: Session, mission_id: str) -> Event | None:
    return session.scalar(
        select(Event)
        .where(
            Event.mission_id == mission_id,
            Event.event_type.in_(PRAVA_SESSION_EVENT_TYPES),
        )
        .order_by(Event.sequence.desc())
    )


async def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    expected = admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="MAX_ADMIN_TOKEN is not configured")
    if not credentials or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="invalid operator credential")


async def require_robot(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    try:
        expected = robot_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="MAX_ROBOT_TOKEN is not configured") from exc
    if not credentials or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(
        credentials.credentials,
        expected,
    ):
        raise HTTPException(status_code=401, detail="invalid robot credential")


def mission_view(session: Session, mission: Mission) -> MissionView:
    events = session.scalars(select(Event).where(Event.mission_id == mission.id).order_by(Event.sequence)).all()
    source_mission_id = mission.parent_mission_id or mission.id
    source_order_events = session.scalars(
        select(Event)
        .where(
            Event.mission_id == source_mission_id,
            Event.event_type.like("SWIGGY_ORDER_%"),
        )
        .order_by(Event.sequence)
    ).all()
    attempts = session.scalars(select(ExternalAttempt).where(ExternalAttempt.mission_id == mission.id).order_by(ExternalAttempt.started_at)).all()
    robot_job = session.scalar(
        select(RobotJob).where(RobotJob.mission_id == mission.id)
    )
    attempt_views = [AttemptView.model_validate(attempt) for attempt in attempts]
    payment_action = None
    for event in reversed(events):
        if event.event_type in PRAVA_SESSION_EVENT_TYPES:
            action = {**event.payload}
            action.setdefault("environment", "sandbox")
            payment_action = PaymentActionView(
                provider="PRAVA",
                **action,
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
        robot_job=RobotJobView.model_validate(robot_job) if robot_job else None,
        source_order_events=source_order_events,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as session:
        recover_in_progress_attempts(session)
    await teleop_hub.start()
    try:
        yield
    finally:
        await teleop_hub.stop()


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
        "purchase_enabled": purchase_enabled(),
        "environment": runtime_environment(),
        "teleop_enabled": teleop_hub.feature_enabled,
    }


@app.get("/api/teleop/status", dependencies=[Depends(require_admin)])
async def teleop_status() -> dict:
    return teleop_hub.status()


@app.post("/api/teleop/emergency-stop", dependencies=[Depends(require_admin)])
async def teleop_emergency_stop() -> dict:
    await teleop_hub.emergency_stop_now(
        "operator_http_emergency_stop",
        actor="http_operator",
    )
    return teleop_hub.status()


@app.websocket("/api/teleop/ws/controller")
async def teleop_controller(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin != web_origin():
        await websocket.close(code=4403)
        return
    expected = admin_token()
    if not expected:
        await websocket.close(code=1013)
        return
    if await authenticate_websocket(
        websocket,
        expected_token=expected,
        role="controller",
    ) is None:
        return
    try:
        await teleop_hub.attach_controller(websocket)
    except TeleopConflict as exc:
        await websocket.send_json({
            "type": "error",
            "code": "controller_conflict",
            "message": str(exc),
        })
        await websocket.close(code=4409)
        return
    await teleop_hub.controller_loop(websocket)


@app.websocket("/api/teleop/ws/agent")
async def teleop_agent(websocket: WebSocket) -> None:
    try:
        expected = robot_token()
    except RuntimeError:
        await websocket.close(code=1013)
        return
    auth = await authenticate_websocket(
        websocket,
        expected_token=expected,
        role="agent",
    )
    if auth is None:
        return
    agent_id = auth.get("agent_id")
    agent_version = auth.get("agent_version")
    if (
        not isinstance(agent_id, str)
        or not 1 <= len(agent_id) <= 64
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in agent_id)
    ):
        await websocket.send_json({
            "type": "error",
            "code": "invalid_agent_id",
            "message": "agent_id must contain 1-64 letters, numbers, underscores, or hyphens",
        })
        await websocket.close(code=4400)
        return
    if (
        not isinstance(agent_version, str)
        or not 1 <= len(agent_version) <= 32
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in agent_version
        )
    ):
        await websocket.send_json({
            "type": "error",
            "code": "invalid_agent_version",
            "message": "agent_version contains an invalid value",
        })
        await websocket.close(code=4400)
        return
    try:
        await teleop_hub.attach_agent(websocket, agent_id, agent_version)
    except TeleopConflict as exc:
        await websocket.send_json({
            "type": "error",
            "code": "agent_conflict",
            "message": str(exc),
        })
        await websocket.close(code=4409)
        return
    await teleop_hub.agent_loop(websocket)


@app.get("/api/readiness", dependencies=[Depends(require_admin)])
async def readiness(session: Session = Depends(get_session)) -> dict:
    checks: dict[str, dict] = {}
    try:
        checks["prava"] = await PravaClient().readiness()
    except IntegrationError as exc:
        secret = os.getenv("PRAVA_SECRET_KEY", "")
        checks["prava"] = {
            "configured": secret.startswith(("sk_test_", "sk_live_")),
            "connected": False,
            "error": str(exc),
        }
    try:
        telegram_bot_token()
        telegram_owner_user_id()
        telegram_webhook_secret()
        checks["telegram"] = {"configured": True, "owner_only": True}
    except RuntimeError:
        checks["telegram"] = {
            "configured": False,
            "error": "Telegram owner credentials are not configured",
        }
    for name, operation in {
        "swiggy_mcp": SwiggyClient().readiness,
        "swiggy_browser": SwiggyBrowserCheckout().readiness,
    }.items():
        try:
            checks[name] = await operation()
        except IntegrationError as exc:
            checks[name] = {"connected": False, "error": str(exc)}
    checks["order_sync_worker"] = order_sync_worker_readiness()
    node = latest_robot_node(session)
    checks["robot"] = {
        "connected": False,
        "motion_enabled": False,
    }
    if node:
        seen = node.last_seen_at
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        checks["robot"]["connected"] = (
            utcnow() - seen
        ).total_seconds() <= robot_heartbeat_stale_seconds()
        checks["robot"]["status"] = node.status
    return {
        "status": (
            "ready"
            if all(readiness_check_passes(check) for check in checks.values())
            else "blocked"
        ),
        "safe_to_purchase": (
            purchase_enabled()
            and checks["prava"].get("configured", False)
            and checks["prava"].get("connected", False)
            and checks["swiggy_mcp"].get("connected", False)
            and checks["swiggy_browser"].get("connected", False)
            and checks["order_sync_worker"].get("connected", False)
        ),
        "purchase_enabled": purchase_enabled(),
        "motion_enabled": False,
        "checks": checks,
    }


@app.get("/api/payments/prava/complete", response_class=HTMLResponse)
async def prava_complete() -> str:
    return "<h1>Prava verification complete</h1><p>You can close this page. Max will continue automatically.</p>"


@app.get("/api/robot/v1/next", dependencies=[Depends(require_robot)])
async def robot_next(session: Session = Depends(get_session)):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    job = next_robot_job(session)
    if not job:
        return {
            "schema_version": 1,
            "job": None,
            "motion_enabled": False,
        }
    return {
        "schema_version": 1,
        "motion_enabled": False,
        "job": {
            "schema_version": 1,
            "mission_id": job.mission_id,
            "command_id": job.command_id,
            "destination": job.destination,
            "dry_run": job.dry_run,
            "expected_version": job.expected_version,
            "trigger_source": job.trigger_source,
            "trigger_status": job.trigger_status,
        },
    }


@app.get("/api/robot/v1/current", dependencies=[Depends(require_robot)])
async def robot_current(session: Session = Depends(get_session)):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    job = current_robot_job(session)
    if not job:
        return {
            "schema_version": 1,
            "job": None,
            "motion_enabled": False,
        }
    mission = session.get(Mission, job.mission_id)
    return {
        "schema_version": 1,
        "motion_enabled": False,
        "job": {
            "schema_version": 1,
            "mission_id": job.mission_id,
            "command_id": job.command_id,
            "destination": job.destination,
            "dry_run": job.dry_run,
            "expected_version": mission.version,
            "phase": mission.phase,
            "job_status": job.status,
            "trigger_source": job.trigger_source,
            "trigger_status": job.trigger_status,
        },
    }


@app.get("/api/robot/v1/order-status", dependencies=[Depends(require_robot)])
async def robot_order_status(
    after: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    events = session.scalars(
        select(Event)
        .where(
            Event.id > after,
            Event.event_type.like("SWIGGY_ORDER_%"),
            Event.provider == "SWIGGY_INSTAMART_MCP",
        )
        .order_by(Event.id)
        .limit(50)
    ).all()
    values = []
    for event in events:
        mission = session.get(Mission, event.mission_id)
        quote = Quote.model_validate(mission.quote) if mission and mission.quote else None
        normalized = event.payload.get("normalized_status", "UNKNOWN")
        values.append({
            "event_id": event.id,
            "mission_id": event.mission_id,
            "normalized_status": normalized,
            "raw_status": event.payload.get("raw_status"),
            "eta_text": event.payload.get("eta_text"),
            "destination": quote.destination if quote else None,
            "robot_action": (
                "QUEUE_DRY_RUN_DISPATCH"
                if normalized == "ARRIVED_AT_DELIVERY_LOCATION"
                else "WAIT"
            ),
            "observed_at": event.created_at,
        })
    return {
        "schema_version": 1,
        "motion_enabled": False,
        "next_cursor": events[-1].id if events else after,
        "events": values,
    }


@app.post("/api/robot/v1/ack", response_model=MissionView, dependencies=[Depends(require_robot)])
async def robot_ack(body: RobotPollAck, session: Session = Depends(get_session)):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    return mission_view(session, acknowledge_robot_job(session, body))


@app.post("/api/robot/v1/heartbeat", dependencies=[Depends(require_robot)])
async def robot_heartbeat(body: RobotHeartbeat, session: Session = Depends(get_session)):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    node = record_robot_heartbeat(session, body)
    return {
        "schema_version": 1,
        "robot_id": node.id,
        "accepted": True,
        "motion_enabled": False,
        "server_time": utcnow(),
    }


@app.get("/api/robot/v1/status", dependencies=[Depends(require_admin)])
async def robot_status(session: Session = Depends(get_session)):
    node = latest_robot_node(session)
    if not node:
        return {
            "schema_version": 1,
            "connected": False,
            "motion_enabled": False,
            "robot": None,
        }
    seen = node.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    stale = (utcnow() - seen).total_seconds() > robot_heartbeat_stale_seconds()
    return {
        "schema_version": 1,
        "connected": not stale,
        "motion_enabled": False,
        "robot": {
            "robot_id": node.id,
            "agent_version": node.agent_version,
            "mode": node.mode,
            "status": node.status,
            "subsystems": node.subsystems,
            "last_error": node.last_error,
            "last_seen_at": node.last_seen_at,
        },
    }


@app.post(
    "/api/robot/v1/lifecycle",
    response_model=MissionView,
    dependencies=[Depends(require_robot)],
)
async def robot_lifecycle(
    body: RobotLifecycleReport,
    session: Session = Depends(get_session),
):
    if robot_mode() != "pi_poll":
        raise HTTPException(status_code=409, detail="outbound Pi polling is not enabled")
    return mission_view(session, record_robot_lifecycle_report(session, body))


@app.post("/api/integrations/telegram/webhook", status_code=202)
async def telegram_webhook(
    body: dict,
    x_telegram_secret: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
    session: Session = Depends(get_session),
) -> dict:
    try:
        expected = telegram_webhook_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Telegram webhook is not configured") from exc
    if not x_telegram_secret or not hmac.compare_digest(x_telegram_secret, expected):
        raise HTTPException(status_code=401, detail="invalid Telegram webhook credential")
    try:
        inbound = parse_telegram_update(body)
    except TelegramError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if inbound is None:
        return {"accepted": False, "reason": "unsupported_update"}
    if not verify_telegram_owner(inbound.user_id) or inbound.chat_id != inbound.user_id:
        return {"accepted": False, "reason": "owner_not_allowed"}
    inserted = enqueue_telegram_update(session, inbound)
    return {"accepted": True, "duplicate": not inserted}


async def start_live_prava_approval(session: Session, mission: Mission, command_id: str) -> Mission:
    if payment_mode() != "prava" or mission.phase != "AWAITING_OWNER_APPROVAL":
        return mission
    quote = Quote.model_validate(mission.quote)
    try:
        prava = PravaClient()
        prava_session = await prava.create_session(quote)
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
            "environment": prava.environment,
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
            resolved_quote = await swiggy_quote_with_transport_retry(intent)
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


@app.get("/api/missions/active", response_model=MissionView, dependencies=[Depends(require_admin)])
async def get_active_mission(session: Session = Depends(get_session)):
    mission = session.scalar(select(Mission).where(Mission.active_slot == "active"))
    if not mission:
        raise HTTPException(status_code=404, detail="no active mission")
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
            resolved_quote = await swiggy_quote_with_transport_retry(intent)
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
        existing = prava_session_event(session, mission_id)
        if not existing:
            try:
                prava = PravaClient()
                prava_session = await prava.create_session(current_quote)
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
                    "environment": prava.environment,
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
    event = prava_session_event(session, mission_id)
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
        if not purchase_enabled():
            raise HTTPException(
                status_code=409,
                detail="external merchant checkout is disabled by MAX_PURCHASE_ENABLED",
            )
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
        session_event = prava_session_event(session, mission_id)
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
        event = prava_session_event(session, mission_id)
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
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    existing = session.scalar(select(Event).where(
        Event.mission_id == mission_id,
        Event.command_id == body.command_id,
    ))
    revocation: str | None = None
    if not existing and mission.phase in {"PAYMENT_APPROVAL_REQUIRED", "PAYMENT_PERMISSION_READY"}:
        prava_event = prava_session_event(session, mission_id)
        if prava_event:
            try:
                await PravaClient().revoke_session(prava_event.payload["session_id"])
                revocation = "confirmed"
            except (IntegrationError, KeyError):
                # Local cancellation must still win so no worker can use a
                # credential even when the external revocation is unavailable.
                revocation = "failed"
    return mission_view(
        session,
        cancel(
            session,
            mission_id,
            body.expected_version,
            body.command_id,
            prava_revocation=revocation,
        ),
    )


@app.post("/api/missions/{mission_id}/commands/close-unresolved", response_model=MissionView, dependencies=[Depends(require_admin)])
async def close_unresolved_mission(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, close_unresolved(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/start-staged", response_model=MissionView, dependencies=[Depends(require_admin)])
async def start_staged(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, start_staged_fulfilment(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/package-ready", response_model=MissionView, dependencies=[Depends(require_admin)])
async def mark_package_ready(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, package_ready(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/run-robot", response_model=MissionView, dependencies=[Depends(require_admin)])
async def run_robot(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    if robot_mode() == "pi_poll":
        mission = session.get(Mission, mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        stage_robot_job(
            session,
            mission,
            expected_version=body.expected_version,
            command_id=body.command_id,
            dry_run=robot_dry_run(),
        )
        return mission_view(session, mission)
    if robot_mode() == "pi":
        mission = session.get(Mission, mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        if (
            mission.version != body.expected_version
            or mission.environment != "staged_demo"
            or mission.phase != "READY_TO_DISPATCH"
            or mission.fulfilment_status not in {"PACKAGE_READY", "ROBOT_DRY_RUN_ACKNOWLEDGED"}
        ):
            raise HTTPException(status_code=409, detail="robot dispatch is blocked until staged PACKAGE_READY")
        quote = Quote.model_validate(mission.quote)
        dry_run = robot_dry_run()
        try:
            ack = await RobotClient().dispatch(
                mission_id=mission_id,
                command_id=body.command_id,
                destination=quote.destination,
                dry_run=dry_run,
            )
        except IntegrationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return mission_view(
            session,
            record_robot_dispatch_acknowledgement(
                session,
                mission_id,
                body.expected_version,
                body.command_id,
                dry_run=ack.dry_run,
                motion_started=ack.motion_started,
            ),
        )
    return mission_view(session, run_robot_simulation(session, mission_id, body.expected_version, body.command_id))
