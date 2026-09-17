# Deployment

One Railway project, two environments, four service instances. Supabase provides
Postgres, Auth and Storage from outside Railway.

## The map

| Environment | Service | Root directory | Git branch | Supabase project |
|---|---|---|---|---|
| `dev` | `frontend` | `/frontend` | `dev` | `herbal-evidence-dev` |
| `dev` | `backend` | `/backend` | `dev` | `herbal-evidence-dev` |
| `production` | `frontend` | `/frontend` | `main` | `herbal-evidence-prod` |
| `production` | `backend` | `/backend` | `main` | `herbal-evidence-prod` |

| Supabase project | Ref | Region |
|---|---|---|
| `herbal-evidence-dev` | `wnttlpxiycghqiibdpjr` | eu-central-1 |
| `herbal-evidence-prod` | `sptckumvgpfgluyxxiug` | eu-central-1 |

Both are in the `Gil AI Course` organization (`bmwbpotofrnbijikkeib`).

Repository: `github.com/go2gil-bot/herbal-evidence`.

## Rules that are easy to break

- **`dev` talks only to `dev`.** The dev frontend's `API_BASE_URL` points at the
  dev backend, and the dev backend's `SUPABASE_URL` at the dev project. Same for
  production. A single crossed value silently mixes real and test data.
- **Production secrets are never copied into `dev`.** Railway will happily clone
  variables when you create an environment; each environment's values are set
  separately here for exactly that reason.
- **`API_BASE_URL` must be the public HTTPS domain**, not a `.railway.internal`
  address. The browser resolves it, not the container.
- **A manual `railway up` proves nothing about branch wiring.** It deploys what
  is on disk. Branch integration is verified separately, below.
- **Migrations are promoted deliberately**, never on backend startup.

## First-time setup

The CLI cannot do all of this; what must be done in the dashboard is marked.

```bash
npm install -g @railway/cli
railway login          # opens a browser
```

1. **Create the project and link it**

   ```bash
   railway init --name herbal-evidence
   railway link
   ```

2. **Create the two environments.** Railway starts with `production`; add `dev`:

   ```bash
   railway environment new dev
   ```

3. **Add two services per environment**, named `frontend` and `backend`.

4. **Connect the repository - dashboard.** For each of the four service
   instances: Settings -> Source -> connect `go2gil-bot/herbal-evidence`, set
   **Root Directory** (`/frontend` or `/backend`) and **Branch** (`dev` for the
   dev environment, `main` for production).

   The Railway account needs access to the `go2gil-bot` GitHub account. If it is
   signed in as a different GitHub user, grant that user access to the repository
   first - this is the step most likely to block.

5. **Set variables** (next section), then let each service deploy.

6. **Generate a public domain** for each service (Settings -> Networking ->
   Generate Domain), then come back and set `API_BASE_URL` and the CORS values to
   the domains Railway assigned.

## Variables

Values live in `supabase/.env` locally (gitignored). Nothing secret belongs in
git, in `config.js`, or in a variable that reaches the browser.

### backend

| Variable | dev | production | Secret? |
|---|---|---|---|
| `APP_ENV` | `dev` | `production` | no |
| `SUPABASE_URL` | dev project URL | prod project URL | no |
| `SUPABASE_PUBLISHABLE_KEY` | dev anon key | prod anon key | no (public by design) |
| `SUPABASE_SECRET_KEY` | dev service-role key | prod service-role key | **yes** |
| `SUPABASE_JWT_ISSUER` | `<url>/auth/v1` | `<url>/auth/v1` | no |
| `FRONTEND_ORIGIN` | dev frontend domain | prod frontend domain | no |
| `CORS_ALLOWED_ORIGINS` | dev frontend domain | prod frontend domain | no |
| `AI_PROVIDER` | `openai` | `openai` | no |
| `AI_MODEL` | `gpt-5.2` | `gpt-5.2` | no |
| `AI_API_KEY` | key | key | **yes** |
| `NCBI_API_KEY` | optional | optional | **yes** |
| `NCBI_CONTACT_EMAIL` | optional | optional | no |
| `LOG_LEVEL` | `INFO` | `INFO` | no |

`PORT` is injected by Railway; do not set it.

### frontend

All four are public - `entrypoint.sh` writes them into `/srv/config.js` at
container start, which means every value here is visible in the browser.

| Variable | dev | production |
|---|---|---|
| `APP_ENV` | `dev` | `production` |
| `API_BASE_URL` | dev backend public HTTPS domain | prod backend public HTTPS domain |
| `SUPABASE_URL` | dev project URL | prod project URL |
| `SUPABASE_PUBLISHABLE_KEY` | dev anon key | prod anon key |

`APP_ENV=dev` is what shows the amber "development environment" banner. Setting
it to `dev` in production would tell real users their data is not real.

Set them with:

```bash
railway variables --environment dev --service backend --set APP_ENV=dev
```

## Migrations

Schema changes are Git-versioned and promoted explicitly. The backend never runs
migrations at startup, so a bad deploy cannot take the schema with it.

```bash
# dev first, always
npx supabase db push --project-ref wnttlpxiycghqiibdpjr -p "$DEV_DB_PASSWORD"

# production, only after dev is verified
npx supabase db push --project-ref sptckumvgpfgluyxxiug -p "$PROD_DB_PASSWORD"
```

`supabase link` fails on this machine (`AlreadyExists: supabase/.temp`), so
`--project-ref` is passed directly. There is no local stack - Docker is not
installed - so `supabase start` and `db diff` are unavailable.

**Seeds:** `supabase/seed.sql` is reference data and is safe in production.
`supabase/seeds/dev_mock.sql` refuses to run unless `app.allow_mock_seed` is set
to `yes`, and must never be run against production.

### Rollback

Roll forward with a new migration; do not edit an applied one. The only
exception is a migration that has not been pushed anywhere yet.

A destructive change is deployed in two steps - add the new shape, deploy code
that writes both, then remove the old shape in a later migration - so that
rolling the application back does not meet a schema it cannot read.

## Verifying the wiring

Deploying manually with `railway up` does **not** prove branch integration. Check
it directly:

1. Push a trivial change to `dev`. Only the two `dev` services should build;
   `railway logs --environment production` should show nothing new.
2. Merge to `main` via pull request. Only the two production services should build.
3. `curl https://<prod-backend>/ready` - every check should say `set`.
4. Open the production frontend: **no amber dev banner**.
5. Open the dev frontend: **the banner is there**.
6. Sign in on dev, create a request, then confirm in the Supabase dashboard that
   the row landed in `herbal-evidence-dev` and **not** in `herbal-evidence-prod`.

## Auth email

### What is configured

Both projects had `site_url` still set to Supabase's default
`http://localhost:3000`, which means every verification and recovery link
pointed at a machine that was not the user's. Fixed 2026-09-17:

| Project | `site_url` | Redirects allowed |
|---|---|---|
| dev | `https://frontend-dev-62e0.up.railway.app` | its own `/auth.html`, plus `http://localhost:4173/auth.html` |
| production | `https://frontend-production-ed33.up.railway.app` | its own `/auth.html`, twice |

Production's allow-list deliberately contains no loopback address.

Apply or inspect with:

```bash
scripts/auth-config.sh dev diff
scripts/auth-config.sh production push
```

Read the diff before pushing. `config push` only applies what `config.toml`
declares - ten hosted properties it does not mention are left alone - but a
non-interactive push defaults to proceeding, so the diff is the only review step.

### What is still missing: a sender

Supabase's built-in email sender is rate limited to a handful of messages per
hour and is documented as being for testing only. **Registration works, but the
verification email will often not arrive.** Until SMTP is configured, do not open
the production site to real users.

Chosen provider: **Brevo** (free tier, 300 messages/day, no domain required).

1. In Brevo: verify a sender address, then create an **SMTP key** under
   SMTP & API. The SMTP login is usually `something@smtp-brevo.com` - it is not
   the account email - and the password is that key, not the account password.
2. Put four values in `supabase/.env` (gitignored):

   ```
   SMTP_HOST=smtp-relay.brevo.com
   SMTP_USER=<the SMTP login Brevo shows>
   SMTP_PASS=<the SMTP key>
   SMTP_SENDER=<the verified sender address>
   ```

3. `scripts/auth-config.sh dev diff`, read it, then `push`.
4. Register a real address on dev and confirm the email arrives before touching
   production.

The script includes `supabase/config.smtp.toml` **only when all four variables
are non-empty**. This is not caution for its own sake: with a variable missing,
the CLI passes `env(SMTP_HOST)` through as that literal string and still sets
`enabled = true`, so a half-configured push enables SMTP with nonsense and breaks
sending outright. All four, or none.

#### Deliverability without a domain

Sending from a free webmail address (`@gmail.com`, `@outlook.com`) through a
third-party relay fails those providers' DMARC policy, so messages are commonly
rejected or filed as spam by the recipient. Brevo restricts this for that reason.

For a small pilot where participants are told to expect the email, this is
usually survivable. For anything wider, a domain - about $10/year - plus the DNS
records Brevo asks for is the actual fix, and it is the difference between
"verification emails work" and "verification emails sometimes work".
