import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from .. import config
from .events import create_tag_event
from .scenario import ScenarioConfig, ScenarioScheduler
from .tag_generator import TagGenerator
from .test_config import TestConfig

Sender = Callable[[str], Awaitable[None]]
Closer = Callable[[], Awaitable[None]]
logger = logging.getLogger(__name__)
MAX_BUFFERED_MESSAGES = 1000


class Reader:
    """Simulates the subset of FXR90 reader behavior consumed by Ultra Tracker."""

    def __init__(self) -> None:
        self.radio_active = False
        self.event_num = 0
        self.test_config = TestConfig()
        self.scenario: ScenarioConfig | None = None
        self._task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._senders: dict[Sender, Closer] = {}
        self._tags_sent = 0
        self._good_tags_sent = 0
        self._noise_tags_sent = 0
        self._started_at = 0.0
        self._last_error = ""
        self._custom_noise_remaining = 0
        self._buffered_messages: list[str] = []

    def register_sender(self, sender: Sender, closer: Closer) -> None:
        self._senders[sender] = closer
        logger.info("[FX90] WebSocket CONNECTED | clients=%d", len(self._senders))
        if self._buffered_messages:
            asyncio.create_task(self._flush_buffered_messages(sender))

    async def _flush_buffered_messages(self, sender: Sender) -> None:
        messages, self._buffered_messages = self._buffered_messages, []
        logger.info("[FX90] FLUSHING BUFFERED MESSAGES | count=%d", len(messages))
        for message in messages:
            try:
                await sender(message)
            except Exception:
                self.unregister_sender(sender)
                break

    def unregister_sender(self, sender: Sender) -> None:
        self._senders.pop(sender, None)
        logger.info("[FX90] WebSocket DISCONNECTED | clients=%d", len(self._senders))

    def test_status(self) -> dict:
        remaining = (self.scenario.runner_count if self.scenario else self.test_config.runner_count) - self._good_tags_sent
        return {
            "scanning": self.radio_active,
            "clients": len(self._senders),
            "tags_sent": self._tags_sent,
            "good_tags_sent": self._good_tags_sent,
            "noise_tags_sent": self._noise_tags_sent,
            "remaining": max(0, remaining),
            "custom_noise_remaining": self._custom_noise_remaining,
            "elapsed_seconds": round(time.monotonic() - self._started_at, 1) if self._started_at else 0,
            "event_num": self.event_num,
            "last_error": self._last_error,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "config": self.test_config.to_dict(),
        }

    def update_test_config(self, values: dict) -> None:
        if self.radio_active:
            raise RuntimeError("stop the reader before changing test settings")
        self.test_config.update(values)

    def set_scenario(self, scenario: ScenarioConfig) -> None:
        if self.radio_active:
            raise RuntimeError("stop the reader before changing scenarios")
        scenario.validate()
        self.scenario = scenario

    async def reset(self) -> None:
        await self.stop()
        self.scenario = None
        self._tags_sent = 0
        self._good_tags_sent = 0
        self._noise_tags_sent = 0
        self._custom_noise_remaining = 0
        self._last_error = ""
        self._buffered_messages.clear()

    def status(self) -> dict:
        return {
            "antennas": {str(i): "connected" for i in range(1, 7)},
            "ble": {"beaconCounts": {"altBeacon": 0, "eddystone": 0, "generic": 0, "iBeacon": 0, "total": 0}, "scanStartTime": "", "scanState": "scanning" if self.radio_active else "stopped"},
            "cpu": {"system": 0, "user": 1},
            "flash": {key: {"free": 0, "total": 0, "used": 0} for key in ["platform", "readerConfig", "readerData", "rootFileSystem"]},
            "impinjGen2X": {"feature": "none", "isActive": False},
            "interfaceConnectionStatus": {"data": [{"connectionError": "", "connectionStatus": "connected" if self._senders else "disconnected", "description": "WEBSOCKET_TEST", "interface": "WEBSOCKET_TEST"}]},
            "ntp": {"offset": 0, "reach": -1},
            "powerNegotiation": "POE+", "powerSource": "PWR_BRICK",
            "radioActivity": "active" if self.radio_active else "inactive", "radioConnection": "connected",
            "ram": {"free": 70, "total": 100, "used": 30},
            "systemTime": datetime.now().strftime("%m/%d/%Y %H:%M"), "temperature": 31, "uptime": "0D0H0M0S",
        }

    def mode(self) -> dict:
        return {"delayBetweenAntennaCycles": {"duration": 0, "type": "DISABLED"}, "environment": "AUTO_DETECT", "transmitPower": [27] * 6, "type": "CUSTOM"}

    async def start(self) -> None:
        if self.radio_active:
            return
        self.test_config.validate()
        self.scenario = None
        self._start_tasks()

    async def start_scenario(self) -> None:
        if self.radio_active:
            return
        if self.scenario is None:
            raise ValueError("no scenario selected")
        self.scenario.validate()
        self._start_tasks()

    def _start_tasks(self) -> None:
        self.radio_active = True
        self._tags_sent = self._good_tags_sent = self._noise_tags_sent = 0
        self._custom_noise_remaining = len(self.test_config.noise_tags or [])
        self._last_error = ""
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._generate_race())
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        logger.info("[FX90] SCANNING | scenario=%s sent=0 good=0 noise=0 custom_noise=%d clients=%d", self.scenario.name if self.scenario else "manual", self._custom_noise_remaining, len(self._senders))

    async def stop(self) -> None:
        self.radio_active = False
        for task_name in ("_task", "_heartbeat_task"):
            task = getattr(self, task_name)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            setattr(self, task_name, None)
        logger.info("[FX90] STOPPED | sent=%d good=%d noise=%d custom_noise_remaining=%d clients=%d", self._tags_sent, self._good_tags_sent, self._noise_tags_sent, self._custom_noise_remaining, len(self._senders))

    async def _heartbeat(self) -> None:
        while self.radio_active:
            await asyncio.sleep(config.HEARTBEAT_SECONDS)
            if self.radio_active:
                logger.info("[FX90] SCANNING | sent=%d good=%d noise=%d custom_noise_remaining=%d clients=%d", self._tags_sent, self._good_tags_sent, self._noise_tags_sent, self._custom_noise_remaining, len(self._senders))

    async def _generate_race(self) -> None:
        if self.scenario:
            await self._generate_scenario()
        else:
            await self._generate_manual_race()

    async def _generate_manual_race(self) -> None:
        cfg = self.test_config
        generator = TagGenerator(cfg.bib_start, cfg.bib_end, cfg.runner_count, cfg.tag_order, noise_tags=cfg.noise_tags)
        remaining = generator.race_tags()
        race_complete_logged = False
        try:
            while self.radio_active:
                if cfg.report_each_tag_once and not remaining:
                    if not race_complete_logged:
                        race_complete_logged = True
                        logger.info("[FX90] RACE COMPLETE | sent=%d good=%d noise=%d custom_noise_remaining=%d clients=%d", self._tags_sent, self._good_tags_sent, self._noise_tags_sent, self._custom_noise_remaining, len(self._senders))
                    await asyncio.sleep(1)
                    continue
                count = min(random.randint(1, cfg.max_burst_size), len(remaining) if cfg.report_each_tag_once else cfg.max_burst_size)
                for _ in range(count):
                    if await self._should_disconnect(): return
                    tag_id, is_noise = generator.next_tag(remaining, cfg.noise_percent, cfg.report_each_tag_once)
                    await self._emit_tag(generator, tag_id, is_noise, cfg.tag_delay_ms)
                    if count > 1:
                        await asyncio.sleep(random.uniform(cfg.max_burst_seconds / count * 0.25, cfg.max_burst_seconds / count * 1.5))
                await asyncio.sleep(random.uniform(cfg.between_bursts_min, cfg.between_bursts_max))
        except Exception as exc:
            self._handle_generator_error(exc)

    async def _generate_scenario(self) -> None:
        scenario = self.scenario
        if scenario is None:
            return
        cfg = self.test_config
        rng = random.Random(scenario.random_seed)
        generator = TagGenerator(
            scenario.bib_start,
            scenario.bib_end,
            scenario.runner_count,
            cfg.tag_order,
            noise_tags=cfg.noise_tags,
            rng=rng,
        )
        remaining = generator.race_tags()
        scheduler = ScenarioScheduler(scenario)
        previous = 0.0
        try:
            index = 0
            while self.radio_active and index < len(scheduler.arrivals):
                count, arrival = scheduler.next_burst(index)
                await asyncio.sleep(max(0, (arrival - previous) / scenario.time_scale))
                previous = arrival
                burst_arrivals = scheduler.arrivals[index:index + count]
                for tag_index, _arrival in enumerate(burst_arrivals):
                    if not self.radio_active:
                        return
                    if not remaining and scenario.report_each_tag_once:
                        return
                    if await self._should_disconnect():
                        return

                    if tag_index > 0:
                        gap = burst_arrivals[tag_index] - burst_arrivals[tag_index - 1]
                        await asyncio.sleep(max(0, gap / scenario.time_scale))
                        if await self._should_disconnect():
                            return

                    if scenario.noise.percent > 0 and rng.random() < scenario.noise.percent / 100:
                        await self._emit_tag(generator, generator.next_noise_tag(), True, 0)
                        if await self._should_disconnect():
                            return
                    if not remaining and scenario.report_each_tag_once:
                        return
                    await self._emit_tag(
                        generator,
                        generator.next_runner_tag(remaining, scenario.report_each_tag_once),
                        False,
                        0,
                    )
                index += count
                previous = burst_arrivals[-1]
            if self.radio_active:
                await asyncio.sleep(max(0, (scenario.duration_seconds - previous) / scenario.time_scale))
                logger.info("[FX90] SCENARIO COMPLETE | name=%s sent=%d good=%d noise=%d", scenario.name, self._tags_sent, self._good_tags_sent, self._noise_tags_sent)
        except Exception as exc:
            self._handle_generator_error(exc)

    async def _should_disconnect(self) -> bool:
        cfg = self.test_config
        if cfg.disconnect_after_seconds and time.monotonic() - self._started_at >= cfg.disconnect_after_seconds:
            await self._disconnect_all("disconnect-after-seconds")
            return True
        if cfg.disconnect_after_tags and self._tags_sent >= cfg.disconnect_after_tags:
            await self._disconnect_all("disconnect-after-tags")
            return True
        return False

    async def _emit_tag(self, generator: TagGenerator, tag_id: str, is_noise: bool, delay_ms: float) -> None:
        self._custom_noise_remaining = generator.custom_noise_remaining
        self.event_num += 1
        self._tags_sent += 1
        if is_noise: self._noise_tags_sent += 1
        else: self._good_tags_sent += 1
        if delay_ms: await asyncio.sleep(delay_ms / 1000)
        await self._broadcast(create_tag_event(self.event_num, tag_id))

    def _handle_generator_error(self, exc: Exception) -> None:
        self._last_error = str(exc)
        logger.exception("[FX90] GENERATOR ERROR")
        self.radio_active = False

    async def _disconnect_all(self, reason: str) -> None:
        logger.warning("[FX90] TEST DISCONNECT | reason=%s clients=%d", reason, len(self._senders))
        closers = list(self._senders.values())
        for closer in closers:
            try: await closer()
            except Exception: pass
        self._senders.clear()

    async def _broadcast(self, message: str) -> None:
        if not self._senders:
            self._buffered_messages.append(message)
            if len(self._buffered_messages) > MAX_BUFFERED_MESSAGES:
                del self._buffered_messages[: len(self._buffered_messages) - MAX_BUFFERED_MESSAGES]
            return
        for sender in list(self._senders):
            try: await sender(message)
            except Exception: self.unregister_sender(sender)
