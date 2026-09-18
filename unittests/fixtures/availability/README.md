# Availability response fixtures

These are synthetic test scenarios based on observed API response structures.
They are not a passenger itinerary or a record of a specific person's bookings.

Guest and booking IDs are placeholders. Sailing dates are fictional; date-bearing
offering IDs have been replaced with synthetic identifiers. Conflict references
remain consistent so the tests exercise real relationships between fields.
Reserved states, party sizes, limits, stock values, and conflict combinations are
retained as test cases. Public Royal Caribbean product codes and show names are
kept to exercise the existing API contracts.

`escape_room_a.json` and `escape_room_b.json` reduce the two captured
`pt_onboardActivities` responses to three representative sessions each: an
unrestricted session, a session with fewer seats, and one with a hard conflict.
They preserve Royal's `PER_SEAT` unit and reported age restrictions. Product,
guest, reservation and offering IDs are fictional, and dates are shifted to 2099.
No names, ages, birth dates, order details or conflicting booked-activity details
are retained.

Do not add original browser captures, HAR files, credentials, session/cart tokens,
guest names, personal contact details, or real booking identifiers to this folder.
