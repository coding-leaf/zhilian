import { describe, it, expect } from 'vitest';
import pinia, {
  useUserStore,
  useMaterialStore,
  usePracticeStore,
  useReportStore,
} from '@/stores/index';

describe('Stores Index Entry', () => {
  it('should export pinia instance and all 4 store composables', () => {
    expect(pinia).toBeDefined();
    expect(useUserStore).toBeTypeOf('function');
    expect(useMaterialStore).toBeTypeOf('function');
    expect(usePracticeStore).toBeTypeOf('function');
    expect(useReportStore).toBeTypeOf('function');
  });
});
