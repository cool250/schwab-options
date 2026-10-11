import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

export default defineConfig({
  // basicSsl: serve the dev server over HTTPS with a self-signed cert (the
  // browser shows a one-time warning). Schwab only accepts HTTPS callback
  // URLs, so this is what lets Settings → Reconnect Schwab work locally, via
  // SCHWAB_APP_CALLBACK_URL=https://127.0.0.1:3000/api/auth/schwab/callback.
  // Dev-server only — production builds are unaffected.
  plugins: [react(), basicSsl()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
  server: {
    // Bind to 127.0.0.1 explicitly (macOS can resolve "localhost" to IPv6
    // only), and open the app at https://127.0.0.1:3000 — the same origin
    // Schwab redirects back to, so the app login (sessionStorage, per
    // origin) is still there when the reconnect lands.
    host: '127.0.0.1',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true, // needed for the /api/market/ws/chain live-quote stream
      },
    },
  },
})
