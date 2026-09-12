"""Calendar contracts use fictional sailings and credentials; no network or notifications."""
import copy
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'config', c.CruiseAppConfig())
    monkeypatch.setattr(c, 'log', Mock())
    monkeypatch.setattr(c, 'log_warn', Mock())
    monkeypatch.setattr(c, '_execute_api_request', Mock(side_effect=AssertionError('Unmocked network call')))
    sailing = c.CalendarSailing('IC', '20991010', 'America/New_York')
    settings = c.CalendarSettings((sailing,), str(tmp_path/'calendar'))
    account = c.AccountInfo('calendar@example.invalid', 'NOT_A_PASSWORD')
    account.access = c.APIAccess('NOT_A_TOKEN', 'fake-account', Mock())
    booking = {'shipCode': 'IC', 'sailDate': '20991010', 'bookingId': 'PRIVATE_BOOKING',
               'numberOfNights': 3, 'passengerId': 'PRIVATE_GUEST', 'stateroomNumber': '1234'}
    itinerary = {'shipCode': 'IC', 'shipName': 'Example Ship', 'canceled': False, 'itinerary': {'events': [
        {'day': 1, 'port': {'portType': 'EMBARK', 'portName': 'Example Departure',
                          'arrivalDateTime': '20991010T000000', 'departureDateTime': '20991010T163000'}},
        {'day': 2, 'port': {'portType': 'CRUISING', 'portName': 'Cruising',
                          'arrivalDateTime': '20991011T000000', 'departureDateTime': '20991011T235959'}},
        {'day': 3, 'port': {'portType': 'DOCKED', 'portName': 'Example Port',
                          'arrivalDateTime': '20991012T080000', 'departureDateTime': '20991012T180000'}},
        {'day': 4, 'port': {'portType': 'DEBARK', 'portName': 'Example Departure',
                          'arrivalDateTime': '20991013T060000', 'departureDateTime': '20991013T235959'}},
    ]}}
    checkin = {'checkWindowOpenStartDateTime': '2099-08-26T00:00:00.000Z', 'isCheckinAvailable': False}
    fetch = Mock(side_effect=lambda account, url: copy.deepcopy(checkin if url.endswith('/enriched') else itinerary))
    monkeypatch.setattr(c, 'calendar_sailing_payload', fetch)
    return settings, account, booking, itinerary, checkin, fetch


def run_capture(calendar, **kwargs):
    settings, account, booking, *_ = calendar
    export = c.CalendarExport(settings)
    export.capture(account, [booking], **kwargs)
    export.finish()
    return export


def events(export):
    return [e['fields'] for e in export.data['events'].values()]


def test_generation_excludes_sea_days_and_ignores_placeholders(calendar):
    export = run_capture(calendar)
    rows = events(export)
    assert len(rows) == 5
    assert not any('Cruising' in str(r) for r in rows)
    port = next(r for r in rows if 'Visit' in r['SUMMARY'])
    assert port['DTSTART'] == '20991012T080000'
    assert port['DTEND'] == '20991012T180000'
    assert 'ship time may differ' in port['DESCRIPTION']
    assert next(r for r in rows if ': Depart' in r['SUMMARY'])['DTSTART'] == '20991010T163000'
    arrive = next(r for r in rows if ': Arrive' in r['SUMMARY'])
    assert arrive['DTSTART'] == '20991013T060000' and 'DTEND' not in arrive
    payment = next(r for r in rows if 'Final payment' in r['SUMMARY'])
    assert 'DTSTART;VALUE=DATE' in payment
    assert 'Estimated' in payment['DESCRIPTION']
    assert 'Cabin 1234' in payment['SUMMARY']
    for path in export.directory.iterdir():
        data = path.read_text()
        assert all(secret not in data for secret in ['PRIVATE_BOOKING','PRIVATE_GUEST','NOT_A_PASSWORD','NOT_A_TOKEN','calendar@example.invalid'])


@pytest.mark.parametrize('opening, expected', [('2099-08-26T00:00:00.000Z','20990826T040100Z'),
                                              ('2099-01-15T00:00:00.000Z','20990115T050100Z')])
def test_checkin_uses_written_date_at_0001_departure_zone(calendar, opening, expected):
    calendar[4]['checkWindowOpenStartDateTime'] = opening
    export = run_capture(calendar)
    row = next(r for r in events(export) if 'Check-in' in r['SUMMARY'])
    assert row['DTSTART'] == expected
    assert '00:01 in America/New_York' in row['DESCRIPTION']


def test_updates_keep_uid_and_increment_only_changed_event(calendar):
    first = run_capture(calendar)
    old = copy.deepcopy(first.data['events'])
    same = run_capture(calendar)
    assert same.data['events'] == old
    calendar[3]['itinerary']['events'][2]['port']['departureDateTime'] = '20991012T190000'
    changed = run_capture(calendar)
    assert set(changed.data['events']) == set(old)
    revised = [uid for uid in old if changed.data['events'][uid] != old[uid]]
    assert len(revised) == 1
    assert changed.data['events'][revised[0]]['sequence'] == 1


def test_failure_preserves_last_good_events_and_missing_booking_is_not_cancellation(calendar):
    first = run_capture(calendar)
    before = (first.directory/'cruises.ics').read_bytes()
    calendar[5].side_effect = c.CalendarError('request failed')
    failed = c.CalendarExport(calendar[0])
    failed.capture(calendar[1], [calendar[2]])
    with pytest.raises(c.CalendarError, match='incomplete'):
        failed.finish()
    assert (first.directory/'cruises.ics').read_bytes() == before
    missing = c.CalendarExport(calendar[0])
    with pytest.raises(c.CalendarError, match='incomplete'):
        missing.finish()
    assert (first.directory/'cruises.ics').read_bytes() == before


def test_open_checkin_without_date_retains_existing_opening(calendar):
    first = run_capture(calendar)
    calendar[4].pop('checkWindowOpenStartDateTime')
    calendar[4]['isCheckinAvailable'] = True
    again = run_capture(calendar)
    assert again.data['events'] == first.data['events']


def test_unknown_future_checkin_has_no_invented_date(calendar):
    calendar[4].pop('checkWindowOpenStartDateTime')
    export = run_capture(calendar)
    assert not any('Check-in' in r['SUMMARY'] for r in events(export))


def test_linked_accounts_dedupe_itinerary_and_bookings_but_keep_distinct_cabins(calendar):
    export = c.CalendarExport(calendar[0])
    export.capture(calendar[1], [calendar[2]])
    export.capture(replace(calendar[1], username='second@example.invalid'),
                   [calendar[2], dict(calendar[2], bookingId='ANOTHER_BOOKING', stateroomNumber='5678')])
    export.finish()
    assert calendar[5].call_count == 2
    assert len([r for r in events(export) if 'Final payment' in r['SUMMARY']]) == 2
    assert len([r for r in events(export) if 'Visit' in r['SUMMARY']]) == 1


@pytest.mark.parametrize('mutation', [
    lambda info: info.update(itinerary={'events': []}),
    lambda info: info['itinerary']['events'][2]['port'].update(departureDateTime=None),
    lambda info: info['itinerary']['events'][2]['port'].update(portType='UNRECOGNIZED'),
    lambda info: info['itinerary']['events'][2]['port'].update(arrivalDateTime='20991012T080000Z'),
    lambda info: info['itinerary']['events'][2]['port'].update(departureDateTime='20991012T070000'),
])
def test_invalid_partial_itinerary_preserves_prior_ports(calendar, mutation):
    first = run_capture(calendar)
    mutation(calendar[3])
    export = c.CalendarExport(calendar[0])
    export.capture(calendar[1], [calendar[2]])
    with pytest.raises(c.CalendarError): export.finish()
    assert export.data['events'] == first.data['events']


def test_payment_reuses_price_summary_and_existing_overrides(calendar):
    c.config.reservation_prices = [{'reservation': 'PRIVATE_BOOKING', 'finalPaymentDate': '2099-07-01'}]
    c.config.reservation_names = {'PRIVATE_BOOKING': 'Family cabin'}
    export = run_capture(calendar, payment_rows=[{'dedupe_key': 'PRIVATE_BOOKING|20991010',
                         'final_payment': date(2099,7,1), 'balance_due': False}])
    payment = next(r for r in events(export) if 'Final payment' in r['SUMMARY'])
    assert payment['DTSTART;VALUE=DATE'] == '20990701'
    assert payment['DESCRIPTION'] == 'Configured override. Paid'
    assert 'Family cabin' in payment['SUMMARY']


def test_explicit_sailing_removal_removes_its_events(calendar):
    first = run_capture(calendar)
    export = c.CalendarExport(c.CalendarSettings((), calendar[0].output_directory))
    export.finish()
    assert not export.data['events']
    assert not export.data['sailings']


def test_corrupt_capture_does_not_replace_feed(calendar):
    first = run_capture(calendar)
    before = (first.directory/'cruises.ics').read_bytes()
    (first.directory/'calendar-data.json').write_text('{broken')
    with pytest.raises(c.CalendarError): c.CalendarExport(calendar[0])
    assert (first.directory/'cruises.ics').read_bytes() == before


def test_failed_atomic_replace_keeps_previous_file(calendar, monkeypatch):
    first = run_capture(calendar)
    path = first.directory/'cruises.ics'
    before = path.read_bytes()
    monkeypatch.setattr(c.os, 'replace', Mock(side_effect=PermissionError('not writable')))
    with pytest.raises(PermissionError): c.calendar_atomic_write(path, b'new')
    assert path.read_bytes() == before
    assert not list(first.directory.glob('.calendar-*'))


def test_ics_escaping_and_unicode_folding():
    title = 'é' * 90 + ', port; room\\deck\nNew line'
    event = {'x': {'modified':'20990101T000000Z','sequence':0,'fields':{'SUMMARY':title,'DTSTART':'20991010T163000'}}}
    data = c.calendar_ics(event)
    assert all(len(line) <= 75 for line in data.split(b'\r\n'))
    text = data.decode().replace('\r\n ', '')
    assert 'SUMMARY:' + 'é'*90 + '\\, port\\; room\\\\deck\\nNew line\r\n' in text
    assert text.startswith('BEGIN:VCALENDAR\r\n') and text.endswith('END:VCALENDAR\r\n')


@pytest.mark.parametrize('raw', [[], {'enabled':'true'}, {'sailings':[]}, {'sailings':[{'ship':'IC','sailDate':'2099-10-10','departureTimeZone':'BAD_ZONE'}]},
    {'sailings':[{'ship':'IC','sailDate':'bad','departureTimeZone':'UTC'}]}])
def test_invalid_config_is_rejected_without_io(raw):
    with pytest.raises(ValueError): c.parse_calendar_config(raw)


def test_disabled_and_valid_config(tmp_path):
    assert c.parse_calendar_config(None) is None
    assert c.parse_calendar_config({'enabled':False}) is None
    raw = {'outputDirectory':str(tmp_path/'does-not-exist'), 'sailings':[{'ship':'IC','sailDate':'2099-10-10','departureTimeZone':'America/New_York'}]}
    result = c.parse_calendar_config(raw)
    assert result.sailings[0].key == 'IC20991010'
    assert not Path(result.output_directory).exists()


def test_capture_works_with_availability_only_and_all_watches_disabled(calendar, monkeypatch):
    settings, account, booking, *_ = calendar
    c.config.accounts = [account]
    monkeypatch.setattr(c, 'login', Mock(return_value=account.access))
    monkeypatch.setattr(c, 'availability_json', Mock(return_value={'payload':{'profileBookings':[booking]}}))
    monkeypatch.setattr(c, 'process_availability_bookings', Mock(return_value=True))
    availability = c.AvailabilitySettings((c.AvailabilityWatch('disabled','disabled','PRIVATE_BOOKING','show',enabled=False),), True, True)
    export = c.CalendarExport(settings)
    c.run_availability_only(availability, export)
    assert len(export.data['events']) == 5
    account.access.session.close.assert_called_once()


@pytest.mark.parametrize('failed', [False, True])
def test_main_exports_after_prices_and_reports_calendar_failure(calendar, monkeypatch, failed):
    settings, account, booking, *_ = calendar
    c.config.calendar = settings
    c.config.accounts = [account]
    c.config.history = Mock()
    c.config.output_watch_as_json = True
    monkeypatch.setattr(c, 'login', Mock(return_value=account.access))
    monkeypatch.setattr(c, 'get_profile', Mock(return_value=('OH', '', 0)))
    monkeypatch.setattr(c, 'get_ship_dictionary_web', Mock())
    order = []
    monkeypatch.setattr(c, 'get_voyages', Mock(side_effect=lambda *a, **k: order.append('prices') or [booking]))
    monkeypatch.setattr(c.CheckinPaymentTracker, 'print_table', lambda self: order.append('summary'))
    monkeypatch.setattr(c, 'write_watch_price_json', Mock(side_effect=lambda *a: order.append('json')))
    finish = c.CalendarExport.finish
    def export(self):
        order.append('calendar')
        finish(self)
    monkeypatch.setattr(c.CalendarExport, 'finish', export)
    if failed:
        calendar[5].side_effect = c.CalendarError('unavailable')
        with pytest.raises(c.CalendarError): c.main()
    else:
        c.main()
    assert order == ['prices', 'summary', 'json', 'calendar']
    assert c.config.history.finish_run.call_args.args[0] == ('error' if failed else 'ok')
    account.access.session.close.assert_called_once()


@pytest.mark.parametrize('payload', [None, {}, {'payload': {'sailingInfo': []}},
    {'errors': ['failed'], 'payload': {'sailingInfo': {'shipCode':'IC'}}}])
def test_sailing_response_validation(monkeypatch, payload):
    monkeypatch.setattr(c, '_execute_api_request', Mock(return_value=Mock(status_code=200, json=Mock(return_value=payload))))
    with pytest.raises(c.CalendarError): c.calendar_sailing_payload(None, 'https://example.invalid')



def test_confirmed_cancellation_without_itinerary_marks_existing_events(calendar):
    first = run_capture(calendar)
    calendar[3].update(canceled=True, itinerary={'events': []})
    canceled = run_capture(calendar)
    assert set(canceled.data['events']) == set(first.data['events'])
    assert all(row['STATUS'] == 'CANCELLED' for row in events(canceled))
    assert all(e['sequence'] == 1 for e in canceled.data['events'].values())
