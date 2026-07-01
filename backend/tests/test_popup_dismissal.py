from app.agents.step_executor import _dismiss_known_popups


class _FakeButton:
    def __init__(self, text, displayed=True, enabled=True):
        self.text = text
        self._displayed = displayed
        self._enabled = enabled
        self.click_count = 0

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled

    def get_attribute(self, name):
        return None

    def click(self):
        self.click_count += 1
        self._displayed = False  # simulate the popup closing


class _AlwaysVisibleButton(_FakeButton):
    def click(self):
        self.click_count += 1  # popup keeps reappearing — never closes


class _FakeDriver:
    def __init__(self, buttons):
        self._buttons = buttons

    def find_elements(self, by, selector):
        return self._buttons


def test_dismisses_ok_button():
    button = _FakeButton("OK")
    _dismiss_known_popups(_FakeDriver([button]))
    assert button.click_count == 1


def test_dismisses_update_later_button_case_insensitive():
    button = _FakeButton("Update Later")
    _dismiss_known_popups(_FakeDriver([button]))
    assert button.click_count == 1

    button2 = _FakeButton("UPDATE LATER")
    _dismiss_known_popups(_FakeDriver([button2]))
    assert button2.click_count == 1


def test_does_not_click_real_business_buttons():
    buttons = [
        _FakeButton("Close"),
        _FakeButton("Cancel"),
        _FakeButton("Submit"),
        _FakeButton("Send to Supervisor"),
        _FakeButton("Yes"),
        _FakeButton("No"),
    ]
    _dismiss_known_popups(_FakeDriver(buttons))
    assert all(b.click_count == 0 for b in buttons)


def test_ignores_hidden_or_disabled_matching_buttons():
    hidden = _FakeButton("OK", displayed=False)
    disabled = _FakeButton("OK", enabled=False)
    _dismiss_known_popups(_FakeDriver([hidden, disabled]))
    assert hidden.click_count == 0
    assert disabled.click_count == 0


def test_dismisses_multiple_chained_popups_in_one_call():
    first = _FakeButton("OK")
    second = _FakeButton("Update Later")
    driver = _FakeDriver([first, second])
    _dismiss_known_popups(driver, max_dismissals=5)
    assert first.click_count == 1
    assert second.click_count == 1


def test_stops_after_max_dismissals_to_avoid_infinite_loop():
    button = _AlwaysVisibleButton("OK")
    _dismiss_known_popups(_FakeDriver([button]), max_dismissals=3)
    assert button.click_count == 3
