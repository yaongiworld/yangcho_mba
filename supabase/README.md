# supabase/

Postgres schema migrations + local dev config (added when needed).

## Apply migrations

Once the Supabase project exists and `dashboard/.env.local` has the URL + anon key, apply:

```bash
# From the dashboard/ directory:
npx supabase db push
```

Or apply via the Supabase SQL editor (paste each migration file).

## After applying

Regenerate TypeScript types for the dashboard:

```bash
cd dashboard && npm run db:types
```

Pydantic models in `pipeline/schemas.py` (W3) mirror the schema by hand — generated types only flow into the dashboard.

## Migration naming

`NNNN_short_name.sql`. Always increment NNNN, never edit a shipped migration. Schema changes always come as a new file.
