#include <cassert>
#include <cstring>

#include "pulley_state.hpp"

using max_pulley::Direction;
using max_pulley::Inputs;
using max_pulley::PulleyStateMachine;
using max_pulley::Reply;
using max_pulley::State;

int main() {
  PulleyStateMachine pulley(10000, 1000);
  Inputs at_bottom{false, true, false};
  Inputs travelling{false, false, false};
  Inputs at_top{true, false, false};

  auto started = pulley.move("trip_up_1", Direction::Up, 100, at_bottom);
  assert(started.reply == Reply::Ack);
  assert(pulley.motorDirection() == Direction::Up);
  assert(pulley.keepalive("trip_up_1", 500).reply == Reply::Ack);

  auto arrived = pulley.tick(900, at_top);
  assert(arrived.reply == Reply::Done);
  assert(pulley.state() == State::Idle);
  assert(pulley.motorDirection() == Direction::None);
  assert(pulley.move("trip_up_1", Direction::Up, 950, at_top).reply == Reply::Done);

  assert(pulley.move("trip_down_2", Direction::Down, 1000, at_top).reply == Reply::Ack);
  auto watchdog = pulley.tick(2001, travelling);
  assert(watchdog.reply == Reply::Error);
  assert(std::strcmp(watchdog.reason, "KEEPALIVE_TIMEOUT") == 0);
  assert(pulley.state() == State::Fault);
  assert(pulley.motorDirection() == Direction::None);

  assert(pulley.reset(at_top).reply == Reply::Ack);
  assert(pulley.state() == State::Idle);
  assert(pulley.reset({false, false, true}).reply == Reply::Error);
  return 0;
}
