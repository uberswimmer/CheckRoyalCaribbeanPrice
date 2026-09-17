"""Captured response contracts plus failure, persistence, and orchestration tests.

All fixtures are allowlisted reductions; guest/booking identifiers are synthetic.
No tests contact Royal Caribbean or send real notifications.
"""
import copy
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c

FIXTURES = Path(__file__).parent / 'fixtures' / 'availability'


def capture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def party_for(data):
    return tuple((g['id'], g['reservationId']) for g in data['payload']['guests'])


def watch_for(name='headliner', mode='party'):
    data = capture(name)
    return c.AvailabilityWatch('watch', name, 'booking-1',
        'dining' if name == 'railway' else 'show', data['payload']['productCode'], mode)


def evaluate(name='headliner', mode='party', data=None):
    original = capture(name)
    return c.evaluate_availability(data if data is not None else original,
        watch_for(name, mode), original['payload']['productCode'], name, party_for(original))


@pytest.fixture(autouse=True)
def globals_without_network(monkeypatch):
    conf = c.CruiseAppConfig()
    conf.apobj = Mock()
    conf.apobj.notify.return_value = True
    monkeypatch.setattr(c, 'config', conf)
    monkeypatch.setattr(c, 'history', Mock())
    monkeypatch.setattr(c, 'log', Mock())
    monkeypatch.setattr(c, 'log_warn', Mock())
    monkeypatch.setattr(c, '_execute_api_request', Mock(side_effect=AssertionError('Unmocked network call')))
    return conf


@pytest.fixture
def context(tmp_path):
    account = c.AccountInfo('example@example.invalid', 'not-a-password')
    account.access = c.APIAccess('fake-token', 'fake-account', Mock())
    booking = {'bookingId': 'booking-1', 'passengerId': 'guest-1', 'shipCode': 'IC',
               'sailDate': '20991010', 'numberOfNights': 7, 'bookingCurrency': 'USD',
               'passengersInStateroom': [{'passengerId': 'guest-1'}]}
    watch = watch_for(mode='release')
    settings = c.AvailabilitySettings((watch,), True, False, str(tmp_path/'state.sqlite3'))
    return account, booking, watch, settings, (('guest-1', 'booking-1'),)


def test_headliner_conflict_is_scoped_to_early_offering():
    r = evaluate()
    assert r.state == 'available'
    assert r.times == ('2098-04-06T21:30:00',)
    assert all(not o['active'] for o in capture('headliner')['payload']['offerings'])


def test_release_ignores_personal_conflicts():
    r = evaluate(mode='release')
    assert r.times == ('2098-04-06T19:15:00', '2098-04-06T21:30:00')


def test_elemental_reserved_guests_do_not_hide_release():
    assert evaluate('elemental').state == 'unavailable'
    assert evaluate('elemental', 'release').state == 'available'


def test_railway_party_and_release_differ():
    r = evaluate('railway')
    assert r.state == 'available'
    assert r.times == ('2098-07-02T20:30:00', '2098-07-02T20:40:00',
                       '2098-07-04T20:30:00', '2098-07-04T20:40:00')
    assert len(evaluate('railway', 'release').times) == 12


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(error={'message':'failure'}),
    lambda d: d.update(warnings=['incomplete']),
    lambda d: d['payload'].update(productCode='wrong'),
    lambda d: d['payload'].update(categoryId='pt_dining'),
    lambda d: d['payload'].update(offerings=None),
    lambda d: d['payload'].update(guests=[]),
    lambda d: d['payload']['guests'][0].update(remainingBookableQty=None),
    lambda d: d['payload']['guests'][0].update(remainingBookableQty=True),
    lambda d: d['payload']['guests'][0].update(issues=[{'type':'NEW_RESTRICTION'}]),
    lambda d: d['payload']['guests'][0].update(issues=[{'type':'USER_HAS_HARD_CONFLICT','conflict':[]}]),
    lambda d: d['payload']['guests'][0].update(issues=[{'type':'USER_HAS_HARD_CONFLICT','conflict':{'offering':'bad'}}]),
    lambda d: d['payload']['offerings'][1].update(stockLevelStatus='NEW_STATUS'),
    lambda d: d['payload']['offerings'][1].update(stockLevel=None),
    lambda d: d['payload']['offerings'][1].update(stockLevel=float('nan')),
    lambda d: d['payload']['offerings'][1].update(dateTime='tomorrow'),
    lambda d: d['payload']['offerings'][1].update(issues='bad'),
    lambda d: d['payload']['offerings'][1].update(issues=[{'type':'NEW_RESTRICTION'}]),
    lambda d: d['payload']['offerings'].append(copy.deepcopy(d['payload']['offerings'][1])),
])
def test_malformed_or_unknown_evidence_never_announces_opening(mutation):
    data = capture('headliner')
    mutation(data)
    assert evaluate(data=data).state == 'unknown'


def test_party_rejects_insufficient_stock_and_guest_limit():
    data = capture('headliner')
    data['payload']['offerings'][1]['stockLevel'] = 1
    assert evaluate(data=data).state == 'unavailable'
    data = capture('headliner')
    data['payload']['guestLimit'] = 5
    assert evaluate(data=data).state == 'unavailable'


@pytest.mark.parametrize('status', ['inStock', 'outOfStock', 'OUT_OF_STOCK'])
def test_zero_inventory_does_not_alert(status):
    data = capture('headliner')
    for o in data['payload']['offerings']:
        o.update(stockLevel=0, stockLevelStatus=status)
    assert evaluate(data=data).state == 'unavailable'


def test_missing_guest_conflict_target_is_unknown():
    data = capture('headliner')
    del data['payload']['guests'][0]['issues'][0]['conflict']
    assert evaluate(data=data).state == 'unknown'


def test_no_offerings_is_known_unavailable():
    data = capture('headliner')
    data['payload']['offerings'] = []
    assert evaluate(data=data).state == 'unavailable'


def test_wonder_typed_absence_and_complete_icon_catalog(context, monkeypatch):
    a,b,*_ = context
    fetch = Mock(side_effect=[capture('wonder_catalog'),capture('icon_catalog')])
    monkeypatch.setattr(c, 'availability_json', fetch)
    assert c.availability_products(a,b,'show') == []
    assert len(c.availability_products(a,b,'show')) == 6
    assert fetch.call_args.kwargs['json_data']['variables']['category'] == 'show'


def test_partial_pagination_is_unknown(context, monkeypatch):
    a,b,*_ = context
    first = capture('icon_catalog')
    first['data']['products']['pageInfo'].update(totalPages=2,totalResults=12)
    monkeypatch.setattr(c, 'availability_json', Mock(side_effect=[first,capture('wonder_catalog')]))
    with pytest.raises(c.AvailabilityUnknown):
        c.availability_products(a,b,'show')


def test_successful_multiple_pages(context, monkeypatch):
    a,b,*_ = context
    first = capture('icon_catalog')
    first['data']['products']['pageInfo'].update(totalPages=2,totalResults=12)
    second = copy.deepcopy(first)
    for p in second['data']['products']['commerceProducts']:p['id'] += '-next'
    monkeypatch.setattr(c, 'availability_json', Mock(side_effect=[first,second]))
    assert len(c.availability_products(a,b,'show')) == 12


@pytest.mark.parametrize('data', [
    {}, {'data':{'products':None}}, {'errors':[{'message':'unauthorized'}]},
    {'data':{'products':{'__typename':'CommerceProductExceptions','exceptions':[{'__typename':'InvalidCategoryException'}]}}},
])
def test_catalog_failure_is_not_absence(context, monkeypatch, data):
    a,b,*_ = context
    monkeypatch.setattr(c, 'availability_json', Mock(return_value=data))
    with pytest.raises(c.AvailabilityUnknown):c.availability_products(a,b,'show')


def test_transport_and_graphql_errors(context, monkeypatch):
    a,*_ = context
    for response in [None, Mock(status_code=403), Mock(status_code=200, json=Mock(return_value={'errors':[{}]})),
                     Mock(status_code=200,json=Mock(side_effect=ValueError()))]:
        monkeypatch.setattr(c, '_execute_api_request', Mock(return_value=response))
        with pytest.raises(c.AvailabilityUnknown):c.availability_json(a,'POST','https://example.invalid')


def test_eligibility_request_uses_booking_context_without_cart_mutation(context, monkeypatch):
    a,b,w,_,party = context
    response = capture('headliner')
    for o in response['payload']['offerings']:o['dateTime'] = o['dateTime'].replace('2098-04-06', '2099-10-10')
    fetch = Mock(return_value=response)
    monkeypatch.setattr(c, 'availability_json', fetch)
    c.availability_eligibility(a,b,w,w.product,party)
    assert fetch.call_args.args[1] == 'POST'
    assert fetch.call_args.args[2].endswith('/eligibility/v1/eligibility')
    body = fetch.call_args.kwargs['json_data']
    assert body['cartId'] == ''
    assert body['startDate'] == '20991010' and body['endDate'] == '20991017'
    assert body['guests'] == [{'id':'guest-1','reservationId':'booking-1'}]
    assert body['email'] == a.username


def state_result(state='available', product='Y7QG'):
    return c.AvailabilityResult(product,'Headliner',state,'test',('2099-10-10T21:30:00',) if state=='available' else ())


def deliver(context, results=None):
    a,b,w,s,p = context
    return c.deliver_availability(s,a,b,w,p,results if results is not None else [state_result()])


def test_first_available_notifies_once_across_new_connections(context):
    assert deliver(context)
    assert deliver(context)
    assert c.config.apobj.notify.call_count == 1
    assert 'category/pt_show?bookingId=booking-1&shipCode=IC&sailDate=20991010' in c.config.apobj.notify.call_args.kwargs['body']


def test_dry_run_does_not_swallow_first_live_alert(context):
    a,b,w,s,p = context
    assert deliver((a,b,w,replace(s,dry_run=True),p))
    assert not Path(s.state_file).exists()
    c.config.apobj.notify.assert_not_called()
    assert deliver(context)
    c.config.apobj.notify.assert_called_once()


@pytest.mark.parametrize('failure', [False, None, RuntimeError('secret must not be logged')])
def test_delivery_failure_retries(context, failure):
    if isinstance(failure,Exception):c.config.apobj.notify.side_effect = failure
    else:c.config.apobj.notify.return_value = failure
    assert not deliver(context)
    c.config.apobj.notify.side_effect = None
    c.config.apobj.notify.return_value = True
    assert deliver(context)
    assert c.config.apobj.notify.call_count == 2


def test_no_notifier_does_not_acknowledge(context):
    saved = c.config.apobj
    c.config.apobj = None
    assert not deliver(context)
    c.config.apobj = saved
    assert deliver(context)
    saved.notify.assert_called_once()


@pytest.mark.parametrize('reopen,expected', [(False,1),(True,2)])
def test_known_closed_reopens_only_when_requested(context,reopen,expected):
    a,b,w,s,p = context
    ctx = a,b,replace(w,notify_on_reopen=reopen),s,p
    deliver(ctx)
    deliver(ctx,[state_result('unavailable')])
    deliver(ctx)
    assert c.config.apobj.notify.call_count == expected


def test_unknown_never_rearms_or_changes_state(context):
    a,b,w,s,p = context
    ctx = a,b,replace(w,notify_on_reopen=True),s,p
    deliver(ctx)
    assert not deliver(ctx,[state_result('unknown')])
    with sqlite3.connect(s.state_file) as db:
        assert db.execute('SELECT last_state,notified FROM availability_v1').fetchone() == ('available',1)
    deliver(ctx)
    assert c.config.apobj.notify.call_count == 1


def test_aggregate_new_products_and_skip_acknowledged_ones(context):
    first = replace(state_result(product='first'), title='First show')
    second = replace(state_result(product='second'), title='Second show')
    third = replace(state_result(product='third'), title='Third show')
    deliver(context, [first, second])
    assert c.config.apobj.notify.call_count == 1
    deliver(context, [first, second, third])
    assert c.config.apobj.notify.call_count == 2
    body = c.config.apobj.notify.call_args.kwargs['body']
    assert 'Third show:' in body and 'First show:' not in body and 'Second show:' not in body


def test_scope_separates_accounts_sailings_and_modes(context):
    a,b,w,s,p = context
    base = c.availability_scope(a,b,w,p)
    assert base != c.availability_scope(replace(a,username='another'),b,w,p)
    assert base != c.availability_scope(a,dict(b,sailDate='20991017'),w,p)
    assert base != c.availability_scope(a,b,replace(w,mode='party'),p)
    assert base == c.availability_scope(a,b,w,(('new-guest','booking-1'),))


def test_individual_product_failure_does_not_block_other_shows(context,monkeypatch):
    a,b,w,s,p = context
    w = replace(w,product=None)
    monkeypatch.setattr(c,'availability_products',Mock(return_value=[
        {'id':'first','title':'First','type':{'id':'pt_show'}},
        {'id':'Y7QG','title':'Headliner','type':{'id':'pt_show'}}]))
    monkeypatch.setattr(c,'availability_eligibility',Mock(side_effect=[c.AvailabilityUnknown('failed'),capture('headliner')]))
    assert not c.process_availability_bookings(a,[b],replace(s,watches=(w,)))
    c.config.apobj.notify.assert_called_once()
    assert 'Headliner:' in c.config.apobj.notify.call_args.kwargs['body']


def test_disabled_departed_and_other_bookings_make_no_product_requests(context,monkeypatch):
    a,b,w,s,p = context
    lookup = Mock(side_effect=AssertionError('must not query'))
    monkeypatch.setattr(c,'availability_products',lookup)
    assert c.process_availability_bookings(a,[b],replace(s,watches=(replace(w,enabled=False),)))
    assert c.process_availability_bookings(a,[dict(b,sailDate='20000101')],s)
    assert c.process_availability_bookings(a,[dict(b,bookingId='another')],s)
    lookup.assert_not_called()


def test_only_mode_uses_no_price_profile_or_ship_discovery(context,monkeypatch):
    a,b,w,s,p = context
    c.config.availability = s
    c.config.accounts = [a]
    monkeypatch.setattr(c,'login',Mock(return_value=a.access))
    monkeypatch.setattr(c,'availability_json',Mock(return_value={'payload':{'profileBookings':[b]}}))
    monkeypatch.setattr(c,'process_availability_bookings',Mock(return_value=True))
    profile = Mock(side_effect=AssertionError('price profile called'))
    monkeypatch.setattr(c,'get_profile',profile)
    monkeypatch.setattr(c,'get_ship_dictionary_web',profile)
    monkeypatch.setattr(c,'get_orders',profile)
    monkeypatch.setattr(c,'get_cruise_price',profile)
    c.main()
    a.access.session.close.assert_called_once()
    profile.assert_not_called()


def test_missing_reservation_fails_only_mode(context,monkeypatch):
    a,b,w,s,p = context
    c.config.accounts = [a]
    monkeypatch.setattr(c,'login',Mock(return_value=a.access))
    monkeypatch.setattr(c,'availability_json',Mock(return_value={'payload':{'profileBookings':[]}}))
    with pytest.raises(c.AvailabilityUnknown):c.run_availability_only(s)
    a.access.session.close.assert_called_once()


def valid_config():
    return {'only':True,'dryRun':True,'watches':[{'id':'shows','reservation':123,'category':'show'}]}


def test_config_defaults_and_normalization():
    assert c.parse_availability_config(None) is None
    s = c.parse_availability_config(valid_config())
    assert s.only and s.dry_run
    assert s.watches[0].reservation == '123'
    assert s.watches[0].product is None and s.watches[0].mode == 'release'


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(only='false'),
    lambda d:d.update(dryRun='true'),
    lambda d:d.update(dryrun=False),
    lambda d:d.update(stateFile=':memory:'),
    lambda d:d.update(watches=[]),
    lambda d:d['watches'].append(copy.deepcopy(d['watches'][0])),
    lambda d:d['watches'][0].update(category='dining'),
    lambda d:d['watches'][0].update(category='pt_show'),
    lambda d:d['watches'][0].update(mode='available'),
    lambda d:d['watches'][0].update(reservation=None),
    lambda d:d['watches'][0].update(enabled='false'),
    lambda d:d['watches'][0].update(guests=[]),
    lambda d:d['watches'][0].update(guests=[{'id':'guest'}]),
])
def test_invalid_config_rejected(mutation):
    data = valid_config()
    mutation(data)
    with pytest.raises(ValueError):c.parse_availability_config(data)


def test_eligibility_rejects_other_sailing(context,monkeypatch):
    a,b,w,s,p = context
    monkeypatch.setattr(c,'availability_json',Mock(return_value=capture('headliner')))
    with pytest.raises(c.AvailabilityUnknown,match='outside requested sailing'):
        c.availability_eligibility(a,b,w,w.product,p)


def test_api_body_failure_status(context,monkeypatch):
    a,*_ = context
    monkeypatch.setattr(c,'_execute_api_request',Mock(return_value=Mock(status_code=200,
        json=Mock(return_value={'status':500,'payload':{}}))))
    with pytest.raises(c.AvailabilityUnknown):c.availability_json(a,'GET','https://example.invalid')


def test_failed_account_does_not_prevent_remaining_accounts(context,monkeypatch):
    a,b,w,s,p = context
    another = replace(a,username='second@example.invalid')
    c.config.accounts = [a,another]
    monkeypatch.setattr(c,'login',Mock(side_effect=[SystemExit(1),a.access]))
    monkeypatch.setattr(c,'availability_json',Mock(return_value={'payload':{'profileBookings':[b]}}))
    process = Mock(return_value=True)
    monkeypatch.setattr(c,'process_availability_bookings',process)
    monkeypatch.setattr(c.time,'sleep',Mock())
    with pytest.raises(c.AvailabilityUnknown):c.run_availability_only(s)
    process.assert_called_once_with(another,[b],s)


def test_all_disabled_does_not_login(context,monkeypatch):
    a,b,w,s,p = context
    c.config.accounts = [a]
    login = Mock(side_effect=AssertionError('must not login'))
    monkeypatch.setattr(c,'login',login)
    c.run_availability_only(replace(s,watches=(replace(w,enabled=False),)))
    login.assert_not_called()


def test_catalog_failure_cannot_rearm_previously_notified_product(context,monkeypatch):
    a,b,w,s,p = context
    w = replace(w,notify_on_reopen=True)
    deliver((a,b,w,s,p))
    monkeypatch.setattr(c,'availability_products',Mock(side_effect=c.AvailabilityUnknown('outage')))
    assert not c.process_availability_bookings(a,[b],replace(s,watches=(w,)))
    deliver((a,b,w,s,p))
    assert c.config.apobj.notify.call_count == 1


def test_disappeared_show_can_rearm_after_complete_empty_catalog(context,monkeypatch):
    a,b,w,s,p = context
    w = replace(w,product=None,notify_on_reopen=True)
    ctx = a,b,w,s,p
    deliver(ctx)
    monkeypatch.setattr(c,'availability_products',Mock(return_value=[]))
    assert c.process_availability_bookings(a,[b],replace(s,watches=(w,)))
    deliver(ctx)
    assert c.config.apobj.notify.call_count == 2


def test_unwritable_state_does_not_send(context,monkeypatch):
    a,b,w,s,p = context
    monkeypatch.setattr(c,'availability_products',Mock(return_value=[
        {'id':w.product,'title':'Headliner','type':{'id':'pt_show'}}]))
    monkeypatch.setattr(c,'availability_eligibility',Mock(return_value=capture('headliner')))
    directory = str(Path(s.state_file).parent)
    assert not c.process_availability_bookings(a,[b],replace(s,state_file=directory))
    c.config.apobj.notify.assert_not_called()


def test_concurrent_deliveries_are_serialized(context):
    import concurrent.futures
    # Both processes may observe an opening. The second notification decision
    # must see the first transaction's acknowledgement.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda _:deliver(context),range(2)))
    assert c.config.apobj.notify.call_count == 1


def test_end_to_end_only_mode_uses_captured_contracts_and_persists(context,monkeypatch):
    from datetime import date as real_date
    class TestDate(real_date):
        @classmethod
        def today(cls):return cls(2026,9,10)
    monkeypatch.setattr(c,'date',TestDate)
    a,b,w,s,p = context
    b = dict(b,sailDate='20980406')
    data = capture('headliner')
    w = replace(w,mode='party',guests=party_for(data))
    s = replace(s,watches=(w,))
    c.config.accounts = [a]
    c.config.availability = s
    monkeypatch.setattr(c,'login',Mock(return_value=a.access))
    catalog = capture('icon_catalog')
    cp = catalog['data']['products']
    cp['commerceProducts'] = [x for x in cp['commerceProducts'] if x['id']==w.product]
    cp['pageInfo'].update(totalResults=1,totalPages=1)
    calls=[]
    def transport(account,method,url,**kwargs):
        assert account is a
        calls.append((method,url))
        if '/profileBookings/' in url:
            answer={'payload':{'profileBookings':[b]}}
        elif url.endswith('/graphql'):
            assert kwargs['json_data']['variables']['reservationId']=='booking-1'
            answer=catalog
        elif url.endswith('/eligibility/v1/eligibility'):
            body=kwargs['json_data']
            assert len(body['guests'])==6 and body['categoryId']=='pt_show' and body['cartId']==''
            answer=data
        else:raise AssertionError('Unexpected endpoint')
        return Mock(status_code=200,json=Mock(return_value=answer))
    monkeypatch.setattr(c,'_execute_api_request',transport)
    c.main()
    c.main()
    assert len(calls)==6
    c.config.apobj.notify.assert_called_once()
    body=c.config.apobj.notify.call_args.kwargs['body']
    assert '21:30' in body and '19:15' not in body


def test_booking_path_returns_snapshot_without_running_availability_early(context,monkeypatch):
    a,b,w,s,p = context
    c.config.availability=replace(s,only=False)
    monkeypatch.setattr(c,'_execute_api_request',Mock(return_value=Mock(
        json=Mock(return_value={'payload':{'profileBookings':[]}}))))
    process=Mock(return_value=True)
    monkeypatch.setattr(c,'process_availability_bookings',process)
    bookings = c.get_voyages(a,c.DiscountProfile('',None,False,False,False,False,False),c.ShipRegistry())
    assert bookings == []
    process.assert_not_called()


def test_validate_cli_makes_no_requests(tmp_path):
    import subprocess,sys,yaml
    raw={'accountInfo':[{'username':'example@example.invalid','password':'not-a-password'}],
         'availability':valid_config()}
    path=tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(raw))
    proc=subprocess.run([sys.executable,'CheckRoyalCaribbeanPrice.py','-c',str(path),'--validate-config'],
                        capture_output=True,text=True,timeout=10)
    assert proc.returncode==0,proc.stderr
    assert 'No Royal Caribbean requests made' in proc.stdout
    assert not (tmp_path/'availability.sqlite3').exists()


@pytest.mark.parametrize('dry_run', [True, False])
def test_discovery_skips_other_category_without_error_or_notification(context, monkeypatch, dry_run):
    # pt_onboardActivities is confirmed by the sanitized Star console output.
    a, b, w, s, p = context
    w = replace(w, product=None)
    products = [
        {'id': 'escape-1', 'title': 'Escape room', 'type': {'id': 'pt_onboardActivities'}},
        {'id': 'dinner-1', 'title': 'Experience dinner', 'type': {'id': 'pt_dining'}},
    ]
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=products))
    eligibility = Mock(side_effect=AssertionError('must not query another product type'))
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    assert c.process_availability_bookings(a, [b], replace(s, watches=(w,), dry_run=dry_run))
    eligibility.assert_not_called()
    c.config.apobj.notify.assert_not_called()
    assert any('2 other-category products skipped' in call.args[0] for call in c.log.call_args_list)
    if dry_run:
        assert not Path(s.state_file).exists()


def test_mixed_catalog_still_checks_and_notifies_matching_show(context, monkeypatch):
    a, b, w, s, p = context
    products = [
        {'id': 'escape-1', 'title': 'Escape room', 'type': {'id': 'pt_onboardActivities'}},
        {'id': w.product, 'title': 'Headliner', 'type': {'id': 'pt_show'}},
    ]
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=products))
    eligibility = Mock(return_value=capture('headliner'))
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    discovery = replace(w, product=None)
    assert c.process_availability_bookings(a, [b], replace(s, watches=(discovery,)))
    eligibility.assert_called_once_with(a, b, discovery, w.product, p)
    c.config.apobj.notify.assert_called_once()
    assert 'Headliner:' in c.config.apobj.notify.call_args.kwargs['body']
    assert 'Escape room' not in c.config.apobj.notify.call_args.kwargs['body']


def test_explicit_product_type_mismatch_stays_unknown(context, monkeypatch):
    a, b, w, s, p = context
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[
        {'id': w.product, 'title': 'Other type', 'type': {'id': 'pt_activity'}}]))
    eligibility = Mock(side_effect=AssertionError('must not query another product type'))
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    assert not c.process_availability_bookings(a, [b], s)
    eligibility.assert_not_called()
    c.config.apobj.notify.assert_not_called()


@pytest.mark.parametrize('product_type', [None, {}, [], 'pt_show', {'id': None}, {'id': 'pt_'}, {'id': 'invalid'}])
def test_malformed_type_does_not_block_valid_show_or_hide_error(context, monkeypatch, product_type):
    a, b, w, s, p = context
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[
        {'id': 'broken', 'title': 'Malformed', 'type': product_type},
        {'id': w.product, 'title': 'Headliner', 'type': {'id': 'pt_show'}}]))
    monkeypatch.setattr(c, 'availability_eligibility', Mock(return_value=capture('headliner')))
    assert not c.process_availability_bookings(a, [b], replace(s, watches=(replace(w, product=None),)))
    c.config.apobj.notify.assert_called_once()
    assert 'Headliner:' in c.config.apobj.notify.call_args.kwargs['body']


def test_skipped_type_change_preserves_previous_notification(context, monkeypatch):
    a, b, w, s, p = context
    w = replace(w, product=None, notify_on_reopen=True)
    ctx = a, b, w, s, p
    deliver(ctx)
    before = sqlite3.connect(s.state_file)
    original = before.execute('SELECT * FROM availability_v1').fetchall()
    before.close()
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[
        {'id': 'Y7QG', 'title': 'Changed type', 'type': {'id': 'pt_activity'}}]))
    assert c.process_availability_bookings(a, [b], replace(s, watches=(w,)))
    after = sqlite3.connect(s.state_file)
    assert after.execute('SELECT * FROM availability_v1').fetchall() == original
    after.close()
    deliver(ctx)
    assert c.config.apobj.notify.call_count == 1


def setup_combined_console(context, monkeypatch):
    from types import SimpleNamespace
    a, b, w, s, p = context
    c.config.availability = replace(s, only=False)
    c.config.accounts = [a]
    c.config.prospective_cruises = [SimpleNamespace(cruise_URL='https://example.invalid', paid_price=100)]
    monkeypatch.setattr(c, 'login', Mock(side_effect=lambda account: account.access))
    monkeypatch.setattr(c, 'get_profile', Mock(return_value=('OH', '', 0)))
    monkeypatch.setattr(c, 'get_ship_dictionary_web', Mock())
    monkeypatch.setattr(c, 'new_api_session', Mock(return_value=Mock()))
    monkeypatch.setattr(c.time, 'sleep', Mock())
    return a, b


def test_combined_availability_runs_after_all_price_watches_before_summary(context, monkeypatch):
    a, b = setup_combined_console(context, monkeypatch)
    second = replace(a, username='second@example.invalid', access=c.APIAccess('fake', 'second', Mock()))
    c.config.accounts.append(second)
    events = []
    def booked(account, *args, **kwargs):
        events.append(('booked-prices-and-watches', account.username))
        return [b]
    def availability(account, bookings, settings):
        assert bookings == [b]
        account.access.session.close.assert_not_called()
        events.append(('availability', account.username))
        return True
    monkeypatch.setattr(c, 'get_voyages', Mock(side_effect=booked))
    monkeypatch.setattr(c, 'get_cruise_price', Mock(side_effect=lambda *a, **k: events.append(('prospective-prices', None))))
    monkeypatch.setattr(c, 'process_availability_bookings', Mock(side_effect=availability))
    monkeypatch.setattr(c.CheckinPaymentTracker, 'print_table', lambda self: events.append(('summary', None)))
    c.main()
    assert events == [('booked-prices-and-watches', a.username),
                      ('booked-prices-and-watches', second.username),
                      ('prospective-prices', None), ('availability', a.username),
                      ('availability', second.username), ('summary', None)]
    assert c.login.call_count == 2
    a.access.session.close.assert_called_once()
    second.access.session.close.assert_called_once()
    assert sum('Reservation Availability Watches' in call.args[0] for call in c.log.call_args_list) == 1


@pytest.mark.parametrize('failure_stage', ['second_account', 'prospective', 'availability'])
def test_deferred_sessions_close_on_later_failure(context, monkeypatch, failure_stage):
    a, b = setup_combined_console(context, monkeypatch)
    second = replace(a, username='second@example.invalid', access=c.APIAccess('fake', 'second', Mock()))
    c.config.accounts.append(second)
    monkeypatch.setattr(c, 'get_voyages', Mock(side_effect=[
        [b], RuntimeError('test failure') if failure_stage == 'second_account' else [b]]))
    monkeypatch.setattr(c, 'get_cruise_price', Mock(side_effect=RuntimeError('test failure') if failure_stage == 'prospective' else None))
    monkeypatch.setattr(c, 'process_availability_bookings', Mock(side_effect=RuntimeError('test failure') if failure_stage == 'availability' else None))
    with pytest.raises(RuntimeError, match='test failure'):
        c.main()
    a.access.session.close.assert_called_once()
    second.access.session.close.assert_called_once()


def test_availability_console_uses_status_colors_and_groups_times(context):
    a, b, w, s, p = context
    results = [c.AvailabilityResult('show', 'Show', 'available', 'inventory',
               ('2099-10-10T19:15:00', '2099-10-10T21:30:00')),
               c.AvailabilityResult('closed', 'Closed', 'unavailable', 'no offerings'),
               c.AvailabilityResult('error', 'Error', 'unknown', 'request failed')]
    assert not c.deliver_availability(replace(s, dry_run=True), a, b, w, p, results)
    lines = [call.args[0] for call in c.log.call_args_list]
    assert any(c.GREEN + 'Show: Available' in line for line in lines)
    assert any(c.YELLOW + 'Closed: Unavailable' in line for line in lines)
    assert any(c.RED + 'Error: Unknown' in line for line in lines)
    assert any('19:15, 21:30' in line and line.startswith('      ') for line in lines)
    assert not any('2099-10-10T' in line for line in lines)


@pytest.mark.parametrize('failure', ['check', 'missing_booking', 'booking_lookup'])
def test_combined_failure_finishes_price_outputs_and_marks_run_failed(context, monkeypatch, failure):
    a, b = setup_combined_console(context, monkeypatch)
    c.history = Mock()
    c.config.output_watch_as_json = True
    events = []
    bookings = [b] if failure == 'check' else ([] if failure == 'missing_booking' else None)
    monkeypatch.setattr(c, 'get_voyages', Mock(return_value=bookings))
    monkeypatch.setattr(c, 'get_cruise_price', Mock(side_effect=lambda *a, **k: events.append('prospective')))
    monkeypatch.setattr(c, 'process_availability_bookings', Mock(return_value=failure != 'check'))
    monkeypatch.setattr(c.CheckinPaymentTracker, 'print_table', lambda self: events.append('summary'))
    monkeypatch.setattr(c, 'write_watch_price_json', Mock(side_effect=lambda *a: events.append('export')))
    with pytest.raises(c.AvailabilityUnknown):
        c.main()
    assert events == ['prospective', 'summary', 'export']
    assert c.history.finish_run.call_args.args[0] == 'error'
    a.access.session.close.assert_called_once()
    if failure == 'missing_booking':
        assert any('Configured reservations were not found' in call.args[0] for call in c.log_warn.call_args_list)


def test_combined_missing_booking_is_resolved_across_accounts(context, monkeypatch):
    a, b = setup_combined_console(context, monkeypatch)
    c.history = Mock()
    c.config.prospective_cruises = []
    second = replace(a, username='second@example.invalid', access=c.APIAccess('fake', 'second', Mock()))
    c.config.accounts.append(second)
    monkeypatch.setattr(c, 'get_voyages', Mock(side_effect=[[], [b]]))
    monkeypatch.setattr(c, 'process_availability_bookings', Mock(return_value=True))
    c.main()
    c.history.finish_run.assert_called_once_with('ok')
    assert not any('Configured reservations were not found' in call.args[0] for call in c.log_warn.call_args_list)


def test_catalog_reused_between_watches_but_eligibility_and_later_runs_are_fresh(context, monkeypatch):
    a, b, w, s, p = context
    second = replace(w, id='second', mode='party', guests=party_for(capture('headliner')))
    settings = replace(s, dry_run=True, watches=(w, second))
    catalog = Mock(return_value=[{'id':w.product, 'title':'Show', 'type':{'id':'pt_show'}}])
    monkeypatch.setattr(c, 'availability_products', catalog)
    eligibility = Mock(return_value=capture('headliner'))
    monkeypatch.setattr(c, 'availability_eligibility', eligibility)
    for _ in range(2):
        assert c.process_availability_bookings(a, [b], settings)
    assert catalog.call_count == 2
    assert eligibility.call_count == 4
    assert eligibility.call_args_list[0].args[2].mode == 'release'
    assert eligibility.call_args_list[1].args[2].mode == 'party'


def test_catalog_failure_is_shared_within_run_and_retried_next_run(context, monkeypatch):
    a, b, w, s, p = context
    settings = replace(s, watches=(w, replace(w, id='second')))
    deliver(context)
    catalog = Mock(side_effect=[c.AvailabilityUnknown('temporary error'), []])
    monkeypatch.setattr(c, 'availability_products', catalog)
    assert not c.process_availability_bookings(a, [b], settings)
    catalog.assert_called_once()
    deliver(context)
    c.config.apobj.notify.assert_called_once()
    assert c.process_availability_bookings(a, [b], settings)
    assert catalog.call_count == 2


def test_catalog_cache_isolated_by_account_booking_and_category(context, monkeypatch):
    a, b, w, s, p = context
    settings = replace(s, dry_run=True, watches=(w,
        replace(w, id='other-booking', reservation='booking-2'),
        replace(w, id='dining', category='dining', product='SAMPLE_DINING')))
    other_booking = dict(b, bookingId='booking-2')
    catalog = Mock(return_value=[])
    monkeypatch.setattr(c, 'availability_products', catalog)
    for account in (a, replace(a, username='other@example.invalid')):
        assert c.process_availability_bookings(account, [b, other_booking], settings)
    assert catalog.call_count == 6


@pytest.mark.parametrize('change, expected', [
    (lambda d:d.update(dryrun=True), 'availability: unrecognized configuration key(s): dryrun'),
    (lambda d:d['watches'][0].update(mod='release'), 'availability.watches[0]: unrecognized configuration key(s): mod'),
    (lambda d:d['watches'][0].update(enabled='false'), 'availability.watches[0]: enabled must be true or false'),
    (lambda d:d['watches'][0].update(guests=[{'id':'test','reservationID':'SECRET_VALUE'}]), 'availability.watches[0].guests[0]: unrecognized configuration key(s): reservationID'),
    (lambda d:d['watches'][0].update(reservation=None), 'availability.watches[0]: reservation must be a nonempty identifier'),
])
def test_config_diagnostics_identify_location_without_echoing_values(change, expected):
    raw = valid_config()
    change(raw)
    with pytest.raises(ValueError) as exc:
        c.parse_availability_config(raw)
    assert str(exc.value) == expected
    assert 'SECRET_VALUE' not in str(exc.value)


@pytest.mark.parametrize('failure, traceback_expected', [
    (c.AvailabilityUnknown('incomplete availability check'), False),
    (RuntimeError('unexpected programming error'), True),
])
def test_cli_error_dispatch_keeps_nonzero_exit_without_expected_failure_traceback(monkeypatch, failure, traceback_expected):
    from io import StringIO
    from unittest.mock import MagicMock
    monkeypatch.setattr(c, 'VALIDATE_CONFIG_ONLY', False, raising=False)
    monkeypatch.setattr(c, 'get_config_path', Mock(return_value='unused.yaml'))
    monkeypatch.setattr(c, 'load_config_objects', Mock(return_value=c.config))
    monkeypatch.setattr(c, 'main', Mock(side_effect=failure))
    monkeypatch.setattr(c.traceback, 'print_exc', Mock())
    c.config.notify_on_error = True
    c.config.apobj = MagicMock()
    c.config.apobj.__len__.return_value = 1
    stderr = StringIO()
    monkeypatch.setattr(c.sys, 'stderr', stderr)
    with pytest.raises(SystemExit) as exc:
        c.cli()
    assert exc.value.code == 1
    assert str(failure) in stderr.getvalue()
    assert c.traceback.print_exc.called is traceback_expected
    c.config.apobj.notify.assert_called_once()


def test_http_status_diagnostic_does_not_expose_response_body(context, monkeypatch):
    a, *_ = context
    monkeypatch.setattr(c, '_execute_api_request', Mock(return_value=Mock(status_code=401,
        json=Mock(return_value={'token':'DO_NOT_LOG'}))))
    with pytest.raises(c.AvailabilityUnknown) as exc:
        c.availability_json(a, 'GET', 'https://example.invalid')
    assert str(exc.value) == 'Royal API returned HTTP 401'


def test_missing_notifier_diagnostic_remains_retryable(context):
    c.config.apobj = None
    assert not deliver(context)
    assert any('No notification service configured' in call.args[0] for call in c.log_warn.call_args_list)
    c.config.apobj = Mock()
    c.config.apobj.notify.return_value = True
    assert deliver(context)
    c.config.apobj.notify.assert_called_once()


def test_state_storage_diagnostic_is_actionable_and_does_not_expose_exception(context, monkeypatch):
    a, b, w, s, p = context
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[]))
    monkeypatch.setattr(c, 'deliver_availability', Mock(side_effect=PermissionError('PRIVATE_PATH')))
    assert not c.process_availability_bookings(a, [b], s)
    messages = '\n'.join(call.args[0] for call in c.log_warn.call_args_list)
    assert 'check availability.stateFile and directory permissions' in messages
    assert 'PRIVATE_PATH' not in messages


def test_combined_failure_does_not_skip_later_accounts(context, monkeypatch):
    a, b = setup_combined_console(context, monkeypatch)
    c.history = Mock()
    c.config.prospective_cruises = []
    second = replace(a, username='second@example.invalid', access=c.APIAccess('fake', 'second', Mock()))
    c.config.accounts.append(second)
    monkeypatch.setattr(c, 'get_voyages', Mock(return_value=[b]))
    checks = Mock(side_effect=[False, True])
    monkeypatch.setattr(c, 'process_availability_bookings', checks)
    with pytest.raises(c.AvailabilityUnknown):
        c.main()
    assert [call.args[0] for call in checks.call_args_list] == [a, second]
    assert c.history.finish_run.call_args.args[0] == 'error'
    a.access.session.close.assert_called_once()
    second.access.session.close.assert_called_once()


def test_availability_section_spacing_and_completion_precede_summary(context, monkeypatch):
    from io import StringIO
    import logging
    a, b = setup_combined_console(context, monkeypatch)
    c.config.availability = replace(c.config.availability, watches=(replace(c.config.availability.watches[0], product=None),))
    stream = StringIO()
    logger = logging.Logger('availability-spacing')
    logger.addHandler(logging.StreamHandler(stream))
    monkeypatch.setattr(c, 'log', c.EasyLogger(logger))
    monkeypatch.setattr(c, 'log_warn', c.log.warn)
    monkeypatch.setattr(c, 'get_voyages', Mock(return_value=[b]))
    monkeypatch.setattr(c, 'get_cruise_price', Mock(side_effect=lambda *a, **k: c.log('Last price result')))
    monkeypatch.setattr(c, 'availability_products', Mock(return_value=[]))
    monkeypatch.setattr(c.CheckinPaymentTracker, 'print_table', lambda self: c.log('Upcoming Check-In & Final Payment Dates'))
    c.main()
    text = c.StripAnsiFilter.ANSI_REGEX.sub('', stream.getvalue())
    assert 'Last price result\n \nReservation Availability Watches\n \n' in text
    assert '\n    headliner\n      No entertainment products listed' in text
    assert 'Availability checks completed successfully\n \nUpcoming Check-In' in text


def test_compact_alert_groups_dates_separates_shows_and_keeps_one_booking_link(context):
    a, b, w, s, p = context
    c.config.date_display_format = '%Y-%m-%d'
    results = [c.AvailabilityResult('one', 'Comedy', 'available', 'inventory',
               ('2099-10-10T20:30:00-04:00', '2099-10-10T22:30:00-04:00', '2099-10-11T19:00:00-04:00')),
               c.AvailabilityResult('two', 'Ice Show', 'available', 'inventory', ('2099-10-12T21:15:00',))]
    assert c.deliver_availability(s, a, b, w, p, results)
    body = c.config.apobj.notify.call_args.kwargs['body']
    assert '\n\nComedy:\n2099-10-10: 20:30, 22:30\n2099-10-11: 19:00' in body
    assert '\n\nIce Show:\n2099-10-12: 21:15' in body
    assert body.count('https://') == 1 and '/product/' not in body
    assert 'pt_show?bookingId=booking-1&shipCode=IC&sailDate=20991010' in body
    assert 'Inventory released; personal conflicts not checked.' in body
    assert 'Times as returned by Royal.' in body
    assert 'T20:30' not in body and '20:30:00' not in body


def test_compact_alert_retains_preview_limit_but_console_has_all_times(context):
    a, b, w, s, p = context
    times = tuple(f'2099-10-10T{hour:02d}:00:00' for hour in range(10, 18))
    assert c.deliver_availability(s, a, b, w, p,
        [c.AvailabilityResult('one', 'Show', 'available', 'inventory', times)])
    body = c.config.apobj.notify.call_args.kwargs['body']
    assert '(+2 more times in Cruise Planner)' in body
    assert '15:00' in body and '16:00' not in body
    assert any('16:00, 17:00' in call.args[0] for call in c.log.call_args_list)


def test_compact_dining_alert_retains_party_and_table_caveats(context):
    a, b, w, s, p = context
    w = replace(w, category='dining', mode='party')
    assert c.deliver_availability(s, a, b, w, p, [state_result()])
    body = c.config.apobj.notify.call_args.kwargs['body']
    assert 'no detected restrictions for the configured party' in body
    assert 'pt_dining?' in body and 'pt_show' not in body
    assert 'Reported stock does not guarantee a table for the full party.' in body
    assert 'personal conflicts not checked' not in body


def test_native_apprise_split_preserves_all_shows_and_retries_failed_delivery(context):
    apprise = pytest.importorskip('apprise')
    a, b, w, s, p = context
    notifier = apprise.Apprise()
    assert notifier.add('pover://' + 'a'*30 + '@' + 'b'*30 + '/?overflow=split')
    service = next(iter(notifier))
    # Replace the transport, so no real notifications or network calls are possible.
    service.send = Mock(return_value=True)
    c.config.apobj = notifier
    results = [c.AvailabilityResult(str(i), f'Show {i:02d} with an example title', 'available', 'inventory',
                                   ('2099-10-10T20:30:00', '2099-10-11T22:30:00')) for i in range(30)]
    service.send.side_effect = lambda **kwargs: 'Show 00' not in kwargs['body']
    assert not c.deliver_availability(s, a, b, w, p, results)
    with sqlite3.connect(s.state_file) as db:
        assert db.execute('SELECT SUM(notified) FROM availability_v1').fetchone()[0] == 0
    service.send.reset_mock()
    service.send.side_effect = None
    assert c.deliver_availability(s, a, b, w, p, results)
    chunks = [call.kwargs['body'] for call in service.send.call_args_list]
    assert len(chunks) > 1
    assert all(len(chunk) <= service.body_maxlen for chunk in chunks)
    delivered = '\n'.join(chunks)
    assert all(f'Show {i:02d}' in delivered for i in range(30))
    assert 'category/pt_show?' in delivered
    service.send.reset_mock()
    assert c.deliver_availability(s, a, b, w, p, results)
    service.send.assert_not_called()
