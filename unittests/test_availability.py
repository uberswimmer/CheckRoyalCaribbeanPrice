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
    assert r.times == ('2026-10-10T21:30:00',)
    assert all(not o['active'] for o in capture('headliner')['payload']['offerings'])


def test_release_ignores_personal_conflicts():
    r = evaluate(mode='release')
    assert r.times == ('2026-10-10T19:15:00', '2026-10-10T21:30:00')


def test_elemental_reserved_guests_do_not_hide_release():
    assert evaluate('elemental').state == 'unavailable'
    assert evaluate('elemental', 'release').state == 'available'


def test_railway_party_and_release_differ():
    r = evaluate('railway')
    assert r.state == 'available'
    assert r.times == ('2027-02-12T20:30:00', '2027-02-12T20:40:00',
                       '2027-02-14T20:30:00', '2027-02-14T20:40:00')
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
    for o in response['payload']['offerings']:o['dateTime'] = o['dateTime'].replace('2026', '2099')
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
    assert 'pt_show/product/Y7QG' in c.config.apobj.notify.call_args.kwargs['body']


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
    deliver(context,[state_result(product='first'),state_result(product='second')])
    assert c.config.apobj.notify.call_count == 1
    deliver(context,[state_result(product='first'),state_result(product='second'),state_result(product='third')])
    assert c.config.apobj.notify.call_count == 2
    body = c.config.apobj.notify.call_args.kwargs['body']
    assert '/third?' in body and '/first?' not in body


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
    b = dict(b,sailDate='20261010')
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
    assert '21:30:00' in body and '19:15:00' not in body


def test_normal_booking_path_invokes_availability_without_changing_price_work(context,monkeypatch):
    a,b,w,s,p = context
    c.config.availability=replace(s,only=False)
    monkeypatch.setattr(c,'_execute_api_request',Mock(return_value=Mock(
        json=Mock(return_value={'payload':{'profileBookings':[]}}))))
    process=Mock(return_value=True)
    monkeypatch.setattr(c,'process_availability_bookings',process)
    c.get_voyages(a,c.DiscountProfile('',None,False,False,False,False,False),c.ShipRegistry())
    process.assert_called_once_with(a,[],c.config.availability)


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
