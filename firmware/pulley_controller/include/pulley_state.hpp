#pragma once

#include <cctype>
#include <cstdint>
#include <cstring>

namespace max_pulley {

constexpr std::size_t kRequestIdSize = 25;

enum class Direction { None, Up, Down };
enum class State { Idle, MovingUp, MovingDown, Fault };
enum class Reply { None, Ack, Done, Stopped, Error };

struct Inputs {
  bool upper_limit;
  bool lower_limit;
  bool emergency_stop;
};

struct Event {
  Reply reply = Reply::None;
  Direction direction = Direction::None;
  char request_id[kRequestIdSize] = {};
  const char* reason = "";
};

class PulleyStateMachine {
 public:
  PulleyStateMachine(std::uint32_t max_travel_ms,
                     std::uint32_t keepalive_timeout_ms)
      : max_travel_ms_(max_travel_ms),
        keepalive_timeout_ms_(keepalive_timeout_ms) {}

  Event move(const char* request_id, Direction direction, std::uint32_t now,
             Inputs inputs) {
    Event safety = tick(now, inputs);
    if (safety.reply != Reply::None) return safety;
    if (!validRequestId(request_id) || direction == Direction::None) {
      return event(Reply::Error, direction, request_id, "BAD_COMMAND");
    }
    if (state_ == State::Fault) {
      return event(Reply::Error, direction, request_id, fault_reason_);
    }
    if (moving()) {
      if (std::strcmp(active_request_id_, request_id) == 0 &&
          active_direction_ == direction) {
        last_keepalive_at_ = now;
        return event(Reply::Ack, direction, request_id, "MOVING");
      }
      return event(Reply::Error, direction, request_id, "BUSY");
    }
    if (std::strcmp(last_request_id_, request_id) == 0) {
      if (last_direction_ != direction) {
        return event(Reply::Error, direction, request_id, "ID_REUSED");
      }
      return event(last_reply_, direction, request_id, last_reason_);
    }
    if ((direction == Direction::Up && inputs.upper_limit) ||
        (direction == Direction::Down && inputs.lower_limit)) {
      remember(request_id, direction, Reply::Done, "AT_LIMIT");
      return event(Reply::Done, direction, request_id, "AT_LIMIT");
    }

    copyId(active_request_id_, request_id);
    active_direction_ = direction;
    state_ = direction == Direction::Up ? State::MovingUp : State::MovingDown;
    started_at_ = now;
    last_keepalive_at_ = now;
    return event(Reply::Ack, direction, request_id, "MOVING");
  }

  Event keepalive(const char* request_id, std::uint32_t now) {
    if (!moving()) {
      return event(Reply::Error, Direction::None, request_id, "NOT_MOVING");
    }
    if (!validRequestId(request_id) ||
        std::strcmp(active_request_id_, request_id) != 0) {
      return event(Reply::Error, Direction::None, request_id, "ID_MISMATCH");
    }
    last_keepalive_at_ = now;
    return event(Reply::Ack, active_direction_, request_id, "KEEPALIVE");
  }

  Event stop(const char* request_id) {
    if (!validRequestId(request_id)) {
      return event(Reply::Error, Direction::None, request_id, "BAD_COMMAND");
    }
    if (!moving()) {
      if (std::strcmp(last_request_id_, request_id) == 0 &&
          last_reply_ == Reply::Stopped) {
        return event(Reply::Stopped, last_direction_, request_id, "STOPPED");
      }
      return event(Reply::Error, Direction::None, request_id, "NOT_MOVING");
    }
    if (std::strcmp(active_request_id_, request_id) != 0) {
      return event(Reply::Error, Direction::None, request_id, "ID_MISMATCH");
    }
    return finish(Reply::Stopped, "STOPPED");
  }

  Event reset(Inputs inputs) {
    if (moving()) {
      return event(Reply::Error, active_direction_, active_request_id_, "BUSY");
    }
    if (inputs.emergency_stop) {
      return event(Reply::Error, Direction::None, "", "ESTOP");
    }
    if (inputs.upper_limit && inputs.lower_limit) {
      return event(Reply::Error, Direction::None, "", "LIMITS_INVALID");
    }
    state_ = State::Idle;
    active_direction_ = Direction::None;
    active_request_id_[0] = '\0';
    last_request_id_[0] = '\0';
    last_direction_ = Direction::None;
    last_reply_ = Reply::None;
    last_reason_ = "";
    fault_reason_ = "";
    return event(Reply::Ack, Direction::None, "", "RESET");
  }

  Event tick(std::uint32_t now, Inputs inputs) {
    if (state_ == State::Fault) return {};
    if (inputs.emergency_stop) return forceFault("ESTOP");
    if (inputs.upper_limit && inputs.lower_limit) {
      return forceFault("LIMITS_INVALID");
    }
    if (!moving()) return {};
    if ((active_direction_ == Direction::Up && inputs.upper_limit) ||
        (active_direction_ == Direction::Down && inputs.lower_limit)) {
      return finish(Reply::Done, "AT_LIMIT");
    }
    if (elapsed(now, started_at_) > max_travel_ms_) {
      return forceFault("TRAVEL_TIMEOUT");
    }
    if (elapsed(now, last_keepalive_at_) > keepalive_timeout_ms_) {
      return forceFault("KEEPALIVE_TIMEOUT");
    }
    return {};
  }

  Event forceFault(const char* reason) {
    Direction direction = active_direction_;
    char request_id[kRequestIdSize] = {};
    copyId(request_id, active_request_id_);
    if (request_id[0] != '\0') {
      remember(request_id, direction, Reply::Error, reason);
    }
    state_ = State::Fault;
    active_direction_ = Direction::None;
    active_request_id_[0] = '\0';
    fault_reason_ = reason;
    return event(Reply::Error, direction, request_id, reason);
  }

  State state() const { return state_; }
  Direction motorDirection() const { return active_direction_; }
  const char* activeRequestId() const { return active_request_id_; }
  const char* faultReason() const { return fault_reason_; }

 private:
  static std::uint32_t elapsed(std::uint32_t now, std::uint32_t then) {
    return now - then;
  }

  static bool validRequestId(const char* value) {
    if (value == nullptr) return false;
    std::size_t length = std::strlen(value);
    if (length == 0 || length >= kRequestIdSize) return false;
    for (std::size_t index = 0; index < length; ++index) {
      unsigned char character = static_cast<unsigned char>(value[index]);
      if (!std::isalnum(character) && character != '-' && character != '_') {
        return false;
      }
    }
    return true;
  }

  static void copyId(char* target, const char* source) {
    if (source == nullptr) {
      target[0] = '\0';
      return;
    }
    std::strncpy(target, source, kRequestIdSize - 1);
    target[kRequestIdSize - 1] = '\0';
  }

  static Event event(Reply reply, Direction direction, const char* request_id,
                     const char* reason) {
    Event value;
    value.reply = reply;
    value.direction = direction;
    copyId(value.request_id, request_id);
    value.reason = reason;
    return value;
  }

  bool moving() const {
    return state_ == State::MovingUp || state_ == State::MovingDown;
  }

  void remember(const char* request_id, Direction direction, Reply reply,
                const char* reason) {
    copyId(last_request_id_, request_id);
    last_direction_ = direction;
    last_reply_ = reply;
    last_reason_ = reason;
  }

  Event finish(Reply reply, const char* reason) {
    Event value = event(reply, active_direction_, active_request_id_, reason);
    remember(active_request_id_, active_direction_, reply, reason);
    state_ = State::Idle;
    active_direction_ = Direction::None;
    active_request_id_[0] = '\0';
    return value;
  }

  const std::uint32_t max_travel_ms_;
  const std::uint32_t keepalive_timeout_ms_;
  State state_ = State::Idle;
  Direction active_direction_ = Direction::None;
  char active_request_id_[kRequestIdSize] = {};
  std::uint32_t started_at_ = 0;
  std::uint32_t last_keepalive_at_ = 0;
  char last_request_id_[kRequestIdSize] = {};
  Direction last_direction_ = Direction::None;
  Reply last_reply_ = Reply::None;
  const char* last_reason_ = "";
  const char* fault_reason_ = "";
};

}  // namespace max_pulley
