"""Browser checks for UI behaviour pytest cannot see in the Gradio config: focus, the
help toggle, the help placeholder and the message showing before the reply.

Runs the real app on localhost with a fake LLM. Skipped when Playwright or its
Chromium is not installed (`python -m playwright install chromium`).
"""

import re
import threading

import pytest

from fakes import FakeLLM, rules_config
from mini_dm.app import UI_CSS, build_ui

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

ATTACK = '{"action": "attack", "target": "ashfang"}'
AC_ANSWER = "AC means armour class: how hard someone is to hit."

FIGHT_INPUT = "#fight-input textarea"
HELP_INPUT = "#help-input textarea"
SIDEBAR = "#help-sidebar"


class GatedLLM(FakeLLM):
    """A FakeLLM that holds every reply until the test opens the gate."""

    def __init__(self, replies):
        super().__init__(replies)
        self.gate = threading.Event()

    def chat(self, messages, **kwargs):
        assert self.gate.wait(timeout=10), "the test never opened the gate"
        return super().chat(messages, **kwargs)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except sync_api.Error as err:
            pytest.skip(f"Chromium is not installed for Playwright: {err}")
        yield browser
        browser.close()


@pytest.fixture
def open_app(browser):
    """Launches the app with the given LLM client and returns a page showing it."""
    launched = []

    def _open(client):
        demo = build_ui(rules_config(), client=client)
        _, url, _ = demo.launch(
            server_name="127.0.0.1", prevent_thread_lock=True, quiet=True, css=UI_CSS
        )
        page = browser.new_page()
        launched.append((demo, page))
        page.goto(url)
        page.wait_for_selector(FIGHT_INPUT)
        return page

    yield _open
    for demo, page in launched:
        page.close()
        demo.close()


def _help_button(page):
    return page.get_by_role("button", name="Help", exact=True)


def test_fight_input_has_the_cursor_on_load(open_app):
    page = open_app(FakeLLM([]))
    expect(page.locator(FIGHT_INPUT)).to_be_focused()


def test_help_button_opens_and_closes_the_sidebar_and_moves_the_cursor(open_app):
    page = open_app(FakeLLM([]))
    sidebar = page.locator(SIDEBAR)

    _help_button(page).click()
    expect(sidebar).to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator(HELP_INPUT)).to_be_focused()

    _help_button(page).click()
    expect(sidebar).not_to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator(FIGHT_INPUT)).to_be_focused()


def test_closing_help_with_its_chevron_also_moves_the_cursor_to_the_fight(open_app):
    page = open_app(FakeLLM([]))
    chevron = page.locator(f"{SIDEBAR} .toggle-button")

    _help_button(page).click()
    expect(page.locator(HELP_INPUT)).to_be_focused()
    chevron.click()

    expect(page.locator(SIDEBAR)).not_to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator(FIGHT_INPUT)).to_be_focused()


def test_help_placeholder_sits_top_left(open_app):
    page = open_app(FakeLLM([]))
    _help_button(page).click()
    placeholder = page.locator("#help .placeholder")

    expect(placeholder).to_have_css("justify-content", "flex-start")
    expect(placeholder).to_have_css("align-items", "flex-start")
    expect(placeholder.locator("p")).to_have_css("text-align", "left")
    # Top left, but clear of the chat's floating "Help" label and off the edge.
    text = placeholder.locator("p").bounding_box()
    label = page.locator("#help label").bounding_box()
    chat = page.locator("#help").bounding_box()
    assert text["y"] >= label["y"] + label["height"]
    assert text["x"] >= chat["x"] + 8


def test_fight_message_shows_before_the_reply(open_app):
    llm = GatedLLM([ATTACK, "Steel meets scale."])
    page = open_app(llm)
    textbox = page.locator(FIGHT_INPUT)

    textbox.fill("I attack")
    textbox.press("Enter")

    expect(page.locator("#fight").get_by_text("I attack")).to_be_visible()
    expect(textbox).to_have_value("")
    expect(textbox).to_be_disabled()  # no second message while the first is answered

    llm.gate.set()
    expect(page.locator("#fight").get_by_text("Steel meets scale.")).to_be_visible()
    expect(textbox).to_be_enabled()
    expect(textbox).to_be_focused()


def test_help_question_shows_before_the_answer(open_app):
    llm = GatedLLM([AC_ANSWER])
    page = open_app(llm)
    _help_button(page).click()
    textbox = page.locator(HELP_INPUT)

    textbox.fill("What is AC?")
    textbox.press("Enter")

    expect(page.locator("#help").get_by_text("What is AC?")).to_be_visible()
    expect(textbox).to_have_value("")
    expect(textbox).to_be_disabled()

    llm.gate.set()
    expect(page.locator("#help").get_by_text(AC_ANSWER)).to_be_visible()
    expect(textbox).to_be_enabled()
    expect(textbox).to_be_focused()
