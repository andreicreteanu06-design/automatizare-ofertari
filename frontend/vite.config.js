import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

const pdfHeaders = {
  name: 'local-pdfcraft-policy',
  configureServer(server) { installPdfHeaders(server); },
  configurePreviewServer(server) { installPdfHeaders(server); },
};
function installPdfHeaders(server) {
  server.middlewares.use((req, res, next) => {
    if (req.url?.startsWith('/pdfcraft/')) {
      res.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'self' 'wasm-unsafe-eval' 'sha256-JHDu+Ej8RRKyGx1IP3L83mcU+PJYuvvCoVew/IklZwA='; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'");
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Referrer-Policy', 'no-referrer');
    }
    next();
  });
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    build: { assetsInlineLimit: 0 }, // CSP: fonts and images remain same-origin files.
    plugins: [react(), tailwindcss(), pdfHeaders],
    server: { proxy: { '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8080', changeOrigin: true, timeout: 900000 } } },
  };
});
