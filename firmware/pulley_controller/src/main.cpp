#include <Arduino.h>

#include <cstring>

#include "pulley_state.hpp"

#ifndef PULLEY_RPWM_PIN
#define PULLEY_RPWM_PIN 25
#endif
#ifndef PULLEY_LPWM_PIN
#define PULLEY_LPWM_PIN 26
#endif
#ifndef PULLEY_REN_PIN
#define PULLEY_REN_PIN 27
#endif
#ifndef PULLEY_LEN_PIN
#define PULLEY_LEN_PIN 14
#endif
#ifndef PULLEY_UPPER_LIMIT_PIN
#define PULLEY_UPPER_LIMIT_PIN 32
#endif
#ifndef PULLEY_LOWER_LIMIT_PIN
#define PULLEY_LOWER_LIMIT_PIN 33
#endif
#ifndef PULLEY_ESTOP_PIN
#define PULLEY_ESTOP_PIN 23
#endif
#ifndef PULLEY_PWM_DUTY
#define PULLEY_PWM_DUTY 90
#endif
#ifndef PULLEY_PWM_FREQUENCY
#define PULLEY_PWM_FREQUENCY 1000
#endif
#ifndef PULLEY_MAX_TRAVEL_MS
#define PULLEY_MAX_TRAVEL_MS 15000
#endif
#ifndef PULLEY_KEEPALIVE_TIMEOUT_MS
#define PULLEY_KEEPALIVE_TIMEOUT_MS 1000
#endif
#ifndef PULLEY_DIRECTION_DEADTIME_MS
#define PULLEY_DIRECTION_DEADTIME_MS 50
#endif
#ifndef PULLEY_DIRECTION_INVERTED
#define PULLEY_DIRECTION_INVERTED 0
#endif

static_assert(PULLEY_PWM_DUTY > 0 && PULLEY_PWM_DUTY <= 255,
              "PULLEY_PWM_DUTY must be between 1 and 255");
static_assert(PULLEY_MAX_TRAVEL_MS >= 1000,
              "PULLEY_MAX_TRAVEL_MS must be at least one second");
static_assert(PULLEY_KEEPALIVE_TIMEOUT_MS >= 250,
              "PULLEY_KEEPALIVE_TIMEOUT_MS must be at least 250 ms");

namespace {

constexpr std::uint8_t kRpwmChannel = 0;
constexpr std::uint8_t kLpwmChannel = 1;
constexpr std::size_t kLineSize = 96;

max_pulley::PulleyStateMachine controller(PULLEY_MAX_TRAVEL_MS,
                                      PULLEY_KEEPALIVE_TIMEOUT_MS);
max_pulley::Direction applied_direction = max_pulley::Direction::None;
char line_buffer[kLineSize] = {};
std::size_t line_length = 0;
bool line_overflow = false;

const char* directionName(max_pulley::Direction direction) {
  switch (direction) {
    case max_pulley::Direction::Up:
      return "UP";
    case max_pulley::Direction::Down:
      return "DOWN";
    default:
      return "NONE";
  }
}

const char* stateName(max_pulley::State state) {
  switch (state) {
    case max_pulley::State::MovingUp:
      return "MOVING_UP";
    case max_pulley::State::MovingDown:
      return "MOVING_DOWN";
    case max_pulley::State::Fault:
      return "FAULT";
    default:
      return "IDLE";
  }
}

max_pulley::Inputs readInputs() {
  // All three safety inputs are normally closed to GND. HIGH therefore means
  // endpoint reached, switch opened, or wire disconnected.
  return {
      digitalRead(PULLEY_UPPER_LIMIT_PIN) == HIGH,
      digitalRead(PULLEY_LOWER_LIMIT_PIN) == HIGH,
      digitalRead(PULLEY_ESTOP_PIN) == HIGH,
  };
}

void stopMotor() {
  ledcWrite(kRpwmChannel, 0);
  ledcWrite(kLpwmChannel, 0);
  digitalWrite(PULLEY_REN_PIN, LOW);
  digitalWrite(PULLEY_LEN_PIN, LOW);
  applied_direction = max_pulley::Direction::None;
}

void applyMotor(max_pulley::Direction requested) {
  if (requested == applied_direction) return;
  stopMotor();
  if (requested == max_pulley::Direction::None) return;
  delay(PULLEY_DIRECTION_DEADTIME_MS);
  digitalWrite(PULLEY_REN_PIN, HIGH);
  digitalWrite(PULLEY_LEN_PIN, HIGH);
  bool up = requested == max_pulley::Direction::Up;
  if (PULLEY_DIRECTION_INVERTED) up = !up;
  ledcWrite(up ? kRpwmChannel : kLpwmChannel, PULLEY_PWM_DUTY);
  applied_direction = requested;
}

void emit(const max_pulley::Event& event) {
  if (event.reply == max_pulley::Reply::None) return;
  const char* request_id = event.request_id[0] ? event.request_id : "-";
  switch (event.reply) {
    case max_pulley::Reply::Ack:
      Serial.printf("ACK %s %s %s\n", request_id,
                    directionName(event.direction), event.reason);
      break;
    case max_pulley::Reply::Done:
      Serial.printf("DONE %s %s %s\n", request_id,
                    directionName(event.direction), event.reason);
      break;
    case max_pulley::Reply::Stopped:
      Serial.printf("STOPPED %s %s\n", request_id, event.reason);
      break;
    case max_pulley::Reply::Error:
      Serial.printf("%s %s %s\n",
                    controller.state() == max_pulley::State::Fault ? "FAULT"
                                                                 : "ERR",
                    request_id, event.reason);
      break;
    default:
      break;
  }
}

void emitStatus() {
  max_pulley::Inputs inputs = readInputs();
  const char* request_id = controller.activeRequestId()[0]
                               ? controller.activeRequestId()
                               : "-";
  const char* fault = controller.faultReason()[0] ? controller.faultReason() : "-";
  Serial.printf(
      "STATE %s ACTIVE %s DIRECTION %s UPPER %u LOWER %u ESTOP %u FAULT %s\n",
      stateName(controller.state()), request_id,
      directionName(controller.motorDirection()),
      static_cast<unsigned>(inputs.upper_limit),
      static_cast<unsigned>(inputs.lower_limit),
      static_cast<unsigned>(inputs.emergency_stop), fault);
}

max_pulley::Direction parseDirection(const char* value) {
  if (value && std::strcmp(value, "UP") == 0) return max_pulley::Direction::Up;
  if (value && std::strcmp(value, "DOWN") == 0) {
    return max_pulley::Direction::Down;
  }
  return max_pulley::Direction::None;
}

char* nextToken(char** context) { return ::strtok_r(nullptr, " ", context); }

void rejectCommand() { Serial.println("ERR - BAD_COMMAND"); }

void handleLine(char* line) {
  max_pulley::Event safety = controller.tick(millis(), readInputs());
  applyMotor(controller.motorDirection());
  emit(safety);
  if (safety.reply == max_pulley::Reply::Error) return;

  char* context = nullptr;
  char* command = ::strtok_r(line, " ", &context);
  if (!command) return;

  if (std::strcmp(command, "PING") == 0) {
    if (nextToken(&context)) {
      rejectCommand();
      return;
    }
    Serial.println("PONG 1");
    return;
  }
  if (std::strcmp(command, "STATUS") == 0) {
    if (nextToken(&context)) {
      rejectCommand();
      return;
    }
    emitStatus();
    return;
  }
  if (std::strcmp(command, "RESET") == 0) {
    if (nextToken(&context)) {
      rejectCommand();
      return;
    }
    max_pulley::Event event = controller.reset(readInputs());
    applyMotor(controller.motorDirection());
    emit(event);
    return;
  }

  char* request_id = nextToken(&context);
  if (std::strcmp(command, "MOVE") == 0) {
    char* direction = nextToken(&context);
    if (!request_id || !direction || nextToken(&context)) {
      rejectCommand();
      return;
    }
    max_pulley::Event event = controller.move(
        request_id, parseDirection(direction), millis(), readInputs());
    applyMotor(controller.motorDirection());
    emit(event);
    return;
  }
  if (std::strcmp(command, "KEEPALIVE") == 0) {
    if (!request_id || nextToken(&context)) {
      rejectCommand();
      return;
    }
    emit(controller.keepalive(request_id, millis()));
    return;
  }
  if (std::strcmp(command, "STOP") == 0) {
    if (!request_id || nextToken(&context)) {
      rejectCommand();
      return;
    }
    max_pulley::Event event = controller.stop(request_id);
    applyMotor(controller.motorDirection());
    emit(event);
    return;
  }
  rejectCommand();
}

void readSerial() {
  while (Serial.available()) {
    char character = static_cast<char>(Serial.read());
    if (character == '\r') continue;
    if (character == '\n') {
      if (!line_overflow) {
        line_buffer[line_length] = '\0';
        handleLine(line_buffer);
      }
      line_length = 0;
      line_overflow = false;
      continue;
    }
    if (line_overflow) continue;
    if (line_length + 1 >= kLineSize) {
      line_overflow = true;
      max_pulley::Event event = controller.forceFault("PROTOCOL_OVERFLOW");
      applyMotor(controller.motorDirection());
      emit(event);
      continue;
    }
    line_buffer[line_length++] = character;
  }
}

bool pinsAreDistinct() {
  const int pins[] = {
      PULLEY_RPWM_PIN,       PULLEY_LPWM_PIN,        PULLEY_REN_PIN,
      PULLEY_LEN_PIN,        PULLEY_UPPER_LIMIT_PIN, PULLEY_LOWER_LIMIT_PIN,
      PULLEY_ESTOP_PIN,
  };
  for (std::size_t left = 0; left < sizeof(pins) / sizeof(pins[0]); ++left) {
    for (std::size_t right = left + 1; right < sizeof(pins) / sizeof(pins[0]);
         ++right) {
      if (pins[left] == pins[right]) return false;
    }
  }
  return true;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  if (!pinsAreDistinct()) {
    Serial.println("FAULT - GPIO_CONFLICT");
    while (true) delay(1000);
  }
  pinMode(PULLEY_REN_PIN, OUTPUT);
  pinMode(PULLEY_LEN_PIN, OUTPUT);
  digitalWrite(PULLEY_REN_PIN, LOW);
  digitalWrite(PULLEY_LEN_PIN, LOW);
  pinMode(PULLEY_UPPER_LIMIT_PIN, INPUT_PULLUP);
  pinMode(PULLEY_LOWER_LIMIT_PIN, INPUT_PULLUP);
  pinMode(PULLEY_ESTOP_PIN, INPUT_PULLUP);

  ledcSetup(kRpwmChannel, PULLEY_PWM_FREQUENCY, 8);
  ledcSetup(kLpwmChannel, PULLEY_PWM_FREQUENCY, 8);
  ledcAttachPin(PULLEY_RPWM_PIN, kRpwmChannel);
  ledcAttachPin(PULLEY_LPWM_PIN, kLpwmChannel);
  stopMotor();

  emit(controller.tick(millis(), readInputs()));
  Serial.println("BOOT MAX_PULLEY 1");
  emitStatus();
}

void loop() {
  readSerial();
  max_pulley::Event event = controller.tick(millis(), readInputs());
  applyMotor(controller.motorDirection());
  emit(event);
  delay(1);
}
