"""Personal itinerary contracts, using fictional guests/sailings and mocked HTTP."""
import copy
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c
from unittests.test_calendar import calendar, run_capture, events


def guest(reservation='PRIVATE_BOOKING', pid='PRIVATE_GUEST', name='EXAMPLE'):
    return {'reservationId':reservation, 'id':pid, 'firstName':name, 'lastName':'PRIVATE_SURNAME',
            'dob':'PRIVATE_BIRTHDATE', 'orderCode':'PRIVATE_ORDER', 'status':'BOOKED',
            'fulfillment':{'port':'Example Theater','meetingTime':None}}


def item(identity='SESSION_A', title='Example show', start='2099-10-11T20:15:00', end='2099-10-11T21:05:00'):
    return {'id':identity, 'productSummary':{'id':'PRODUCT_A','title':title, 'atYourLeisure':False},
            'offering':{'id':identity,'dateTime':start,'endDateTime':end},
            'guests':[guest()]}


@pytest.fixture
def activities(calendar, monkeypatch):
    calendar = (replace(calendar[0], include_activities=True), *calendar[1:])
    payload = {'status':200, 'error':None, 'warnings':None, 'payload':{'itineraryItems':[item()]}}
    response = Mock(status_code=200, json=Mock(side_effect=lambda:copy.deepcopy(payload)))
    monkeypatch.setattr(c, '_execute_api_request', Mock(return_value=response))
    return calendar, payload


def activity_events(export):
    return {k:v for k,v in export.data['events'].items() if v.get('activitySailing')}


def test_request_and_schedule_are_shared_by_feed_report_and_private_capture(activities):
    calendar, payload = activities
    show = payload['payload']['itineraryItems'][0]
    show['guests'].append(guest('UNSELECTED_BOOKING','OTHER_GUEST','UNSELECTED'))
    export = run_capture(calendar)
    call = c._execute_api_request.call_args
    assert call.args[1] == 'GET' and call.args[2].endswith('/calendar/v1/itinerary')
    assert call.kwargs['params'] == {'passengerId':'PRIVATE_GUEST','reservationId':'PRIVATE_BOOKING',
        'sailingId':'IC20991010','currencyIso':'USD','includeMedia':'false','includeAllBookings':'true'}
    event = next(iter(activity_events(export).values()))['fields']
    assert event['DTSTART'] == '20991011T201500' and event['DTEND'] == '20991011T210500'
    assert event['LOCATION'] == 'Example Theater' and 'Guests: Example' in event['DESCRIPTION']
    report = '\n'.join(str(call.args[0]) for call in c.log.call_args_list)
    assert 'Scheduled Activities & Reservations' in report
    assert '20:15–21:05' in report and 'Example show' in report
    for path in export.directory.iterdir():
        text = path.read_text()
        assert not any(v in text for v in ['PRIVATE_BOOKING','PRIVATE_GUEST','PRIVATE_SURNAME',
            'PRIVATE_BIRTHDATE','PRIVATE_ORDER','UNSELECTED','SESSION_A','NOT_A_TOKEN','calendar@example.invalid'])


def test_leisure_overrides_placeholder_and_spa_uses_explicit_interval(activities):
    calendar, payload = activities
    spa = item('SPA','Treatment - 75 minutes','2099-10-11T10:00:00','2099-10-11T11:30:00')
    leisure = item('CABANA','Example cabana','2099-10-12T09:30:00','2099-10-12T09:30:00')
    leisure['guests'][0]['fulfillment']['meetingTime'] = 'At Your Leisure'
    payload['payload']['itineraryItems'] = [spa,leisure]
    export = run_capture(calendar)
    rows = [e['fields'] for e in activity_events(export).values()]
    spa_row = next(r for r in rows if '75 minutes' in r['SUMMARY'])
    assert spa_row['DTEND'] == '20991011T113000'
    cabana = next(r for r in rows if 'cabana' in r['SUMMARY'])
    assert cabana['DTSTART;VALUE=DATE'] == '20991012'
    assert 'DTSTART' not in cabana and 'DTEND' not in cabana and cabana['TRANSP'] == 'TRANSPARENT'
    assert 'At your leisure' in str(c.log.call_args_list)


def test_reschedule_updates_same_uid_and_rebooking_cancels_old_session(activities):
    calendar, payload = activities
    first = activity_events(run_capture(calendar))
    assert activity_events(run_capture(calendar)) == first
    row = payload['payload']['itineraryItems'][0]
    row['offering'].update(dateTime='2099-10-11T19:15:00',endDateTime='2099-10-11T20:05:00')
    changed = activity_events(run_capture(calendar))
    assert set(changed) == set(first)
    assert next(iter(changed.values()))['sequence'] == 1
    row.update(id='SESSION_B')
    new = activity_events(run_capture(calendar))
    assert len(new) == 2 and new[next(iter(first))]['fields']['STATUS'] == 'CANCELLED'
    assert sum(v['fields'].get('STATUS') != 'CANCELLED' for v in new.values()) == 1


@pytest.mark.parametrize('mode', ['empty','cancelled'])
def test_complete_snapshot_removal_cancels_once(activities, mode):
    calendar, payload = activities
    first = activity_events(run_capture(calendar))
    if mode == 'empty': payload['payload']['itineraryItems'] = []
    else: payload['payload']['itineraryItems'][0]['guests'][0]['status'] = 'CANCELLED'
    canceled = activity_events(run_capture(calendar))
    assert set(canceled) == set(first)
    assert next(iter(canceled.values()))['fields']['STATUS'] == 'CANCELLED'
    assert next(iter(canceled.values()))['sequence'] == 1
    assert activity_events(run_capture(calendar)) == canceled


@pytest.mark.parametrize('mutation', [
    lambda p:p.update(error='failed'), lambda p:p.update(warnings=['partial']),
    lambda p:p['payload'].update(itineraryItems=None),
    lambda p:p['payload']['itineraryItems'][0]['offering'].update(dateTime='2099-10-11'),
    lambda p:p['payload']['itineraryItems'][0]['offering'].update(dateTime='2099-10-11T20:15:00Z'),
    lambda p:p['payload']['itineraryItems'][0]['offering'].update(dateTime='2099-11-11T20:15:00'),
    lambda p:p['payload']['itineraryItems'][0]['offering'].update(endDateTime='2099-10-11T19:00:00'),
    lambda p:p['payload']['itineraryItems'][0]['guests'][0].update(status='UNKNOWN'),
    lambda p:p['payload']['itineraryItems'][0]['guests'][0].update(reservationId=None),
])
def test_incomplete_or_ambiguous_response_retains_old_schedule(activities, mutation):
    calendar, payload = activities
    first = run_capture(calendar)
    mutation(payload)
    export = c.CalendarExport(calendar[0]); export.capture(calendar[1],[calendar[2]])
    with pytest.raises(c.CalendarError): export.finish()
    assert activity_events(export) == activity_events(first)
    assert 'previously captured' in str(c.log.call_args_list)


def test_timeout_does_not_cancel_and_failed_first_capture_is_not_empty(activities):
    calendar, _ = activities
    c._execute_api_request.return_value = None
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[calendar[2]])
    with pytest.raises(c.CalendarError): export.finish()
    assert 'schedule unavailable' in str(c.log.call_args_list)
    assert not activity_events(export)


def test_multiple_selected_cabins_dedupe_sessions_and_filter_guests(activities):
    calendar, payload = activities
    row = payload['payload']['itineraryItems'][0]
    row['guests'].extend([guest('SECOND_BOOKING','SECOND_GUEST','SECOND'),guest('THIRD_BOOKING','THIRD_GUEST','THIRD')])
    export = c.CalendarExport(calendar[0])
    bookings = [calendar[2],dict(calendar[2],bookingId='SECOND_BOOKING',passengerId='SECOND_GUEST')]
    export.capture(calendar[1],bookings); export.capture(calendar[1],bookings); export.finish()
    assert c._execute_api_request.call_count == 2
    assert len(activity_events(export)) == 1
    event = next(iter(activity_events(export).values()))['fields']
    assert 'Example, Second' in event['DESCRIPTION'] and 'Third' not in event['DESCRIPTION']


def test_removing_reservation_drops_its_guests_and_disabling_clears_activity_capture(activities):
    calendar, payload = activities
    row = payload['payload']['itineraryItems'][0]
    row['guests'].append(guest('SECOND_BOOKING','SECOND_GUEST','SECOND'))
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[calendar[2],dict(calendar[2],bookingId='SECOND_BOOKING')]);export.finish()
    settings = replace(calendar[0], sailings=(), reservations=('PRIVATE_BOOKING',))
    export = c.CalendarExport(settings); export.capture(calendar[1],[calendar[2]]); export.finish()
    assert 'Second' not in str(activity_events(export))
    disabled = replace(settings, include_activities=False)
    c._execute_api_request.reset_mock()
    export = c.CalendarExport(disabled); export.capture(calendar[1],[calendar[2]]); export.finish()
    c._execute_api_request.assert_not_called()
    assert not activity_events(export)
    assert 'activities' not in export.data['sailings']['IC20991010']


def test_optional_configuration():
    raw = {'reservations':['1000001']}
    assert not c.parse_calendar_config(raw).include_activities
    assert c.parse_calendar_config(dict(raw,includeActivities=True)).include_activities
    with pytest.raises(ValueError, match='includeActivities'):
        c.parse_calendar_config(dict(raw,includeActivities='true'))


def test_failed_refresh_after_good_capture_and_missing_booking_preserve_events(activities):
    calendar, _ = activities
    first = activity_events(run_capture(calendar))
    c._execute_api_request.return_value = Mock(status_code=403)
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[calendar[2]])
    with pytest.raises(c.CalendarError):export.finish()
    assert activity_events(export) == first
    missing = c.CalendarExport(calendar[0]);missing.capture(calendar[1],[])
    with pytest.raises(c.CalendarError):missing.finish()
    assert activity_events(missing) == first


def test_untimed_end_has_no_invented_duration_and_leisure_flag_is_supported(activities):
    calendar, payload = activities
    row = payload['payload']['itineraryItems'][0]
    row['offering']['endDateTime'] = None
    export = run_capture(calendar)
    assert 'DTEND' not in next(iter(activity_events(export).values()))['fields']
    row['productSummary']['atYourLeisure'] = True
    export = run_capture(calendar)
    assert 'DTSTART;VALUE=DATE' in next(iter(activity_events(export).values()))['fields']


def test_conflicting_selected_cabin_details_do_not_delete_previous_calendar(activities):
    calendar, payload = activities
    row = payload['payload']['itineraryItems'][0]
    row['guests'].append(guest('SECOND_BOOKING','SECOND_GUEST','SECOND'))
    bookings = [calendar[2],dict(calendar[2],bookingId='SECOND_BOOKING')]
    first = c.CalendarExport(calendar[0]);first.capture(calendar[1],bookings);first.finish()
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[bookings[0]])
    row['offering'].update(dateTime='2099-10-11T19:15:00')
    export.capture(calendar[1],[bookings[1]])
    with pytest.raises(c.CalendarError):export.finish()
    assert activity_events(export) == activity_events(first)


def test_availability_only_reuses_login_and_captures_booked_activities(activities, monkeypatch):
    calendar, _ = activities
    settings, account, booking, *_ = calendar
    c.config.accounts = [account]
    monkeypatch.setattr(c,'login',Mock(return_value=account.access))
    monkeypatch.setattr(c,'availability_json',Mock(return_value={'payload':{'profileBookings':[booking]}}))
    monkeypatch.setattr(c,'process_availability_bookings',Mock(return_value=True))
    availability = c.AvailabilitySettings((c.AvailabilityWatch('disabled','disabled','PRIVATE_BOOKING','show',enabled=False),),True,True)
    export = c.CalendarExport(settings)
    c.run_availability_only(availability,export)
    assert len(activity_events(export)) == 1
    account.access.session.close.assert_called_once()


def test_normal_run_includes_schedule_even_when_price_alert_is_ignored(activities, monkeypatch):
    calendar, _ = activities
    settings, account, booking, *_ = calendar
    c.config.calendar = settings
    c.config.accounts = [account]
    c.config.ignored_price_alerts = [c.PriceAlertExclusion('PRIVATE_BOOKING','pt_show','PRODUCT_A')]
    monkeypatch.setattr(c,'login',Mock(return_value=account.access))
    monkeypatch.setattr(c,'get_profile',Mock(return_value=('OH','',0)))
    monkeypatch.setattr(c,'get_ship_dictionary_web',Mock())
    monkeypatch.setattr(c,'get_voyages',Mock(return_value=[booking]))
    monkeypatch.setattr(c.CheckinPaymentTracker,'print_table',Mock())
    c.main()
    data = json.loads((c.Path(settings.output_directory)/'calendar-data.json').read_text())
    assert sum(bool(e.get('activitySailing')) for e in data['events'].values()) == 1
    assert 'Scheduled Activities & Reservations' in str(c.log.call_args_list)


def test_private_guest_removal_does_not_linger_in_canceled_tombstone(activities):
    calendar, payload = activities
    payload['payload']['itineraryItems'][0]['guests'].append(guest('SECOND_BOOKING','SECOND_GUEST','SECOND'))
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[calendar[2],dict(calendar[2],bookingId='SECOND_BOOKING')]);export.finish()
    payload['payload']['itineraryItems'] = []
    settings = replace(calendar[0],sailings=(),reservations=('PRIVATE_BOOKING',))
    export = c.CalendarExport(settings);export.capture(calendar[1],[calendar[2]]);export.finish()
    assert 'Second' not in json.dumps(export.data)


def test_new_reservation_failure_marks_partial_schedule_and_overnight_end(activities):
    calendar, payload = activities
    payload['payload']['itineraryItems'][0]['offering'].update(dateTime='2099-10-11T23:30:00',endDateTime='2099-10-12T00:30:00')
    export = c.CalendarExport(calendar[0]);export.capture(calendar[1],[calendar[2]])
    c._execute_api_request.return_value = None
    export.capture(calendar[1],[dict(calendar[2],bookingId='SECOND_BOOKING')])
    with pytest.raises(c.CalendarError):export.finish()
    assert 'schedule may be incomplete' in str(c.log.call_args_list)
    assert '23:30–00:30 (+1 day)' in str(c.log.call_args_list)
