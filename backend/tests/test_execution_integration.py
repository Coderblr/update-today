"""Real, non-mocked end-to-end verification of the Module 2 Execution Engine: launches
the local synthetic NBC fixture app as a subprocess, drives a genuine Microsoft Edge
session through a full Maker-Checker feature file, and asserts on what actually got
persisted (steps, screenshots, healing, failure classification).
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from app.agents.browser import build_edge_driver
from app.agents.step_executor import _dismiss_known_popups
from app.core.config import get_settings
from app.models.execution import Execution, ExecutionFeatureFile, ExecutionStep, Failure, HealingHistory
from app.models.locator import LocatorEntry
from app.services.execution_service import execute_execution_run

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "storage" / "fixtures" / "nbc_sim"
FEATURE_DIR = Path(__file__).resolve().parents[2] / "storage" / "fixtures" / "feature_files"
FIXTURE_PORT = 9100
FIXTURE_URL = f"http://127.0.0.1:{FIXTURE_PORT}/login"
EDGE_DRIVER_PATH = Path(__file__).resolve().parents[2] / "tools" / "msedgedriver" / "msedgedriver.exe"

pytestmark = pytest.mark.skipif(
    not EDGE_DRIVER_PATH.exists(), reason="msedgedriver.exe not present; real-browser test requires it"
)


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="module")
def fixture_app():
    if _port_open(FIXTURE_PORT):
        yield
        return

    process = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(FIXTURE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        if _port_open(FIXTURE_PORT):
            break
        time.sleep(0.25)
    else:
        process.terminate()
        pytest.fail("Fixture app did not start within timeout")

    yield
    process.terminate()
    process.wait(timeout=5)


def _read_feature(name: str) -> dict:
    return {"filename": name, "raw_text": (FEATURE_DIR / name).read_text(encoding="utf-8")}


def test_maker_checker_execution_runs_end_to_end(fixture_app, db_session):
    settings = get_settings()
    settings.edge_driver_path = str(EDGE_DRIVER_PATH)

    execution = Execution(base_url=FIXTURE_URL, failure_mode="stop", status="pending")
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    feature_file = _read_feature("01_happy_path_maker_checker.feature")
    db_session.add(
        ExecutionFeatureFile(
            execution_id=execution.id, sequence=1, filename=feature_file["filename"],
            raw_text=feature_file["raw_text"], status="pending",
        )
    )
    db_session.commit()

    execute_execution_run(
        db_session,
        execution.id,
        base_url=FIXTURE_URL,
        feature_files=[feature_file],
        failure_mode="stop",
        headless=True,
    )

    db_session.refresh(execution)
    assert execution.status == "success", execution.error_message
    assert execution.total_steps == 16
    assert execution.passed_steps == 16
    assert execution.failed_steps == 0

    steps = (
        db_session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.sequence)
        .all()
    )
    assert len(steps) == 16
    for step in steps:
        assert step.status == "passed"
        assert Path(step.screenshot_before).exists()
        assert Path(step.screenshot_after).exists()

    branch_code_step = next(s for s in steps if "Branch Code" in s.step_text)
    assert branch_code_step.locator_used == "#branch_code"

    remarks_step = next(s for s in steps if "Additional remarks" in s.step_text)
    assert remarks_step.locator_used == "#remarks"


def test_tab_after_fill_triggers_blur_lookup_and_popup_gets_dismissed(fixture_app):
    """Real (non-mocked) proof for the two behaviors just added to handle real NBC
    screens: (1) FillStep tabs out of the field after typing, the same as a real
    NBC field's "Press TAB after entering Account Number" instruction, which is what
    actually fires the fixture's onblur handler; (2) `_dismiss_known_popups` then
    recognizes and closes the resulting "Applicable charge..." style alert (an exact
    translation of the real popup from the user's NBC screenshots) by clicking its
    "OK" button. Drives a genuine Edge session directly against the fixture page
    rather than going through a full feature-file execution, so the popup's actual
    show/hide state can be inspected before and after."""
    settings = get_settings()
    settings.edge_driver_path = str(EDGE_DRIVER_PATH)

    driver = build_edge_driver(headless=True)
    try:
        driver.get(f"http://127.0.0.1:{FIXTURE_PORT}/wizard/1")
        account_field = driver.find_element(By.ID, "account_number")
        account_field.send_keys("AC-12345")

        popup = driver.find_element(By.ID, "charge_popup")
        assert popup.is_displayed() is False, "popup should not appear until the field is blurred"

        account_field.send_keys(Keys.TAB)
        assert popup.is_displayed() is True, "tabbing out should have fired onblur and shown the popup"

        _dismiss_known_popups(driver)
        assert popup.is_displayed() is False, "the popup's OK button should have been auto-clicked"
    finally:
        driver.quit()


def test_real_style_phrasing_feature_file_runs_end_to_end(fixture_app, db_session):
    """The user's existing Java/Cucumber framework uses phrasing like 'the user is
    logged into NBC using "makerID" and "makerPassword"' and 'we enter the the
    account as "X" in cash withdrawal screen' — this proves the platform's generic
    engine runs that exact style of feature file directly, with credential
    placeholders resolved from the backend vault and field phrases fuzzy-matched to
    the Locator Repository, end to end through a full Maker-Checker cycle."""
    settings = get_settings()
    settings.edge_driver_path = str(EDGE_DRIVER_PATH)
    settings.maker_username = "tester"
    settings.maker_password = "Passw0rd!"
    settings.checker_username = "approver"
    settings.checker_password = "Approve123!"

    execution = Execution(base_url=FIXTURE_URL, failure_mode="stop", status="pending")
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    feature_file = _read_feature("07_txn1060_real_style.feature")
    db_session.add(
        ExecutionFeatureFile(
            execution_id=execution.id, sequence=1, filename=feature_file["filename"],
            raw_text=feature_file["raw_text"], status="pending",
        )
    )
    db_session.commit()

    execute_execution_run(
        db_session, execution.id, base_url=FIXTURE_URL, feature_files=[feature_file],
        failure_mode="stop", headless=True,
    )

    db_session.refresh(execution)
    assert execution.status == "success", execution.error_message
    assert execution.failed_steps == 0
    assert execution.total_steps == 15

    steps = (
        db_session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.sequence)
        .all()
    )
    account_step = next(s for s in steps if "the the account" in s.step_text)
    assert account_step.locator_used == "#account_number"  # "the account" fuzzy-matched

    branch_step = next(s for s in steps if "branch code" in s.step_text)
    assert branch_step.locator_used == "#branch_code"  # inside the iframe

    remarks_step = next(s for s in steps if "remarks" in s.step_text)
    assert remarks_step.locator_used == "#remarks"  # inside the Shadow DOM


def test_failure_is_classified_and_persisted(fixture_app, db_session):
    execution = Execution(base_url=FIXTURE_URL, failure_mode="stop", status="pending")
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    feature_file = _read_feature("02_failure_case.feature")
    db_session.add(
        ExecutionFeatureFile(
            execution_id=execution.id, sequence=1, filename=feature_file["filename"],
            raw_text=feature_file["raw_text"], status="pending",
        )
    )
    db_session.commit()

    execute_execution_run(
        db_session, execution.id, base_url=FIXTURE_URL, feature_files=[feature_file],
        failure_mode="stop", headless=True,
    )

    db_session.refresh(execution)
    assert execution.status == "failed"
    assert execution.failed_steps == 1

    failed_step = (
        db_session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.status == "failed")
        .one()
    )
    failure = db_session.query(Failure).filter(Failure.execution_step_id == failed_step.id).one()
    assert failure.category == "locator_not_found"
    assert failure.confidence > 0


def test_continue_on_failure_runs_subsequent_feature_files(fixture_app, db_session):
    execution = Execution(base_url=FIXTURE_URL, failure_mode="continue", status="pending")
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    feature_files = [_read_feature("02_failure_case.feature"), _read_feature("03_second_file.feature")]
    for sequence, ff in enumerate(feature_files, start=1):
        db_session.add(
            ExecutionFeatureFile(
                execution_id=execution.id, sequence=sequence, filename=ff["filename"],
                raw_text=ff["raw_text"], status="pending",
            )
        )
    db_session.commit()

    execute_execution_run(
        db_session, execution.id, base_url=FIXTURE_URL, feature_files=feature_files,
        failure_mode="continue", headless=True,
    )

    feature_file_rows = {
        row.filename: row.status
        for row in db_session.query(ExecutionFeatureFile).filter(ExecutionFeatureFile.execution_id == execution.id)
    }
    assert feature_file_rows["02_failure_case.feature"] == "failed"
    assert feature_file_rows["03_second_file.feature"] == "success"


def test_self_healing_recovers_a_stale_locator(fixture_app, db_session):
    entry = LocatorEntry(
        transaction_number="1060",
        screen_name="screen_1",
        field_name="Customer Name *",
        priority_locator="#totally_wrong_id",
        priority_locator_type="id",
        fallback_locator="#also_wrong",
        fallback_locator_type="id",
        ai_confidence_score=0.95,
        is_mandatory=True,
        control_type="text_input",
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    execution = Execution(base_url=FIXTURE_URL, failure_mode="stop", status="pending")
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    feature_file = _read_feature("03_second_file.feature")
    db_session.add(
        ExecutionFeatureFile(
            execution_id=execution.id, sequence=1, filename=feature_file["filename"],
            raw_text=feature_file["raw_text"], status="pending",
        )
    )
    db_session.commit()

    execute_execution_run(
        db_session, execution.id, base_url=FIXTURE_URL, feature_files=[feature_file],
        failure_mode="stop", headless=True,
    )

    db_session.refresh(execution)
    assert execution.status == "success", execution.error_message
    assert execution.healed_steps == 1

    healing_rows = db_session.query(HealingHistory).filter(HealingHistory.old_locator == "#totally_wrong_id").all()
    assert len(healing_rows) == 1
    assert healing_rows[0].new_locator == "#customer_name"
    assert healing_rows[0].success is True

    db_session.refresh(entry)
    assert entry.priority_locator == "#customer_name"
    assert entry.fallback_locator == "#totally_wrong_id"
