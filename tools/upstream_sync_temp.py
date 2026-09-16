from pathlib import Path

source = Path('CheckRoyalCaribbeanPrice.py').read_text()
tests = Path('unittests/test_price_checker.py').read_text()

required_source = [
    'def check_if_room_is_available(params: CruiseURLParams) -> tuple[Optional[bool], List[Dict[str, Any]]]:',
    'letter_matched_subtype = None',
    'wanted_letters = _code_letters(params.stateroom_subtype) or _code_letters(params.stateroom_category_code)',
    'params.stateroom_subtype = letter_matched_subtype',
    'Past Final Payment Date of {final_payment_date_display}',
    'rebook_decision = "past_final_payment"',
    'class AvailabilityWatch:',
    'def run_availability_only(',
    'def finish_availability_run(',
]
for needle in required_source:
    if needle not in source:
        raise SystemExit(f'merged source missing required invariant: {needle}')

required_tests = [
    'test_availability_resolves_renamed_subtype_via_category_letters',
    'test_availability_letters_fallback_does_not_false_positive',
    'test_availability_exact_match_still_wins_unchanged',
]
for needle in required_tests:
    if needle not in tests:
        raise SystemExit(f'merged tests missing upstream regression: {needle}')

baseline_path = Path('UPSTREAM-BASELINE.md')
baseline = baseline_path.read_text()
baseline = baseline.replace('Baseline commit: `7dbd6cb9332c5934caa7ba11060f40a15c7904dd`',
                            'Baseline commit: `eaaf68fe9a80cda2a455a88305fcd81f33862962`')
baseline = baseline.replace('Commit subject: Merge pull request #117 from tecmage/fix-nights-brand',
                            'Commit subject: Fix for #119')
baseline_path.write_text(baseline)

review_path = Path('AVAILABILITY-REVIEW.md')
review = review_path.read_text()
section = '''\n## Upstream cabin-subtype and final-payment sync review\n\nUpstream `main` through `eaaf68fe9a80cda2a455a88305fcd81f33862962` was merged on an isolated review branch. Git merged the source and tests cleanly. Review verifies that Royal's renamed funnel subtype-code fallback coexists with the fork's tri-state cabin-inventory result, and that the best-price path now displays an expired final-payment date. Entertainment/dining availability orchestration, scheduled checks, persistent notification state, configuration compatibility, calendar/report exports, and the dedicated GHCR workflow are unchanged. No configuration or state migration is required.\n'''
if '## Upstream cabin-subtype and final-payment sync review' not in review:
    review += section
review_path.write_text(review)
