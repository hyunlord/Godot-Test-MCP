import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../../src/visualizer_web_dist',
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
    target: 'es2020'
  }
});
