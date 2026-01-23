import { UserManager, WebStorageStateStore, type UserManagerSettings } from "oidc-client-ts";

function requiredEnv(name: keyof ImportMetaEnv): string {
  const v = import.meta.env[name];
  if (!v || !v.trim()) throw new Error(`Missing ${name}`);
  return v.trim();
}

export function createUserManager(): UserManager {
  const settings: UserManagerSettings = {
    authority: requiredEnv("VITE_OIDC_ISSUER"),
    client_id: requiredEnv("VITE_OIDC_CLIENT_ID"),
    redirect_uri: requiredEnv("VITE_OIDC_REDIRECT_URI"),
    response_type: "code",
    scope: "openid profile email roles",
    // Avoid a browser-side /userinfo fetch (can fail due to CORS/content-type quirks);
    // we rely on the id_token claims + calling the API /me for identity.
    loadUserInfo: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage })
  };
  return new UserManager(settings);
}

export function postLogoutRedirectUri(): string | undefined {
  const v = import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI;
  return v?.trim() ? v.trim() : undefined;
}
