"""
Peer-to-Peer Communications Broker Service for SIH 26123 Fleet Coordination System.
Network-Centric Coordination Architecture (Bharat Electronics Limited).

TOPIC HIERARCHY:
- `fleet/robot/{id}/state`: Periodic broadcast of AMR position, velocity, intent path, and status.
- `fleet/tasks/allocations`: Broadcast of task assignment decisions from Hungarian allocator.
- `fleet/tasks/blocked`: Broadcast from AMR to report a blocked route for automatic task reallocation.
- `fleet/alerts/maintenance`: Broadcast of predictive maintenance flags.
- `fleet/congestion/updates`: Broadcast of intersection near-miss/conflict telemetry for heatmap tracking.

Designed so no single robot or server "owns" the coordination.
"""

import fnmatch
import logging
from typing import Dict, List, Any, Callable, Optional
import multiprocessing as mp
import queue
import threading
from queue import Empty
import time

from .security import SecurityContext

logger = logging.getLogger("CommsBrokerService")


def matches_topic(pattern: str, topic: str) -> bool:
    """
    Evaluates MQTT-style wildcard matching:
    '+' matches a single topic level.
    '#' matches multiple topic levels.
    """
    # Convert MQTT wildcards to fnmatch/glob style
    pat_parts = pattern.split("/")
    top_parts = topic.split("/")

    i = 0
    j = 0
    while i < len(pat_parts) and j < len(top_parts):
        if pat_parts[i] == "#":
            return True
        elif pat_parts[i] == "+" or pat_parts[i] == top_parts[j]:
            i += 1
            j += 1
        else:
            return False

    if i < len(pat_parts) and pat_parts[i] == "#":
        return True

    return i == len(pat_parts) and j == len(top_parts)


class ProcessMessageBus:
    """
    High-performance, multi-process / multi-agent IPC Message Bus implementing true peer-to-peer
    publish/subscribe channels for independently executing AMR processes.
    Works natively across Windows, Linux, and containerized deployments.
    """

    def __init__(self, enable_security: bool = True, use_multiprocessing: bool = False):
        self.enable_security = enable_security
        self.security = SecurityContext() if enable_security else None
        self.use_multiprocessing = use_multiprocessing
        self._subscriptions: List[Dict[str, Any]] = []
        self._lock = mp.Lock() if use_multiprocessing else threading.Lock()

    def register_client_queue(self, client_id: str, topic_patterns: List[str]) -> Any:
        """Registers an independent process's inbound queue for subscribed topics."""
        q = mp.Queue() if self.use_multiprocessing else queue.Queue()
        with self._lock:
            self._subscriptions.append({
                "client_id": client_id,
                "patterns": topic_patterns,
                "queue": q,
            })
        logger.info(f"Client '{client_id}' subscribed to patterns: {topic_patterns}")
        return q

    def publish(self, topic: str, sender_id: str, payload: Dict[str, Any]) -> None:
        """
        Broadcasts a message to all subscribing clients whose pattern matches topic.
        Includes cryptographic security envelope.
        """
        if self.enable_security and self.security:
            envelope = self.security.wrap_envelope(sender_id=sender_id, payload=payload)
        else:
            envelope = {
                "sender_id": sender_id,
                "timestamp": time.time(),
                "payload": payload,
            }

        msg_packet = {
            "topic": topic,
            "envelope": envelope,
        }

        with self._lock:
            subscribers = list(self._subscriptions)

        for sub in subscribers:
            # Prevent client receiving its own state echo unless explicitly required
            if sub["client_id"] == sender_id and "state" in topic:
                continue

            for pat in sub["patterns"]:
                if matches_topic(pat, topic):
                    try:
                        sub["queue"].put_nowait(msg_packet)
                    except Exception:
                        pass
                    break


class PeerBrokerClient:
    """
    Client interface used by each individual robot process or service
    to interact with the peer communications fabric.
    """

    def __init__(self, client_id: str, bus: ProcessMessageBus, subscribed_topics: List[str]):
        self.client_id = client_id
        self.bus = bus
        self.inbox_queue = bus.register_client_queue(client_id, subscribed_topics)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        self.bus.publish(topic=topic, sender_id=self.client_id, payload=payload)

    def poll_messages(self, max_messages: int = 100) -> List[Dict[str, Any]]:
        """Non-blocking polling of newly arrived peer messages."""
        messages = []
        for _ in range(max_messages):
            try:
                msg = self.inbox_queue.get_nowait()
                messages.append(msg)
            except Empty:
                break
        return messages
