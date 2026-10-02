/* eslint-env node */

/*
 * This file runs in a Node context (it's NOT transpiled by Babel), so use only
 * the ES6 features that are supported by your Node version. https://node.green/
 */

// Configuration for your app
// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js

const { configure } = require('quasar/wrappers');
const path = require('path');

const inject = require('@rollup/plugin-inject');
const esbuildShim = require.resolve('node-stdlib-browser/helpers/esbuild/shim');

module.exports = configure(async function () {
  const { default: stdLibBrowser } = await import('node-stdlib-browser');
  return {
    eslint: {
      warnings: true,
      errors: true,
    },

    // https://v2.quasar.dev/quasar-cli-vite/prefetch-feature
    // preFetch: true,

    // app boot file (/src/boot)
    // --> boot files are part of "main.js"
    // https://v2.quasar.dev/quasar-cli-vite/boot-files
    boot: ['sentry', 'i18n', 'axios', 'routeGuards', 'apexcharts'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#css
    css: ['app.scss'],

    // https://github.com/quasarframework/quasar/tree/dev/extras
    extras: [
      'mdi-v5',
      'roboto-font', // optional, you are not bound to it
    ],

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#build
    build: {
      target: {
        browser: ['es2019', 'edge88', 'firefox78', 'chrome87', 'safari13.1'],
        node: 'node24',
      },

      htmlFilename: 'index.html',

      env: {
        // Base URL for API requests when the app is not served by the portal itself (the Electron kiosk)
        apiBaseUrl: process.env.API_BASE_URL,
        vueRouterMode: 'history',
      },

      vueRouterMode: 'history', // available values: 'hash', 'history'
      // vueRouterBase,
      // vueDevtools,
      polyfillModulePreload: true,
      vueOptionsAPI: true,

      // rebuildCache: true, // rebuilds Vite/linter/etc cache on startup

      showProgress: true,
      minify: true,

      extendViteConf(viteConf, {}) {
        // The Node polyfills are for the page only. @quasar/app-vite 3 also
        // applies `alias` to the kiosk's main process and preload, which need
        // the real Node modules.
        viteConf.resolve.alias = {
          ...viteConf.resolve.alias,
          ...stdLibBrowser,
        };

        viteConf.plugins.push({
          ...inject({
            global: [esbuildShim, 'global'],
            process: [esbuildShim, 'process'],
            Buffer: [esbuildShim, 'Buffer'],
          }),
          enforce: 'post',
        });

        viteConf.optimizeDeps.esbuildOptions = {
          ...viteConf.optimizeDeps.esbuildOptions,
          define: {
            global: 'globalThis',
          },
          // Enable esbuild polyfill plugins
          plugins: [],
        };

        viteConf.optimizeDeps.include = ['buffer', 'process'];
      },
      viteVuePluginOptions: {},

      alias: {
        // Every import prefix the code uses. @quasar/app-vite 3 only adds `@`
        // by itself, so the ones version 1 added that the code needs are
        // listed here, plus `types`, which came from tsconfig.json through
        // vite-tsconfig-paths.
        src: path.join(__dirname, 'src'),
        app: __dirname,
        components: path.join(__dirname, 'src/components'),
        layouts: path.join(__dirname, 'src/layouts'),
        pages: path.join(__dirname, 'src/pages'),
        boot: path.join(__dirname, 'src/boot'),
        types: path.join(__dirname, 'src/types'),
        '@components': path.join(__dirname, 'src/components/'),
        '@icons': path.join(__dirname, 'src/icons/'),
        '@store': path.join(__dirname, 'src/store/'),
        '@mixins': path.join(__dirname, 'src/mixins/'),
        '@assets': path.join(__dirname, 'src/assets/'),
      },

      vitePlugins: [
        [
          '@intlify/vite-plugin-vue-i18n',
          {
            // if you want to use Vue I18n Legacy API, you need to set `compositionOnly: false`
            compositionOnly: false,

            // if you want to use named tokens in your Vue I18n messages, such as 'Hello {name}',
            // you need to set `runtimeOnly: false`
            runtimeOnly: false,

            // you need to set i18n resource including paths !
            include: path.join(__dirname, './src/i18n/**'),
          },
        ],
      ],
    },

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#devServer
    devServer: {
      https: false,
      port: 8080,
      open: false, // opens browser window automatically
      proxy: {
        // proxy requests when running dev server
        '/api/ws/access': {
          target: 'ws://127.0.0.1:8000',
          ws: true,
          changeOrigin: false,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: false,
        },
        '/admin': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/openid': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/static': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#framework
    framework: {
      lang: 'en-US', // Quasar language pack
      iconSet: 'mdi-v7',
      config: {
        dark: 'auto', // or Boolean true/false
        loadingBar: { color: 'accent' },
        iconSet: 'mdi-v7', // Quasar icon set

        // For special cases outside of where the auto-import strategy can have an impact
        // (like functional components as one of the examples),
        // you can manually specify Quasar components/directives to be available everywhere:
        //
        // components: [],
        // directives: [],
      },
      // Quasar plugins
      plugins: ['Dialog', 'LoadingBar', 'Cookies', 'Notify'],

      // animations: 'all', // --- includes all animations
      // https://v2.quasar.dev/options/animations
      // animations: ['fadeIn', 'fadeOut', 'bounceInLeft', 'bounceOutRight'],

      // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#sourcefiles
      // sourceFiles: {
      //   rootComponent: 'src/App.vue',
      //   router: 'src/router/index',
      //   store: 'src/store/index',
      //   registerServiceWorker: 'src-pwa/register-service-worker',
      //   serviceWorker: 'src-pwa/custom-service-worker',
      //   pwaManifestFile: 'src-pwa/manifest.json',
      //   electronMain: 'src-electron/electron-main',
      //   electronPreload: 'src-electron/electron-preload'
      // },
    },
    // https://v2.quasar.dev/quasar-cli-vite/developing-ssr/configuring-ssr
    ssr: {
      // ssrPwaHtmlFilename: 'offline.html', // do NOT use index.html as name!
      // will mess up SSR

      // extendSSRWebserverConf (esbuildConf) {},
      // extendPackageJson (json) {},

      pwa: false,

      // manualStoreHydration: true,
      // manualPostHydrationTrigger: true,

      prodPort: 3000, // The default port that the production server should use
      // (gets superseded if process.env.PORT is specified at runtime)

      middlewares: [
        'render', // keep this as last one
      ],
    },

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/developing-electron-apps/configuring-electron
    electron: {
      // extendElectronMainConf (esbuildConf)
      // extendElectronPreloadConf (esbuildConf)

      inspectPort: 5858,

      bundler: 'packager', // 'packager' or 'builder'

      packager: {
        // https://github.com/electron-userland/electron-packager/blob/master/docs/api.md#options
        // OS X / Mac App Store
        // appBundleId: '',
        // appCategoryType: '',
        // osxSign: '',
        // protocol: 'myapp://path',
        // Windows only
        // win32metadata: { ... }
      },

      builder: {
        // https://www.electron.build/configuration/configuration

        appId: 'membermatters',
      },

      nodeIntegration: true,
    },

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/developing-browser-extensions/configuring-bex
    bex: {
      // contentScripts: [
      //   'my-content-script'
      // ],
      // extendBexScriptsConf (esbuildConf) {}
      // extendBexManifestJson (json) {}
    },
  };
});
