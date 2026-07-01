"""Crawl Orchestrator.

Runs Steps 1-4 from the Module 1 spec in sequence: launch Edge, log in, search the
transaction, then recursively explore every reachable screen of that transaction
(wizard pages, popups, in-page panel changes — iframes/Shadow DOM are handled
per-page by `dom_crawling_agent`).

Earlier versions of this module only clicked elements whose visible text matched a
fixed pair of keyword lists ("next"/"continue"/... for wizard advancement,
"view"/"details"/... for popups). That broke on a real enterprise screen where
neither list matched anything meaningful, and is also why a real bug surfaced: with
no real candidate, the crawl could end up acting on whatever else loosely matched —
including, in one observed case, a Logout control. This version instead explores
every visible, non-destructive clickable element generically (the recursive
discover -> open -> extract -> go back -> track-visited pattern), with a hard-coded
safety blacklist so nothing that looks like a final/destructive action (submit,
confirm, post, pay, transfer, delete, approve, authorize, logout, ...) is ever
auto-clicked — those are recorded as "discovered, not explored" instead, since
auto-clicking them on a live banking system could fire a real transaction.

This is plain orchestration code, not free-text LLM reasoning — it's exposed to the
rest of the platform as a LangChain `Tool` (see `app/agents/langchain_tools.py`) so
the deterministic browser-driving steps are invokable from an agent context, while
the actual element-by-element decisions stay debuggable and deterministic.
"""

import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from app.agents.browser import build_edge_driver
from app.agents.dom_crawling_agent import (
    crawl_current_page,
    extract_elements,
    find_and_crawl_popup,
    flatten_screens,
)
from app.agents.login_agent import perform_login
from app.agents.mandatory_field_agent import refine_mandatory_flags
from app.agents.self_healing_agent import fuzzy_best_match
from app.agents.transaction_search_agent import search_transaction
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Never auto-clicked during discovery, regardless of how navigational it might look —
# these are the actions that change real state on a live banking system. Checked as a
# substring against the element's visible text, so "Submit for Approval", "Logout",
# "Confirm Transfer", etc. are all caught.
_BLOCKED_HINTS = [
    "logout",
    "log out",
    "sign out",
    "signout",
    "log off",
    "logoff",
    "submit",
    "confirm",
    "post",
    "pay",
    "transfer",
    "delete",
    "remove",
    "approve",
    "authorize",
    "save",
    "cancel",
    "close",
    "exit",
    "finish",
    "complete",
]

_FILLABLE_CONTROL_TYPES = {"text_input", "textarea", "date_picker"}
_MAX_EXPLORE_DEPTH = 4


def _is_blocked(text: str) -> bool:
    lowered = text.strip().lower()
    return any(hint in lowered for hint in _BLOCKED_HINTS)


def _find_clickable_elements(driver: WebDriver) -> list[WebElement]:
    elements = driver.find_elements(By.CSS_SELECTOR, "button, input[type='button'], input[type='submit'], a")
    return [el for el in elements if el.is_displayed()]


def _element_label(el: WebElement) -> str:
    return (el.text or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip()


def _element_signature(url: str, el: WebElement) -> str:
    label = _element_label(el).lower()
    el_id = el.get_attribute("id") or ""
    return f"{url}::{el.tag_name}::{el_id}::{label}"


def _fill_sample_data(driver: WebDriver, sample_data: dict[str, str] | None) -> int:
    """Opportunistically fills empty fields on the current page from user-supplied
    sample data (fuzzy-matched by field name) so navigation/actions gated behind
    "enter valid data first" can actually be reached. Never overwrites a field that
    already has a value. Returns how many fields were filled."""
    if not sample_data:
        return 0

    elements = extract_elements(driver)
    labeled = [
        (el.get("label_text") or el.get("aria_label") or el.get("placeholder") or el.get("name"), el)
        for el in elements
        if el.get("control_type") in _FILLABLE_CONTROL_TYPES
    ]
    labels = [label for label, _ in labeled if label]

    filled = 0
    for field_name, value in sample_data.items():
        best_label = fuzzy_best_match(field_name, labels)
        if best_label is None:
            continue
        match = next((el for label, el in labeled if label == best_label), None)
        if match is None or not match.get("xpath"):
            continue
        try:
            web_el = driver.find_element(By.XPATH, match["xpath"])
        except Exception:
            continue
        if not web_el.is_displayed() or not web_el.is_enabled():
            continue
        if (web_el.get_attribute("value") or "").strip():
            continue  # already has a value — don't clobber real data
        try:
            web_el.clear()
            web_el.send_keys(value)
            filled += 1
        except Exception:
            continue
    return filled


def _explore(
    driver: WebDriver,
    screen_name: str,
    parent_screen_name: str | None,
    depth: int,
    all_screens: list[dict],
    navigation_graph: dict[str, list[str]],
    visited_actions: set[str],
    sample_data: dict[str, str] | None,
    max_pages: int,
) -> None:
    if len(all_screens) >= max_pages:
        return

    root_screen = crawl_current_page(driver, screen_name)
    all_screens.extend(flatten_screens(root_screen))
    if parent_screen_name:
        navigation_graph.setdefault(parent_screen_name, []).append(screen_name)

    _fill_sample_data(driver, sample_data)

    if depth >= _MAX_EXPLORE_DEPTH:
        return

    current_url = driver.current_url
    trigger_handle = driver.current_window_handle

    # Re-fetch clickable elements fresh on every iteration rather than looping over
    # one list captured up front: after a `driver.back()` (or any navigation) the
    # page's DOM is recreated, which silently invalidates every WebElement handle
    # from before — continuing to iterate the old list raises (caught, swallowed)
    # StaleElementReferenceExceptions on each remaining element, which used to mean
    # everything after the first navigating click on a screen never got explored.
    # `visited_actions` (keyed by url+tag+id/text) makes re-fetching safe: already-
    # handled elements are skipped, so this converges instead of looping forever.
    safety_iterations = 0
    max_safety_iterations = 200
    while True:
        safety_iterations += 1
        if safety_iterations > max_safety_iterations or len(all_screens) >= max_pages:
            break

        candidate = None
        for el in _find_clickable_elements(driver):
            label = _element_label(el)
            if _is_blocked(label):
                signature = _element_signature(current_url, el)
                if signature not in visited_actions:
                    visited_actions.add(signature)
                    navigation_graph.setdefault(screen_name, []).append(
                        f"[not explored - blocked] {label or '(unlabeled)'}"
                    )
                continue
            signature = _element_signature(current_url, el)
            if signature in visited_actions:
                continue
            candidate = (el, signature)
            break

        if candidate is None:
            break  # nothing new left to explore on this screen
        el, signature = candidate
        visited_actions.add(signature)

        handles_before = driver.window_handles
        try:
            el.click()
        except Exception:
            continue

        try:
            if len(driver.window_handles) > len(handles_before):
                popup_name = f"{screen_name}_popup_{len(all_screens) + 1}"
                popup_screen = find_and_crawl_popup(driver, trigger_handle, popup_name)
                if popup_screen:
                    popup_screen["parent_screen_name"] = screen_name
                    all_screens.append(popup_screen)
                    navigation_graph.setdefault(screen_name, []).append(popup_screen["screen_name"])
                continue

            if driver.current_url != current_url:
                child_name = f"{screen_name}_{len(all_screens) + 1}"
                _explore(
                    driver, child_name, screen_name, depth + 1, all_screens, navigation_graph,
                    visited_actions, sample_data, max_pages,
                )
                driver.back()
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                if driver.current_url != current_url:
                    # Couldn't cleanly return to the parent screen — stop exploring
                    # this branch rather than risk wandering further off-course.
                    break
            # else: in-page-only change (SPA-style) — already captured by the next
            # loop iteration's fresh element scan; nothing further to do here.
        except Exception:
            logger.warning("Exploration step failed on screen %s; continuing", screen_name, exc_info=True)
            continue


def run_crawl(
    base_url: str,
    username: str | None,
    password: str | None,
    transaction_number: str | None,
    transaction_name: str | None,
    feature_file_text: str | None = None,
    headless: bool | None = None,
    sample_data: dict[str, str] | None = None,
) -> dict:
    """Returns {"screens": [...], "navigation_graph": {...}} with screens flattened
    and locator-ready elements already mandatory-refined."""
    settings = get_settings()
    driver = build_edge_driver(headless=headless)
    all_screens: list[dict] = []
    navigation_graph: dict[str, list[str]] = {}

    try:
        if username and password:
            perform_login(driver, base_url, username, password)
        else:
            driver.get(base_url)

        if transaction_number or transaction_name:
            search_transaction(driver, transaction_number, transaction_name)

        _explore(
            driver,
            screen_name="screen_1",
            parent_screen_name=None,
            depth=0,
            all_screens=all_screens,
            navigation_graph=navigation_graph,
            visited_actions=set(),
            sample_data=sample_data,
            max_pages=settings.crawl_max_pages,
        )

        for screen in all_screens:
            screen["elements"] = refine_mandatory_flags(screen["elements"], feature_file_text)

        return {"screens": all_screens, "navigation_graph": navigation_graph}
    finally:
        driver.quit()
