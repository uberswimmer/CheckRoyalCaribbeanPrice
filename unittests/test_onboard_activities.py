"""Royal activity release alerts using upstream categories and readable v2 state."""
import copy
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c
from unittests.test_availability import capture, context, globals_without_network


@pytest.mark.parametrize('selection, products', [(True, None), ({'products': ['EXAMPLE_ESCAPE_A']}, ('EXAMPLE_ESCAPE_A',))])
def test_activity_selection_uses_upstream_reservation_schema(selection, products):
    settings = c.parse_availability_config({'reservations': [
        {'reservation': 'booking-1', 'onboardActivities': selection}]})
    assert settings.reservations[0].categories == (c.AvailabilityCategory('onboardActivities', products),)
    assert settings.dry_run


@pytest.mark.parametrize('selection', ['true', None, [], {}, {'products': []},
    {'products': ['A', 'A']}, {'products': [True]}, {'products': ['A'], 'mode': 'party'}])
def test_activity_selection_rejects_ambiguous_or_legacy_settings(selection):
    with pytest.raises(ValueError):
        c.parse_availability_config({'reservations': [
            {'reservation': 'booking-1', 'onboardActivities': selection}]})


def test_activities_remain_opt_in_and_can_be_disabled():
    for extra in ({}, {'onboardActivities': False}):
        settings = c.parse_availability_config({'reservations': [
            {'reservation': 'booking-1', 'shows': True, **extra}]})
        assert settings.reservations[0].categories == (c.AvailabilityCategory('show'),)


@pytest.mark.parametrize('fixture', ['escape_room_a', 'escape_room_b'])
def test_captured_activity_release_ignores_personal_age_and_conflicts(fixture):
    data = capture(fixture)
    result = c.evaluate_availability(data, 'onboardActivities', data['payload']['productCode'], 'Activity')
    assert result.state == 'available'
    assert result.times == tuple(o['dateTime'] for o in data['payload']['offerings'])
    assert c.evaluate_availability(data, 'show', data['payload']['productCode'], 'Activity').state == 'unknown'


@pytest.mark.parametrize('status, stock, expected', [('lowStock', 1, 'available'),
    ('inStock', 0, 'unavailable'), ('NEW_STATUS', 12, 'unknown')])
def test_activity_inventory_uses_upstream_release_rules(status, stock, expected):
    data = capture('escape_room_a')
    for offering in data['payload']['offerings']:
        offering.update(stockLevelStatus=status, stockLevel=stock)
    assert c.evaluate_availability(data, 'onboardActivities', 'EXAMPLE_ESCAPE_A', 'Activity').state == expected


def activity_context(context, selection=None):
    account, booking, show, settings, _ = context
    booking = dict(booking, shipCode='ST', sailDate='20990328')
    activity = c.AvailabilityCategory('onboardActivities', selection)
    settings = replace(settings, reservations=(c.AvailabilityReservation('booking-1', (show, activity)),))
    show_data = capture('headliner')
    for offering in show_data['payload']['offerings']:
        offering['dateTime'] = '2099-03-28' + offering['dateTime'][10:]
    payloads = {data['payload']['productCode']: data for data in
                (show_data, capture('escape_room_a'), capture('escape_room_b'))}
    products = [{'id': pid, 'title': pid, 'type': {'id': data['payload']['categoryId']}}
                for pid, data in payloads.items()]
    return account, booking, show, activity, settings, payloads, products


@pytest.mark.parametrize('selection', [None, ('EXAMPLE_ESCAPE_A',)])
def test_shared_catalog_routing_grouped_alerts_and_v2_restart(context, monkeypatch, selection):
    account, booking, show, activity, settings, payloads, products = activity_context(context, selection)
    calls = []

    def transport(a, method, url, **kwargs):
        assert a is account and method == 'POST'
        body = kwargs['json_data']
        if url.endswith('/graphql'):
            assert body['variables']['category'] == 'show'
            calls.append('catalog')
            answer = {'data': {'products': {'__typename': 'CommerceProductResultSuccess',
                'pageInfo': {'totalPages': 1, 'totalResults': len(products)}, 'commerceProducts': products}}}
        else:
            assert url.endswith('/eligibility/v1/eligibility')
            answer = payloads[body['productCode']]
            assert body['categoryId'] == answer['payload']['categoryId']
            assert body['cartId'] == ''
            calls.append(body['productCode'])
        return Mock(status_code=200, json=Mock(return_value=copy.deepcopy(answer)))

    monkeypatch.setattr(c, '_execute_api_request', transport)
    for _ in range(2):
        assert c.process_availability_bookings(account, [booking], settings)
    assert calls.count('catalog') == 2  # One fetch per run for both categories.
    assert calls.count(show.products[0]) == 2
    assert calls.count('EXAMPLE_ESCAPE_A') == 2
    assert calls.count('EXAMPLE_ESCAPE_B') == (0 if selection else 2)
    assert c.config.apobj.notify.call_count == 2  # One aggregate per category, then deduplicated.
    body = c.config.apobj.notify.call_args_list[1].kwargs['body']
    assert 'Onboard activities' in body and 'EXAMPLE_ESCAPE_A' in body
    assert show.products[0] not in body and '/category/pt_show?' in body
    state = json.loads(Path(settings.state_file).read_text())
    assert state['version'] == 2
    assert set(state['scopes']) == {c.availability_scope(account, booking, cat.category) for cat in (show, activity)}
    rows = state['scopes'][c.availability_scope(account, booking, activity.category)]
    assert len(rows) == (1 if selection else 2)
    assert all(row == {'last_state': 'available', 'notified': True} for row in rows.values())


@pytest.mark.parametrize('absent', [True, False])
def test_shared_absent_or_partial_catalog_preserves_activity_state(context, monkeypatch, absent):
    account, booking, show, activity, settings, payloads, products = activity_context(context)
    previous = c.AvailabilityResult('EXAMPLE_ESCAPE_B', 'Activity B', 'available', 'test', ('2099-03-29T11:00:00',))
    assert c.deliver_availability(settings, account, booking, activity, True, [previous])
    before = c.read_reservation_state(Path(settings.state_file))['scopes'][c.availability_scope(account, booking, activity.category)]['EXAMPLE_ESCAPE_B']
    retained = [p for p in products if p['id'] != 'EXAMPLE_ESCAPE_B']
    catalog = Mock(return_value=None) if absent else Mock(side_effect=c.AvailabilityCatalogIncomplete('truncated', retained))
    monkeypatch.setattr(c, 'availability_products', catalog)
    eligibility = Mock(side_effect=lambda a,b,cat,pid,party: payloads[pid])
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    assert c.process_availability_bookings(account, [booking], settings)
    catalog.assert_called_once_with(account, booking, 'show')
    after = c.read_reservation_state(Path(settings.state_file))['scopes'][c.availability_scope(account, booking, activity.category)]['EXAMPLE_ESCAPE_B']
    assert after == before
    assert eligibility.call_count == (0 if absent else 2)


@pytest.mark.parametrize('failure_point', ['catalog', 'eligibility'])
def test_transport_failure_pauses_both_entertainment_categories(context, monkeypatch, failure_point):
    account, booking, show, activity, settings, payloads, products = activity_context(context)
    catalog = Mock(return_value=products)
    eligibility = Mock(side_effect=c.AvailabilityRequestFailed('transport failed'))
    if failure_point == 'catalog':
        catalog.side_effect = c.AvailabilityCatalogIncomplete('transport failed', products, request_failed=True)
    monkeypatch.setattr(c, 'availability_products', catalog)
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    assert not c.process_availability_bookings(account, [booking], settings)
    catalog.assert_called_once()
    assert eligibility.call_count == (0 if failure_point == 'catalog' else 1)
    c.config.apobj.notify.assert_not_called()


def test_catalog_cache_never_crosses_accounts_or_bookings(context, monkeypatch):
    account, booking, show, activity, settings, payloads, products = activity_context(context)
    other_booking = dict(booking, bookingId='booking-2')
    other_account = c.AccountInfo('second@example.invalid', 'not-a-password')
    settings = replace(settings, dry_run=True, reservations=settings.reservations + (
        c.AvailabilityReservation('booking-2', (show, activity)),))
    catalog = Mock(return_value=[])
    monkeypatch.setattr(c, 'availability_products', catalog)
    for current_account in (account, other_account):
        assert c.process_availability_bookings(current_account, [booking, other_booking], settings)
    assert [(call.args[0].username, call.args[1]['bookingId'], call.args[2]) for call in catalog.call_args_list] == [
        (a.username, b['bookingId'], 'show') for a in (account, other_account) for b in (booking, other_booking)]


def test_unknown_activity_inventory_does_not_rearm_release(context):
    account, booking, show, activity, settings, payloads, products = activity_context(context)
    data = payloads['EXAMPLE_ESCAPE_A']
    result = c.evaluate_availability(data, activity.category, 'EXAMPLE_ESCAPE_A', 'Activity')
    assert c.deliver_availability(settings, account, booking, activity, True, [result])
    for offering in data['payload']['offerings']:
        offering['stockLevelStatus'] = 'NEW_STATUS'
    unknown = c.evaluate_availability(data, activity.category, 'EXAMPLE_ESCAPE_A', 'Activity')
    assert unknown.state == 'unknown'
    assert not c.deliver_availability(settings, account, booking, activity, True, [unknown])
    assert c.deliver_availability(settings, account, booking, activity, True, [result])
    c.config.apobj.notify.assert_called_once()
