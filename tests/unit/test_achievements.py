"""Tests for the achievement registry, the rules, the engine and the rotation.

Three properties get the most attention, because each is one that fails
silently rather than loudly:

- A malformed definition must fail at load, not produce an achievement that
  quietly never unlocks.
- Evaluation must be idempotent, so running the engine on every write does not
  create duplicate unlocks or double-credit points.
- The celebration rotation must be fair, so a note-logger still sees the general
  lines rather than only the note ones.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from bm_tracker import auth, celebrate, scoring
from bm_tracker.achievements import custom as custom_rules
from bm_tracker.achievements import engine, facts, registry, rules
from bm_tracker.models import AchievementUnlock, CelebrationSeen, User
from bm_tracker.routes.people import Badge
from bm_tracker.routes.people import _by_tier as group_by_tier
from bm_tracker.routes.stats import _interleave
from bm_tracker.services import bm_service
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: A minimal, valid registry used to exercise the loader.
MINIMAL = """
[achievement_tiers]
common = 2
rare = 10

[[achievement]]
key = "one_bm"
name = "One"
description = "A single entry."
tier = "common"
rule.all = [{ bm_count_total = { gte = 1 } }]

[[achievement]]
key = "lots"
name = "Lots"
description = "Ten entries."
tier = "rare"
rule.all = [{ bm_count_total = { gte = 10 } }]
"""


def _write(tmp_path: Path, text: str) -> Path:
    """Write a registry to a temp file.

    Args:
        tmp_path: The temp directory.
        text: The registry body.

    Returns:
        The path written.
    """
    target = tmp_path / "registry.toml"
    target.write_text(text, encoding="utf-8")
    return target


async def _user(session: AsyncSession, username: str = "cal") -> User:
    """Create a signed-in-able user.

    Args:
        session: The session to write through.
        username: The account name.

    Returns:
        The created `User`.
    """
    user = User(
        username=username,
        display_name=username.title(),
        password_hash=auth.hash_password("an excellent long passphrase"),
        timezone="UTC",
    )
    session.add(user)
    await session.commit()
    return user


async def _log(session: AsyncSession, user: User, count: int, *, when: date) -> None:
    """Log `count` BMs on one day.

    Args:
        session: The session to write through.
        user: The owner.
        count: How many.
        when: The occurrence date.
    """
    await bm_service.log_nothing_today(
        session, user, when, logged_at=datetime(when.year, when.month, when.day, 20, 0)
    )
    for index in range(count):
        await bm_service.log_bm(
            session,
            user,
            when,
            occurred_local=datetime(when.year, when.month, when.day, 7 + index, 0),
            bristol_type=4,
            logged_at=datetime(when.year, when.month, when.day, 20, 0),
        )


# --- the registry ---------------------------------------------------------


def test_the_shipped_registry_loads() -> None:
    """The real one is valid, and has the twenty it claims."""
    loaded = registry.load()

    assert len(loaded) >= 20
    assert set(loaded.tiers) >= {"common", "uncommon", "rare", "legendary"}
    # Points come from the tier, and are bounded by it. The ceiling used to be a
    # "joke" tier at 25 — a category that existed to mark two achievements as
    # funny rather than to describe how hard they are, and which was quietly the
    # most valuable tier in the game.
    assert max(loaded.tiers.values()) <= 20


def test_nothing_is_categorised_as_a_joke() -> None:
    """Achievements are entertainment, not a punchline.

    Two of them were filed under a tier called "joke" because their wording is
    funny. The wording stays — it is the good part — but a tier is a claim about
    difficulty, and a fifth rung that outranked legendary made that claim
    nonsense.
    """
    loaded = registry.load()

    assert "joke" not in loaded.tiers
    assert all(a.tier != "joke" for a in loaded.achievements)
    # The two that moved, by name, so a re-triage cannot quietly undo this.
    by_key = {a.key: a for a in loaded.achievements}
    assert by_key["blatherer"].tier == "rare"
    assert by_key["fiery_streak"].tier == "rare"


def test_every_definition_is_well_formed() -> None:
    """No duplicate keys, and every tier has a point value."""
    loaded = registry.load()
    keys = [a.key for a in loaded.achievements]

    assert len(keys) == len(set(keys))
    for achievement in loaded.achievements:
        assert achievement.tier in loaded.tiers
        assert achievement.name
        assert achievement.description
        assert achievement.icon


def test_every_custom_rule_is_used() -> None:
    """`custom.py` cannot quietly grow dead code.

    The loader enforces the same thing at startup; this asserts it survived.
    """
    loaded = registry.load()
    used = {a.custom for a in loaded.achievements if a.custom}

    assert used == set(custom_rules.CUSTOM_RULES)


def test_every_achievement_is_visible() -> None:
    """No hidden flag survives: the catalogue is meant to be read."""
    loaded = registry.load()

    assert all(
        a.icon in {"default"} or (registry.BADGE_DIR / f"{a.icon}.svg").is_file()
        for a in loaded.achievements
    )


def test_an_unknown_fact_fails_at_load(tmp_path: Path) -> None:
    """A typo must fail the deploy, not produce a never-unlocking achievement."""
    bad = MINIMAL.replace("bm_count_total", "bm_count_totl")
    target = _write(tmp_path, bad)

    with pytest.raises(registry.RegistryError, match="unknown fact"):
        registry.load(target)


def test_a_duplicate_key_fails_at_load(tmp_path: Path) -> None:
    """Keys address the unlock table, so they have to be unique."""
    dupe = MINIMAL + MINIMAL.split("[[achievement]]")[1].join(["[[achievement]]", ""])
    target = _write(tmp_path, dupe)

    with pytest.raises(registry.RegistryError, match="[Dd]uplicate"):
        registry.load(target)


def test_a_missing_tier_fails_at_load(tmp_path: Path) -> None:
    """A tier with no point value is a silent zero, not a default."""
    target = _write(tmp_path, MINIMAL.replace('tier = "rare"', 'tier = "legendary"'))

    with pytest.raises(registry.RegistryError, match="tier"):
        registry.load(target)


def test_an_empty_registry_fails_at_load(tmp_path: Path) -> None:
    """An empty registry would render an empty page with no error anywhere."""
    target = _write(tmp_path, "[achievement_tiers]\ncommon = 2\n")

    with pytest.raises(registry.RegistryError, match="no achievements"):
        registry.load(target)


# --- the rules ------------------------------------------------------------


def test_progress_reflects_how_close_a_rule_is() -> None:
    """A locked achievement still says how far along a running total is."""
    fact_set = facts.FactSet(values={"bm_count_total": 5.0})

    verdict = rules.Rule(spec={"bm_count_total": {"gte": 10}}).evaluate(fact_set)

    assert not verdict.unlocked
    assert verdict.progress == pytest.approx(0.5)
    assert (verdict.current, verdict.target) == (5.0, 10.0)


def test_a_record_gets_a_count_but_never_a_percentage() -> None:
    """Nine BMs in one day is not ninety per cent of anything.

    The tenth is not a tenth of a bowel movement, it is a different day, and it
    will not arrive by carrying on as normal. So the tile says what the count is
    and offers no bar, rather than drawing one at nine tenths and implying the
    gap can be walked.
    """
    verdict = rules.Rule(spec={"max_bms_in_day": {"gte": 10}}).evaluate(
        facts.FactSet(values={"max_bms_in_day": 9.0})
    )

    assert not verdict.unlocked
    assert verdict.progress is None, "a best-ever record is not a live ratio"
    assert (verdict.current, verdict.target) == (9.0, 10.0)


def test_a_rolling_window_gets_no_ratio_either() -> None:
    """It counts down as well as up, so any percentage of it is a lie."""
    verdict = rules.Rule(spec={"weekend_entry_count": {"gte": 4}}).evaluate(
        facts.FactSet(values={"weekend_entry_count": 3.0})
    )

    assert verdict.progress is None
    assert (verdict.current, verdict.target) == (3.0, 4.0)


def test_an_upper_bound_has_no_denominator() -> None:
    """Under three days is not a distance to a target, and passing it loses it."""
    verdict = rules.Rule(spec={"max_bms_in_day": {"lte": 5}}).evaluate(
        facts.FactSet(values={"max_bms_in_day": 3.0})
    )

    assert verdict.unlocked
    assert verdict.progress is None
    assert verdict.current is None, "3 / 5 would read as progress towards 5"


def test_a_group_is_only_a_ratio_when_every_part_is_one() -> None:
    """A bar over the logged half of a gated requirement is a broken promise.

    "Log on the Ides of March" and "log fifty this year" is one achievement. You
    can be part-way through the counting and the gate is still months away, so
    the pair has no ratio to show.
    """
    mixed = rules.Rule(
        spec={"all": [{"bm_count_total": {"gte": 50}}, {"logged_mar_15": True}]}
    ).evaluate(facts.FactSet(values={"bm_count_total": 45.0, "logged_mar_15": 0.0}))

    assert mixed.progress is None
    # Nor a count. The thing standing in the way is a date, and "45 / 50" beside
    # it would be the more misleading of the two: it points at five more logs
    # when five more logs change nothing until 15 March.
    assert (mixed.current, mixed.target) == (None, None)

    both_counting = rules.Rule(
        spec={"all": [{"bm_count_total": {"gte": 50}}, {"note_count": {"gte": 10}}]}
    ).evaluate(facts.FactSet(values={"bm_count_total": 45.0, "note_count": 9.0}))

    assert both_counting.progress == pytest.approx(0.9)


def test_a_time_window_shows_nothing_to_measure() -> None:
    """There is no such thing as forty per cent of the way to between 23 and 05."""
    verdict = rules.Rule(
        spec={"time_of_day": {"between": ["23:00", "05:00"]}}
    ).evaluate(facts.FactSet(values={"time_of_day": 2.0}))

    assert verdict.unlocked
    assert verdict.progress is None


def test_all_takes_the_minimum_and_any_the_maximum() -> None:
    """Partially-met requirements read as partial, not as zero."""

    values = {"bm_count_total": 2.0, "note_count": 1.0}
    all_progress = (
        rules.Rule(
            spec={"all": [{"bm_count_total": {"gte": 3}}, {"note_count": {"gte": 8}}]}
        )
        .evaluate(facts.FactSet(values=values))
        .progress
    )
    any_progress = (
        rules.Rule(
            spec={"any": [{"bm_count_total": {"gte": 3}}, {"note_count": {"gte": 8}}]}
        )
        .evaluate(facts.FactSet(values=values))
        .progress
    )

    assert all_progress < any_progress


def test_a_time_window_can_wrap_midnight() -> None:
    """23:00 to 05:00 is two windows, not an empty one."""
    rule = rules.Rule(spec={"time_of_day": {"between": ["23:00", "05:00"]}})

    for hour in (23.5, 2.0, 4.75):
        assert rule.evaluate(facts.FactSet(values={"time_of_day": hour})).unlocked, (
            f"{hour} should be inside the night window"
        )

    for hour in (12.0, 18.0):
        assert not rule.evaluate(facts.FactSet(values={"time_of_day": hour})).unlocked


def test_an_unknown_fact_is_zero_not_an_error() -> None:
    """A fact nobody has earned yet must not blow up a registry evaluation."""
    verdict = rules.Rule(spec={"bm_count_total": {"gte": 1}}).evaluate(
        facts.FactSet(values={})
    )

    assert not verdict.unlocked


# --- the engine -----------------------------------------------------------


async def test_evaluation_is_idempotent(session: AsyncSession) -> None:
    """Running the engine twice must not double-credit anything.

    The engine runs on every write, so this is the property that keeps the
    leaderboard honest.
    """
    user = await _user(session)
    await _log(session, user, 1, when=date(2026, 1, 9))
    await session.commit()

    first = await engine.evaluate(session, user, 2026)
    assert first
    await engine.record(session, first, user.id, 2026)
    await session.commit()

    second = await engine.evaluate(session, user, 2026)
    assert second == []

    total = await session.scalar(select(func.count()).select_from(AchievementUnlock))
    assert total == len(first)


async def test_achievements_re_earn_each_year(session: AsyncSession) -> None:
    """The same achievement in two years is two unlocks."""
    user = await _user(session)
    await _log(session, user, 1, when=date(2025, 1, 9))
    await _log(session, user, 1, when=date(2026, 1, 9))
    await session.commit()

    for year in (2025, 2026):
        fresh = await engine.evaluate(session, user, year)
        await engine.record(session, fresh, user.id, year)
    await session.commit()

    rows = (await session.scalars(select(AchievementUnlock))).all()
    assert {r.year for r in rows} == {2025, 2026}


async def test_the_points_figure_matches_the_leaderboard(
    session: AsyncSession,
) -> None:
    """Achievement points are separate, and never reorder the board."""
    user = await _user(session)
    await _log(session, user, 3, when=date(2026, 1, 9))
    await session.commit()

    fresh = await engine.evaluate(session, user, 2026)
    await engine.record(session, fresh, user.id, 2026)
    await session.commit()

    score = await scoring.score_year(session, user, 2026)
    earned = await engine.earned_points(session, user.id, 2026)

    assert score.logging_points > 0
    assert earned > 0
    # The two never mix: the leaderboard sorts on logging points alone.
    assert (
        score.logging_points
        == score.day_points + score.note_points + score.entry_points
    )


async def test_every_achievement_is_listed_earned_or_not(
    session: AsyncSession,
) -> None:
    """The catalogue is the fun part, so nothing is hidden from it."""
    user = await _user(session)
    await _log(session, user, 1, when=date(2026, 1, 9))
    await session.commit()

    # The page reports what has been *recorded*, so record first: in the app
    # that happens on every write, and this test skipped it.
    fresh = await engine.evaluate(session, user, 2026)
    await engine.record(session, fresh, user.id, 2026)
    await session.commit()

    statuses = await engine.status_for(session, user, 2026)

    assert len(statuses) == len(engine.REGISTRY)
    assert all(s.achievement.name for s in statuses)
    earned = [s for s in statuses if s.unlocked]
    assert len(earned) == len(fresh) >= 1
    # Everything still appears, earned or not.
    assert len(statuses) == len(engine.REGISTRY)


# --- the celebration rotation --------------------------------------------


async def test_the_rotation_is_fair(session: AsyncSession) -> None:
    """Every line in a pool is seen before any repeats.

    The property that a user who always notes still gets the general lines, and
    that nobody is stuck with one message.
    """
    user = await _user(session, "bee")

    seen: list[str] = []
    for _ in range(len(celebrate.POOLS["bouncy"])):
        said = await celebrate.pick(session, user.id, "log_any", blend=False)
        assert said is not None
        seen.append(said)
        await session.commit()

    assert len(set(seen)) == len(seen), "a line repeated before the pool was exhausted"


async def test_rotation_is_per_user(session: AsyncSession) -> None:
    """One user's rotation does not consume another's."""
    one = await _user(session, "one")
    two = await _user(session, "two")

    first_for_one = await celebrate.pick(session, one.id, "bouncy", blend=False)
    first_for_two = await celebrate.pick(session, two.id, "bouncy", blend=False)
    await session.commit()

    assert first_for_one == first_for_two

    rows = (await session.scalars(select(CelebrationSeen))).all()
    assert len({row.user_id for row in rows}) == 2


async def test_a_specific_pool_is_preferred(session: AsyncSession) -> None:
    """A note gets a note line, not a generic one."""
    user = await _user(session, "cal")

    said = await celebrate.pick(session, user.id, "log_none", blend=False)
    await session.commit()

    assert said in {m.text for m in celebrate.POOLS["log_none"]}


async def test_the_catalogue_is_well_formed() -> None:
    """Every pool has lines, and the fallback exists."""
    assert celebrate.POOLS
    for name, messages in celebrate.POOLS.items():
        assert messages, f"pool {name!r} is empty"
        assert all(m.text and m.id for m in messages)
    assert celebrate.POOLS[celebrate.DEFAULT_POOL]


def test_time_based_facts_use_a_real_window() -> None:
    """The late-night window must survive as a wrapping range."""
    loaded = registry.load()
    night = loaded.get("night_owl")
    spec = night.rule.spec if night.rule is not None else {}

    assert spec == {"any": [{"time_of_day": {"between": ["23:00", "05:00"]}}]}


def test_a_streak_achievement_uses_the_derived_streak() -> None:
    """Guard against a rule referencing a fact nothing computes."""
    for achievement in registry.load().achievements:
        if achievement.rule is None:
            continue
        for fact in _facts_in(achievement.rule.spec):
            assert fact in rules.KNOWN_FACTS, f"{achievement.key!r} uses {fact!r}"


def _facts_in(spec: object) -> set[str]:
    """Return every fact name a rule tree references.

    Args:
        spec: The rule tree.

    Returns:
        The fact names found.
    """
    found: set[str] = set()
    if isinstance(spec, dict):
        for key, value in spec.items():
            if key in ("all", "any") and isinstance(value, list):
                for child in value:
                    found |= _facts_in(child)
            elif key not in ("all", "any", "custom"):
                found.add(str(key))
    return found


def test_the_tier_values_bound_the_whole_catalogue() -> None:
    """Even unlocking everything cannot rival a year of logging."""
    loaded = registry.load()
    worst_case = sum(max(loaded.tiers.values()) for _ in loaded.achievements)
    a_perfect_year = 365 * 15

    assert worst_case < a_perfect_year


def test_every_known_fact_is_actually_produced() -> None:
    """A fact in the vocabulary that nothing computes is a silent hole.

    `KNOWN_FACTS` and the builder's list used to be two separate declarations
    that had already drifted, which is how a rule can name something that
    always reads as zero. One list now, and this asserts the builder fills it.
    """
    import asyncio  # noqa: PLC0415

    from bm_tracker import auth  # noqa: PLC0415
    from bm_tracker.achievements import facts  # noqa: PLC0415
    from bm_tracker.database import get_engine, get_session_factory  # noqa: PLC0415
    from bm_tracker.models import Base, User  # noqa: PLC0415

    async def run() -> None:
        engine = get_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = get_session_factory(engine)
        async with factory() as session:
            person = User(
                username="cal",
                display_name="Cal",
                password_hash=auth.hash_password("x" * 16),
                timezone="UTC",
            )
            session.add(person)
            await session.commit()
            built = await facts.build(session, person, 2026)
            produced = set(built.values)
            assert set(facts.FACT_KEYS) == produced, (
                f"declared but never produced: "
                f"{sorted(set(facts.FACT_KEYS) - produced)}"
            )

    asyncio.run(run())


def test_the_catalogue_is_the_size_we_intend() -> None:
    """One hundred and twenty, by agreement, and not three hundred by inertia.

    Variety by volume is the opposite of variety by idea: the first twenty-one
    were twenty-one ways of saying "your number is at least N", and the answer
    was a bigger vocabulary and a smaller catalogue, not a bigger catalogue.
    """
    loaded = registry.load()
    assert len(loaded) == 120, f"the catalogue is {len(loaded)}, not 120"


def test_the_catalogue_covers_more_than_one_shape() -> None:
    """Most definitions should need two things to be true at once.

    Twenty of the original twenty-one used a single condition, which is why the
    collection read as one idea repeated. This is the regression guard: a
    plurality of definitions must be composed.
    """
    loaded = registry.load()

    def conditions(spec: dict) -> int:
        if "all" in spec:
            return len(spec["all"])
        if "any" in spec:
            return len(spec["any"])
        return 1

    counts = [
        conditions(a.rule.spec) for a in loaded.achievements if a.rule is not None
    ]
    composed = sum(1 for n in counts if n > 1)
    assert composed / len(counts) > 0.4, (
        f"only {composed} of {len(counts)} definitions use more than one condition"
    )


def test_status_shows_a_count_where_there_is_no_ratio() -> None:
    """What the tile renders for a locked record achievement."""
    status = engine.Status(
        achievement=registry.load().achievements[0],
        unlocked=False,
        unlocked_at=None,
        progress=None,
        current=9.0,
        target=10.0,
    )

    assert status.count == "9 / 10"


def test_status_with_nothing_to_measure_says_nothing() -> None:
    status = engine.Status(
        achievement=registry.load().achievements[0],
        unlocked=False,
        unlocked_at=None,
        progress=None,
        current=None,
        target=None,
    )

    assert status.count == ""


def test_tier_groups_run_least_rare_first() -> None:
    """Rarest last, so a person's page is a ladder rather than a flat row.

    Alphabetical would put a Legendary earned last March above a Common earned
    on Tuesday, which reads as a mistake rather than as a rarity.
    """

    def badge(tier: str, name: str) -> Badge:
        return Badge(
            key=name, name=name, description=name, icon="default", tier=tier, points=2
        )

    grouped = group_by_tier(
        (
            badge("legendary", "The Century"),
            badge("common", "First Blood"),
            badge("rare", "Quincentenary"),
        )
    )

    # Uncommon has nothing in it and is left out entirely, rather than
    # rendering an empty heading between the two that are populated.
    assert [tier for tier, _ in grouped] == ["common", "rare", "legendary"]


def test_note_achievements_are_intermixed_with_the_others() -> None:
    """A tier is one spread of achievements, not two lists run together.

    They were appended, which put every note achievement in a block at the end
    of its tier. This asserts the spread, and — the part that actually bit —
    that it comes from being told which list a status came from rather than from
    sniffing the key, because a note achievement on the page carries its bare
    key and `is_note_key` looks for a `note:` prefix that is only in the unlock
    table.
    """
    registry = [f"reg{i}" for i in range(12)]
    notes = ["love_poem", "poem", "dream"]
    items = [(k, False) for k in registry] + [(k, True) for k in notes]

    # It takes (status, is_note) and hands back the statuses.
    out = list(_interleave(items))

    assert sorted(out) == sorted(registry + notes), "nothing lost or invented"
    assert len(out) == len(set(out)), "nothing repeated"
    # Every note achievement is separated from the next by at least one other.
    positions = [out.index(n) for n in notes]
    assert all(b - a > 1 for a, b in zip(positions, positions[1:], strict=False)), (
        f"two note achievements are adjacent: {out}"
    )
    # And they start before the end, which is the whole point.
    assert min(positions) < len(registry), "they are all still bunched at the end"


def test_a_tier_with_no_note_achievements_is_untouched() -> None:
    items = [(f"reg{i}", False) for i in range(4)]
    assert _interleave(items) == items
