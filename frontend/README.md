# Delta Code frontend

The Delta Code frontend contains the public product site and authenticated API
regression dashboard. It runs on React 19, TypeScript, and native Next.js, and
is deployed on Vercel.

## Local development

Requirements:

- Node.js `>=22.13.0`
- the Delta Code API, either locally or on Railway

Install dependencies and start the development server:

```bash
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Without an API URL, the interface uses clearly labeled preview data. To connect
the local frontend to the hosted API, create `frontend/.env`:

```dotenv
NEXT_PUBLIC_DELTA_CODE_API_URL=https://web-production-e59907.up.railway.app
```

All authenticated requests use `credentials: "include"` because GitHub sessions
are stored in secure backend cookies.

## Product routes

| Route | Purpose |
| --- | --- |
| `/` | Public landing page |
| `/product` | Product capabilities |
| `/how-it-works` | Verification workflow |
| `/docs` | Local and API documentation |
| `/security` | Access and security model |
| `/overview` | Authenticated workspace summary |
| `/runs` | Searchable run history and per-repository grouping |
| `/runs/{id}` | Run verdict, branch metadata, errors, retry, and evidence |
| `/repositories` | Accessible public, private, and internal repositories |
| `/settings/integrations` | GitHub account, installation, and permissions |
| `/settings/account` | Account identity and appearance |

Light mode is the default. Users can switch to the low-glare dark mode from the
application sidebar, public header, or account settings.

## Commands

- `npm run dev` — start local development
- `npm run lint` — run ESLint
- `npm run build` — create a production Next.js build
- `npm test` — build and verify all rendered routes
- `npx vercel deploy` — create a Vercel preview deployment
- `npx vercel deploy --prod` — deploy to Vercel production

## Vercel deployment

Import the repository into Vercel and configure:

- **Project Name:** `deltacode`
- **Framework Preset:** Next.js
- **Root Directory:** `frontend`
- **Production Branch:** `main`
- **Environment variable:**
  `NEXT_PUBLIC_DELTA_CODE_API_URL=https://web-production-e59907.up.railway.app`

After the first production deployment, copy the canonical Vercel URL into the
Railway web service's `FRONTEND_URL` variable and redeploy Railway. This enables
OAuth redirects and credentialed CORS for the new frontend. Preview domains
that need authenticated API access must also be explicitly added to Railway's
comma-separated `ALLOWED_ORIGINS` variable.
