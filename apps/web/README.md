# Max Admin Web

Owns the admin dashboard and operator controls. It renders authoritative API
state; it does not duplicate mission or payment logic in the browser.

## Local setup

```bash
npm install
npm run dev
```

The page defaults to `http://127.0.0.1:8000` for the API. Override it only when
needed with `VITE_API_URL`. The operator token is held in React memory and is
never written to local or session storage. Mission IDs may be placed in the URL
so refresh can reload authoritative backend state.

Build verification:

```bash
npm run build
```

This is one page using React, native fetch, and CSS. There is no router, client
state store, component library, WebSocket, or frontend workflow engine.
