/**
 * Pinia Stores Central Registration and Export Entry
 * Strictly converges global application state to exactly 4 stores.
 */

import { createPinia } from 'pinia';

export const pinia = createPinia();

export * from './userStore';
export * from './materialStore';
export * from './practiceStore';
export * from './reportStore';

export default pinia;
