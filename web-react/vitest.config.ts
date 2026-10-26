import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const jestDomVitest = fileURLToPath(
  new URL(
    './node_modules/@testing-library/jest-dom/dist/vitest.mjs',
    import.meta.url,
  ),
);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@testing-library/jest-dom/vitest': jestDomVitest,
      'react-router-dom': fileURLToPath(
        new URL(
          './node_modules/react-router-dom/dist/index.js',
          import.meta.url,
        ),
      ),
      '@tanstack/react-query': fileURLToPath(
        new URL(
          './node_modules/@tanstack/react-query/build/modern/index.js',
          import.meta.url,
        ),
      ),
      '@testing-library/react': fileURLToPath(
        new URL(
          './node_modules/@testing-library/react/dist/@testing-library/react.esm.js',
          import.meta.url,
        ),
      ),
    },
  },
  server: {
    fs: {
      allow: ['..'],
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['../test/web-react/**/*.test.ts'],
    setupFiles: ['../test/web-react/setup.ts'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/._*', '../test/**/._*'],
  },
});
