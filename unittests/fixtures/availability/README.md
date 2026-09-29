# Availability response fixtures

These are synthetic test scenarios based on observed API response structures.
They are not a passenger itinerary or a record of a specific person's bookings.

Guest and booking IDs are placeholders. Sailing dates are fictional; date-bearing
offering IDs have been replaced with synthetic identifiers. Conflict references
remain consistent so the tests exercise real relationships between fields.
Examples of existing reservations, stock values, and conflicts are retained to
verify that release alerts depend on inventory rather than personal eligibility. Public Royal Caribbean product codes and show names are
kept to exercise the existing API contracts.

`escape_room_a.json` and `escape_room_b.json` retain three representative offerings
from each observed `pt_onboardActivities` response shape. Product, guest, booking
and offering identifiers are fictional, and dates are shifted to 2099. Age and
conflict flags are retained only to verify that release evaluation ignores personal
restrictions. No names, ages, birth dates, orders or real conflict details remain.

Do not add original browser captures, HAR files, credentials, session/cart tokens,
guest names, personal contact details, or real booking identifiers to this folder.
