import { contextBridge, ipcRenderer } from "electron";

export type BackendConfig = {
  backendUrl: string;
  backendToken: string;
};

export type LoginResult = { logged_in: boolean; error?: string };

export type SendResult =
  | { ok: true; method: string }
  | {
      ok: false;
      error:
        | "not_logged_in"
        | "not_on_live"
        | "input_not_found"
        | "send_button_not_found"
        | "send_button_disabled"
        | "rate_limited"
        | "send_failed";
      detail?: string;
      retryAfterMs?: number;
    };

const api = {
  getConfig: (): Promise<BackendConfig> => ipcRenderer.invoke("config:get"),
  login: (): Promise<LoginResult> => ipcRenderer.invoke("auth:login"),
  logout: (): Promise<{ logged_in: boolean }> => ipcRenderer.invoke("auth:logout"),
  isLoggedIn: (): Promise<boolean> => ipcRenderer.invoke("auth:isLoggedIn"),
  getSessionCookies: (): Promise<{
    session_id: string | null;
    tt_target_idc: string | null;
  }> => ipcRenderer.invoke("auth:getSessionCookies"),
  navigateToLive: (username: string): Promise<void> =>
    ipcRenderer.invoke("tiktok:navigateToLive", username),
  sendComment: (text: string): Promise<SendResult> =>
    ipcRenderer.invoke("tiktok:sendComment", text),
};

contextBridge.exposeInMainWorld("api", api);

export type ElectronApi = typeof api;
