import { createSSRApp } from 'vue';
import App from './App.vue';
import { pinia } from './stores';

/**
 * Creates and configures the root UniApp instance.
 * Strictly registers Pinia global state container.
 */
export function createApp() {
  const app = createSSRApp(App);
  app.use(pinia);

  return {
    app,
    pinia,
  };
}
