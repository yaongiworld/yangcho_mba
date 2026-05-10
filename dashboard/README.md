# dashboard/

Next.js 15 (App Router) + Tailwind 4 + Supabase. Deployed to Vercel.

## Routes

| Path | Page | When implemented |
|------|------|-----|
| `/` | Hero Story Layer (today's top moment) | W6 |
| `/trends` | Trend Radar (top 10 scored moments) | W5 |
| `/brief/[id]` | Brief Detail (full chain + 3 playbook outputs) | W5 |
| `/methodology` | 3 hero case studies + scoring formula + last-run timestamp | W5 + W1 |
| `/admin/queue` | Yangcho's review queue (auth-gated) | W7 |

## Bundle policy

- `/` is intentionally tiny. No Recharts, no heavy client libs. Pure HTML+CSS where possible.
- Recharts is dynamic-imported only on `/trends`.
- The hero page is the screenshot every essay supplement uses; it must load fast.

## Setup (deferred — not done yet)

1. `npm install`
2. Create Supabase project, copy URL + anon key into `.env.local` (template in `.env.example`).
3. Apply migrations from `../supabase/migrations/`.
4. `npm run db:types` to regenerate `types/db.ts` from the live schema.
5. `npm run dev`.

The `npm install` and Supabase setup steps need real keys. Skipped during W1 scaffolding per the "no system installs without explicit approval" rule.
