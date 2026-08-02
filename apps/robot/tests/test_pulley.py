import os
import unittest

from max_robot.pulley import PulleyClient


class PulleyClientTests(unittest.TestCase):
    def test_handshake_move_keepalive_and_limit_completion(self) -> None:
        master, slave = os.openpty()
        device = os.ttyname(slave)
        os.close(slave)
        client = PulleyClient(device)
        try:
            client.poll(1.0)
            self.assertEqual(os.read(master, 64), b"PING\n")
            os.write(master, b"PONG 1\n")
            client.poll(1.1)
            self.assertTrue(client.ready)

            client.start("trip-42", "DOWN", 1.2)
            self.assertEqual(os.read(master, 64), b"MOVE trip-42 DOWN\n")
            os.write(master, b"ACK trip-42 DOWN MOVING\n")
            client.poll(1.3)
            client.poll(1.6)
            self.assertEqual(os.read(master, 64), b"KEEPALIVE trip-42\n")

            os.write(master, b"DONE trip-42 DOWN AT_LIMIT\n")
            client.poll(1.7)
            self.assertEqual(client.completed_request_id, "trip-42")
            self.assertIsNone(client.fault_reason)
        finally:
            client.close()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
