# GramSakhi legacy compatibility boundaries

Active application code uses GramSakhi terminology (`CitizenAccount`, citizen chat, schemes).
A small set of **physical names** remains on purpose so existing databases, tokens, and clients keep working.

This is not leftover healthcare product code. Do not rename these without a data migration.

## Database (do not rename in place)

| Physical name | Application name | Why it remains |
|---------------|------------------|----------------|
| `family_accounts` | `CitizenAccount` | Existing SQLite and Supabase tables; conversations FK this table |
| `family_sessions` | `CitizenSession` | Existing session table |
| `family_sessions.family_account_id` | `CitizenSession.citizen_account_id` | Existing column mapped via SQLAlchemy |
| `conversations.citizen_account_id` → `family_accounts.id` | unchanged FK | Citizen id column already renamed; parent table name kept |
| `rag_documents.hospital_id` | unused nullable column | Old scoping; GramSakhi ingest sets NULL. Do not drop without a migration. |
| `ingest(..., hospital_id=)` | ignored kwarg | Call-site compatibility; does not scope documents |
| `sahyog.db` filename | migrator still accepts it | Older local SQLite files; new default is `gramsakhi.db` |

## API / clients (do not drop without a versioned contract)

| Field | Why it remains |
|-------|----------------|
| `family_account_id` on `/api/auth` token JSON | Backward-compatible alias of `citizen_account_id`. Android and older web clients still read it. |
| `familyAccountId` localStorage key | Transitional read/write alongside `citizenAccountId` |

## Historical documentation (not runtime)

These describe the former Sahyog healthcare system and must stay accurate:

- `migration_audit.md`
- `docs/sahyog_to_gramsakhi_migration.md`
- `database/schemas/*`, `database/seeders/*`, `database/queries/*`, `database/migrations/*`

They are **not** imported by the GramSakhi API.
