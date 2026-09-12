"""
Unit Tests for Peer-to-Peer Communications Broker Service (SIH 26123 - Bharat Electronics Limited).
Validates MQTT wildcard matching, HMAC-SHA256 message authentication, and peer delivery.
"""

import pytest
from services.comms_broker import ProcessMessageBus, PeerBrokerClient, matches_topic, SecurityContext


def test_mqtt_topic_wildcard_matching():
    """Verify single-level (+) and multi-level (#) MQTT wildcard matching."""
    # Exact match
    assert matches_topic("fleet/robot/AMR-01/state", "fleet/robot/AMR-01/state") is True
    assert matches_topic("fleet/robot/AMR-01/state", "fleet/robot/AMR-02/state") is False

    # Single-level wildcard (+)
    assert matches_topic("fleet/robot/+/state", "fleet/robot/AMR-01/state") is True
    assert matches_topic("fleet/robot/+/state", "fleet/robot/AMR-99/state") is True
    assert matches_topic("fleet/robot/+/state", "fleet/robot/AMR-01/status/extra") is False

    # Multi-level wildcard (#)
    assert matches_topic("fleet/tasks/#", "fleet/tasks/allocations") is True
    assert matches_topic("fleet/tasks/#", "fleet/tasks/blocked/emergency") is True
    assert matches_topic("fleet/#", "fleet/robot/AMR-01/state") is True


def test_hmac_security_envelope():
    """Verify cryptographic signing and tamper detection for defense requirements."""
    sec = SecurityContext(shared_secret_key="TEST_BEL_SECRET_KEY")

    payload = {"robot_id": "AMR-01", "position": [5, 5]}
    envelope = sec.wrap_envelope(sender_id="AMR-01", payload=payload)

    # Valid verification
    is_valid, reason = sec.verify_envelope(envelope)
    assert is_valid is True
    assert reason == "Verified"

    # Tampered payload detection
    tampered_envelope = dict(envelope)
    tampered_envelope["payload"] = {"robot_id": "AMR-01", "position": [99, 99]}
    is_valid, reason = sec.verify_envelope(tampered_envelope)
    assert is_valid is False
    assert "tampering" in reason.lower()


def test_peer_message_bus_delivery():
    """Verify message exchange between two client endpoints over the message bus."""
    bus = ProcessMessageBus(enable_security=True)

    client_1 = PeerBrokerClient(
        client_id="AMR-01",
        bus=bus,
        subscribed_topics=["fleet/robot/+/state"],
    )
    client_2 = PeerBrokerClient(
        client_id="AMR-02",
        bus=bus,
        subscribed_topics=["fleet/robot/+/state"],
    )

    # AMR-01 publishes state
    client_1.publish(
        topic="fleet/robot/AMR-01/state",
        payload={"position": [10, 12], "battery": 95.0},
    )

    # AMR-02 polls inbox and receives message
    messages = client_2.poll_messages()
    assert len(messages) == 1
    msg = messages[0]
    assert msg["topic"] == "fleet/robot/AMR-01/state"
    assert msg["envelope"]["sender_id"] == "AMR-01"
    assert msg["envelope"]["payload"]["position"] == [10, 12]
