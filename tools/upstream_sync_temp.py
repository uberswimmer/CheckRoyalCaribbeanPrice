from pathlib import Path

source_path = Path('CheckRoyalCaribbeanPrice.py')
source = source_path.read_text()

anchor = '''    if is_gty and stateroom_types:\n        return True, []\n\n    for stateroom_type in stateroom_types:\n'''
replacement = '''    if is_gty and stateroom_types:\n        return True, []\n\n    # Royal can rename funnel subtype codes while retaining category-family letters.\n    # If the booking still carries the old subtype, resolve it via the lead-in category\n    # and adopt the current funnel code for the downstream pricing request.\n    letter_matched_subtype = None\n\n    def _code_letters(code: Optional[str]) -> str:\n        return re.sub(r"[^A-Za-z]", "", code or "").upper()\n\n    wanted_letters = _code_letters(params.stateroom_subtype) or _code_letters(params.stateroom_category_code)\n\n    for stateroom_type in stateroom_types:\n'''
if source.count(anchor) != 1:
    raise SystemExit('GTY insertion anchor not unique')
source = source.replace(anchor, replacement, 1)

anchor = '''                # The endpoint lists available subtypes; some responses omit counts.\n                return True, []\n\n            # Defensively extract pricing trees to protect against missing API sub-keys\n'''
replacement = '''                # The endpoint lists available subtypes; some responses omit counts.\n                return True, []\n\n            # Keep the first non-guarantee subtype whose lead-in category shares the\n            # booking family letters. Exact subtype matches above always win.\n            if (letter_matched_subtype is None and wanted_letters\n                    and not stateroom_subtype.get("guarantee")\n                    and _code_letters(cur_category_code) == wanted_letters):\n                letter_matched_subtype = cur_subtype_code\n\n            # Defensively extract pricing trees to protect against missing API sub-keys\n'''
if source.count(anchor) != 1:
    raise SystemExit('subtype fallback anchor not unique')
source = source.replace(anchor, replacement, 1)

anchor = '''    # Fall-through state: The loops completed without finding our exact cabin style.\n    # The room is sold out, so we return False along with the collected alternative options.\n    return False, available_rooms\n'''
replacement = '''    if letter_matched_subtype is not None:\n        log(f"\\tSubtype code {params.stateroom_subtype} is no longer offered under that name; "\n            f"using current code {letter_matched_subtype} for the same category family")\n        params.stateroom_subtype = letter_matched_subtype\n        return True, []\n\n    # Fall-through state: The loops completed without finding our exact cabin style.\n    # The room is sold out, so we return False along with the collected alternative options.\n    return False, available_rooms\n'''
if source.count(anchor) != 1:
    raise SystemExit('fall-through anchor not unique')
source = source.replace(anchor, replacement, 1)

anchor = '''        elif desire_refund_price:\n            temp_string += f" Non-refundable price is {base_price:.2f} {url_params.currency_code}"\n\n        log(temp_string)\n'''
replacement = '''        elif desire_refund_price:\n            temp_string += f" Non-refundable price is {base_price:.2f} {url_params.currency_code}"\n\n        if automatic_URL and past_final_payment_date:\n            temp_string += f"{YELLOW} Past Final Payment Date of {final_payment_date_display}{RESET}"\n            rebook_decision = "past_final_payment"\n\n        log(temp_string)\n'''
if source.count(anchor) != 1:
    raise SystemExit('final-payment insertion anchor not unique')
source = source.replace(anchor, replacement, 1)
source_path.write_text(source)

test_path = Path('unittests/test_price_checker.py')
tests = test_path.read_text()
old = '''def test_availability_false_when_subtype_code_absent():\n    params = _availability_params(subtype="2D", category_code="2D")\n'''
new = '''def test_availability_false_when_subtype_code_absent():\n    # Use a genuinely absent category family; D/4D now correctly resolves a stale D-family subtype.\n    params = _availability_params(subtype="Z", category_code="9Z")\n'''
if tests.count(old) != 1:
    raise SystemExit('absent subtype test anchor not unique')
tests = tests.replace(old, new, 1)

insert_before = '''\ndef test_apply_overrides_category_mirroring():\n'''
added = '''\n\ndef test_availability_resolves_renamed_subtype_via_category_letters():\n    params = _availability_params(subtype="U", category_code="2U")\n    mock_resp = MagicMock()\n    mock_resp.status_code = 200\n    mock_resp.text = _room_selection_rsc(code="V", category_code="4U")\n    with patch('CheckRoyalCaribbeanPrice._execute_api_request', return_value=mock_resp):\n        available, alternates = check_if_room_is_available(params)\n    assert available is True\n    assert alternates == []\n    assert params.stateroom_subtype == "V"\n\n\ndef test_availability_letters_fallback_does_not_false_positive():\n    params = _availability_params(subtype="Z", category_code="9Z")\n    mock_resp = MagicMock()\n    mock_resp.status_code = 200\n    mock_resp.text = _room_selection_rsc(code="D", category_code="4D")\n    with patch('CheckRoyalCaribbeanPrice._execute_api_request', return_value=mock_resp):\n        available, alternates = check_if_room_is_available(params)\n    assert available is False\n    assert len(alternates) == 1\n    assert params.stateroom_subtype == "Z"\n\n\ndef test_availability_exact_match_still_wins_unchanged():\n    params = _availability_params(subtype="D", category_code="2D")\n    mock_resp = MagicMock()\n    mock_resp.status_code = 200\n    mock_resp.text = _room_selection_rsc(code="D", category_code="4D")\n    with patch('CheckRoyalCaribbeanPrice._execute_api_request', return_value=mock_resp):\n        available, alternates = check_if_room_is_available(params)\n    assert available is True\n    assert alternates == []\n    assert params.stateroom_subtype == "D"\n\n'''
if tests.count(insert_before) != 1:
    raise SystemExit('test insertion anchor not unique')
tests = tests.replace(insert_before, added + insert_before, 1)
test_path.write_text(tests)

baseline_path = Path('UPSTREAM-BASELINE.md')
baseline = baseline_path.read_text()
baseline = baseline.replace('Baseline commit: `7dbd6cb9332c5934caa7ba11060f40a15c7904dd`',
                            'Baseline commit: `eaaf68fe9a80cda2a455a88305fcd81f33862962`')
baseline = baseline.replace('Commit subject: Merge pull request #117 from tecmage/fix-nights-brand',
                            'Commit subject: Fix for #119')
baseline_path.write_text(baseline)

review_path = Path('AVAILABILITY-REVIEW.md')
review = review_path.read_text()
section = '''\n## Upstream cabin-subtype and final-payment sync review\n\nUpstream `main` through `eaaf68fe9a80cda2a455a88305fcd81f33862962` was merged on an isolated review branch. The sync adopts Royal's renamed funnel subtype-code fallback while preserving the fork's tri-state inventory result, and adds the upstream final-payment status correction for best-price output. Entertainment/dining availability orchestration, scheduled checks, persistent notification state, configuration compatibility, calendar/report exports, and the dedicated GHCR workflow are unchanged. No configuration or state migration is required.\n'''
if '## Upstream cabin-subtype and final-payment sync review' not in review:
    review += section
review_path.write_text(review)
