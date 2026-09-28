"""Tests for the navigation shell and the icon rendering.

The icon tests exist because of a bug that was silent and ugly: Jinja escaped
the inline SVG, so `<svg ...>` rendered as visible text. Nothing errored, the
tests passed, and every page became about 4800px wide. An assertion that the
markup is a real element rather than escaped text is the only thing that catches
it.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from bm_tracker import auth
from bm_tracker.icons import UnknownIconError, icon
from bm_tracker.models import User
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from bm_tracker.settings import Settings

PASSWORD = "an excellent long passphrase"
ESCAPED_SVG = re.compile(r"&lt;svg")


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client with the app's lifespan running."""
    from bm_tracker.app import create_app  # noqa: PLC0415

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://testserver") as http,
        app.router.lifespan_context(app),
    ):
        yield http


async def _sign_in(client: AsyncClient, session: AsyncSession) -> None:
    """Create a user and drive the real sign-in form.

    Args:
        client: The HTTP client.
        session: The session to create the user through.
    """
    session.add(
        User(
            username="cal",
            display_name="Cal",
            password_hash=auth.hash_password(PASSWORD),
            timezone="Europe/London",
        )
    )
    await session.commit()
    page = await client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token
    await client.post(
        "/login",
        data={
            "csrf_token": token.group(1),
            "username": "cal",
            "password": PASSWORD,
        },
    )


@pytest.mark.parametrize(
    "path",
    ["/", "/log", "/dashboard", "/people", "/leaderboard", "/achievements", "/help"],
)
async def test_icons_render_as_elements_not_escaped_text(
    client: AsyncClient, session: AsyncSession, path: str
) -> None:
    """Every page inlines real SVG, and none of it is escaped into the text."""
    await _sign_in(client, session)

    page = await client.get(path)

    assert page.status_code == 200
    assert '<svg class="ico' in page.text, "no inlined icon on this page"
    assert not ESCAPED_SVG.search(page.text), "an icon was HTML-escaped into text"


async def test_the_date_picker_keeps_a_visible_icon(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The date field has an icon we draw, not one the user agent may not.

    Chromium draws the native picker indicator with a font that is not always
    installed, and when it is missing the field shows an empty box.
    """
    await _sign_in(client, session)

    page = await client.get("/log")

    assert 'class="ico date-field__icon"' in page.text


async def test_the_drawer_holds_every_destination(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The links moved out of the top bar and into the drawer, all of them."""
    await _sign_in(client, session)

    page = await client.get("/")

    drawer = re.search(r'class="app-drawer__list".*?</ul>', page.text, re.S)
    assert drawer, "no drawer"
    links = re.findall(r'href="([^"]+)"', drawer.group(0))
    for href in (
        "/",
        "/log",
        "/dashboard",
        "/people",
        "/leaderboard",
        "/achievements",
        "/settings",
        "/help",
    ):
        # Match the href, not the whole tag: the current page's link carries
        # aria-current and a class, and asserting on the closing bracket meant
        # the feed was "unreachable" precisely because you were on it.
        assert href in links, f"{href} is not reachable; the drawer has {links}"
    assert 'id="nav"' in page.text, "no drawer"
    assert 'href="#nav"' in page.text, "nothing opens the drawer"


def test_an_unknown_icon_is_an_error() -> None:
    """A typo fails loudly rather than shipping an empty box."""
    with pytest.raises(UnknownIconError):
        icon("definitely-not-an-icon")


def test_an_icon_class_cannot_smuggle_markup() -> None:
    """The class is an allowlist, not a hole into the attribute."""
    with pytest.raises(UnknownIconError):
        icon("menu", 'x" onload="alert(1)')


async def test_the_date_field_has_a_working_calendar_button(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The calendar is a button we draw that opens the platform's picker.

    The native picker is kept — on a phone it is the OS calendar — but the
    indicator is not, because the user agent draws it with a font that is not
    always installed. These three things have to hold together: our button, a
    real `input[type=date]` for the form, and a script wired to the button.
    """
    await _sign_in(client, session)

    page = await client.get("/log")

    assert 'type="date"' in page.text, "the native date input is gone"
    assert "data-date-picker-toggle" in page.text, "nothing opens the calendar"
    assert 'aria-controls="date"' in page.text, "the button is not tied to the field"
    assert 'class="ico date-field__icon"' in page.text, "the button has no icon"


async def test_the_date_script_is_loaded(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Without the script the button is decoration."""
    await _sign_in(client, session)

    page = await client.get("/log")

    assert "/static/js/datepicker.js" in page.text
    script = await client.get("/static/js/datepicker.js")
    assert script.status_code == 200
    assert "showPicker" in script.text


async def test_log_is_not_in_the_top_bar(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Log is a bottom tab, so the top bar does not repeat it.

    Two controls for the same action in two bars is one too many, and the top
    one was the copy that overflowed the bar on a phone.
    """
    await _sign_in(client, session)

    page = await client.get("/")

    top_bar = page.text.split('class="app-drawer"', 1)[0]
    assert 'href="/log"' not in top_bar, "Log is duplicated in the top bar"
    # It is still reachable, in the tab bar.
    assert 'class="app-tab' in page.text
    assert 'href="/log"' in page.text


async def test_no_page_loads_a_third_party_script(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Every script on a page is served by us.

    htmx used to be pulled from unpkg, without `defer`, and used by nothing: no
    `hx-` attributes, no htmx calls, no partial swaps. It was a render-blocking
    request to a third party in exchange for nothing, and when that CDN was slow
    or unreachable it held up the whole document — including the deferred scripts
    this app does depend on.

    Bootstrap and htmx are both self-hosted, or both absent, for the same
    reason: one less party between the app and its own code.
    """
    await _sign_in(client, session)

    for path in ("/", "/log", "/people", "/dashboard"):
        page = await client.get(path)
        external = re.findall(r'<script[^>]+src="(https?://[^"]+)"', page.text)
        assert not external, f"{path} loads third-party scripts: {external}"


async def test_the_skip_link_reaches_the_top_of_the_viewport_when_scrolled(
    client: AsyncClient, session: AsyncSession
) -> None:
    """It is `position: fixed`, so a scrolled page does not put it out of reach.

    It was `absolute`, which anchored it to the document: with the page scrolled
    to 351px, focusing it put it at -343px from the top of the viewport. The
    only person who ever sees this link is someone tabbing through a page long
    enough to want skipping, which is exactly when it was missing.
    """
    await _sign_in(client, session)
    css = await client.get("/static/css/custom.css")

    block = re.search(r"(?m)^\.skip-link\s*\{(.*?)^\}", css.text, re.S)
    assert block, "no .skip-link rule"
    assert "position: fixed" in block.group(1), (
        "an absolutely positioned skip link is unreachable on a scrolled page"
    )


async def test_focus_is_drawn_in_the_app_accent(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Every focusable control gets one visible ring, in our colour.

    Without this, every control fell back to the user agent's default: a 1px
    auto outline in near-black, which is invisible against the dark theme and
    disagrees with the cards' own focus treatment.
    """
    await _sign_in(client, session)
    css = (await client.get("/static/css/custom.css")).text

    assert ":focus-visible" in css, "no focus-visible styling at all"
    ring = re.search(r":where\([^)]*\):focus-visible\s*\{(.*?)\}", css, re.S)
    assert ring, "no rule covering focusable controls"
    assert "outline:" in ring.group(1), "the ring is not an outline"
    assert "var(--bs-primary)" in ring.group(1), (
        "the ring should be the app's accent, not the user agent's default"
    )


async def test_the_names_you_tap_are_big_enough(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Names are the main tap target on three pages, so they get 44px.

    The feed, the leaderboard and the people list each lead with a person's
    name, and each of those was 19-24px tall — laid out as inline text and
    never given a height. Apple's minimum is 44 and Material's is 48dp; below
    about 30 the miss rate climbs sharply.

    This is a stylesheet assertion rather than a layout one because the test
    client has no viewport to measure against; the rule is what the size comes
    from.
    """
    await _sign_in(client, session)
    css = (await client.get("/static/css/custom.css")).text

    rule = re.search(
        r"(?m)^\.feed__who,\s*\n\.board__who,\s*\n\.people-row__name\s*\{(.*?)^\}",
        css,
        re.S,
    )
    assert rule, "no rule sizing the name links"
    assert "min-height: 44px" in rule.group(1)


async def test_the_open_drawer_locks_and_hides_the_page_behind_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Opening the drawer stops the page moving and takes it out of reach.

    `:target` alone gave the panel, and nothing else. A touch on the scrim
    scrolled the list behind it, so the drawer looked frozen while the page
    moved under the scrim; and a screen reader tabbing out of the drawer walked
    back into content that was invisible behind it.

    `inert` is the one attribute that removes a whole subtree from the tab
    order and the accessibility tree at once, rather than reaching in and
    adjusting tabindex on a dozen elements.
    """
    await _sign_in(client, session)
    script = (await client.get("/static/js/nav.js")).text

    assert "inert" in script, "the content behind the drawer is still reachable"
    assert "overflow" in script
    assert 'position = "fixed"' in script, (
        "the page can still scroll behind an open drawer"
    )
    # And every page has the element the drawer makes inert.
    page = await client.get("/")
    assert 'id="main"' in page.text
