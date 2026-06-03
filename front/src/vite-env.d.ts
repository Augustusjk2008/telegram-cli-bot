/// <reference types="vite/client" />

declare const __PUBLIC_ENV__: Record<string, string | undefined>;
declare const __APP_VERSION__: string;

interface Window {
  __TCB_PUBLIC_ENV__?: Record<string, string | undefined>;
}
