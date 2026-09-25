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

/**
 * Resets internal state for test environment isolation.
 */
export function _resetStateForTesting(): void {
  isRefreshing = false;
  pendingQueue = [];
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
      uni.reLaunch({ url: '/pages/login/index' });
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
    isRefreshing = false;

    // Retry the original failing request with the refreshed token
    const retryResult = await request<T>(options);

    // Drain pending replay queue
    const queuedRequests = [...pendingQueue];
    pendingQueue = [];
    queuedRequests.forEach((item) => {
      request(item.options).then(item.resolve).catch(item.reject);
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

  let response: UniApp.RequestSuccessCallbackResult;
  try {
    response = await callUniRequest({
      url: resolveUrl(options.url),
      method: options.method || 'GET',
      data: options.data as string | AnyObject | ArrayBuffer | undefined,
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

  // Check 401 or business authentication failure code 20001
  const is401 = statusCode === 401 || resData.code === 20001;
  if (is401 && !isRefreshUrl) {
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
