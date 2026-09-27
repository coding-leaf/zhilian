/**
 * ZhiLian Mini-Program Unified Network Request Client
 * Wraps uni.request into Promise, auto-injects Bearer token,
 * handles 401 token refreshing with concurrency replay queue,
 * and intercepts business error codes into AppError.
 */

import { AppError } from './error';
import { storage } from './storage';
import { resolveUrl } from '../config/env';
import type { ApiResponse, RequestOptions } from '../types/common';
import type { TokenPairResponse } from '../types/auth';

interface PendingRequest {
  options: RequestOptions;
  resolve: (value: ApiResponse<unknown>) => void;
  reject: (reason?: unknown) => void;
}

let isRefreshing = false;
let pendingQueue: PendingRequest[] = [];

/** Maximum number of silent-refresh replays before aborting to avoid an unbounded loop. */
const MAX_AUTH_RETRY_COUNT = 1;

export type TokenRefreshListener = (tokens: TokenPairResponse) => void;

let tokenRefreshListener: TokenRefreshListener | null = null;

/**
 * Registers a listener notified whenever a silent token refresh succeeds.
 *
 * Keeps request layer free of store imports (no circular dependency): the Pinia
 * user store subscribes here to sync its in-memory tokens with storage.
 */
export function setTokenRefreshListener(listener: TokenRefreshListener | null): void {
  tokenRefreshListener = listener;
}

/**
 * Resets internal state for test environment isolation.
 */
export function _resetStateForTesting(): void {
  isRefreshing = false;
  pendingQueue = [];
  tokenRefreshListener = null;
}

/**
 * Returns current pending queue length for assertions in tests.
 */
export function _getPendingQueueLength(): number {
  return pendingQueue.length;
}

/**
 * Returns whether refresh is currently in progress.
 */
export function _isRefreshing(): boolean {
  return isRefreshing;
}

/**
 * Helper to safely redirect to login page upon terminal authentication failure.
 */
function redirectToLogin(): void {
  try {
    if (typeof uni !== 'undefined' && typeof uni.reLaunch === 'function') {
      uni.reLaunch({ url: '/pages/auth/login' });
    }
  } catch {
    // Suppress navigation errors during tests
  }
}

/**
 * Executes low-level uni.request with dual support for callback and Promise return styles.
 */
function callUniRequest(
  reqOptions: UniApp.RequestOptions,
): Promise<UniApp.RequestSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const res = uni.request({
      ...reqOptions,
      success: (result) => {
        if (!settled) {
          settled = true;
          resolve(result as UniApp.RequestSuccessCallbackResult);
        }
      },
      fail: (err) => {
        if (!settled) {
          settled = true;
          reject(err);
        }
      },
    });

    const potentialPromise = res as unknown as Promise<UniApp.RequestSuccessCallbackResult>;
    if (potentialPromise && typeof potentialPromise.then === 'function') {
      potentialPromise
        .then((result) => {
          if (!settled) {
            settled = true;
            resolve(result);
          }
        })
        .catch((err) => {
          if (!settled) {
            settled = true;
            reject(err);
          }
        });
    }
  });
}

/**
 * Calls backend refresh token endpoint.
 */
async function executeRefreshToken(refreshToken: string): Promise<TokenPairResponse> {
  const response = await callUniRequest({
    url: resolveUrl('/api/v1/auth/refresh'),
    method: 'POST',
    data: { refresh_token: refreshToken },
    header: { 'Content-Type': 'application/json' },
  });

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new AppError(20001, '登录状态已过期，请重新登录', {
      status_code: response.statusCode,
    });
  }

  const resData = (
    typeof response.data === 'object' && response.data !== null ? response.data : {}
  ) as Record<string, unknown>;

  if (typeof resData.code === 'number' && resData.code !== 0 && resData.code !== 200) {
    throw new AppError(
      resData.code,
      typeof resData.message === 'string' ? resData.message : undefined,
    );
  }

  const payload = (resData.data ? resData.data : resData) as TokenPairResponse;
  if (!payload || !payload.access_token) {
    throw new AppError(20001, '登录状态已过期，请重新登录');
  }

  return payload;
}

/**
 * Handles 401 unauthorized response with silent refresh and concurrency queuing.
 */
async function handle401Error<T>(options: RequestOptions): Promise<ApiResponse<T>> {
  const tokens = storage.getItem('auth_tokens');
  if (!tokens?.refresh_token) {
    storage.removeItem('auth_tokens');
    redirectToLogin();
    throw new AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 });
  }

  if (isRefreshing) {
    return new Promise<ApiResponse<T>>((resolve, reject) => {
      pendingQueue.push({
        options,
        resolve: resolve as (val: ApiResponse<unknown>) => void,
        reject,
      });
    });
  }

  isRefreshing = true;

  try {
    const newTokens = await executeRefreshToken(tokens.refresh_token);
    storage.setItem('auth_tokens', newTokens);
    tokenRefreshListener?.(newTokens);
    isRefreshing = false;

    // Retry the original failing request with the refreshed token, marking the attempt
    const retryOptions: RequestOptions = {
      ...options,
      _retryCount: (options._retryCount ?? 0) + 1,
    };
    const retryResult = await request<T>(retryOptions);

    // Drain pending replay queue
    const queuedRequests = [...pendingQueue];
    pendingQueue = [];
    queuedRequests.forEach((item) => {
      const queuedOptions: RequestOptions = {
        ...item.options,
        _retryCount: (item.options._retryCount ?? 0) + 1,
      };
      request(queuedOptions).then(item.resolve).catch(item.reject);
    });

    return retryResult;
  } catch (err) {
    isRefreshing = false;
    storage.removeItem('auth_tokens');
    const authError =
      err instanceof AppError
        ? err
        : new AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 });

    const queuedRequests = [...pendingQueue];
    pendingQueue = [];
    queuedRequests.forEach((item) => item.reject(authError));

    redirectToLogin();
    throw authError;
  }
}

/**
 * Unified network request function.
 *
 * @param options Request configuration options.
 * @returns Standard ApiResponse promise.
 */
export async function request<T = unknown>(options: RequestOptions): Promise<ApiResponse<T>> {
  const isRefreshUrl = options.url.includes('/auth/refresh');
  // Anonymous endpoints (login/refresh and other skipAuth calls) must never trigger
  // silent refresh or login redirection on 401/20001: they surface the raw backend error.
  const isAnonymous = options.skipAuth === true;

  // If silent token refreshing is currently in progress, enqueue immediately
  if (isRefreshing && !isRefreshUrl) {
    return new Promise<ApiResponse<T>>((resolve, reject) => {
      pendingQueue.push({
        options,
        resolve: resolve as (val: ApiResponse<unknown>) => void,
        reject,
      });
    });
  }

  // Inject Authorization header if tokens exist and skipAuth is not set
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (!options.skipAuth) {
    const tokens = storage.getItem('auth_tokens');
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }
  }

  const method = (options.method || 'GET').toUpperCase();
  let requestData = options.data;
  if (
    method === 'GET' &&
    requestData &&
    typeof requestData === 'object' &&
    !Array.isArray(requestData)
  ) {
    const cleaned: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(requestData as Record<string, unknown>)) {
      if (v !== undefined && v !== null && v !== '') cleaned[k] = v;
    }
    requestData = cleaned;
  }

  let response: UniApp.RequestSuccessCallbackResult;
  try {
    response = await callUniRequest({
      url: resolveUrl(options.url),
      // PATCH is a valid HTTP verb used by folder rename / material move, but the
      // bundled UniApp typings omit it; assert to the framework's method union.
      method: (options.method || 'GET') as UniApp.RequestOptions['method'],
      data: requestData as string | AnyObject | ArrayBuffer | undefined,
      header: headers,
      timeout: options.timeout || 15000,
    });
  } catch (err: unknown) {
    throw new AppError(-1, '网络连接异常，请检查网络设置', {
      details: { original_error: String(err) },
    });
  }

  const { statusCode, data } = response;
  const resData = (typeof data === 'object' && data !== null ? data : {}) as Record<
    string,
    unknown
  >;

  // Check 401 or business authentication failure code 20001.
  // Only authenticated requests enter silent-refresh; anonymous endpoints fall through
  // to the raw error interception below (no token clearing, no redirectToLogin).
  const is401 = statusCode === 401 || resData.code === 20001;
  if (is401 && !isRefreshUrl && !isAnonymous) {
    // Circuit breaker: a replayed request that still returns 401 must not re-enter the
    // silent-refresh loop, otherwise a half-failed backend hangs the promise forever.
    if ((options._retryCount ?? 0) >= MAX_AUTH_RETRY_COUNT) {
      storage.removeItem('auth_tokens');
      redirectToLogin();
      throw new AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 });
    }
    return handle401Error<T>(options);
  }

  // Intercept HTTP non-2xx status codes
  if (statusCode < 200 || statusCode >= 300) {
    const errorCode = typeof resData.code === 'number' ? resData.code : statusCode;
    const errorMsg = typeof resData.message === 'string' ? resData.message : undefined;
    throw new AppError(errorCode, errorMsg, {
      details: resData.details as Record<string, unknown> | undefined,
      status_code: statusCode,
    });
  }

  // Intercept business error codes
  if (typeof resData.code === 'number' && resData.code !== 0 && resData.code !== 200) {
    const errorMsg = typeof resData.message === 'string' ? resData.message : undefined;
    throw new AppError(resData.code, errorMsg, {
      details: resData.details as Record<string, unknown> | undefined,
      status_code: statusCode,
    });
  }

  // Return standard ApiResponse structure
  if (typeof resData.code === 'number' && 'data' in resData) {
    return resData as unknown as ApiResponse<T>;
  }

  return {
    code: 0,
    message: typeof resData.message === 'string' ? resData.message : 'success',
    data: data as T,
  };
}

export default request;
