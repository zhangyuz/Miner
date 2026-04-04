import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  // Set the third parameter to all env regardless of the `VITE_` prefix.
  loadEnv(mode, process.cwd(), '')
  
  // Environment-specific configurations
  const envConfigs = {
    development: {
      apiBaseUrl: 'http://localhost:80',
      proxyTarget: 'http://localhost:80',
    },
    test: {
      apiBaseUrl: 'http://localhost:8080',
      proxyTarget: 'http://localhost:8080',
    },
    staging: {
      apiBaseUrl: 'https://staging-api.stkguru.com',
      proxyTarget: 'https://staging-api.stkguru.com',
    },
    production: {
      apiBaseUrl: 'https://api.stkguru.com',
      proxyTarget: 'https://api.stkguru.com',
    },
    ghpages: {
      apiBaseUrl: 'https://stk.guru',
      proxyTarget: '',
    },
    'ghpages-dev': {
      // For ghpages-dev, we serve static files from public/api/, so no proxy needed
      apiBaseUrl: '', // will be set to window.location.origin in client
      proxyTarget: '', // no proxy needed for static files
    },
    docker: {
      apiBaseUrl: '',
      proxyTarget: '',
    },
  }

  const currentEnv = mode || 'development'
  const config = envConfigs[currentEnv as keyof typeof envConfigs] || envConfigs.development

  // For ghpages-dev, set apiBaseUrl/proxyTarget to window.location.origin if possible
  if (currentEnv === 'ghpages-dev') {
    // In Node.js context, we can't access window, so use a fallback
    const origin = 'http://localhost:5173'
    config.apiBaseUrl = origin
    config.proxyTarget = origin
  }

  return {
    plugins: [react()],
    define: {
      // Make environment variables available to the client
      __API_BASE_URL__: JSON.stringify(config.apiBaseUrl),
      __ENV__: JSON.stringify(currentEnv),
    },
    server: {
      ...((currentEnv !== 'ghpages' && currentEnv !== 'ghpages-dev') && {
        proxy: {
          '/api': {
            target: config.proxyTarget,
            changeOrigin: true,
            secure: false,
            configure: (proxy) => {
              proxy.on('error', (_err) => {
                // Proxy error handling
              })
              proxy.on('proxyReq', (_, _req) => {
                // Proxy request handling
              })
              proxy.on('proxyRes', (_proxyRes, _req) => {
                // Proxy response handling
              })
            },
          },
        },
      }),
      hmr: {
        // Fix WebSocket connection issues
        port: 5173,
        host: 'localhost',
        protocol: 'ws',
        timeout: 30000,
        // Disable HMR overlay for service worker errors
        overlay: false,
      },
      // Add better error handling and logging
      watch: {
        usePolling: false,
        interval: 1000,
      },
    },
    // Optimize for development
    optimizeDeps: {
      include: ['react', 'react-dom', 'highcharts', 'highcharts-react-official'],
      exclude: ['@tanstack/react-query'] // Exclude from pre-bundling to reduce initial size
    },
    // Disable service worker for development
    worker: {
      format: 'es'
    },
    // Build configuration
    build: {
      outDir: 'dist',
      sourcemap: currentEnv === 'development',
      chunkSizeWarningLimit: 1000, // Increase warning limit to 1MB
      minify: 'esbuild', // Use esbuild for faster builds
      rollupOptions: {
        output: {
          manualChunks: {
            // Core React libraries
            'react-vendor': ['react', 'react-dom'],
            // Chart libraries (heaviest dependencies)
            'charts-vendor': ['highcharts', 'highcharts-react-official'],
            // React Query
            'query-vendor': ['@tanstack/react-query'],
            // Utility libraries
            'utils-vendor': ['react-intersection-observer'],
          },
          // Optimize chunk naming
          chunkFileNames: () => `js/[name]-[hash].js`,
          entryFileNames: 'js/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash].[ext]',
        },
        // Tree shaking optimizations
        treeshake: {
          moduleSideEffects: false,
          propertyReadSideEffects: false,
          unknownGlobalSideEffects: false,
        },
      },
    },
  }
})
