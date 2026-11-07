import random


class TagGenerator:
    """Generates reader-compatible RFID tags from decimal bib numbers."""

    TAG_LENGTH = 24
    BIB_LENGTH = 4
    HEX_CHARS = "0123456789ABCDEF"

    def __init__(self, bib_start: int, bib_end: int, runner_count: int, tag_order: str,
                 noise_tags: list[str] | None = None, noise_pool_size: int = 50,
                 rng: random.Random | None = None) -> None:
        self.bibs = list(range(bib_start, bib_end + 1))
        if runner_count > len(self.bibs):
            raise ValueError("runner_count cannot exceed the configured bib range")
        if bib_start < 0 or bib_end > 9999:
            raise ValueError("bib numbers must fit in four decimal digits")
        self.runner_count = runner_count
        self.tag_order = tag_order
        self.rng = rng or random
        if tag_order == "random" and runner_count < len(self.bibs):
            # sample from the whole bib range, not just the first runner_count bibs
            self._race_bibs = self.rng.sample(self.bibs, runner_count)
        else:
            self._race_bibs = self.bibs[:runner_count]
        self._custom_noise_remaining = list(noise_tags) if noise_tags else []
        self._reported_runner_tags: set[str] = set()
        runner_tags = set(self.race_tags())
        self.noise_tags = self._generate_noise_tags(noise_pool_size, runner_tags)

    @property
    def custom_noise_remaining(self) -> int:
        return len(self._custom_noise_remaining)

    @classmethod
    def _tag_for_bib(cls, bib: int) -> str:
        return f"{bib:0{cls.BIB_LENGTH}d}".rjust(cls.TAG_LENGTH, "0")

    def _generate_noise_tags(self, count: int, runner_tags: set[str]) -> list[str]:
        tags: set[str] = set()
        while len(tags) < count:
            tag = "".join(self.rng.choice(self.HEX_CHARS) for _ in range(self.TAG_LENGTH))
            if tag not in runner_tags:
                tags.add(tag)
        return sorted(tags)

    def race_tags(self) -> list[str]:
        tags = list(self._race_bibs)
        if self.tag_order == "random":
            self.rng.shuffle(tags)
        return [self._tag_for_bib(bib) for bib in tags]

    def next_runner_tag(self, remaining: list[str], report_each_tag_once: bool) -> str:
        if report_each_tag_once:
            while remaining:
                tag = remaining.pop()
                if tag not in self._reported_runner_tags:
                    self._reported_runner_tags.add(tag)
                    return tag
            raise RuntimeError("no runner tags remain")
        tags = self.race_tags()
        return self.rng.choice(tags)

    def next_noise_tag(self) -> str:
        if self._custom_noise_remaining:
            return self._custom_noise_remaining.pop(0)
        if not self.noise_tags:
            raise RuntimeError("noise tag pool must contain at least one tag when noise is enabled")
        return self.rng.choice(self.noise_tags)

    def next_tag(self, remaining: list[str], noise_percent: float, report_each_tag_once: bool) -> tuple[str, bool]:
        if self.rng.random() < noise_percent / 100:
            return self.next_noise_tag(), True
        return self.next_runner_tag(remaining, report_each_tag_once), False
