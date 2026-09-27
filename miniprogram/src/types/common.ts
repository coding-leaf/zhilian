/**
 * ZhiLian Mini-Program Common Data Contracts
 * Defines unified API response, pagination result, error code and request options.
 */

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
  details?: Record<string, unknown>;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type ErrorCode = number;

export interface RequestOptions {
  url: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  data?: unknown;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  timeout?: number;
  /** Internal counter guarding against unbounded 401 silent-refresh replay loops. */
  _retryCount?: number;
}
