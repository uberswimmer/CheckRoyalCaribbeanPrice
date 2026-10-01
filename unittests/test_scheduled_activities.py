"""Booked personal itineraries, using fictional identities and mocked HTTP only."""
import copy
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c


def guest(reservation="booking-1", identity="guest-1", name="EXAMPLE"):
    return {"reservationId": reservation, "id": identity, "firstName": name,
            "lastName": "PRIVATE_SURNAME", "dob": "PRIVATE_DOB", "orderCode": "PRIVATE_ORDER",
            "status": "BOOKED", "fulfillment": {"port": "Example Theater", "meetingTime": None}}


def item(identity="session-1", title="Example show", start="2099-10-11T20:15:00", end="2099-10-11T21:05:00"):
    return {"id": identity, "productSummary": {"id": "product-1", "title": title, "atYourLeisure": False},
            "offering": {"dateTime": start, "endDateTime": end}, "guests": [guest()]}


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "config", c.CruiseAppConfig(date_display_format="%Y-%m-%d"))
    monkeypatch.setattr(c, "history", Mock())
    monkeypatch.setattr(c, "log", Mock())
    monkeypatch.setattr(c, "log_warn", Mock())
    monkeypatch.setattr(c.time, "sleep", Mock())
    account = c.AccountInfo("example@example.invalid", "NOT_A_PASSWORD")
    account.access = c.APIAccess("NOT_A_TOKEN", "NOT_AN_ACCOUNT_ID", Mock())
    booking = {"bookingId": "booking-1", "passengerId": "guest-1", "shipCode": "IC", "sailDate": "20991010",
               "numberOfNights": 7, "bookingCurrency": "USD"}
    payload = {"status": 200, "error": None, "warnings": None, "payload": {"itineraryItems": [item()]}}
    response = Mock(status_code=200, json=Mock(side_effect=lambda: copy.deepcopy(payload)))
    monkeypatch.setattr(c, "_execute_api_request", Mock(return_value=response))
    settings = c.ScheduledActivitiesSettings(("booking-1",), str(tmp_path / "scheduled.json"))
    return account, booking, payload, settings


def capture(context, settings=None, bookings=None):
    a, b, _, s = context
    report = c.ScheduledActivitiesReport(settings or s)
    report.capture(a, [b] if bookings is None else bookings, Mock(get_ship=Mock(return_value="ICON OF THE SEAS")))
    return report


def run(context, **kwargs):
    report = capture(context, **kwargs)
    report.finish()
    return report


def state(context):
    return c.read_scheduled_activities_state(Path(context[3].state_file))


def rows(context):
    return c.group_booked_activities(state(context)["snapshots"])


def output():
    return "\n".join(str(call.args[0]) for call in c.log.call_args_list)


def test_opt_in_config_and_loading(tmp_path, monkeypatch):
    assert c.CruiseAppConfig().scheduled_activities is None
    assert c.parse_scheduled_activities_config(None) is None
    expected = c.ScheduledActivitiesSettings(("1234567", "7654321"), "data/scheduled-activities.json")
    raw = {"reservations": [1234567, " 7654321 "]}
    assert c.parse_scheduled_activities_config(raw) == expected
    path = tmp_path / "config.yaml"
    path.write_text("accountInfo: []\nscheduledActivities:\n  reservations: ['1234567', '7654321']\n")
    monkeypatch.setattr(c, "setup_hybrid_logging", Mock())
    assert c.load_config_objects(str(path)).scheduled_activities == expected


@pytest.mark.parametrize("raw", [False, True, [], {}, {"reservations": []}, {"reservations": "123"},
    {"reservations": [None]}, {"reservations": [True]}, {"reservations": [1.5]}, {"reservations": [""]},
    {"reservations": ["a\n"]}, {"reservations": [123, "123"]}, {"reservations": ["a"], "enabled": True},
    {"reservations": ["a"], "stateFile": " "}, {"reservations": ["a"], "stateFile": None}])
def test_invalid_config_is_rejected(raw):
    with pytest.raises(ValueError, match="scheduledActivities"):
        c.parse_scheduled_activities_config(raw)


def test_readable_identity_allowlist_request_and_report(context):
    a, b, payload, _ = context
    payload["payload"]["itineraryItems"][0]["guests"].append(guest("UNSELECTED_BOOKING", "UNSELECTED_GUEST", "UNSELECTED"))
    run(context)
    call = c._execute_api_request.call_args
    assert call.args[:2] == (a, "GET")
    assert call.args[2].endswith("/calendar/v1/itinerary")
    assert call.kwargs["params"] == {"passengerId": "guest-1", "reservationId": "booking-1", "sailingId": "IC20991010",
        "currencyIso": "USD", "includeMedia": "false", "includeAllBookings": "true"}
    assert call.kwargs["on_failure"] == "retry"
    row = rows(context)[0]
    assert json.loads(row["id"]) == ["IC", "2099-10-10", "product-1", "session-1"]
    assert row["guests"] == {'["booking-1","guest-1"]': "Example"}
    assert 'Scheduled Activities & Reservations' in output()
    assert '20:15–21:05  Example show' in output()
    assert "Example | Example Theater" in output()
    saved = Path(context[3].state_file).read_text()
    assert all(value in saved for value in ("booking-1", "guest-1", "session-1", "product-1"))
    assert not any(value in saved + output() for value in ("PRIVATE_SURNAME", "PRIVATE_DOB", "PRIVATE_ORDER",
        "UNSELECTED", "NOT_A_PASSWORD", "NOT_A_TOKEN", "NOT_AN_ACCOUNT_ID", a.username))


def test_parser_grouping_pure_and_linked_cabins_deduplicated(context):
    a, b, payload, s = context
    payload["payload"]["itineraryItems"][0]["guests"].append(guest("booking-2", "guest-2", "SECOND"))
    original = copy.deepcopy(payload)
    settings = replace(s, reservations=("booking-1", "booking-2"))
    report = capture(context, settings=settings, bookings=[b, dict(b, bookingId="booking-2")])
    report.capture(replace(a, username="linked@example.invalid"), [b], Mock())
    assert c._execute_api_request.call_count == 2
    report.finish()
    snapshots = state(context)["snapshots"]
    saved = copy.deepcopy(snapshots)
    grouped = c.group_booked_activities(snapshots)
    assert len(grouped) == 1 and set(grouped[0]["guests"].values()) == {"Example", "Second"}
    grouped[0]["guests"].clear()
    grouped[0]["scopes"].clear()
    assert snapshots == saved and payload == original
    assert output().count("20:15–21:05  Example show") == 1


def test_reschedule_identity_stable_rebooking_changes_identity(context):
    run(context)
    before = rows(context)[0]["id"]
    activity = context[2]["payload"]["itineraryItems"][0]
    activity["productSummary"]["title"] = "Renamed show"
    activity["offering"].update(dateTime="2099-10-11T19:00:00", endDateTime="2099-10-11T20:00:00")
    run(context)
    assert rows(context)[0]["id"] == before
    activity["id"] = "session-2"
    run(context)
    assert len(rows(context)) == 1 and rows(context)[0]["id"] != before


@pytest.mark.parametrize("mode", ["empty", "CANCELLED", "CANCELED"])
def test_only_complete_success_removes_activities(context, mode):
    run(context)
    payload = context[2]["payload"]
    if mode == "empty":
        payload["itineraryItems"] = []
    else:
        payload["itineraryItems"][0]["guests"][0]["status"] = mode
    run(context)
    assert rows(context) == []
    assert "No scheduled activities in the captured snapshot(s)" in output()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(error="SECRET_ERROR"), lambda p: p.update(warnings=["SECRET_WARNING"]),
    lambda p: p.update(status=206), lambda p: p.update(payload=None),
    lambda p: p["payload"].update(itineraryItems=None),
    lambda p: p["payload"]["itineraryItems"].append(None),
    lambda p: p["payload"]["itineraryItems"][0]["offering"].update(dateTime="2099-10-11"),
    lambda p: p["payload"]["itineraryItems"][0]["offering"].update(dateTime="2099-10-11T20:15:00Z"),
    lambda p: p["payload"]["itineraryItems"][0]["offering"].update(dateTime="2099-11-11T20:15:00"),
    lambda p: p["payload"]["itineraryItems"][0]["offering"].update(endDateTime="2099-10-11T19:00:00"),
    lambda p: p["payload"]["itineraryItems"][0]["offering"].update(endDateTime="2099-10-19T20:15:00"),
    lambda p: p["payload"]["itineraryItems"][0]["guests"][0].update(status="SECRET_STATUS"),
    lambda p: p["payload"]["itineraryItems"][0]["guests"][0].update(id=None),
    lambda p: p["payload"]["itineraryItems"][0]["guests"][0].update(reservationId=None),
    lambda p: p["payload"]["itineraryItems"][0]["productSummary"].update(title="\x00"),
])
def test_malformed_response_retains_last_successful_snapshot(context, mutate):
    run(context)
    before = state(context)
    mutate(context[2])
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before
    assert "STALE" in output()
    assert "SECRET_" not in output() + str(c.log_warn.call_args_list)


@pytest.mark.parametrize("failure", ["none", "http", "json", "exception"])
def test_transport_failure_and_first_failure_are_not_empty_success(context, failure):
    run(context)
    before = state(context)
    request = c._execute_api_request
    if failure == "none":
        request.return_value = None
    elif failure == "http":
        request.return_value.status_code = 500
    elif failure == "json":
        request.return_value.json.side_effect = ValueError("SECRET_JSON")
    else:
        request.side_effect = RuntimeError("SECRET_EXCEPTION")
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before
    fresh = replace(context[3], state_file=str(Path(context[3].state_file).with_name("first.json")))
    with pytest.raises(c.ScheduledActivitiesError):
        run(context, settings=fresh)
    assert "No captured upcoming schedule available" in output()
    assert "SECRET_" not in str(c.log_warn.call_args_list)


def test_failed_capture_retried_once_through_other_account(context):
    a, b, _, _ = context
    response = c._execute_api_request.return_value
    c._execute_api_request.side_effect = [None, response]
    report = capture(context)
    report.capture(a, [b], Mock())
    assert c._execute_api_request.call_count == 1
    report.capture(replace(a, username="other@example.invalid"), [b], Mock(get_ship=Mock(return_value="ICON")))
    report.finish()
    assert c._execute_api_request.call_count == 2 and len(rows(context)) == 1


@pytest.mark.parametrize("category", ["pt_packages", "pt_internet", "pt_beverage"])
def test_only_known_explicitly_untimed_purchases_are_omitted(context, category):
    activity = context[2]["payload"]["itineraryItems"][0]
    activity["productSummary"]["productTypeCategory"] = {"id": category}
    run(context)
    assert len(rows(context)) == 1  # dated packages are still scheduled
    activity["offering"].update(dateTime=None, endDateTime=None)
    run(context)
    assert rows(context) == []
    activity["offering"]["dayOfCruise"] = 2
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)


def test_missing_appointment_time_is_not_an_untimed_purchase(context):
    run(context)
    before = state(context)
    context[2]["payload"]["itineraryItems"][0]["offering"].update(dateTime=None, endDateTime=None)
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before


def test_leisure_missing_end_overnight_and_explicit_duration(context):
    leisure = item("leisure", "Cabana")
    leisure["guests"][0]["fulfillment"]["meetingTime"] = "At Your Leisure"
    context[2]["payload"]["itineraryItems"] = [leisure,
        item("spa", "Treatment - 75 minutes", "2099-10-11T10:00:00", "2099-10-11T11:30:00"),
        item("no-end", "No end", "2099-10-12T10:00:00", None),
        item("equal-end", "Equal end", "2099-10-12T11:00:00", "2099-10-12T11:00:00"),
        item("overnight", "Overnight", "2099-10-12T23:00:00", "2099-10-13T01:00:00")]
    run(context)
    assert "At your leisure  Cabana" in output()
    assert "10:00–11:30  Treatment - 75 minutes" in output()
    assert "10:00  No end" in output() and "11:00  Equal end" in output()
    assert "23:00–2099-10-13 01:00  Overnight" in output()
    assert next(r for r in rows(context) if r["title"] == "Cabana")["end"] is None


def test_linked_cabin_conflicts_preserve_entire_sailing(context):
    a, b, payload, s = context
    payload["payload"]["itineraryItems"][0]["guests"].append(guest("booking-2", "guest-2", "SECOND"))
    settings = replace(s, reservations=("booking-1", "booking-2"))
    bookings = [b, dict(b, bookingId="booking-2")]
    run(context, settings=settings, bookings=bookings)
    before = state(context)
    payload["payload"]["itineraryItems"][0]["productSummary"]["title"] = "Changed"
    report = capture(context, settings=settings)  # second cabin is missing, retain its snapshot
    with pytest.raises(c.ScheduledActivitiesError):
        report.finish()
    assert state(context) == before
    assert "conflicting booked activity details" in str(c.log_warn.call_args_list)
    run(context, settings=settings, bookings=bookings)
    assert rows(context)[0]["title"] == "Changed"  # both cabins change together


def test_explicit_selection_removal_prunes_guests(context):
    _, b, payload, s = context
    payload["payload"]["itineraryItems"][0]["guests"].append(guest("booking-2", "guest-2", "SECOND"))
    run(context, settings=replace(s, reservations=("booking-1", "booking-2")), bookings=[b, dict(b, bookingId="booking-2")])
    run(context)
    assert len(state(context)["snapshots"]) == 1
    assert "guest-2" not in Path(s.state_file).read_text()


@pytest.mark.parametrize("bookings", [[], None, [None]])
def test_missing_or_failed_bookings_preserve_snapshots(context, bookings):
    run(context)
    before = state(context)
    report = c.ScheduledActivitiesReport(context[3])
    report.capture(context[0], bookings, Mock())
    with pytest.raises(c.ScheduledActivitiesError):
        report.finish()
    assert state(context) == before


@pytest.mark.parametrize("contents", [b"", b"not json", b"null", b"[]", b"{}", b"\xff",
    b'{"version":true,"snapshots":{}}', b'{"version":2,"snapshots":{}}',
    b'{"version":1,"snapshots":{},"unexpected":true}', b'{"version":1,"snapshots":{"bad":{}}}'])
def test_corrupt_state_is_never_overwritten(context, contents):
    path = Path(context[3].state_file)
    path.write_bytes(contents)
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert path.read_bytes() == contents


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_atomic_write_failure_preserves_previous_file(context, monkeypatch, operation):
    run(context)
    path = Path(context[3].state_file)
    before = path.read_bytes()
    context[2]["payload"]["itineraryItems"] = []
    monkeypatch.setattr(c.os, operation, Mock(side_effect=OSError("SECRET_DISK")))
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))
    assert "SECRET_DISK" not in str(c.log_warn.call_args_list)


def test_lock_contention_never_changes_state(context):
    run(context)
    path = Path(context[3].state_file)
    before = path.read_bytes()
    with c.cabin_state_lock(path):
        with pytest.raises(c.ScheduledActivitiesError):
            run(context)
    assert path.read_bytes() == before
    assert "overlapping checks" in str(c.log_warn.call_args_list)


def main_setup(context, monkeypatch):
    a, b, _, settings = context
    c.config.accounts = [a]
    c.config.scheduled_activities = settings
    monkeypatch.setattr(c, "login", Mock(side_effect=lambda account: account.access))
    monkeypatch.setattr(c, "get_profile", Mock(return_value=("OH", "", 0)))
    monkeypatch.setattr(c, "get_ship_dictionary_web", Mock())
    monkeypatch.setattr(c, "get_voyages", Mock(return_value=[b]))
    monkeypatch.setattr(c, "CheckinPaymentTracker", Mock(return_value=Mock()))
    monkeypatch.setattr(c, "write_watch_price_json", Mock())
    return a


def test_main_disabled_has_no_requests_or_state(context, monkeypatch):
    main_setup(context, monkeypatch)
    c.config.scheduled_activities = None
    c.main()
    c._execute_api_request.assert_not_called()
    assert not Path(context[3].state_file).exists()


def test_main_independent_of_price_display_and_notifications(context, monkeypatch):
    a = main_setup(context, monkeypatch)
    c.config.display_cruise_prices = False
    c.config.apobj = None
    c.config.ignored_price_alerts = [c.PriceAlertExclusion("booking-1", "pt_show", "product-1")]
    c.main()
    assert len(rows(context)) == 1
    a.access.session.close.assert_called_once()
    c.history.finish_run.assert_called_once_with("ok")


@pytest.mark.parametrize("failure", ["activities", "availability", "login", "casino_only", "celebrity"])
def test_main_finalization_and_partial_failure(context, monkeypatch, failure):
    a = main_setup(context, monkeypatch)
    c.config.output_watch_as_json = True
    order = []
    c.CheckinPaymentTracker.return_value.print_table.side_effect = lambda: order.append("prices")
    c.write_watch_price_json.side_effect = lambda *args: order.append("json")
    c.log.side_effect = lambda line: order.append("schedule") if "Scheduled Activities & Reservations" in str(line) else None
    c.history.finish_run.side_effect = lambda *args: order.append("history")
    if failure == "activities":
        c._execute_api_request.return_value = None
    elif failure == "availability":
        c.config.availability = c.AvailabilitySettings((c.AvailabilityReservation("booking-1", (c.AvailabilityCategory("show"),)),))
        monkeypatch.setattr(c, "process_availability_bookings", Mock(return_value=False))
    elif failure == "login":
        c.login.side_effect = SystemExit(1)
    elif failure == "casino_only":
        a.casino_offers_only = True
        c.config.check_casino_offers = True
        monkeypatch.setattr(c, "check_casino_offers", Mock())
    else:
        a.cruise_line = "celebrity"
    with pytest.raises(SystemExit) as exc:
        c.main()
    assert exc.value.code == c.EXIT_PARTIAL_FAILURE
    assert order == ["prices", "json", "schedule", "history"]
    assert c.history.finish_run.call_args.args[0] == "partial_failure"
    if failure != "login":
        a.access.session.close.assert_called_once()
    if failure in {"casino_only", "celebrity", "login"}:
        c._execute_api_request.assert_not_called()
    if failure == "casino_only":
        c.get_voyages.assert_not_called()
        assert "casinoOffersOnly" in str(c.log_warn.call_args_list)


def test_optional_failure_does_not_skip_later_accounts(context, monkeypatch):
    a = main_setup(context, monkeypatch)
    other = replace(a, username="other@example.invalid", access=c.APIAccess("fake", "other", Mock()))
    c.config.accounts.append(other)
    response = c._execute_api_request.return_value
    c._execute_api_request.side_effect = [None, response]
    c.main()
    assert c.get_voyages.call_count == 2
    assert len(rows(context)) == 1
    a.access.session.close.assert_called_once()
    other.access.session.close.assert_called_once()


@pytest.mark.parametrize("change", [
    lambda p: p["payload"]["itineraryItems"].append(item(title="Conflicting duplicate")),
    lambda p: p["payload"]["itineraryItems"][0]["guests"].append(guest(name="Conflicting duplicate")),
])
def test_duplicate_session_or_guest_conflict_cannot_overwrite_snapshot(context, change):
    run(context)
    before = state(context)
    change(context[2])
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before


@pytest.mark.parametrize("change", [
    lambda s: s.update(capturedAt="2099-10-10T00:00:00"),
    lambda s: s.update(capturedAt="not-a-timestamp"),
    lambda s: s.update(reservation="wrong"),
    lambda s: s.update(nights=True), lambda s: s.update(nights=-1),
    lambda s: s.update(items={}), lambda s: s.update(shipName="\x1b[31m"),
    lambda s: s["items"][0].update(id="hashed-or-old-identity"),
    lambda s: s["items"][0].update(id='["IC","2099-10-10","wrong"]'),
    lambda s: s["items"][0].update(title=""),
    lambda s: s["items"][0].update(start="2099-10-11"),
    lambda s: s["items"][0].update(start="21001011T100000"),
    lambda s: s["items"][0].update(end="20991011T100000"),
    lambda s: s["items"][0].update(leisure=True),
    lambda s: s["items"][0].update(guests={}),
    lambda s: s["items"][0].update(guests={'["wrong","guest-1"]': "Example"}),
    lambda s: s["items"][0].update(secret="must not persist"),
])
def test_malformed_snapshot_fields_are_not_overwritten(context, change):
    run(context)
    saved = state(context)
    change(next(iter(saved["snapshots"].values())))
    path = Path(context[3].state_file)
    path.write_text(json.dumps(saved))
    before = path.read_bytes()
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [lambda b: b.update(sailDate="20991012"), lambda b: b.update(numberOfNights=9)])
def test_ambiguous_booking_context_preserves_state(context, change):
    run(context)
    before = state(context)
    a, b, _, _ = context
    report = capture(context)
    other = dict(b)
    change(other)
    report.capture(replace(a, username="linked@example.invalid"), [other], Mock())
    with pytest.raises(c.ScheduledActivitiesError):
        report.finish()
    assert state(context) == before
    assert "conflicting sailing details" in str(c.log_warn.call_args_list)


def test_unselected_and_completed_bookings_do_not_fetch(context):
    a, b, _, s = context
    report = capture(context, bookings=[dict(b, bookingId="unselected"), dict(b, sailDate="20001010")])
    report.finish()
    c._execute_api_request.assert_not_called()
    assert "No upcoming selected sailings" in output()


def test_sailings_sort_by_date_not_ship_and_independent_failure_preserves_success(context):
    a, b, payload, s = context
    settings = replace(s, reservations=("booking-1", "booking-2", "booking-3"))
    report = capture(context, settings=settings)
    earlier = dict(b, bookingId="booking-2", shipCode="ZZ", sailDate="20990810")
    payload["payload"]["itineraryItems"] = [item(start="2099-08-11T20:00:00", end=None)]
    payload["payload"]["itineraryItems"][0]["guests"] = [guest("booking-2", "guest-2", "SECOND")]
    report.capture(a, [earlier], Mock(get_ship=Mock(return_value="ZZ SHIP")))
    with pytest.raises(c.ScheduledActivitiesError):
        report.finish()
    assert len(state(context)["snapshots"]) == 2
    assert output().index("ZZ SHIP (2099-08-10)") < output().index("ICON OF THE SEAS (2099-10-10)")
    assert "Schedule may be incomplete" in output()


def test_newer_concurrent_capture_wins(context):
    older = capture(context)
    context[2]["payload"]["itineraryItems"][0]["productSummary"]["title"] = "Newer title"
    run(context)
    before = state(context)
    older.finish()
    assert state(context) == before
    assert rows(context)[0]["title"] == "Newer title"


def test_successful_rebinding_removes_old_sailing_only_after_capture(context):
    run(context)
    context[1]["shipCode"] = "ZZ"
    c._execute_api_request.return_value.json.side_effect = ValueError("invalid JSON")
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert next(iter(state(context)["snapshots"].values()))["ship"] == "IC"
    c._execute_api_request.return_value.json.side_effect = lambda: copy.deepcopy(context[2])
    run(context)
    assert len(state(context)["snapshots"]) == 1
    assert next(iter(state(context)["snapshots"].values()))["ship"] == "ZZ"


def test_shared_request_pacing_is_reused(context):
    a = context[0]
    a._reservation_request_finished = c.time.monotonic()
    run(context)
    assert c.time.sleep.call_count == 1
    assert 0 < c.time.sleep.call_args.args[0] <= c.RESERVATION_REQUEST_INTERVAL_SECONDS


def test_royal_capture_not_invalidated_by_same_id_in_other_brand(context):
    a, b, _, _ = context
    report = capture(context)
    report.capture(replace(a, cruise_line="celebrity"), [b], Mock())
    report.finish()
    assert len(rows(context)) == 1
    assert c._execute_api_request.call_count == 1


def test_parser_is_pure_and_does_not_modify_payload(context):
    payload = context[2]
    original = copy.deepcopy(payload)
    parsed = c.parse_booked_activities(payload, ship="IC", sail_date=c.date(2099, 10, 10),
                                      reservation="booking-1", nights=7)
    assert len(parsed) == 1 and payload == original
    c._execute_api_request.assert_not_called()
    c.log.assert_not_called()
    c.log_warn.assert_not_called()


@pytest.mark.parametrize("key,value", [("shipCode", None), ("sailDate", "invalid"), ("numberOfNights", 0),
    ("numberOfNights", True), ("numberOfNights", 7.5), ("passengerId", None)])
def test_invalid_booking_context_cannot_request_or_replace(context, key, value):
    run(context)
    before = state(context)
    c._execute_api_request.reset_mock()
    context[1][key] = value
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    c._execute_api_request.assert_not_called()
    assert state(context) == before


def test_disabled_feature_does_not_touch_existing_state(context, monkeypatch):
    run(context)
    before = Path(context[3].state_file).read_bytes()
    main_setup(context, monkeypatch)
    c.config.scheduled_activities = None
    c._execute_api_request.reset_mock()
    c.main()
    assert Path(context[3].state_file).read_bytes() == before
    c._execute_api_request.assert_not_called()


@pytest.mark.parametrize("value", [False, 0, {}, "", "2099-10-11"])
def test_malformed_end_is_not_treated_as_missing(context, value):
    run(context)
    before = state(context)
    context[2]["payload"]["itineraryItems"][0]["offering"]["endDateTime"] = value
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before


def test_id_whitespace_is_not_silently_normalized(context):
    run(context)
    before = state(context)
    context[2]["payload"]["itineraryItems"][0]["id"] = "session-1\n"
    with pytest.raises(c.ScheduledActivitiesError):
        run(context)
    assert state(context) == before
