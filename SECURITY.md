# Security and data policy

Keep personal portfolios, account records, credentials, licensed raw data and private reports outside version control. The runtime private/ directory is ignored.

Use synthetic inputs for public tests, demonstrations, screenshots and bug reports. Changing an account name is not sufficient anonymization.

Prepare a public source snapshot with python scripts/export_public.py --destination NEW_DIRECTORY. The exporter uses a whitelist, checks credential/path patterns and omits Git history. Review the exported files before publishing. A pattern scan cannot prove the absence of all private information.

Code uses MIT; third-party data retains its own terms. Adapters do not grant access or redistribution rights. Public availability alone does not establish permission to redistribute.

For security reports use private vulnerability reporting when available. Send a synthetic reproducer and versions without credentials or financial records.
