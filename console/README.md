# FlakeGuard Console (frontend)

React 18 + Vite + TypeScript. No UI library: styling is `src/styles/*.css`, copied from the approved design.

```bash
npm install
cp .env.example .env        # VITE_USE_MOCK=1 runs everything on built-in sample data
npm run dev                 # http://localhost:5173
npm run build               # must pass with no errors
```

- `src/types.ts` is the API contract. The backend must return these shapes.
- `src/api/client.ts` switches between mock and real API with `VITE_USE_MOCK`.
- `src/copy.ts` holds the exact wording for every unusual state.
- `src/components/treeLayout.ts` computes the Repo map tree geometry from data.
- Routes: `/` Live, `/findings`, `/repo-map`, `/results`, `/no-tests`, `/states`, `/bot-text`.
