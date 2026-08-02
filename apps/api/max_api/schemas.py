from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Environment(StrEnum):
    LOCAL = "local"
    SANDBOX = "sandbox"
    STAGED = "staged_demo"
    PRODUCTION = "production"


class Phase(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    AWAITING_OWNER_APPROVAL = "AWAITING_OWNER_APPROVAL"
    PAYMENT_APPROVAL_REQUIRED = "PAYMENT_APPROVAL_REQUIRED"
    PAYMENT_PERMISSION_READY = "PAYMENT_PERMISSION_READY"
    MERCHANT_CHECKOUT_IN_PROGRESS = "MERCHANT_CHECKOUT_IN_PROGRESS"
    PAYMENT_RESULT_REPORT_REQUIRED = "PAYMENT_RESULT_REPORT_REQUIRED"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    CHECKOUT_OUTCOME_UNKNOWN = "CHECKOUT_OUTCOME_UNKNOWN"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    READY_TO_DISPATCH = "READY_TO_DISPATCH"
    EN_ROUTE_TO_PICKUP = "EN_ROUTE_TO_PICKUP"
    AT_PICKUP = "AT_PICKUP"
    ITEM_SECURED = "ITEM_SECURED"
    RETURNING = "RETURNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BudgetMeaning(StrEnum):
    EXACT = "exact"
    MAXIMUM = "maximum"
    MINIMUM = "minimum"
    RANGE = "range"


class ShoppingIntent(BaseModel):
    item: str | None = Field(default=None, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=20)
    budget_meaning: BudgetMeaning | None = None
    budget_min_minor: int | None = Field(
        default=None, ge=0, description="Lower budget bound; null when budget_meaning is maximum."
    )
    budget_max_minor: int | None = Field(
        default=None, ge=0, description="Upper budget bound; null when budget_meaning is minimum."
    )
    currency: Literal["INR"] = "INR"
    destination: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_budget_shape(self):
        low, high = self.budget_min_minor, self.budget_max_minor
        if self.budget_meaning is None and (low is not None or high is not None):
            raise ValueError("budget bounds require a budget meaning")
        if self.budget_meaning == BudgetMeaning.EXACT and (low is None or high is None or low != high):
            raise ValueError("exact budget requires equal minimum and maximum")
        if self.budget_meaning == BudgetMeaning.MAXIMUM and (low is not None or high is None):
            raise ValueError("maximum budget requires only a maximum")
        if self.budget_meaning == BudgetMeaning.MINIMUM and (low is None or high is not None):
            raise ValueError("minimum budget requires only a minimum")
        if self.budget_meaning == BudgetMeaning.RANGE and (low is None or high is None or low > high):
            raise ValueError("range budget requires an ordered minimum and maximum")
        return self


class Quote(BaseModel):
    revision: int = Field(ge=1)
    merchant: str
    product_name: str
    variant_id: str
    quantity: int = Field(ge=1)
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern="^[A-Z]{3}$")
    destination: str
    environment: Environment
    expires_at: datetime
    line_items: list["QuoteLine"] = Field(default_factory=list)


class QuoteLine(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    unit_price_minor: int = Field(ge=0)
    quantity: int = Field(ge=1, le=100)


class ProviderResult(BaseModel):
    provider: str
    operation: str
    environment: Environment
    status: Literal["APPROVED", "DECLINED", "UNKNOWN", "TIMED_OUT", "NOT_SUBMITTED"]
    terminal: bool
    redacted_reference: str | None = None
    error_class: str | None = None
    retry_eligible: bool = False


class MissionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MissionReply(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=0)
    command_id: str = Field(min_length=8, max_length=48)


class CommandBase(BaseModel):
    expected_version: int = Field(ge=0)
    command_id: str = Field(min_length=8, max_length=48)


class ApproveCommand(CommandBase):
    quote_hash: str = Field(min_length=64, max_length=64)
    simulated_outcome: str = Field(default="decline", pattern="^(decline|unknown|timeout)$")


class RequoteCommand(CommandBase):
    amount_minor: int = Field(ge=1)


class RobotPollAck(BaseModel):
    mission_id: str = Field(min_length=8, max_length=64)
    command_id: str = Field(min_length=8, max_length=64)
    status: Literal["ACKNOWLEDGED"]
    dry_run: bool
    motion_started: bool


class RobotHeartbeat(BaseModel):
    robot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    agent_version: str = Field(min_length=1, max_length=32)
    mode: Literal["dry_run", "physical"]
    status: Literal["IDLE", "READY", "BUSY", "DEGRADED", "EMERGENCY_STOP"]
    subsystems: dict[
        str,
        Literal["healthy", "present", "degraded", "unavailable", "disabled"],
    ]
    last_error: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def required_subsystems(self):
        required = (
            {"camera", "gps", "imu", "audio", "motors", "emergency_stop"}
            if self.mode == "dry_run"
            else {
                "camera",
                "odometry",
                "localization",
                "obstruction",
                "motors",
                "controller",
                "emergency_stop",
            }
        )
        if not required.issubset(self.subsystems):
            raise ValueError(f"{self.mode} heartbeat is missing required subsystems")
        return self


class RobotLifecycleReport(BaseModel):
    mission_id: str = Field(min_length=8, max_length=64)
    command_id: str = Field(min_length=8, max_length=64)
    event_id: str = Field(min_length=8, max_length=64)
    expected_version: int = Field(ge=0)
    stage: Literal["AT_PICKUP", "ITEM_SECURED", "RETURNING", "COMPLETED", "CANCELLED"]
    dry_run: bool
    motion_started: bool


class BindOrderCommand(CommandBase):
    order_id: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_type: str
    component: str
    provider: str | None
    human_intervened: bool
    environment: str
    phase_before: str
    phase_after: str
    payload: dict
    created_at: datetime


class PublicEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_type: str
    component: str
    environment: str
    phase_after: str
    created_at: datetime


class PublicMissionView(BaseModel):
    id: str
    phase: str
    environment: str
    product_name: str | None
    merchant: str | None
    quantity: int | None
    amount_minor: int | None
    currency: str | None
    commerce_status: str
    payment_status: str
    checkout_status: str
    fulfilment_status: str
    notification_status: str
    delivery_status: str | None
    robot_status: str | None
    created_at: datetime
    updated_at: datetime
    events: list[PublicEventView]


class PublicRobotView(BaseModel):
    connected: bool
    status: str
    camera: str
    gps: str
    last_seen_at: datetime | None


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    operation: str
    environment: str
    status: str
    terminal: bool | None
    redacted_reference: str | None
    error_class: str | None
    retry_eligible: bool
    started_at: datetime
    finished_at: datetime | None


class ApprovalView(BaseModel):
    status: str
    quote_hash: str | None


class CheckoutView(BaseModel):
    status: str
    latest_attempt: AttemptView | None


class RobotJobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    command_id: str
    expected_version: int
    destination: str
    dry_run: bool
    trigger_source: str
    trigger_status: str
    status: str
    created_at: datetime
    delivered_at: datetime | None
    acknowledged_at: datetime | None


class PaymentActionView(BaseModel):
    provider: Literal["PRAVA"]
    environment: Literal["sandbox", "production"]
    session_id: str
    order_id: str
    approval_url: str
    expires_at: datetime


class DeliveryView(BaseModel):
    order_reference: str | None = None
    status: str = "NOT_TRACKING"
    eta_at: datetime | None = None
    dispatch_at: datetime | None = None
    last_checked_at: datetime | None = None
    armed: bool = False
    robot_status: str = "NOT_STARTED"
    alert: str | None = None


class MissionView(BaseModel):
    id: str
    parent_mission_id: str | None
    version: int
    phase: str
    environment: str
    agent_mode: str
    request_text: str
    intent: ShoppingIntent | None
    clarification_question: str | None
    quote: Quote | None
    quote_hash: str | None
    commerce_status: str
    payment_status: str
    checkout_status: str
    fulfilment_status: str
    notification_status: str
    created_at: datetime
    updated_at: datetime
    events: list[EventView]
    attempts: list[AttemptView]
    approval: ApprovalView
    checkout: CheckoutView
    payment_action: PaymentActionView | None = None
    robot_job: RobotJobView | None = None
    source_order_events: list[EventView] = Field(default_factory=list)
    delivery: DeliveryView | None = None
