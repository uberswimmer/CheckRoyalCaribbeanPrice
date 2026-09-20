"""Onboard activity eligibility, using reduced captures with fictional identities."""
import copy
import sqlite3
from dataclasses import replace
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c
from unittests.test_availability import (
    capture, context, globals_without_network, party_for, valid_config,
)


def activity_watch(product=None, mode='release'):
    return c.AvailabilityWatch('activities', 'Onboard activities', 'booking-1',
                               'onboardActivities', product, mode)


@pytest.mark.parametrize('product', [None, 'EXAMPLE_ESCAPE_A'])
def test_activity_configuration_supports_discovery_and_exact_product(product):
    raw = valid_config()
    raw['watches'][0]['category'] = 'onboardActivities'
    if product:
        raw['watches'][0]['product'] = product
    watch = c.parse_availability_config(raw).watches[0]
    assert watch.category == 'onboardActivities' and watch.product == product


@pytest.mark.parametrize('category', ['spa', 'onboardactivities', 'pt_onboardActivities', []])
def test_unverified_or_misspelled_categories_fail_configuration(category):
    raw = valid_config()
    raw['watches'][0]['category'] = category
    with pytest.raises(ValueError, match='category must be'):
        c.parse_availability_config(raw)


@pytest.mark.parametrize('fixture', ['escape_room_a', 'escape_room_b'])
def test_release_ignores_age_and_conflicts_while_party_honors_both(fixture):
    data = capture(fixture)
    product = data['payload']['productCode']
    party = party_for(data)
    release = c.evaluate_availability(data, activity_watch(), product, 'Escape room', party)
    assert release.state == 'available' and len(release.times) == 3
    restricted = c.evaluate_availability(data, activity_watch(mode='party'), product, 'Escape room', party)
    assert restricted.state == 'unavailable' and restricted.reason == 'guest age requirement not met'
    adults = c.evaluate_availability(data, activity_watch(mode='party'), product, 'Escape room', party[:2])
    assert adults.state == 'available'
    assert adults.times == tuple(o['dateTime'] for o in data['payload']['offerings'][:2])


@pytest.mark.parametrize('unit', [None, 'PER_GROUP'])
def test_activity_party_requires_supported_seat_inventory(unit):
    data = capture('escape_room_a')
    data['payload']['salesUnit'] = unit
    product = data['payload']['productCode']
    party = party_for(data)[:2]
    assert c.evaluate_availability(data, activity_watch(mode='party'), product, 'Activity', party).state == 'unknown'
    assert c.evaluate_availability(data, activity_watch(), product, 'Activity', party).state == 'available'


def test_activity_party_handles_insufficient_stock_and_unknown_restrictions():
    data = capture('escape_room_a')
    party = party_for(data)[:2]
    product = data['payload']['productCode']
    for offering in data['payload']['offerings'][:2]:
        offering['stockLevel'] = 1
    assert c.evaluate_availability(data, activity_watch(mode='party'), product, 'Activity', party).state == 'unavailable'
    data['payload']['guests'][0]['issues'].append({'type':'UNRECOGNIZED_RESTRICTION'})
    assert c.evaluate_availability(data, activity_watch(mode='party'), product, 'Activity', party).state == 'unknown'


@pytest.mark.parametrize('affected, available_count', [('guest-1', 1), ('guest-3', 2)])
def test_offering_age_restrictions_only_affect_selected_guests(affected, available_count):
    data = capture('escape_room_a')
    data['payload']['offerings'][0]['issues'] = [{'type':'AGE_REQUIREMENT_NOT_MET','guestId':affected}]
    result = c.evaluate_availability(data, activity_watch(mode='party'),
        data['payload']['productCode'], 'Activity', party_for(data)[:2])
    assert result.state == 'available' and len(result.times) == available_count


@pytest.mark.parametrize('product', [None, 'EXAMPLE_ESCAPE_A'])
def test_show_and_activity_watches_share_catalog_but_keep_types_and_alert_state(context, monkeypatch, product):
    account, booking, show_watch, settings, _ = context
    booking = dict(booking, shipCode='ST', sailDate='20990328')
    watch = activity_watch(product)
    settings = replace(settings, watches=(show_watch, watch))
    show = capture('headliner')
    for o in show['payload']['offerings']:
        o['dateTime'] = '2099-03-28' + o['dateTime'][10:]
    payloads = {p['payload']['productCode']: p for p in
                (show, capture('escape_room_a'), capture('escape_room_b'))}
    products = [{'id':pid, 'title':pid, 'type':{'id':data['payload']['categoryId']}}
                for pid, data in payloads.items()]
    catalog = {'data':{'products':{'__typename':'CommerceProductResultSuccess',
        'pageInfo':{'totalPages':1,'totalResults':len(products)},'commerceProducts':products}}}
    calls = []
    def transport(a, method, url, **kwargs):
        assert a is account and method == 'POST'
        body = kwargs['json_data']
        if url.endswith('/graphql'):
            assert body['variables']['category'] == 'show'
            calls.append('catalog')
            answer = catalog
        else:
            assert url.endswith('/eligibility/v1/eligibility')
            answer = payloads[body['productCode']]
            assert body['categoryId'] == answer['payload']['categoryId']
            calls.append(body['productCode'])
        return Mock(status_code=200, json=Mock(return_value=copy.deepcopy(answer)))
    monkeypatch.setattr(c, '_execute_api_request', transport)
    for _ in range(2):
        assert c.process_availability_bookings(account, [booking], settings)
    assert calls.count('catalog') == 2
    assert calls.count('EXAMPLE_ESCAPE_A') == 2
    assert calls.count('EXAMPLE_ESCAPE_B') == (0 if product else 2)
    assert c.config.apobj.notify.call_count == 2
    activity_body = c.config.apobj.notify.call_args_list[1].kwargs['body']
    assert 'EXAMPLE_ESCAPE_A' in activity_body and show_watch.product not in activity_body
    assert '/category/pt_show?' in activity_body  # Link to the observed storefront page.
    with sqlite3.connect(settings.state_file) as db:
        rows = db.execute('SELECT product, notified FROM availability_v1').fetchall()
    assert len(rows) == (2 if product else 3) and all(n == 1 for _, n in rows)


def test_activity_discovery_reports_its_own_category_when_no_matches(context, monkeypatch):
    account, booking, _, settings, _ = context
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[
        {'id':'SHOW', 'title':'Example show', 'type':{'id':'pt_show'}}]))
    settings = replace(settings, watches=(activity_watch(),), dry_run=True)
    assert c.process_availability_bookings(account, [booking], settings)
    assert 'No matching onboard activity products listed' in str(c.log.call_args_list)
    c._execute_api_request.assert_not_called()


def test_activity_unknown_inventory_does_not_rearm_acknowledged_release(context, monkeypatch):
    account, booking, _, settings, party = context
    watch = replace(activity_watch('EXAMPLE_ESCAPE_A'), notify_on_reopen=True)
    settings = replace(settings, watches=(watch,))
    data = capture('escape_room_a')
    result = c.evaluate_availability(data, watch, watch.product, 'Activity', party)
    assert c.deliver_availability(settings, account, booking, watch, party, [result])
    for o in data['payload']['offerings']:
        o['stockLevelStatus'] = 'NEW_STATUS'
    unknown = c.evaluate_availability(data, watch, watch.product, 'Activity', party)
    assert unknown.state == 'unknown'
    assert not c.deliver_availability(settings, account, booking, watch, party, [unknown])
    assert c.deliver_availability(settings, account, booking, watch, party, [result])
    c.config.apobj.notify.assert_called_once()
