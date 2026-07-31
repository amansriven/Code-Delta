# Delta Code frontend

The Delta Code frontend contains the public product site and authenticated API
regression dashboard. It runs on React 19, TypeScript, Vinext, and Cloudflare
Workers.

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
- `npm run build` — create a production Worker build
- `npm test` — build and verify all rendered routes
- `npx wrangler deploy` — deploy the `deltacode` Worker

The Worker name and public API environment variable are configured in
`wrangler.jsonc`.
