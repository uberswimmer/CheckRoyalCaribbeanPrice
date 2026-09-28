# Fork image publication

The canonical fork deployment, migration, rollback and publishing instructions
are now in [Local web setup](LOCAL-WEB-SETUP.md).

The existing checker and reports image names are unchanged:

- `ghcr.io/OWNER/royalcaribbean-availability`
- `ghcr.io/OWNER/royalcaribbean-availability-reports`

Both retain `latest` and `sha-<full commit SHA>` tags. The legacy word
"availability" in these image names does not select an execution mode.
