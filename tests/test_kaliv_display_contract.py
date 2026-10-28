"""Kaliv display protocol v1, sender side (protocol/kaliv-display-v1.json).

tests/mic-probe-kaliv-contract.cjs proves the receiver behaves as the contract
says. This file proves the Python senders agree with the same file: the same
namespace and text limit, only contract states, and that CastSender accepts
exactly the ACKs the contract (and so the receiver) produces. No Nest Hub or
network is involved.
"""
import ast
import json
from pathlib import Path
import queue
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from kalivhub_mirror_server import CastSender, MAX_DISPLAY_UNITS, NAMESPACE, utf16_units  # noqa: E402

CONTRACT = json.loads((ROOT / "protocol" / "kaliv-display-v1.json").read_text(encoding="utf-8"))
SENDERS = ("kalivhub_mirror_server.py", "modelrig_cast_bridge.py", "remote_mic_probe.py")


def contract_ack(command):
    """What a contract-conforming receiver answers to ``command``."""
    spec = CONTRACT["commands"][command["type"]]
    ack = {"type": spec["ack"], "request_id": command["request_id"]}
    if command["type"] == "SET_STATE":
        ok = command.get("state") in CONTRACT["states"]
        ack.update(result="updated" if ok else "invalid", **({"state": command["state"]} if ok else {}))
    elif command["type"] == "SHOW_MESSAGE":
        ok = isinstance(command.get("text"), str) and utf16_units(command["text"]) <= CONTRACT["max_text_utf16_units"]
        ack.update(result="shown", length=utf16_units(command["text"])) if ok else ack.update(result="invalid")
    elif command["type"] == "CLEAR_MESSAGE":
        ack.update(result="cleared")
    return ack


class FakeController:
    def __init__(self, sender):
        self.sender, self.sent = sender, []

    def send_message(self, message):
        self.sent.append(message)
        self.sender.acks.put_nowait(contract_ack(message))


def offline_sender():
    sender = CastSender("192.168.1.50", "TESTAPP")
    sender.connect = lambda: None  # no pychromecast, no network
    sender.controller = FakeController(sender)
    return sender


class TestConstantsMatchContract(unittest.TestCase):
    def test_namespace_and_limit(self):
        self.assertEqual(NAMESPACE, CONTRACT["namespace"])
        self.assertEqual(MAX_DISPLAY_UNITS, CONTRACT["max_text_utf16_units"])

    def test_every_sender_uses_the_contract_namespace(self):
        for name in SENDERS:
            tree = ast.parse((ROOT / "tools" / name).read_text(encoding="utf-8"))
            namespaces = {node.value for node in ast.walk(tree)
                          if isinstance(node, ast.Constant) and isinstance(node.value, str)
                          and node.value.startswith("urn:x-cast:")}
            self.assertEqual(namespaces, {CONTRACT["namespace"]}, name)

    def test_senders_only_send_contract_states(self):
        for name in SENDERS:
            tree = ast.parse((ROOT / "tools" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                pairs = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
                kind = pairs.get("type")
                if isinstance(kind, ast.Constant) and kind.value == "SET_STATE":
                    state = pairs.get("state")
                    if isinstance(state, ast.Constant):
                        self.assertIn(state.value, CONTRACT["states"], f"{name}: {state.value}")


class TestCastSenderAcceptsContractAcks(unittest.TestCase):
    def test_each_display_command_completes_against_a_contract_receiver(self):
        sender = offline_sender()
        for state in CONTRACT["states"]:
            sender.send({"type": "SET_STATE", "state": state})
        sender.send({"type": "SHOW_MESSAGE", "text": "Hej 😀"})
        sender.send({"type": "SHOW_MESSAGE", "text": "x" * CONTRACT["max_text_utf16_units"]})
        sender.send({"type": "CLEAR_MESSAGE"})
        sent = sender.controller.sent
        self.assertEqual(len(sent), len(CONTRACT["states"]) + 3)
        self.assertTrue(all(len(m["request_id"]) == 32 for m in sent), "every command carries a request_id")
        self.assertTrue(sender.correlated_acks, "a contract receiver echoes IDs, so correlation turns on")

    def test_an_invalid_ack_is_not_taken_as_success(self):
        sender = offline_sender()
        with self.assertRaises(TimeoutError):
            # A receiver that answers 'invalid' must not count as delivered.
            sender.send({"type": "SET_STATE", "state": "not-a-state"})

    def test_unsupported_commands_never_reach_the_cast_channel(self):
        sender = offline_sender()
        with self.assertRaises(ValueError):
            sender.send({"type": "GET_DISPLAY_STATUS"})  # a query, not a display command
        self.assertEqual(sender.controller.sent, [])


if __name__ == "__main__":
    unittest.main()
